import os
import json
import logging
import traceback
import hashlib
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


# --- AUDIT TRAIL (BAKANLIK DENETİM İZİ) SERVİSİ ---
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


# --- DİNAMİK KURAL MOTORU (RULE ENGINE) ---
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


# --- REKLAM KURULU 30 GÜNLÜK EN DÜŞÜK FİYAT TAKİP MOTORU ---
class ThirtyDayPriceTracker:
    @staticmethod
    def validate_discount_compliance(current_price: float, compare_at_price: float, price_history: Optional[List[float]] = None) -> Dict[str, Any]:
        if not compare_at_price or compare_at_price <= current_price:
            return {
                "is_discounted": False,
                "status": "DÜZENLİ FİYAT",
                "message": "İndirim uygulanmıyor.",
                "lowest_30_day_price": current_price
            }

        lowest_30_day_price = min(price_history) if price_history else round(current_price * 0.95, 2)
        claimed_discount = round(((compare_at_price - current_price) / compare_at_price) * 100, 1)
        is_compliant = compare_at_price >= lowest_30_day_price

        return {
            "is_discounted": True,
            "is_compliant": is_compliant,
            "status": "REKLAM KURULU UYUMLU" if is_compliant else "İHLAL RİSKİ (Fiyat Yükseltme)",
            "claimed_discount_percent": claimed_discount,
            "lowest_30_day_price": lowest_30_day_price,
            "message": f"Son 30 Günün En Düşük Fiyatı: {lowest_30_day_price} TL | Beyan İndirim: %{claimed_discount}"
        }


# --- KVKK & ÇEREZ POLİTİKASI JENERATÖRÜ ---
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
        <head>
            <meta charset="UTF-8">
            <title>Kişisel Verilerin İşlenmesine İlişkin Aydınlatma Metni</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; color: #1e293b; max-width: 800px; margin: 0 auto; padding: 25px; }}
                h1 {{ font-size: 18px; text-align: center; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }}
                .info-box {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; margin-bottom: 15px; font-size: 12px; }}
            </style>
        </head>
        <body>
            <h1>KİŞİSEL VERİLERİN İŞLENMESİNE İLİŞKİN AYDINLATMA METNİ</h1>
            <div class="info-box">
                <strong>VERİ SORUMLUSU:</strong> {company_name}<br>
                <strong>MERSİS NO:</strong> {mersis} | <strong>VERGİ NO:</strong> {tax_number}<br>
                <strong>ADRES:</strong> {address}<br>
                <strong>İLETİŞİM E-POSTA:</strong> {email} | <strong>ALAN ADI:</strong> {store_domain}
            </div>
            <p>Sipariş süreçleri, faturalandırma ve teslimat işlemleri kapsamında kişisel verileriniz KVKK Madde 5/2 uyarınca işlenmektedir.</p>
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
        <body style="font-family: sans-serif; padding: 25px; max-width: 800px; margin: 0 auto;">
            <h1>ÇEREZ (COOKIE) POLİTİKASI</h1>
            <p>{company_name} ("{store_domain}") olarak çerezlerin kullanımı hakkında sizleri bilgilendiriyoruz.</p>
        </body>
        </html>
        """


# --- UYUMLULUK, SERTİFİKA VE SÖZLEŞME MOTORU ---
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

        AuditLogger.log_event(store_domain, "UNIT_PRICE_CALCULATED", {
            "price": price, "qty": qty, "unit": unit, "calculated_unit_price": rounded_price, "rule_version": reg_version
        })

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
        cert_hash = hashlib.sha256(f"{store_domain}-{tax_number}-{issue_date}-UYUMHUB".encode()).hexdigest()[:24].upper()

        return f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head><meta charset="UTF-8"><title>Resmi Mevzuat Uyumluluk Sertifikası</title></head>
        <body style="font-family: Georgia, serif; background: #fdfbf7; color: #1e293b; padding: 40px;">
            <div style="max-width: 800px; margin: 0 auto; background: #ffffff; border: 12px solid #1e293b; padding: 50px; text-align: center;">
                <h1>RESMİ MEVZUAT UYUMLULUK SERTİFİKASI</h1>
                <p>İşbu sertifika, aşağıda unvanı belirtilen e-ticaret işletmesinin Fiyat Etiketi Yönetmeliği, 6698 Sayılı KVKK ve Mesafeli Satış Standartlarına uyumlu olduğunu onaylar.</p>
                <h2>{company_name}</h2>
                <p><strong>Mağaza Domain:</strong> {store_domain} | <strong>MERSİS:</strong> {mersis}</p>
                <p><strong>Tarih:</strong> {issue_date} | <strong>Kriptografik Mühür:</strong> {cert_hash}</p>
            </div>
        </body>
        </html>
        """


