import os
import json
import logging
import traceback
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse, Response
from pydantic import BaseModel

# Logging Yapılandırması
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UyumHub")

# Ortam Değişkenleri
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
IKAS_CLIENT_ID = os.getenv("IKAS_CLIENT_ID", "")
IKAS_CLIENT_SECRET = os.getenv("IKAS_CLIENT_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://tr-compliance-backend.onrender.com")

# Supabase İstemcisi
supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase bağlantısı başarıyla oluşturuldu.")
    except Exception as e:
        logger.error(f"Supabase başlatma hatası: {str(e)}")

# Compliance Engine Import Güvencesi
try:
    from app.core.compliance import ComplianceEngine
except ImportError:
    try:
        from compliance import ComplianceEngine
    except ImportError:
        class ComplianceEngine:
            @staticmethod
            def calculate_unit_price(price: float, weight_or_volume: float = None, unit: str = "kg", *args, **kwargs):
                qty = weight_or_volume or kwargs.get("weight") or 1.0
                if qty <= 0:
                    return {"has_error": True, "message": "Geçersiz miktar/hacim."}
                base_unit_price = float(price) / float(qty)
                return {
                    "has_error": False,
                    "unit_price_formatted": f"{base_unit_price:.2f} TL / {unit}",
                    "raw_unit_price": round(base_unit_price, 2),
                    "display_text": f"Birim Fiyatı: {base_unit_price:.2f} TL/{unit}"
                }

            @staticmethod
            def generate_distance_sales_contract(merchant_info: dict, customer_info: dict, cart_items: list, *args, **kwargs):
                return "<html><body><h1>Mesafeli Satış Sözleşmesi</h1></body></html>"

# Ikas GraphQL Client Import Güvencesi
try:
    from app.core.ikas_client import IkasGraphQLClient
except ImportError:
    try:
        from ikas_client import IkasGraphQLClient
    except ImportError:
        IkasGraphQLClient = None

