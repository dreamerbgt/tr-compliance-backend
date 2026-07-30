import os
import json
import logging
import traceback
import hashlib
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


# --- AUDIT TRAIL SERVİSİ ---
class AuditLogger:
    @staticmethod
    def log_event(store_domain: str, event_type: str, details: Dict[str, Any]):
        log_payload = {
            "store_domain": store_domain,
            "event_type": event_type,
            "details": json.dumps(details, ensure_ascii=False),
            "created_at": datetime.utcnow().isoformat()
        }
        logger.info(f"[AUDIT TRAIL] {store_domain} -> {event_type}: {details}")
        if supabase_client:
            try:
                supabase_client.table("audit_logs").insert(log_payload).execute()
            except Exception as e:
                logger.error(f"Audit log yazılamadı: {str(e)}")


# --- DİNAMİK KURAL MOTORU ---
class DynamicRuleEngine:
    @staticmethod
    def get_active_rule(unit: str) -> Dict[str, Any]:
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
            logger.warning(f"Dinamik kural okunamadı: {str(e)}")
        return default_rule


# --- KVKK & UYUMLULUK MOTORU ---
class KVKKEngine:
    @staticmethod
    def generate_kvkk_notice(merchant_info: Dict[str, Any], store_domain: str) -> str:
        company_name = merchant_info.get("company_name", "UyumHub Test Mağazası A.Ş.")
        tax_number = merchant_info.get("tax_number", "1234567890")
        mersis = merchant_info.get("mersis_no", "0123456789000015")
        address = merchant_info.get("address", "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri")
        email = merchant_info.get("email", "destek@uyumhub.com")

        return f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head><meta charset="UTF-8"><title>KVKK Aydınlatma Metni</title></head>
        <body style="font-family: Arial, sans-serif; padding: 25px; color: #1e293b;">
            <h1>KİŞİSEL VERİLERİN İŞLENMESİNE İLİŞKİN AYDINLATMA METNİ</h1>
            <p><strong>Veri Sorumlusu:</strong> {company_name} (MERSİS: {mersis})</p>
            <p><strong>Adres:</strong> {address} | <strong>E-Posta:</strong> {email}</p>
        </body>
        </html>
        """

    @staticmethod
    def generate_cookie_policy(merchant_info: Dict[str, Any], store_domain: str) -> str:
        company_name = merchant_info.get("company_name", "UyumHub Test Mağazası A.Ş.")
        return f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head><meta charset="UTF-8"><title>Çerez Politikası</title></head>
        <body style="font-family: Arial, sans-serif; padding: 25px;">
            <h1>ÇEREZ POLİTİKASI</h1>
            <p>{company_name} ("{store_domain}") mağazamızda kullanılan çerezler hakkında bilgilendirme.</p>
        </body>
        </html>
        """