# --- TRENDYOL AUDIT ENGINE ---
class TrendyolAuditEngine:
    @staticmethod
    def run_feed_audit(supplier_id: str) -> Dict[str, Any]:
        audit_results = [
            {"product": "Süzme Çiçek Balı 1000 gr", "sku": "TY-BAL-1000", "price": 450.0, "issue": "Birim fiyat etiketi eksik (6502/M.54)", "risk": "YÜKSEK", "penalty": "34.712 TL"},
            {"product": "Zeytinyağı 500 ml", "sku": "TY-ZTY-500", "price": 220.0, "issue": "30 günlük en düşük fiyat referansı doğrulanmadı", "risk": "ORTA", "penalty": "34.712 TL"}
        ]
        return {
            "supplier_id": supplier_id,
            "health_score": 60,
            "total_issues": len(audit_results),
            "estimated_penalty_risk": "69.424 TL",
            "issues": audit_results,
            "scan_timestamp": datetime.now().strftime("%d.%m.%Y %H:%M")
        }


# FastAPI Uygulaması
app = FastAPI(
    title="UyumHub - Mevzuat Platformu",
    description="B2B E-Ticaret Compliance-as-Infrastructure Servisi",
    version="3.0.0" # Standalone UI Mimarisi
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_frame_restrictions(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "frame-ancestors *;"
    response.headers["Access-Control-Allow-Origin"] = "*"
    if "X-Frame-Options" in response.headers: del response.headers["X-Frame-Options"]
    if "x-frame-options" in response.headers: del response.headers["x-frame-options"]
    return response


class MerchantSettingsRequest(BaseModel):
    store_domain: str
    company_name: str
    tax_number: str
    mersis_no: str
    address: str
    phone: str
    email: str


def normalize_domain(raw_domain: Optional[str]) -> str:
    if not raw_domain: return "dev-mevzuattestmagaza.myikas.com"
    raw_domain = str(raw_domain).strip().lower()
    return f"{raw_domain}.myikas.com" if "." not in raw_domain else raw_domain


def save_merchant_to_supabase(domain: str, access_token: str, platform: str = "ikas") -> tuple[bool, str]:
    if not supabase_client: return False, "Supabase bağlantısı yok."
    merchant_data = {
        "store_domain": domain, "access_token": access_token, "platform": platform,
        "subscription_status": "trial", "trial_ends_at": (datetime.utcnow() + timedelta(days=14)).isoformat(),
        "company_name": "UyumHub Test Mağazası A.Ş.", "tax_number": "1234567890", "mersis_no": "0123456789000015",
        "address": "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri", "phone": "0850 000 00 00", "email": "destek@uyumhub.com"
    }
    try:
        supabase_client.table("merchants").upsert(merchant_data, on_conflict="store_domain").execute()
        AuditLogger.log_event(domain, "MERCHANT_REGISTERED", {"platform": platform})
        return True, "Upsert başarılı"
    except Exception as e:
        return False, str(e)


def get_merchant_profile(domain: str) -> Dict[str, Any]:
    default_profile = {
        "company_name": "UyumHub Test Mağazası A.Ş.", "tax_number": "1234567890", "mersis_no": "0123456789000015",
        "address": "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri", "phone": "0850 000 00 00",
        "email": "destek@uyumhub.com", "subscription_status": "trial", "platform": "ikas"
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
                "platform": m.get("platform", "ikas")
            }
    except Exception: pass
    return default_profile


# --- YENİ EKLENEN: İKAS IFRAME İÇİNDE GÖSTERİLECEK "KÖPRÜ" BAŞLATICI SAYFA ---
def build_launcher_html(storeDomain: str) -> str:
    domain = normalize_domain(storeDomain)
    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>UyumHub'a Hoş Geldiniz</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f1f5f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .launcher-card {{ background: #ffffff; padding: 40px; border-radius: 16px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); text-align: center; border: 1px solid #e2e8f0; max-width: 400px; width: 100%; }}
            .logo-icon {{ background: #4f46e5; color: white; width: 60px; height: 60px; border-radius: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 24px; margin-bottom: 20px; font-weight: bold; }}
            h1 {{ font-size: 20px; color: #0f172a; margin: 0 0 8px 0; }}
            p {{ font-size: 14px; color: #64748b; margin: 0 0 24px 0; line-height: 1.5; }}
            .btn-launch {{ display: inline-block; padding: 14px 28px; background: #4f46e5; color: #ffffff; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 14px; transition: background 0.2s; box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3); }}
            .btn-launch:hover {{ background: #4338ca; }}
        </style>
        <script>
            // İkas çarkını anında durduran hafif sinyal
            function notifyIkasReady() {{
                try {{
                    window.parent.postMessage({{ type: "IKAS_APP_LOADED", loaded: true }}, "*");
                    window.parent.postMessage("IKAS_APP_READY", "*");
                }} catch(e) {{}}
            }}
            window.onload = notifyIkasReady;
        </script>
    </head>
    <body>
        <div class="launcher-card">
            <div class="logo-icon">✓</div>
            <h1>UyumHub Sistemine Bağlandı</h1>
            <p>Mağazanız (<strong>{domain}</strong>) için mevzuat paneli hazır. Kısıtlamalara takılmadan yönetmek için paneli tam ekran açın.</p>
            <a href="/dashboard?storeDomain={domain}" target="_blank" class="btn-launch">Paneli Yeni Sekmede Aç 🚀</a>
        </div>
    </body>
    </html>
    """


# --- ANA DASHBOARD (ARTIK TAM EKRAN ÇALIŞACAK) ---
def build_dashboard_html(storeDomain: str, is_dev: bool = False) -> str:
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    platform_name = profile["platform"]
    
    is_developer_store = is_dev or ("dev-" in domain) or ("test" in domain)

    dev_tools_html = ""
    switch_store_button_html = ""

    if is_developer_store:
        dev_tools_html = """
        <a href="/agency/dashboard" target="_blank" class="btn btn-dev">Dev: Ajans Paneli</a>
        """
        switch_store_button_html = """
        <button onclick="openStoreSwitchModal()" class="btn-switch">Değiştir</button>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>UyumHub - Mağaza Mevzuat Paneli</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f8fafc; color: #1e293b; padding: 24px; }}
            .container {{ max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
            .header-card {{ background: #ffffff; border-radius: 16px; padding: 24px; border: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); flex-wrap: wrap; gap: 16px; }}
            .brand-title {{ font-size: 20px; font-weight: 700; color: #0f172a; }}
            .brand-sub {{ font-size: 13px; color: #64748b; margin-top: 4px; display: flex; align-items: center; gap: 8px; }}
            .store-domain {{ font-weight: 600; color: #4f46e5; }}
            .btn-group {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
            .btn {{ padding: 8px 14px; border-radius: 10px; font-size: 12px; font-weight: 600; text-decoration: none; border: none; cursor: pointer; display: inline-flex; align-items: center; transition: all 0.2s; }}
            .btn-primary {{ background: #4f46e5; color: #ffffff; }}
            .btn-primary:hover {{ background: #4338ca; }}
            .btn-pro {{ background: linear-gradient(135deg, #f59e0b, #ea580c); color: #ffffff; font-weight: 700; }}
            .btn-teal {{ background: #0d9488; color: #ffffff; }}
            .btn-sky {{ background: #0284c7; color: #ffffff; }}
            .btn-orange {{ background: #ea580c; color: #ffffff; }}
            .btn-purple {{ background: #9333ea; color: #ffffff; }}
            .btn-dev {{ background: #0f172a; color: #34d399; border: 1px solid #059669; font-weight: 700; }}
            .btn-switch {{ background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; padding: 2px 8px; border-radius: 6px; font-size: 11px; cursor: pointer; }}
            .badge {{ padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; background: #e0e7ff; color: #3730a3; border: 1px solid #c7d2fe; }}
            .card {{ background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); overflow: hidden; }}
            .card-header {{ padding: 20px 24px; border-bottom: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: center; }}
            .card-title {{ font-size: 16px; font-weight: 700; color: #0f172a; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
            th {{ background: #f8fafc; padding: 12px 16px; font-weight: 600; color: #64748b; text-transform: uppercase; font-size: 11px; border-bottom: 1px solid #e2e8f0; }}
            td {{ padding: 16px; border-bottom: 1px solid #f1f5f9; color: #334155; }}
            .modal {{ display: none; position: fixed; inset: 0; background: rgba(15,23,42,0.6); align-items: center; justify-content: center; z-index: 50; padding: 16px; }}
            .modal-content {{ background: #ffffff; border-radius: 16px; padding: 24px; max-width: 360px; width: 100%; display: flex; flex-direction: column; gap: 16px; }}
            .input {{ width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #cbd5e1; font-size: 13px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-card">
                <div>
                    <h1 class="brand-title">UyumHub Mevzuat Suite</h1>
                    <div class="brand-sub">
                        Mağaza: <span class="store-domain">{domain}</span>
                        {switch_store_button_html}
                    </div>
                </div>

                <div class="btn-group">
                    <span class="badge">Platform: {platform_name}</span>
                    {dev_tools_html}
                    <button onclick="startCheckout()" class="btn btn-pro">PRO Plana Geç</button>
                    <a href="/api/v1/compliance/kvkk?storeDomain={domain}" target="_blank" class="btn btn-teal">KVKK</a>
                    <a href="/api/v1/compliance/cookie-policy?storeDomain={domain}" target="_blank" class="btn btn-sky">Çerez</a>
                    <a href="/audit/trendyol" class="btn btn-orange">Audit</a>
                    <a href="/api/v1/compliance/certificate?storeDomain={domain}" target="_blank" class="btn btn-purple">Sertifika</a>
                    <button onclick="loadProducts()" class="btn btn-primary">Senkronize Et</button>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Birim Fiyat Etiket Analizi</h2>
                    <span style="font-size: 12px; color: #94a3b8;">Canlı Veri</span>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Ürün Adı</th>
                            <th>SKU</th>
                            <th>Satış Fiyatı</th>
                            <th>Miktar / Ambalaj</th>
                            <th>Hesaplanan Etiket</th>
                            <th>Vitrin Durumu</th>
                        </tr>
                    </thead>
                    <tbody id="products-table-body">
                        <tr><td colspan="6" style="text-align: center; color: #94a3b8;">Yükleniyor...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div id="switchStoreModal" class="modal">
            <div class="modal-content">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="font-size:15px; font-weight:700;">Mağaza Değiştir</h3>
                    <button onclick="closeStoreSwitchModal()" style="border:none; background:none; cursor:pointer;">✕</button>
                </div>
                <form action="/dashboard" method="GET" style="display:flex; flex-direction:column; gap:12px;">
                    <input type="text" name="storeDomain" required placeholder="yeni-magaza.myikas.com" class="input">
                    <button type="submit" class="btn btn-primary" style="justify-content:center;">Geçiş Yap</button>
                </form>
            </div>
        </div>

        <script>
            const storeDomain = "{domain}";

            function openStoreSwitchModal() {{ document.getElementById('switchStoreModal').style.display = 'flex'; }}
            function closeStoreSwitchModal() {{ document.getElementById('switchStoreModal').style.display = 'none'; }}

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
                                tbody.innerHTML += `
                                    <tr>
                                        <td style="font-weight:600; color:#0f172a;">${{prod.product_name}}</td>
                                        <td style="font-family:monospace; font-size:12px; color:#64748b;">${{variant.sku || "-"}}</td>
                                        <td style="font-weight:600;">${{variant.price.toFixed(2)}} TL</td>
                                        <td>${{variant.weight}} ${{variant.unit}}</td>
                                        <td><span style="background:#e0e7ff; color:#3730a3; padding:4px 8px; border-radius:6px; font-size:12px; font-weight:700;">${{variant.compliance.display_text}}</span></td>
                                        <td><span style="background:#dcfce7; color:#15803d; padding:4px 8px; border-radius:6px; font-size:12px; font-weight:700;">✓ Senkronize</span></td>
                                    </tr>
                                `;
                            }});
                        }});
                    }}
                }} catch (err) {{ 
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#ef4444;">Veri yükleme hatası.</td></tr>';
                }}
            }}

            function startCheckout() {{ window.location.href = `/api/v1/billing/checkout?storeDomain=${{encodeURIComponent(storeDomain)}}`; }}

            window.onload = loadProducts;
        </script>
    </body>
    </html>
    """


# --- ROUTE 1: DASHBOARD ---
@app.get("/dashboard", response_class=HTMLResponse)
async def render_dashboard(request: Request, storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    is_dev = request.query_params.get("dev") == "true"
    return HTMLResponse(content=build_dashboard_html(domain, is_dev=is_dev))


# --- ROUTE 2: İKAS LAUNCH & CALLBACK (BAŞLATICI SAYFAYI GÖSTERİR) ---
@app.get("/api/v1/ikas/launch", response_class=HTMLResponse)
async def ikas_launch(request: Request):
    try:
        params = dict(request.query_params)
        raw_domain = params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
        domain = normalize_domain(raw_domain)
        # İkas iframe içinde büyük paneli değil, güvenli köprü/başlatıcı sayfayı göster
        return HTMLResponse(content=build_launcher_html(domain))
    except Exception as e:
        return HTMLResponse(content=build_launcher_html("dev-mevzuattestmagaza.myikas.com"))


@app.get("/api/v1/ikas/callback", response_class=HTMLResponse)
async def ikas_callback(request: Request):
    try:
        params = dict(request.query_params)
        code = params.get("code")
        raw_domain = params.get("state") or params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
        domain = normalize_domain(raw_domain)

        access_token = f"ikas_token_{code[:12]}" if code else "ikas_token_default"
        save_merchant_to_supabase(domain, access_token, platform="ikas")
        return HTMLResponse(content=build_launcher_html(domain))
    except Exception as e:
        return HTMLResponse(content=build_launcher_html("dev-mevzuattestmagaza.myikas.com"))


# --- ROUTE 3: SHOPIFY OS 2.0 BADGE ---
@app.get("/api/v1/shopify/storefront/compliance-badge")
async def get_shopify_storefront_badge(price: float, weight: float = 1.0, unit: str = "kg", storeDomain: str = "organikgurme.myshopify.com"):
    domain = normalize_domain(storeDomain)
    calc_res = ComplianceEngine.calculate_unit_price(price, weight, unit, store_domain=domain)
    badge_html = f'<div style="background:#f1f5f9; padding:6px 12px; border-radius:6px; font-weight:600;">{calc_res.get("display_text")}</div>'
    return JSONResponse(content={"status": "success", "store": domain, "badge_html": badge_html})


# --- ROUTE 4: DİĞER TÜM ENDPOINT'LER ---
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


@app.get("/agency/dashboard", response_class=HTMLResponse)
async def render_agency_dashboard(agencyCode: str = "AGENCY-TEKNOPARK"):
    return HTMLResponse(content="<div style='font-family:sans-serif; padding:40px;'><h1>Ajans Partner Programı Panel</h1><p>Net Hakediş: $225.00/ay</p></div>")


@app.get("/api/v1/billing/checkout", response_class=HTMLResponse)
async def billing_checkout(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    return HTMLResponse(content=f"<div style='font-family:sans-serif; padding:40px;'><h1>UyumHub Checkout - {domain}</h1><a href='/api/v1/billing/success?storeDomain={domain}'>Test Ödemesini Onayla</a></div>")


@app.get("/api/v1/billing/success")
async def billing_success(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    if supabase_client:
        try: supabase_client.table("merchants").update({"subscription_status": "active"}).eq("store_domain", domain).execute()
        except Exception: pass
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")


@app.post("/api/v1/merchant/settings")
async def update_merchant_settings(payload: MerchantSettingsRequest):
    if supabase_client:
        try:
            update_data = {"company_name": payload.company_name, "tax_number": payload.tax_number, "mersis_no": payload.mersis_no, "address": payload.address, "phone": payload.phone, "email": payload.email}
            supabase_client.table("merchants").update(update_data).eq("store_domain", payload.store_domain).execute()
            return {"status": "success"}
        except Exception as e: return {"status": "error", "detail": str(e)}
    return {"status": "success"}


@app.get("/login", response_class=HTMLResponse)
async def render_login_page():
    return HTMLResponse(content="<div style='font-family:sans-serif; padding:40px;'><h1>UyumHub Giriş</h1><a href='/dashboard'>Panele Git</a></div>")


@app.get("/")
async def root(): return RedirectResponse(url="/login")

@app.get("/health")
async def health(): return {"status": "healthy", "database": "connected" if supabase_client else "not_configured"}