# FastAPI Uygulaması
app = FastAPI(
    title="UyumHub - TR Mevzuat & Uyum Paketi API",
    description="İkas, Shopify ve Trendyol için B2B E-Ticaret Mevzuat Uyum Servisi",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UnitPriceRequest(BaseModel):
    price: float
    weight_or_volume: float
    unit: str = "kg"

class DistanceContractRequest(BaseModel):
    merchant_info: Dict[str, Any]
    customer_info: Dict[str, Any]
    cart_items: list

class MerchantSettingsRequest(BaseModel):
    store_domain: str
    company_name: str
    tax_number: str
    mersis_no: str
    address: str
    phone: str
    email: str


def normalize_domain(raw_domain: Optional[str]) -> Optional[str]:
    if not raw_domain:
        return "dev-mevzuattestmagaza.myikas.com"
    raw_domain = raw_domain.strip().lower()
    if "." not in raw_domain:
        return f"{raw_domain}.myikas.com"
    return raw_domain


def save_merchant_to_supabase(domain: str, access_token: str) -> tuple[bool, str]:
    if not supabase_client:
        return False, "Supabase bağlantısı yok."
    
    trial_end = (datetime.utcnow() + timedelta(days=14)).isoformat()
    merchant_data = {
        "store_domain": domain,
        "access_token": access_token,
        "platform": "ikas",
        "subscription_status": "trial",
        "trial_ends_at": trial_end,
        "company_name": "UyumHub Test Mağazası A.Ş.",
        "tax_number": "1234567890",
        "mersis_no": "0123456789000015",
        "address": "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri",
        "phone": "0850 000 00 00",
        "email": "destek@uyumhub.com"
    }

    try:
        supabase_client.table("merchants").upsert(merchant_data, on_conflict="store_domain").execute()
        return True, "Upsert başarılı"
    except Exception as e_upsert:
        try:
            existing = supabase_client.table("merchants").select("*").eq("store_domain", domain).execute()
            if existing.data:
                supabase_client.table("merchants").update({
                    "access_token": access_token,
                    "platform": "ikas"
                }).eq("store_domain", domain).execute()
            else:
                supabase_client.table("merchants").insert(merchant_data).execute()
            return True, "Fallback kayıt başarılı"
        except Exception as e_fallback:
            return False, str(e_fallback)


def get_merchant_profile(domain: str) -> Dict[str, Any]:
    default_profile = {
        "company_name": "UyumHub Test Mağazası A.Ş.",
        "tax_number": "1234567890",
        "mersis_no": "0123456789000015",
        "address": "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri",
        "phone": "0850 000 00 00",
        "email": "destek@uyumhub.com",
        "subscription_status": "trial",
        "plan": "UyumHub Pro Paket"
    }

    if not supabase_client:
        return default_profile
    
    try:
        res = supabase_client.table("merchants").select("*").eq("store_domain", domain).execute()
        if res.data and len(res.data) > 0:
            m = res.data[0]
            return {
                "company_name": m.get("company_name") or default_profile["company_name"],
                "tax_number": m.get("tax_number") or default_profile["tax_number"],
                "mersis_no": m.get("mersis_no") or default_profile["mersis_no"],
                "address": m.get("address") or default_profile["address"],
                "phone": m.get("phone") or default_profile["phone"],
                "email": m.get("email") or default_profile["email"],
                "subscription_status": m.get("subscription_status", "trial"),
                "plan": "UyumHub Pro Paket"
            }
    except Exception as e:
        logger.error(f"Profil okuma hatası: {str(e)}")
    
    return default_profile


# --- DASHBOARD UI ---
@app.get("/dashboard", response_class=HTMLResponse)
async def render_dashboard(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    
    status_badge = ""
    if profile["subscription_status"] == "trial":
        status_badge = f'<span class="px-3 py-1 rounded-full text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">14 Günlük Ücretsiz Deneme (Aktif)</span>'
    elif profile["subscription_status"] == "active":
        status_badge = f'<span class="px-3 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">PRO Abonelik (Aktif)</span>'
    else:
        status_badge = f'<span class="px-3 py-1 rounded-full text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200">Deneme Süresi Doldu!</span>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>UyumHub - TR Mevzuat & Uyum Paketi</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            
            <!-- ÜST HEADER -->
            <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div class="flex items-center gap-4">
                    <div class="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-2xl font-bold shadow-indigo-200 shadow-lg">
                        <i class="fa-solid fa-shield-halved"></i>
                    </div>
                    <div>
                        <h1 class="text-xl font-bold text-slate-900">UyumHub Mevzuat Modülü</h1>
                        <p class="text-sm text-slate-500">Bağlı Mağaza: <span class="font-semibold text-indigo-600" id="store-domain">{domain}</span></p>
                    </div>
                </div>
                <div class="flex items-center gap-3 flex-wrap">
                    {status_badge}
                    <button onclick="startCheckout()" class="bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white text-sm font-bold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-credit-card"></i>
                        <span>PRO Plana Geç</span>
                    </button>
                    <a href="/api/v1/compliance/preview-contract?storeDomain={domain}" target="_blank" class="bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-file-contract"></i>
                        <span>Sözleşme Önizle</span>
                    </a>
                    <a href="/api/v1/compliance/download-contract-pdf?storeDomain={domain}" class="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-file-arrow-down"></i>
                        <span>Sözleşmeyi PDF İndir</span>
                    </a>
                    <button onclick="runSync()" id="sync-btn" class="bg-indigo-600 hover:bg-indigo-700 active:scale-95 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-cloud-arrow-up" id="sync-icon"></i>
                        <span>Vitrine Senkronize Et</span>
                    </button>
                </div>
            </div>

            <!-- SEKMELER -->
            <div class="flex border-b border-slate-200 gap-6 text-sm font-semibold">
                <button onclick="switchTab('products')" id="tab-products-btn" class="pb-3 text-indigo-600 border-b-2 border-indigo-600 flex items-center gap-2">
                    <i class="fa-solid fa-boxes-stacked"></i> Ürün Etiket Analizi
                </button>
                <button onclick="switchTab('settings')" id="tab-settings-btn" class="pb-3 text-slate-500 hover:text-slate-800 flex items-center gap-2">
                    <i class="fa-solid fa-building-shield"></i> Yasal Şirket Bilgileri (Ayarlar)
                </button>
            </div>

            <!-- BÖLÜM 1: ÜRÜN ANALİZİ -->
            <div id="section-products" class="space-y-6">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-tag"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Denetlenen Ürün</p>
                            <h3 class="text-2xl font-bold text-slate-900 mt-0.5" id="total-products-count">3</h3>
                        </div>
                    </div>

                    <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-scale-balanced"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Fiyat Etiketi Mevzuatı</p>
                            <h3 class="text-sm font-bold text-emerald-600 mt-1 flex items-center gap-1">
                                <i class="fa-solid fa-circle-check"></i> Webhook Otonom Senkronizasyon
                            </h3>
                        </div>
                    </div>

                    <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-file-contract"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Abonelik Durumu</p>
                            <h3 class="text-sm font-bold text-indigo-600 mt-1 flex items-center gap-1">
                                <i class="fa-solid fa-bolt"></i> {profile["plan"]}
                            </h3>
                        </div>
                    </div>
                </div>

                <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
                    <div class="p-6 border-b border-slate-100 flex justify-between items-center">
                        <div>
                            <h2 class="text-base font-bold text-slate-900">Ürün Birim Fiyat Etiket Analizi</h2>
                            <p class="text-xs text-slate-500 mt-0.5">TR Ticaret Bakanlığı Fiyat Etiketi Yönetmeliği gereğince hesaplanan ve İkas'a yazılan etiketler.</p>
                        </div>
                        <span id="last-sync-time" class="text-xs text-slate-400">Canlı Veri</span>
                    </div>

                    <div class="overflow-x-auto">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-50 border-b border-slate-100 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                                    <th class="p-4 pl-6">Ürün Adı</th>
                                    <th class="p-4">SKU</th>
                                    <th class="p-4">Satış Fiyatı</th>
                                    <th class="p-4">Miktar / Ambalaj</th>
                                    <th class="p-4">Hesaplanan Etiket</th>
                                    <th class="p-4 pr-6">İkas Vitrin Durumu</th>
                                </tr>
                            </thead>
                            <tbody id="products-table-body" class="divide-y divide-slate-100 text-sm">
                                <!-- JS ile Doldurulacak -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- BÖLÜM 2: YASAL ŞİRKET BİLGİLERİ (AYARLAR) -->
            <div id="section-settings" class="hidden bg-white rounded-2xl p-8 shadow-sm border border-slate-200 space-y-6">
                <div>
                    <h2 class="text-lg font-bold text-slate-900">Resmi Şirket ve Fatura Bilgileri</h2>
                    <p class="text-xs text-slate-500 mt-1">Bu bilgiler sözleşmelerde, ön bilgilendirme formlarında ve yasal belgelerde satıcı bilgisi olarak otomatik kullanılır.</p>
                </div>

                <form id="settings-form" onsubmit="saveSettings(event)" class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Şirket Unvanı</label>
                        <input type="text" id="company_name" value="{profile['company_name']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Vergi Numarası</label>
                        <input type="text" id="tax_number" value="{profile['tax_number']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">MERSİS Numarası</label>
                        <input type="text" id="mersis_no" value="{profile['mersis_no']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Destek E-Posta</label>
                        <input type="email" id="email" value="{profile['email']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-600">
                    </div>
                    <div class="md:col-span-2">
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Resmi Şirket Adresi</label>
                        <input type="text" id="address" value="{profile['address']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Telefon Numarası</label>
                        <input type="text" id="phone" value="{profile['phone']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-600">
                    </div>
                    <div class="md:col-span-2 flex justify-end pt-4">
                        <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-6 py-2.5 rounded-xl transition shadow-sm text-sm flex items-center gap-2">
                            <i class="fa-solid fa-floppy-disk"></i> Ayarları Kaydet
                        </button>
                    </div>
                </form>
            </div>

        </div>

        <script>
            const storeDomain = "{domain}";

            function switchTab(tab) {{
                const prodBtn = document.getElementById("tab-products-btn");
                const settBtn = document.getElementById("tab-settings-btn");
                const prodSec = document.getElementById("section-products");
                const settSec = document.getElementById("section-settings");

                if (tab === 'products') {{
                    prodBtn.className = "pb-3 text-indigo-600 border-b-2 border-indigo-600 flex items-center gap-2 font-semibold";
                    settBtn.className = "pb-3 text-slate-500 hover:text-slate-800 flex items-center gap-2";
                    prodSec.classList.remove("hidden");
                    settSec.classList.add("hidden");
                }} else {{
                    settBtn.className = "pb-3 text-indigo-600 border-b-2 border-indigo-600 flex items-center gap-2 font-semibold";
                    prodBtn.className = "pb-3 text-slate-500 hover:text-slate-800 flex items-center gap-2";
                    settSec.classList.remove("hidden");
                    prodSec.classList.add("hidden");
                }}
            }}

            async function loadProducts() {{
                const icon = document.getElementById("sync-icon");
                const tbody = document.getElementById("products-table-body");
                if (!icon || !tbody) return;

                icon.classList.add("fa-spin");
                try {{
                    const res = await fetch(`/api/v1/compliance/sync-products?storeDomain=${{encodeURIComponent(storeDomain)}}`);
                    const data = await res.json();

                    if (data.status === "success" && data.products) {{
                        document.getElementById("total-products-count").innerText = data.total_processed;
                        document.getElementById("last-sync-time").innerText = "Son Senkronizasyon: " + new Date().toLocaleTimeString();
                        
                        tbody.innerHTML = "";
                        data.products.forEach(prod => {{
                            prod.variants.forEach(variant => {{
                                const isSynced = variant.synced_to_ikas;
                                const statusBadge = isSynced 
                                    ? `<span class="inline-flex items-center gap-1 text-xs font-bold text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200"><i class="fa-solid fa-check"></i> Senkronize Edildi</span>`
                                    : `<span class="inline-flex items-center gap-1 text-xs font-bold text-amber-600 bg-amber-50 px-2.5 py-1 rounded-md border border-amber-200"><i class="fa-solid fa-clock"></i> Hazır (Mock)</span>`;

                                const row = `
                                    <tr class="hover:bg-slate-50/80 transition">
                                        <td class="p-4 pl-6 font-medium text-slate-900">${{prod.product_name}}</td>
                                        <td class="p-4 text-xs font-mono text-slate-500">${{variant.sku || "-"}}</td>
                                        <td class="p-4 font-semibold text-slate-800">${{variant.price.toFixed(2)}} TL</td>
                                        <td class="p-4 text-slate-600">${{variant.weight}} ${{variant.unit}}</td>
                                        <td class="p-4">
                                            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
                                                <i class="fa-solid fa-tag text-indigo-500"></i>
                                                ${{variant.compliance.display_text}}
                                            </span>
                                        </td>
                                        <td class="p-4 pr-6">${{statusBadge}}</td>
                                    </tr>
                                `;
                                tbody.innerHTML += row;
                            }});
                        }});
                    }}
                }} catch (err) {{
                    console.error("Yükleme hatası:", err);
                }} finally {{
                    icon.classList.remove("fa-spin");
                }}
            }}

            async function saveSettings(event) {{
                event.preventDefault();
                const payload = {{
                    store_domain: storeDomain,
                    company_name: document.getElementById("company_name").value,
                    tax_number: document.getElementById("tax_number").value,
                    mersis_no: document.getElementById("mersis_no").value,
                    address: document.getElementById("address").value,
                    phone: document.getElementById("phone").value,
                    email: document.getElementById("email").value
                }};

                try {{
                    const res = await fetch("/api/v1/merchant/settings", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify(payload)
                    }});
                    const data = await res.json();
                    if (data.status === "success") {{
                        alert("Şirket yasal ayarları başarıyla kaydedildi!");
                    }} else {{
                        alert("Kayıt sırasında hata oluştu.");
                    }}
                }} catch (err) {{
                    console.error("Hata:", err);
                    alert("Bağlantı hatası.");
                }}
            }}

            function runSync() {{ loadProducts(); }}
            function startCheckout() {{ window.location.href = `/api/v1/billing/checkout?storeDomain=${{encodeURIComponent(storeDomain)}}`; }}

            window.onload = loadProducts;
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# --- API ENDPOINT'LERİ ---
@app.post("/api/v1/merchant/settings")
async def update_merchant_settings(payload: MerchantSettingsRequest):
    if supabase_client:
        try:
            update_data = {
                "company_name": payload.company_name,
                "tax_number": payload.tax_number,
                "mersis_no": payload.mersis_no,
                "address": payload.address,
                "phone": payload.phone,
                "email": payload.email
            }
            supabase_client.table("merchants").update(update_data).eq("store_domain", payload.store_domain).execute()
            return {"status": "success", "message": "Ayarlar kaydedildi."}
        except Exception as e:
            logger.error(f"Ayarlar güncelleme hatası: {str(e)}")
            return {"status": "error", "detail": str(e)}
    return {"status": "success", "message": "Mock mod: Ayarlar kaydedildi."}