class ComplianceEngine:
    @staticmethod
    def calculate_unit_price(price: float, weight_or_volume: float = None, unit: str = "kg", store_domain: str = "system", *args, **kwargs):
        qty = weight_or_volume or kwargs.get("weight") or 1.0
        try:
            price = float(price)
            qty = float(qty)
        except (ValueError, TypeError):
            return {"has_error": True, "message": "Geçersiz fiyat veya miktar."}

        if qty <= 0:
            return {"has_error": True, "message": "Geçersiz miktar/hacim."}

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
    def generate_compliance_certificate(merchant_info: Dict[str, Any], store_domain: str) -> str:
        company_name = merchant_info.get("company_name", "UyumHub Test Mağazası A.Ş.")
        tax_number = merchant_info.get("tax_number", "1234567890")
        mersis = merchant_info.get("mersis_no", "0123456789000015")
        issue_date = datetime.now().strftime("%d.%m.%Y")
        cert_hash = hashlib.sha256(f"{store_domain}-{tax_number}-{issue_date}".encode()).hexdigest()[:24].upper()

        return f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head><meta charset="UTF-8"><title>Resmi Sertifika</title></head>
        <body style="font-family: Georgia, serif; text-align: center; padding: 40px; background: #fdfbf7;">
            <div style="border: 10px solid #1e293b; padding: 40px; background: #fff;">
                <h1>RESMİ MEVZUAT UYUMLULUK SERTİFİKASI</h1>
                <h2>{company_name}</h2>
                <p>Alan Adı: {store_domain} | MERSİS: {mersis}</p>
                <p>Kriptografik Mühür: {cert_hash}</p>
            </div>
        </body>
        </html>
        """


class TrendyolAuditEngine:
    @staticmethod
    def run_feed_audit(supplier_id: str) -> Dict[str, Any]:
        return {
            "supplier_id": supplier_id,
            "health_score": 60,
            "estimated_penalty_risk": "69.424 TL",
            "issues": [{"product": "Süzme Çiçek Balı 1000 gr", "issue": "Birim fiyat etiketi eksik"}]
        }


# FastAPI Uygulaması
app = FastAPI(
    title="UyumHub - Mevzuat Platformu",
    description="B2B E-Ticaret Compliance Servisi",
    version="2.3.0"
)

# CORS Ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- CRITICAL FIX: İKAS IFRAME YÜKLEME ENGELİNİ KALDIRAN MIDDLEWARE ---
@app.middleware("http")
async def disable_frame_restrictions(request: Request, call_next):
    response = await call_next(request)
    # İkas iframe engelini kesin olarak kaldırır
    response.headers["Content-Security-Policy"] = "frame-ancestors *;"
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    if "x-frame-options" in response.headers:
        del response.headers["x-frame-options"]
    return response


def normalize_domain(raw_domain: Optional[str]) -> Optional[str]:
    if not raw_domain: return "dev-mevzuattestmagaza.myikas.com"
    raw_domain = raw_domain.strip().lower()
    return f"{raw_domain}.myikas.com" if "." not in raw_domain else raw_domain


def save_merchant_to_supabase(domain: str, access_token: str, platform: str = "ikas") -> tuple[bool, str]:
    if not supabase_client: return False, "Supabase yok."
    merchant_data = {
        "store_domain": domain, "access_token": access_token, "platform": platform,
        "subscription_status": "trial", "company_name": "UyumHub Test Mağazası A.Ş.",
        "tax_number": "1234567890", "mersis_no": "0123456789000015",
        "address": "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri", "phone": "0850 000 00 00", "email": "destek@uyumhub.com"
    }
    try:
        supabase_client.table("merchants").upsert(merchant_data, on_conflict="store_domain").execute()
        return True, "Başarılı"
    except Exception as e:
        return False, str(e)


def get_merchant_profile(domain: str) -> Dict[str, Any]:
    default_profile = {
        "company_name": "UyumHub Test Mağazası A.Ş.", "tax_number": "1234567890", "mersis_no": "0123456789000015",
        "address": "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri", "phone": "0850 000 00 00",
        "email": "destek@uyumhub.com", "subscription_status": "trial", "platform": "ikas", "plan": "UyumHub Pro Paket"
    }
    if not supabase_client: return default_profile
    try:
        res = supabase_client.table("merchants").select("*").eq("store_domain", domain).execute()
        if res.data:
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
                "plan": "UyumHub Pro Paket"
            }
    except Exception: pass
    return default_profile


# --- HTML BUILDER (DEV vs NORMAL KULLANICI AYRIMI) ---
def build_dashboard_html(storeDomain: str, is_dev: bool = False) -> str:
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    platform_name = profile["platform"]
    
    # Sadece geliştirici veya test mağazalarında görünecek araçlar
    is_developer_store = is_dev or ("dev-" in domain) or ("test" in domain)

    dev_tools_html = ""
    switch_store_button_html = ""

    if is_developer_store:
        dev_tools_html = """
        <a href="/agency/dashboard" target="_blank" class="bg-slate-900 hover:bg-slate-800 text-emerald-400 text-xs font-bold px-3 py-2 rounded-xl transition border border-emerald-500/30 flex items-center gap-1">
            <i class="fa-solid fa-code"></i> Dev: Ajans Paneli
        </a>
        """
        switch_store_button_html = """
        <button onclick="openStoreSwitchModal()" class="text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium px-2 py-0.5 rounded border border-slate-300 transition">
            <i class="fa-solid fa-arrows-rotate text-[10px]"></i> Değiştir
        </button>
        """

    status_badge = f'<span class="px-3 py-1 rounded-full text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-200 uppercase">Platform: {platform_name}</span>'
    if profile["subscription_status"] == "active":
        status_badge += ' <span class="px-3 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">PRO (Aktif)</span>'
    else:
        status_badge += ' <span class="px-3 py-1 rounded-full text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">Deneme Süresi</span>'

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>UyumHub - Mağaza Mevzuat Paneli</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            
            <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div class="flex items-center gap-4">
                    <div class="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-2xl font-bold shadow-indigo-200 shadow-lg">
                        <i class="fa-solid fa-shield-halved"></i>
                    </div>
                    <div>
                        <h1 class="text-xl font-bold text-slate-900">UyumHub Mevzuat Suite</h1>
                        <p class="text-sm text-slate-500 flex items-center gap-2">
                            Mağaza: <span class="font-semibold text-indigo-600">{domain}</span>
                            {switch_store_button_html}
                        </p>
                    </div>
                </div>

                <div class="flex items-center gap-2 flex-wrap">
                    {status_badge}
                    {dev_tools_html}
                    <button onclick="startCheckout()" class="bg-gradient-to-r from-amber-500 to-orange-600 text-white text-xs font-bold px-3 py-2 rounded-xl transition cursor-pointer">
                        <i class="fa-solid fa-credit-card"></i> PRO Plana Geç
                    </button>
                    <a href="/api/v1/compliance/kvkk?storeDomain={domain}" target="_blank" class="bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">KVKK</a>
                    <a href="/api/v1/compliance/cookie-policy?storeDomain={domain}" target="_blank" class="bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">Çerez</a>
                    <a href="/audit/trendyol" class="bg-orange-600 hover:bg-orange-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">Audit</a>
                    <a href="/api/v1/compliance/certificate?storeDomain={domain}" target="_blank" class="bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">Sertifika</a>
                    <button onclick="runSync()" id="sync-btn" class="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition cursor-pointer">Senkronize Et</button>
                </div>
            </div>

            <div id="section-products" class="space-y-6">
                <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
                    <div class="p-6 border-b border-slate-100 flex justify-between items-center">
                        <h2 class="text-base font-bold text-slate-900">Birim Fiyat Etiket Analizi</h2>
                        <span id="last-sync-time" class="text-xs text-slate-400">Canlı Veri</span>
                    </div>

                    <div class="overflow-x-auto">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-50 border-b border-slate-100 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                                    <th class="p-4 pl-6">Ürün Adı</th>
                                    <th class="p-4">SKU</th>
                                    <th class="p-4">Satış Fiyatı</th>
                                    <th class="p-4">Miktar</th>
                                    <th class="p-4">Hesaplanan Etiket</th>
                                    <th class="p-4 pr-6">Vitrin Durumu</th>
                                </tr>
                            </thead>
                            <tbody id="products-table-body" class="divide-y divide-slate-100 text-sm">
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

        </div>

        <div id="switchStoreModal" class="hidden fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div class="bg-white rounded-2xl p-6 max-w-sm w-full space-y-4 shadow-2xl border border-slate-200">
                <div class="flex justify-between items-center">
                    <h3 class="text-base font-bold text-slate-900">Mağaza Değiştir</h3>
                    <button onclick="closeStoreSwitchModal()"><i class="fa-solid fa-xmark"></i></button>
                </div>
                <form action="/dashboard" method="GET" class="space-y-3">
                    <input type="text" name="storeDomain" required placeholder="yeni-magaza.myikas.com" class="w-full bg-slate-50 border border-slate-300 rounded-xl px-3 py-2 text-sm text-slate-800">
                    <button type="submit" class="w-full bg-indigo-600 text-white font-bold py-2.5 rounded-xl text-sm">Geçiş Yap</button>
                </form>
            </div>
        </div>

        <script>
            const storeDomain = "{domain}";

            function openStoreSwitchModal() {{ 
                const el = document.getElementById('switchStoreModal');
                if(el) el.classList.remove('hidden'); 
            }}
            function closeStoreSwitchModal() {{ 
                const el = document.getElementById('switchStoreModal');
                if(el) el.classList.add('hidden'); 
            }}

            async function loadProducts() {{
                const tbody = document.getElementById("products-table-body");
                if (!tbody) return;

                try {{
                    const res = await fetch(`/api/v1/compliance/sync-products?storeDomain=${{encodeURIComponent(storeDomain)}}`);
                    const data = await res.json();

                    if (data.status === "success" && data.products) {{
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
                                            </span>
                                        </td>
                                        <td class="p-4 pr-6">
                                            <span class="inline-flex items-center gap-1 text-xs font-bold text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200">
                                                <i class="fa-solid fa-check"></i> Senkronize
                                            </span>
                                        </td>
                                    </tr>
                                `;
                                tbody.innerHTML += row;
                            }});
                        }});
                    }}
                }} catch (err) {{ console.error("Hata:", err); }}
            }}

            function runSync() {{ loadProducts(); }}
            function startCheckout() {{ window.location.href = `/api/v1/billing/checkout?storeDomain=${{encodeURIComponent(storeDomain)}}`; }}

            window.onload = loadProducts;
        </script>
    </body>
    </html>
    """


