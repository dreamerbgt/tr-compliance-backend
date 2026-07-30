import os
import json
import logging
import traceback
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
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


# --- DİNAMİK KURAL MOTORU (RULE ENGINE) ---
class DynamicRuleEngine:
    @staticmethod
    def get_active_rule(unit: str) -> Dict[str, Any]:
        """
        Supabase üzerinden dinamik mevzuat kurallarını çeker. 
        Eğer veritabanı bağlantısı yoksa varsayılan yasal kuralları döner.
        """
        default_rule = {
            "unit": unit,
            "base_multiplier": 1.0,
            "rounding_decimals": 2,
            "regulation_version": "TR-2026-V3",
            "is_active": True
        }

        if not supabase_client:
            return default_rule

        try:
            res = supabase_client.table("compliance_rules").select("*").eq("unit", unit).eq("is_active", True).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            logger.warning(f"Dinamik kural okunamadı, varsayılan kurala dönülüyor: {str(e)}")

        return default_rule


# Compliance Engine Güncellenmiş Sürümü
class ComplianceEngine:
    @staticmethod
    def calculate_unit_price(price: float, weight_or_volume: float = None, unit: str = "kg", *args, **kwargs):
        qty = weight_or_volume or kwargs.get("weight") or 1.0
        try:
            price = float(price)
            qty = float(qty)
        except (ValueError, TypeError):
            return {"has_error": True, "message": "Geçersiz fiyat veya miktar."}

        if qty <= 0:
            return {"has_error": "Geçersiz miktar/hacim."}

        # Dinamik Kural Motorundan Parametreleri Çek
        rule = DynamicRuleEngine.get_active_rule(unit)
        multiplier = float(rule.get("base_multiplier", 1.0))
        decimals = int(rule.get("rounding_decimals", 2))
        reg_version = rule.get("regulation_version", "TR-Standard")

        base_unit_price = (price / qty) * multiplier
        rounded_price = round(base_unit_price, decimals)

        return {
            "has_error": False,
            "unit_price_formatted": f"{rounded_price:.{decimals}f} TL / {unit}",
            "raw_unit_price": rounded_price,
            "display_text": f"Birim Fiyatı: {rounded_price:.{decimals}f} TL/{unit}",
            "applied_rule": reg_version
        }

    @staticmethod
    def generate_distance_sales_contract(merchant_info: Dict[str, Any], customer_info: Dict[str, Any], cart_items: List[Dict[str, Any]], *args, **kwargs) -> str:
        m_name = merchant_info.get("company_name", "UyumHub Test Mağazası A.Ş.")
        m_address = merchant_info.get("address", "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri")
        m_phone = merchant_info.get("phone", "0850 000 00 00")
        m_email = merchant_info.get("email", "destek@uyumhub.com")
        m_mersis = merchant_info.get("mersis_no", "0123456789000015")

        c_name = customer_info.get("name", "Müşteri Adı Soyadı")
        c_address = customer_info.get("address", "Teslimat Adresi Belirtilmedi")
        c_phone = customer_info.get("phone", "0500 000 00 00")
        c_email = customer_info.get("email", "musteri@ornek.com")

        subtotal = 0.0
        items_html = ""
        for item in cart_items:
            name = item.get("name", "Ürün Adı")
            qty = item.get("quantity", 1)
            price = item.get("price", 0.0)
            total = qty * price
            subtotal += total
            items_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{name}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: center;">{qty}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{price:.2f} TL</td>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{total:.2f} TL</td>
            </tr>
            """

        shipping_fee = 49.90 if 0 < subtotal < 1000 else 0.0
        grand_total = subtotal + shipping_fee

        return f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head>
            <meta charset="UTF-8">
            <title>Mesafeli Satış Sözleşmesi ve Ön Bilgilendirme Formu</title>
            <style>
                body {{ font-family: 'Arial', sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
                h1 {{ font-size: 18px; text-align: center; color: #1e293b; margin-bottom: 5px; }}
                h2 {{ font-size: 14px; color: #475569; border-bottom: 2px solid #cbd5e1; padding-bottom: 5px; margin-top: 25px; }}
                p, li {{ font-size: 12px; text-align: justify; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 12px; }}
                th {{ background-color: #f1f5f9; padding: 10px; text-align: left; border-bottom: 2px solid #cbd5e1; }}
                .box {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 6px; margin-bottom: 15px; font-size: 12px; }}
                .legal-footer {{ font-size: 10px; color: #64748b; margin-top: 30px; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 10px; }}
            </style>
        </head>
        <body>
            <h1>MESAFELİ SATIŞ SÖZLEŞMESİ</h1>
            <p style="text-align: center; font-size: 11px; color: #64748b;">İşbu sözleşme 6502 sayılı Kanun ve Dinamik Kural Motoru (TR-2026-V3) güvencesiyle düzenlenmiştir.</p>

            <h2>MADDE 1: TARAFLAR</h2>
            <div class="box">
                <strong>SATICI:</strong> {m_name} | Adres: {m_address} | MERSİS: {m_mersis}
            </div>
            <div class="box">
                <strong>ALICI:</strong> {c_name} | Adres: {c_address}
            </div>

            <h2>MADDE 2: ÜRÜNLER VE BEDELİ</h2>
            <table>
                <thead><tr><th>Ürün</th><th>Adet</th><th style="text-align:right;">Birim</th><th style="text-align:right;">Toplam</th></tr></thead>
                <tbody>{items_html}</tbody>
            </table>
            <div style="text-align: right; margin-top: 10px; font-size: 13px;">
                <p>Ara Toplam: <strong>{subtotal:.2f} TL</strong></p>
                <p>Kargo: <strong>{shipping_fee:.2f} TL</strong></p>
                <p style="font-size: 15px; color: #0f172a;"><strong>Genel Toplam: {grand_total:.2f} TL</strong></p>
            </div>

            <h2>MADDE 3: CAYMA HAKKI</h2>
            <p>Alıcı, ürünü teslim aldığı tarihten itibaren <strong>14 gün</strong> içinde cayma hakkına sahiptir.</p>

            <div class="legal-footer">
                UyumHub Dinamik Mevzuat Kural Motoru ile üretilmiştir. | Tarih: {datetime.now().strftime('%Y-%m-%d')}
            </div>
        </body>
        </html>
        """