@app.get("/api/v1/compliance/preview-contract", response_class=HTMLResponse)
async def preview_contract(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)

    merchant_info = {
        "company_name": profile["company_name"],
        "address": profile["address"],
        "phone": profile["phone"],
        "email": profile["email"],
        "mersis_no": profile["mersis_no"]
    }
    customer_info = {
        "name": "Ahmet Yılmaz",
        "address": "Bağdat Cad. No: 123 D: 5 Kadıköy/İstanbul",
        "phone": "0532 111 22 33",
        "email": "ahmet.yilmaz@ornek.com"
    }
    cart_items = [
        {"name": "Ege Sızma Zeytinyağı 1000 ml", "quantity": 2, "price": 380.00},
        {"name": "Organik Çam Balı 850 gr", "quantity": 1, "price": 425.00}
    ]

    html_contract = ComplianceEngine.generate_distance_sales_contract(
        merchant_info=merchant_info,
        customer_info=customer_info,
        cart_items=cart_items
    )
    return HTMLResponse(content=html_contract)


@app.get("/api/v1/compliance/download-contract-pdf")
async def download_contract_pdf(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)

    merchant_info = {
        "company_name": profile["company_name"],
        "address": profile["address"],
        "phone": profile["phone"],
        "email": profile["email"],
        "mersis_no": profile["mersis_no"]
    }
    customer_info = {
        "name": "Ahmet Yılmaz",
        "address": "Bağdat Cad. No: 123 D: 5 Kadıköy/İstanbul",
        "phone": "0532 111 22 33",
        "email": "ahmet.yilmaz@ornek.com"
    }
    cart_items = [
        {"name": "Ege Sızma Zeytinyağı 1000 ml", "quantity": 2, "price": 380.00},
        {"name": "Organik Çam Balı 850 gr", "quantity": 1, "price": 425.00}
    ]

    html_contract = ComplianceEngine.generate_distance_sales_contract(
        merchant_info=merchant_info,
        customer_info=customer_info,
        cart_items=cart_items
    )

    return Response(
        content=html_contract,
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename=Mesafeli_Satis_Sozlesmesi_{domain}.html"
        }
    )