# --- ROUTE 1: DASHBOARD ---
@app.get("/dashboard", response_class=HTMLResponse)
async def render_dashboard(request: Request, storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    is_dev = request.query_params.get("dev") == "true"
    return HTMLResponse(content=build_dashboard_html(storeDomain, is_dev=is_dev))


# --- ROUTE 2: İKAS LAUNCH & CALLBACK (DOĞRUDAN IFRAME RENDER) ---
@app.get("/api/v1/ikas/launch", response_class=HTMLResponse)
async def ikas_launch(request: Request):
    params = dict(request.query_params)
    raw_domain = params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
    domain = normalize_domain(raw_domain)
    return HTMLResponse(content=build_dashboard_html(domain, is_dev=True))


@app.get("/api/v1/ikas/callback", response_class=HTMLResponse)
async def ikas_callback(request: Request):
    params = dict(request.query_params)
    code = params.get("code")
    raw_domain = params.get("state") or params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
    domain = normalize_domain(raw_domain)

    access_token = f"ikas_token_{code[:12]}" if code else "ikas_token_default"
    save_merchant_to_supabase(domain, access_token, platform="ikas")
    return HTMLResponse(content=build_dashboard_html(domain, is_dev=True))


# --- ROUTE 3: DİĞER SAYFALAR & API'LER ---
@app.get("/login", response_class=HTMLResponse)
async def render_login_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="tr">
    <head><meta charset="UTF-8"><title>UyumHub - Giriş</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-900 text-slate-100 font-sans min-h-screen flex items-center justify-center p-4">
        <div class="max-w-md w-full bg-slate-800 rounded-2xl p-8 space-y-6 border border-slate-700">
            <h1 class="text-2xl font-bold text-center">UyumHub Mağaza Paneli</h1>
            <form action="/dashboard" method="GET" class="space-y-4">
                <input type="text" name="storeDomain" required placeholder="ornek.myikas.com" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white">
                <button type="submit" class="w-full bg-indigo-600 font-bold py-3 rounded-xl">Panele Giriş Yap</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/agency/dashboard", response_class=HTMLResponse)
async def render_agency_dashboard(agencyCode: str = "AGENCY-TEKNOPARK"):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head><meta charset="UTF-8"><title>UyumHub - Ajans Paneli</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-900 text-slate-100 font-sans p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            <div class="bg-slate-800 rounded-2xl p-6 border border-slate-700 flex justify-between items-center">
                <h1 class="text-xl font-bold text-white">Ajans Partner Programı Panel</h1>
                <a href="/login" class="bg-slate-700 text-white text-xs px-4 py-2 rounded-xl">Giriş Ekranına Dön</a>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div class="bg-slate-800 rounded-2xl p-6 border border-slate-700"><p class="text-xs text-slate-400">Bağlı Mağaza</p><h3 class="text-3xl font-bold text-white mt-2">18 Mağaza</h3></div>
                <div class="bg-slate-800 rounded-2xl p-6 border border-slate-700"><p class="text-xs text-slate-400">Net Hakediş</p><h3 class="text-3xl font-bold text-emerald-400 mt-2">$225.00 / ay</h3></div>
                <div class="bg-slate-800 rounded-2xl p-6 border border-slate-700"><p class="text-xs text-slate-400">Komisyon Oranı</p><h3 class="text-3xl font-bold text-indigo-400 mt-2">%25 Komisyon</h3></div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/v1/compliance/sync-products")
async def sync_products(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    try:
        domain = normalize_domain(storeDomain)
        profile = get_merchant_profile(domain)
        platform = profile.get("platform", "ikas").lower()

        products = [
            {"id": "prod_001", "name": "Ege Sızma Zeytinyağı 1000 ml", "variants": [{"id": "var_001", "sku": "ZTY-1L", "price": 380.00, "weight": 1.0, "unit": "L"}]},
            {"id": "prod_002", "name": "Organik Çam Balı 850 gr", "variants": [{"id": "var_002", "sku": "BAL-850G", "price": 425.00, "weight": 0.85, "unit": "kg"}]}
        ]

        processed_products = []
        for prod in products:
            variants_compliance = []
            for variant in prod.get("variants", []):
                price = variant.get("price", 0.0)
                weight = variant.get("weight", 1.0)
                unit = variant.get("unit", "kg")
                compliance_result = ComplianceEngine.calculate_unit_price(price, weight, unit, store_domain=domain)

                variants_compliance.append({
                    "variant_id": variant.get("id"),
                    "sku": variant.get("sku"),
                    "price": price,
                    "weight": weight,
                    "unit": unit,
                    "compliance": compliance_result
                })

            processed_products.append({"product_id": prod.get("id"), "product_name": prod.get("name"), "variants": variants_compliance})

        return {"status": "success", "store": domain, "platform": platform, "products": processed_products}
    except Exception as err:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(err)})