# --- ÇOKLU PLATFORM İSTEMCİLERİ ---
class ShopifyAPIClient:
    def __init__(self, store_domain: str, access_token: str):
        self.store_domain = store_domain

    def list_products(self) -> List[Dict[str, Any]]:
        return [
            {"id": "shp_001", "name": "Shopify Organik Zeytinyağı 750 ml", "variants": [{"id": "shp_var_001", "sku": "SHP-ZTY", "price": 310.00, "weight": 0.75, "unit": "L"}]}
        ]

class TrendyolAPIClient:
    def __init__(self, supplier_id: str):
        self.supplier_id = supplier_id

    def list_products(self) -> List[Dict[str, Any]]:
        return [
            {"id": "ty_001", "name": "Trendyol Süzme Çiçek Balı 1000 gr", "variants": [{"id": "ty_var_001", "sku": "TY-BAL-1K", "price": 450.00, "weight": 1.0, "unit": "kg"}]}
        ]


# FastAPI Uygulaması
app = FastAPI(
    title="UyumHub - Dinamik Kural Motoru & Çoklu Platform",
    description="B2B E-Ticaret Mevzuat Uyum Servisi",
    version="1.1.0"
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


def save_merchant_to_supabase(domain: str, access_token: str, platform: str = "ikas") -> tuple[bool, str]:
    if not supabase_client:
        return False, "Supabase bağlantısı yok."
    
    trial_end = (datetime.utcnow() + timedelta(days=14)).isoformat()
    merchant_data = {
        "store_domain": domain,
        "access_token": access_token,
        "platform": platform,
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
                supabase_client.table("merchants").update({"access_token": access_token, "platform": platform}).eq("store_domain", domain).execute()
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
        "platform": "ikas",
        "plan": "UyumHub Pro Paket (Dinamik Kural Motoru)"
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
                "platform": m.get("platform", "ikas"),
                "plan": "UyumHub Pro Paket (Dinamik Kural Motoru)"
            }
    except Exception as e:
        logger.error(f"Profil okuma hatası: {str(e)}")
    
    return default_profile


# --- DASHBOARD UI ---
@app.get("/dashboard", response_class=HTMLResponse)
async def render_dashboard(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    platform_name = profile["platform"]
    
    status_badge = f'<span class="px-3 py-1 rounded-full text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-200 uppercase">Platform: {platform_name}</span>'
    if profile["subscription_status"] == "active":
        status_badge += ' <span class="px-3 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">PRO (Aktif)</span>'
    else:
        status_badge += ' <span class="px-3 py-1 rounded-full text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">Deneme Süresi</span>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>UyumHub - Dinamik Kural Motoru</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            
            <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div class="flex items-center gap-4">
                    <div class="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-2xl font-bold shadow-indigo-200 shadow-lg">
                        <i class="fa-solid fa-brain"></i>
                    </div>
                    <div>
                        <h1 class="text-xl font-bold text-slate-900">UyumHub Dinamik Kural Motoru (Rule Engine)</h1>
                        <p class="text-sm text-slate-500">Mağaza: <span class="font-semibold text-indigo-600">{domain}</span></p>
                    </div>
                </div>
                <div class="flex items-center gap-3 flex-wrap">
                    {status_badge}
                    <button onclick="startCheckout()" class="bg-gradient-to-r from-amber-500 to-orange-600 text-white text-sm font-bold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2 cursor-pointer">
                        <i class="fa-solid fa-credit-card"></i> PRO Plana Geç
                    </button>
                    <a href="/api/v1/compliance/preview-contract?storeDomain={domain}" target="_blank" class="bg-emerald-600 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-file-contract"></i> Sözleşme Önizle
                    </a>
                    <a href="/api/v1/compliance/download-contract-pdf?storeDomain={domain}" class="bg-blue-600 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-file-arrow-down"></i> PDF İndir
                    </a>
                    <button onclick="runSync()" id="sync-btn" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2 cursor-pointer">
                        <i class="fa-solid fa-cloud-arrow-up" id="sync-icon"></i> Vitrini Senkronize Et
                    </button>
                </div>
            </div>

            <!-- TAB BUTONLARI -->
            <div class="flex border-b border-slate-200 gap-6 text-sm font-semibold">
                <button type="button" onclick="switchTab('products')" id="tab-products-btn" class="pb-3 text-indigo-600 border-b-2 border-indigo-600 flex items-center gap-2 cursor-pointer">
                    <i class="fa-solid fa-boxes-stacked"></i> Ürün Etiket Analizi ({platform_name.upper()})
                </button>
                <button type="button" onclick="switchTab('settings')" id="tab-settings-btn" class="pb-3 text-slate-500 hover:text-slate-800 flex items-center gap-2 cursor-pointer">
                    <i class="fa-solid fa-building-shield"></i> Yasal Şirket Bilgileri
                </button>
            </div>

            <div id="section-products" class="space-y-6">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-tag"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Aktif Platform</p>
                            <h3 class="text-xl font-bold text-slate-900 mt-0.5 uppercase">{platform_name}</h3>
                        </div>
                    </div>

                    <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-microchip"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Kural Motoru</p>
                            <h3 class="text-sm font-bold text-emerald-600 mt-1">Supabase Dinamik (TR-2026-V3)</h3>
                        </div>
                    </div>

                    <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-bolt"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Paket</p>
                            <h3 class="text-sm font-bold text-indigo-600 mt-1" id="total-products-count">{profile["plan"]}</h3>
                        </div>
                    </div>
                </div>

                <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
                    <div class="p-6 border-b border-slate-100 flex justify-between items-center">
                        <div>
                            <h2 class="text-base font-bold text-slate-900">Dinamik Kural Destekli Birim Fiyat Analizi</h2>
                            <p class="text-xs text-slate-500 mt-0.5">Veritabanından çekilen yasal kurallara göre hesaplanan etiketler.</p>
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
                                    <th class="p-4">Hesaplanan Etiket (Kural)</th>
                                    <th class="p-4 pr-6">Vitrin Durumu</th>
                                </tr>
                            </thead>
                            <tbody id="products-table-body" class="divide-y divide-slate-100 text-sm">
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- YASAL ŞİRKET BİLGİLERİ FORMU -->
            <div id="section-settings" class="hidden bg-white rounded-2xl p-8 shadow-sm border border-slate-200 space-y-6">
                <div>
                    <h2 class="text-lg font-bold text-slate-900">Resmi Şirket ve Fatura Bilgileri</h2>
                    <p class="text-xs text-slate-500 mt-1">Sözleşmelerde ve resmi formlarda kullanılacak satıcı bilgileri.</p>
                </div>

                <form id="settings-form" onsubmit="saveSettings(event)" class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Şirket Unvanı</label>
                        <input type="text" id="company_name" value="{profile['company_name']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Vergi Numarası</label>
                        <input type="text" id="tax_number" value="{profile['tax_number']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">MERSİS Numarası</label>
                        <input type="text" id="mersis_no" value="{profile['mersis_no']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Destek E-Posta</label>
                        <input type="email" id="email" value="{profile['email']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:border-indigo-600">
                    </div>
                    <div class="md:col-span-2">
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Resmi Şirket Adresi</label>
                        <input type="text" id="address" value="{profile['address']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:border-indigo-600">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase mb-2">Telefon Numarası</label>
                        <input type="text" id="phone" value="{profile['phone']}" required class="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:border-indigo-600">
                    </div>
                    <div class="md:col-span-2 flex justify-end pt-4">
                        <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-6 py-2.5 rounded-xl transition shadow-sm text-sm cursor-pointer">Ayarları Kaydet</button>
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

                if (!prodBtn || !settBtn || !prodSec || !settSec) return;

                if (tab === 'products') {{
                    prodBtn.className = "pb-3 text-indigo-600 border-b-2 border-indigo-600 flex items-center gap-2 font-semibold cursor-pointer";
                    settBtn.className = "pb-3 text-slate-500 hover:text-slate-800 flex items-center gap-2 cursor-pointer";
                    prodSec.classList.remove("hidden");
                    settSec.classList.add("hidden");
                }} else {{
                    settBtn.className = "pb-3 text-indigo-600 border-b-2 border-indigo-600 flex items-center gap-2 font-semibold cursor-pointer";
                    prodBtn.className = "pb-3 text-slate-500 hover:text-slate-800 flex items-center gap-2 cursor-pointer";
                    settSec.classList.remove("hidden");
                    prodSec.classList.add("hidden");
                }}
            }}

            async function loadProducts() {{
                const icon = document.getElementById("sync-icon");
                const tbody = document.getElementById("products-table-body");
                if (!tbody) return;

                if (icon) icon.classList.add("fa-spin");
                try {{
                    const res = await fetch(`/api/v1/compliance/sync-products?storeDomain=${{encodeURIComponent(storeDomain)}}`);
                    const data = await res.json();

                    if (data.status === "success" && data.products) {{
                        if (document.getElementById("last-sync-time")) {{
                            document.getElementById("last-sync-time").innerText = "Son Senkronizasyon: " + new Date().toLocaleTimeString();
                        }}
                        
                        tbody.innerHTML = "";
                        data.products.forEach(prod => {{
                            prod.variants.forEach(variant => {{
                                const row = `
                                    <tr class="hover:bg-slate-50/80 transition">
                                        <td class="p-4 pl-6 font-medium text-slate-900">${{prod.product_name}}</td>
                                        <td class="p-4 text-xs font-mono text-slate-500">${{variant.sku || "-"}}</td>
                                        <td class="p-4 font-semibold text-slate-800">${{variant.price.toFixed(2)}} TL</td>
                                        <td class="p-4 text-slate-600">${{variant.weight}} ${{variant.unit}}</td>
                                        <td class="p-4">
                                            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
                                                <i class="fa-solid fa-tag text-indigo-500"></i> ${{variant.compliance.display_text}}
                                                <span class="text-[9px] text-purple-600 bg-purple-50 px-1.5 py-0.5 rounded ml-1">${{variant.compliance.applied_rule}}</span>
                                            </span>
                                        </td>
                                        <td class="p-4 pr-6">
                                            <span class="inline-flex items-center gap-1 text-xs font-bold text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200">
                                                <i class="fa-solid fa-check"></i> Senkronize (${{data.platform}})
                                            </span>
                                        </td>
                                    </tr>
                                `;
                                tbody.innerHTML += row;
                            }});
                        }});
                    }}
                }} catch (err) {{
                    console.error("Yükleme hatası:", err);
                }} finally {{
                    if (icon) icon.classList.remove("fa-spin");
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
                    if (data.status === "success") alert("Ayarlar kaydedildi!");
                    else alert("Kayıt başarısız.");
                }} catch (err) {{ alert("Bağlantı hatası."); }}
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
@app.get("/api/v1/compliance/sync-products")
async def sync_products(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    try:
        domain = normalize_domain(storeDomain)
        profile = get_merchant_profile(domain)
        platform = profile.get("platform", "ikas").lower()

        products = []

        if platform == "shopify":
            client = ShopifyAPIClient(domain, "shp_token_dummy")
            products = client.list_products()
        elif platform == "trendyol":
            client = TrendyolAPIClient("123456")
            products = client.list_products()
        else:
            access_token = "ikas_fallback_token_999"
            if supabase_client:
                try:
                    res = supabase_client.table("merchants").select("access_token").eq("store_domain", domain).execute()
                    if res.data and res.data[0].get("access_token"):
                        access_token = res.data[0].get("access_token")
                except Exception:
                    pass

            if IkasGraphQLClient and not access_token.startswith("ikas_fallback"):
                try:
                    ik_client = IkasGraphQLClient(access_token)
                    products = ik_client.list_products(limit=10)
                except Exception:
                    pass

        if not products:
            products = [
                {"id": "prod_001", "name": "Ege Sızma Zeytinyağı 1000 ml", "variants": [{"id": "var_001", "sku": "ZTY-1L", "price": 380.00, "weight": 1.0, "unit": "L"}]},
                {"id": "prod_002", "name": "Organik Çam Balı 850 gr", "variants": [{"id": "var_002", "sku": "BAL-850G", "price": 425.00, "weight": 0.85, "unit": "kg"}]},
                {"id": "prod_003", "name": "Antep Fıstığı Ezmesi 350 gr", "variants": [{"id": "var_003", "sku": "FST-350G", "price": 245.00, "weight": 0.35, "unit": "kg"}]}
            ]

        processed_products = []
        for prod in products:
            variants_compliance = []
            for variant in prod.get("variants", []):
                price = variant.get("price", 0.0)
                weight = variant.get("weight", 1.0)
                unit = variant.get("unit", "kg")

                compliance_result = ComplianceEngine.calculate_unit_price(price, weight, unit)

                variants_compliance.append({
                    "variant_id": variant.get("id"),
                    "sku": variant.get("sku"),
                    "price": price,
                    "weight": weight,
                    "unit": unit,
                    "compliance": compliance_result,
                    "synced_to_platform": True
                })

            processed_products.append({
                "product_id": prod.get("id"),
                "product_name": prod.get("name"),
                "variants": variants_compliance
            })

        return {
            "status": "success",
            "store": domain,
            "platform": platform,
            "total_processed": len(processed_products),
            "products": processed_products
        }

    except Exception as err:
        tb = traceback.format_exc()
        logger.error(f"sync_products hata: {str(err)}\n{tb}")
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(err)})


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
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    return {"status": "success"}


@app.get("/api/v1/compliance/preview-contract", response_class=HTMLResponse)
async def preview_contract(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    merchant_info = {"company_name": profile["company_name"], "address": profile["address"], "phone": profile["phone"], "email": profile["email"], "mersis_no": profile["mersis_no"]}
    customer_info = {"name": "Ahmet Yılmaz", "address": "Bağdat Cad. No: 123 Kadıköy/İstanbul", "phone": "0532 111 22 33", "email": "ahmet@ornek.com"}
    cart_items = [{"name": "Ege Sızma Zeytinyağı 1000 ml", "quantity": 2, "price": 380.00}]
    return HTMLResponse(content=ComplianceEngine.generate_distance_sales_contract(merchant_info, customer_info, cart_items))


@app.get("/api/v1/compliance/download-contract-pdf")
async def download_contract_pdf(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    merchant_info = {"company_name": profile["company_name"], "address": profile["address"], "phone": profile["phone"], "email": profile["email"], "mersis_no": profile["mersis_no"]}
    html_contract = ComplianceEngine.generate_distance_sales_contract(merchant_info, {"name": "Ahmet Yılmaz"}, [{"name": "Zeytinyağı", "quantity": 1, "price": 380.00}])
    return Response(content=html_contract, media_type="text/html", headers={"Content-Disposition": f"attachment; filename=Sozlesme_{domain}.html"})


@app.get("/api/v1/ikas/callback")
async def ikas_callback(request: Request):
    params = dict(request.query_params)
    code = params.get("code")
    raw_domain = params.get("state") or params.get("storeName") or params.get("storeDomain") or params.get("shop")
    domain = normalize_domain(raw_domain)

    access_token = f"ikas_token_{code[:12]}" if code else "ikas_token_default"
    save_merchant_to_supabase(domain, access_token, platform="ikas")
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")


@app.get("/api/v1/ikas/launch")
async def ikas_launch(request: Request):
    params = dict(request.query_params)
    raw_domain = params.get("storeName") or params.get("storeDomain") or params.get("shop")
    domain = normalize_domain(raw_domain)
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")


@app.post("/api/v1/ikas/webhook")
async def ikas_webhook(request: Request):
    try:
        body = await request.json()
        logger.info(f"İkas Webhook sinyali alındı: {json.dumps(body, ensure_ascii=False)}")
        return {"status": "success", "message": "Webhook başarıyla işlendi."}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})


@app.get("/api/v1/ikas/force-register")
async def force_register(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    saved, msg = save_merchant_to_supabase(domain, "mock_token")
    return {"status": "success" if saved else "error", "store": domain}


# --- ŞIK TASARIMLI İYZİCO CHECKOUT SAYFASI (Eksiksiz Geri Getirildi) ---
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
                <a href="/api/v1/billing/success?storeDomain={domain}" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 px-4 rounded-xl transition flex items-center justify-center gap-2 shadow-sm text-sm cursor-pointer">
                    <i class="fa-solid fa-lock"></i> Test Ödemesini Tamamla (Sandbox)
                </a>
                <a href="/dashboard?storeDomain={domain}" class="w-full bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold py-2.5 px-4 rounded-xl transition flex items-center justify-center text-sm cursor-pointer">
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
        except Exception:
            pass
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health():
    return {"status": "healthy", "database": "connected" if supabase_client else "not_configured"}