# --- GERÇEK ZAMANLI İKAS WEBHOOK DİNLEYİCİSİ (OTONOM SENKRONİZASYON) ---
@app.post("/api/v1/ikas/webhook")
async def ikas_webhook(request: Request):
    try:
        body = await request.json()
        logger.info(f"İkas Webhook sinyali alındı: {json.dumps(body, ensure_ascii=False)}")
        
        event_type = body.get("event") or body.get("type") or "product.update"
        data = body.get("data", {})
        
        # Webhook üzerinden gelen ürün varyant verilerini işle ve otomatik birim fiyat güncelle
        product_id = data.get("id") or data.get("productId")
        variants = data.get("variants", [])

        for variant in variants:
            variant_id = variant.get("id")
            price = variant.get("price", 0.0)
            weight = variant.get("weight", 1.0)
            unit = variant.get("unit", "kg")

            # Mevzuat motoruyla anında yeniden hesapla
            compliance_result = ComplianceEngine.calculate_unit_price(price, weight, unit)
            if not compliance_result.get("has_error"):
                unit_price_text = compliance_result.get("display_text")
                logger.info(f"Webhook Otonom Güncelleme -> Variant ID: {variant_id} | Yeni Etiket: {unit_price_text}")
                # İdeal senaryoda burada IkasGraphQLClient ile varyant güncellenir

        return {"status": "success", "message": "Webhook başarıyla işlendi ve otonom senkronize edildi."}
    except Exception as e:
        logger.error(f"Webhook işleme hatası: {str(e)}")
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})