@app.get("/api/v1/compliance/kvkk", response_class=HTMLResponse)
async def get_kvkk_notice(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    return HTMLResponse(content=KVKKEngine.generate_kvkk_notice(profile, domain))

@app.get("/api/v1/compliance/cookie-policy", response_class=HTMLResponse)
async def get_cookie_policy(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    return HTMLResponse(content=KVKKEngine.generate_cookie_policy(profile, domain))

@app.get("/api/v1/compliance/certificate", response_class=HTMLResponse)
async def get_compliance_certificate(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    return HTMLResponse(content=ComplianceEngine.generate_compliance_certificate(profile, domain))

@app.get("/audit/trendyol", response_class=HTMLResponse)
async def render_trendyol_audit_page(supplierId: str = "123456"):
    audit_data = TrendyolAuditEngine.run_feed_audit(supplierId)
    return HTMLResponse(content=f"<div style='font-family:sans-serif; padding:40px;'><h1>Trendyol Audit Supplier: {supplierId}</h1><p>Risk: {audit_data['estimated_penalty_risk']}</p></div>")

@app.get("/api/v1/billing/checkout", response_class=HTMLResponse)
async def billing_checkout(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    return HTMLResponse(content=f"<div style='font-family:sans-serif; padding:40px;'><h1>UyumHub Checkout - {domain}</h1><a href='/api/v1/billing/success?storeDomain={domain}'>Test Ödemesini Onayla</a></div>")

@app.get("/api/v1/billing/success")
async def billing_success(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")

@app.get("/")
async def root(): return RedirectResponse(url="/login")

@app.get("/health")
async def health(): return {"status": "healthy", "database": "connected" if supabase_client else "not_configured"}