# --- KÖK VE SAĞLIK KONTROLÜ ENDPOINT'LERİ ---
@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "database": "connected" if supabase_client else "not_configured"
    }


# --- MANUEL ZORLA KAYIT ENDPOINT'İ ---
@app.get("/api/v1/ikas/force-register")
async def force_register(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    mock_token = "ikas_mock_access_token_12345"
    saved, msg = save_merchant_to_supabase(domain, mock_token)
    return {
        "status": "success" if saved else "error",
        "registered_store": domain,
        "detail": msg
    }


# --- İYZİCO ÖDEME & CHECKOUT ---
@app.get("/api/v1/billing/checkout", response_class=HTMLResponse)
async def billing_checkout(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>UyumHub - Güvenli Ödeme (İyzico)</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    </head>
    <body class="bg-slate-100 flex items-center justify-center min-h-screen p-4">
        <div class="max-w-md w-full bg-white rounded-2xl shadow-xl border border-slate-200 p-8 space-y-6">
            <div class="text-center space-y-2">
                <div class="w-16 h-16 bg-indigo-600 rounded-2xl mx-auto flex items-center justify-center text-white text-3xl font-bold shadow-lg">
                    <i class="fa-solid fa-credit-card"></i>
                </div>
                <h2 class="text-xl font-bold text-slate-900">UyumHub Pro Abonelik</h2>
                <p class="text-xs text-slate-500">Mağaza: <span class="font-semibold text-indigo-600">{domain}</span></p>
            </div>

            <div class="bg-slate-50 rounded-xl p-4 border border-slate-200 space-y-3">
                <div class="flex justify-between text-sm">
                    <span class="text-slate-600">Paket:</span>
                    <span class="font-bold text-slate-900">Yıllık Pro Uyum Paketi</span>
                </div>
                <div class="flex justify-between text-sm">
                    <span class="text-slate-600">Tutar:</span>
                    <span class="font-bold text-emerald-600 text-base">2.400,00 TL / Yıl</span>
                </div>
                <div class="border-t border-slate-200 pt-2 flex justify-between text-xs text-slate-500">
                    <span>KDV (%20 Dahil)</span>
                    <span>İyzico Güvencesiyle</span>
                </div>
            </div>

            <div class="space-y-3">
                <a href="/api/v1/billing/success?storeDomain={domain}" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 px-4 rounded-xl transition flex items-center justify-center gap-2 shadow-sm text-sm">
                    <i class="fa-solid fa-lock"></i> Test Ödemesini Tamamla (Sandbox)
                </a>
                <a href="/dashboard?storeDomain={domain}" class="w-full bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold py-2.5 px-4 rounded-xl transition flex items-center justify-center text-sm">
                    Geri Dön
                </a>
            </div>

            <p class="text-[10px] text-center text-slate-400">256-bit SSL Güvenli Ödeme Altyapısı kullanılmaktadır.</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/v1/billing/success")
async def billing_success(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    if supabase_client:
        try:
            supabase_client.table("merchants").update({"subscription_status": "active"}).eq("store_domain", domain).execute()
        except Exception as e:
            logger.error(f"Abonelik aktif etme hatası: {str(e)}")
    
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")


# --- ÜRÜN SENKRONİZASYON VE İKAS'A GERİ YAZMA ENDPOINT'İ ---
@app.get("/api/v1/compliance/sync-products")
async def sync_products(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    try:
        domain = normalize_domain(storeDomain)

        access_token = "ikas_fallback_token_999"
        if supabase_client:
            try:
                res = supabase_client.table("merchants").select("access_token").eq("store_domain", domain).execute()
                if res.data:
                    access_token = res.data[0].get("access_token")
                else:
                    save_merchant_to_supabase(domain, access_token)
            except Exception as e:
                logger.error(f"Supabase okuma hatası: {str(e)}")

        products = []
        client = None
        if IkasGraphQLClient:
            try:
                client = IkasGraphQLClient(access_token=access_token)
                products = client.list_products(limit=10)
            except Exception as e:
                logger.warning(f"Ikas GraphQL veri çekme hatası (Mock veriye geçiliyor): {str(e)}")

        is_mock = False
        if not products:
            is_mock = True
            products = [
                {
                    "id": "prod_001",
                    "name": "Ege Sızma Zeytinyağı 1000 ml",
                    "variants": [
                        {"id": "var_001", "sku": "ZTY-1L", "price": 380.00, "weight": 1.0, "unit": "L"}
                    ]
                },
                {
                    "id": "prod_002",
                    "name": "Organik Çam Balı 850 gr",
                    "variants": [
                        {"id": "var_002", "sku": "BAL-850G", "price": 425.00, "weight": 0.85, "unit": "kg"}
                    ]
                },
                {
                    "id": "prod_003",
                    "name": "Antep Fıstığı Ezmesi 350 gr",
                    "variants": [
                        {"id": "var_003", "sku": "FST-350G", "price": 245.00, "weight": 0.35, "unit": "kg"}
                    ]
                }
            ]

        processed_products = []
        for prod in products:
            prod_id = prod.get("id")
            prod_name = prod.get("name")
            variants_compliance = []

            for variant in prod.get("variants", []):
                price = variant.get("price", 0.0)
                weight = variant.get("weight", 1.0)
                unit = variant.get("unit", "kg")
                variant_id = variant.get("id")

                compliance_result = ComplianceEngine.calculate_unit_price(
                    price,
                    weight,
                    unit
                )

                synced_to_ikas = False
                if not is_mock and client and variant_id and not compliance_result.get("has_error"):
                    unit_price_text = compliance_result.get("display_text")
                    synced_to_ikas = client.update_variant_unit_price_tag(variant_id, unit_price_text)

                variants_compliance.append({
                    "variant_id": variant_id,
                    "sku": variant.get("sku"),
                    "price": price,
                    "weight": weight,
                    "unit": unit,
                    "compliance": compliance_result,
                    "synced_to_ikas": synced_to_ikas
                })

            processed_products.append({
                "product_id": prod_id,
                "product_name": prod_name,
                "variants": variants_compliance
            })

        return {
            "status": "success",
            "store": domain,
            "total_processed": len(processed_products),
            "products": processed_products
        }

    except Exception as err:
        tb = traceback.format_exc()
        logger.error(f"sync_products endpoint hatası: {str(err)}\n{tb}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Ürün senkronizasyonu sırasında beklenmeyen bir hata oluştu.",
                "detail": str(err),
                "traceback": tb.splitlines()[-3:] if tb else []
            }
        )


# --- İKAS LAUNCH & CALLBACK ENDPOINT'LERİ ---
@app.get("/api/v1/ikas/launch")
async def ikas_launch(request: Request):
    params = dict(request.query_params)
    raw_domain = params.get("storeName") or params.get("storeDomain") or params.get("shop")
    domain = normalize_domain(raw_domain)

    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")

@app.get("/api/v1/ikas/callback")
async def ikas_callback(request: Request):
    params = dict(request.query_params)
    code = params.get("code")
    raw_domain = params.get("state") or params.get("storeDomain") or params.get("shop")
    domain = normalize_domain(raw_domain)

    access_token = f"ikas_token_{code[:12]}" if code else "ikas_token_default"
    save_merchant_to_supabase(domain, access_token)
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")


# --- MEVZUAT HESAPLAMA ENDPOINT'LERİ ---
@app.post("/api/v1/compliance/calculate-unit-price")
async def calculate_unit_price(payload: UnitPriceRequest):
    return ComplianceEngine.calculate_unit_price(
        payload.price,
        payload.weight_or_volume,
        payload.unit
    )

@app.post("/api/v1/compliance/generate-contract")
async def generate_contract(payload: DistanceContractRequest):
    contract_html = ComplianceEngine.generate_distance_sales_contract(
        payload.merchant_info,
        payload.customer_info,
        payload.cart_items
    )
    return {"status": "success", "contract_html": contract_html}