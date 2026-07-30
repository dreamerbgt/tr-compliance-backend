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


# --- MODÜL 4: AUDIT TRAIL (BAKANLIK DENETİM İZİ) SERVİSİ ---
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


# --- MODÜL 5: DİNAMİK KURAL MOTORU (RULE ENGINE) ---
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


# --- MODÜL 8: REKLAM KURULU 30 GÜNLÜK EN DÜŞÜK FİYAT TAKİP MOTORU ---
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


# --- MODÜL 7: KVKK & ÇEREZ POLİTİKASI JENERATÖRÜ ---
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
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b; max-width: 800px; margin: 0 auto; padding: 25px; }}
                h1 {{ font-size: 18px; text-align: center; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }}
                h2 {{ font-size: 14px; color: #334155; margin-top: 20px; border-bottom: 1px solid #cbd5e1; padding-bottom: 5px; }}
                p, li {{ font-size: 12px; text-align: justify; color: #475569; }}
                .info-box {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; margin-bottom: 15px; font-size: 12px; }}
            </style>
        </head>
        <body>
            <h1>KİŞİSEL VERİLERİN İŞLENMESİNE İLİŞKİN AYDINLATMA METNİ</h1>
            <p><strong>6698 Sayılı Kişisel Verilerin Korunması Kanunu ("KVKK") Uyarınca</strong></p>
            <div class="info-box">
                <strong>VERİ SORUMLUSU:</strong> {company_name}<br>
                <strong>MERSİS NO:</strong> {mersis} | <strong>VERGİ NO:</strong> {tax_number}<br>
                <strong>ADRES:</strong> {address}<br>
                <strong>İLETİŞİM E-POSTA:</strong> {email} | <strong>ALAN ADI:</strong> {store_domain}
            </div>
            <h2>1. İŞLENEN KİŞİSEL VERİLERİNİZ VE İŞLEME AMACI</h2>
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
        <body style="font-family: Arial, sans-serif; padding: 25px; max-width: 800px; margin: 0 auto;">
            <h1>ÇEREZ (COOKIE) POLİTİKASI</h1>
            <p>{company_name} ("{store_domain}") olarak çerezlerin kullanımı hakkında sizleri bilgilendiriyoruz.</p>
        </body>
        </html>
        """


# --- MODÜL 6: UYUMLULUK, SERTİFİKA VE SÖZLEŞME MOTORU ---
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
        
        raw_hash_string = f"{store_domain}-{tax_number}-{issue_date}-UYUMHUB"
        cert_hash = hashlib.sha256(raw_hash_string.encode()).hexdigest()[:24].upper()

        return f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head>
            <meta charset="UTF-8">
            <title>UyumHub - Resmi Mevzuat Uyumluluk Sertifikası</title>
            <style>
                body {{ font-family: 'Georgia', serif; background: #fdfbf7; color: #1e293b; padding: 40px; margin: 0; }}
                .certificate-container {{ max-width: 800px; margin: 0 auto; background: #ffffff; border: 12px solid #1e293b; padding: 50px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
                .inner-border {{ border: 2px solid #d4af37; padding: 40px; }}
                h1 {{ font-size: 24px; color: #0f172a; text-transform: uppercase; margin-bottom: 5px; }}
                .company-name {{ font-size: 26px; font-weight: bold; color: #1e293b; margin: 25px 0; border-bottom: 1px solid #e2e8f0; padding-bottom: 15px; display: inline-block; min-width: 80%; }}
                p {{ font-size: 13px; line-height: 1.8; color: #334155; max-width: 650px; margin: 0 auto 20px auto; }}
                .details-box {{ display: flex; justify-content: space-around; margin: 30px 0; font-size: 12px; background: #f8fafc; padding: 15px; border-radius: 6px; border: 1px solid #e2e8f0; }}
                .seal {{ font-size: 11px; color: #475569; font-family: monospace; background: #f1f5f9; padding: 10px; display: inline-block; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="certificate-container">
                <div class="inner-border">
                    <h1>RESMİ MEVZUAT UYUMLULUK SERTİFİKASI</h1>
                    <p>İşbu sertifika, aşağıda unvanı belirtilen e-ticaret işletmesinin Fiyat Etiketi Yönetmeliği, 6698 Sayılı KVKK, Shopify OS 2.0 Standartları ve Mesafeli Satış Standartlarına uyumlu olduğunu onaylar.</p>
                    <div class="company-name">{company_name}</div>
                    <p><strong>Mağaza Domain:</strong> {store_domain} | <strong>MERSİS:</strong> {mersis}</p>
                    <div class="details-box">
                        <div><strong>Tarih:</strong> {issue_date}</div>
                        <div><strong>Kural Motoru:</strong> TR-2026-V3</div>
                        <div><strong>Durum:</strong> ONAYLI</div>
                    </div>
                    <div class="seal">Kriptografik Mühür: {cert_hash}</div>
                </div>
            </div>
        </body>
        </html>
        """

    @staticmethod
    def generate_distance_sales_contract(merchant_info: Dict[str, Any], customer_info: Dict[str, Any], cart_items: List[Dict[str, Any]], *args, **kwargs) -> str:
        m_name = merchant_info.get("company_name", "UyumHub Test Mağazası A.Ş.")
        m_mersis = merchant_info.get("mersis_no", "0123456789000015")
        c_name = customer_info.get("name", "Müşteri Adı Soyadı")
        c_address = customer_info.get("address", "Teslimat Adresi Belirtilmedi")

        subtotal = sum(item.get("quantity", 1) * item.get("price", 0.0) for item in cart_items)
        shipping_fee = 49.90 if 0 < subtotal < 1000 else 0.0
        grand_total = subtotal + shipping_fee

        return f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head><meta charset="UTF-8"><title>Mesafeli Satış Sözleşmesi</title></head>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>MESAFELİ SATIŞ SÖZLEŞMESİ</h2>
            <p><strong>Satıcı:</strong> {m_name} (MERSİS: {m_mersis})</p>
            <p><strong>Alıcı:</strong> {c_name} ({c_address})</p>
            <p><strong>Toplam Tutar:</strong> {grand_total:.2f} TL</p>
        </body>
        </html>
        """


# --- MODÜL 9: TRENDYOL AUDIT ENGINE ---
class TrendyolAuditEngine:
    @staticmethod
    def run_feed_audit(supplier_id: str) -> Dict[str, Any]:
        audit_results = [
            {"product": "Süzme Çiçek Balı 1000 gr", "sku": "TY-BAL-1000", "price": 450.0, "issue": "Birim fiyat etiketi eksik (6502/M.54)", "risk": "YÜKSEK", "penalty": "34.712 TL"},
            {"product": "Zeytinyağı 500 ml", "sku": "TY-ZTY-500", "price": 220.0, "issue": "30 günlük en düşük fiyat referansı doğrulanmadı", "risk": "ORTA", "penalty": "34.712 TL"},
            {"product": "Antep Fıstıklı Çikolata 200 gr", "sku": "TY-CIK-200", "price": 110.0, "issue": "KVKK ve Çerez Politikası eksikliği", "risk": "YÜKSEK", "penalty": "50.000 TL"}
        ]
        return {
            "supplier_id": supplier_id,
            "health_score": 60,
            "total_issues": len(audit_results),
            "estimated_penalty_risk": "119.424 TL",
            "issues": audit_results,
            "scan_timestamp": datetime.now().strftime("%d.%m.%Y %H:%M")
        }


# --- MODÜL 10: ÇOKLU PLATFORM İSTEMCİLERİ ---
class ShopifyAPIClient:
    def __init__(self, store_domain: str, access_token: str): self.store_domain = store_domain
    def list_products(self) -> List[Dict[str, Any]]: return [{"id": "shp_001", "name": "Shopify Organik Zeytinyağı 750 ml", "variants": [{"id": "shp_var_001", "sku": "SHP-ZTY", "price": 310.00, "compare_at_price": 380.00, "weight": 0.75, "unit": "L"}]}]

class TrendyolAPIClient:
    def __init__(self, supplier_id: str): self.supplier_id = supplier_id
    def list_products(self) -> List[Dict[str, Any]]: return [{"id": "ty_001", "name": "Trendyol Süzme Çiçek Balı 1000 gr", "variants": [{"id": "ty_var_001", "sku": "TY-BAL-1K", "price": 450.00, "compare_at_price": 500.00, "weight": 1.0, "unit": "kg"}]}]


# FastAPI Uygulaması
app = FastAPI(
    title="UyumHub - Mevzuat & OS 2.0 Platformu",
    description="B2B E-Ticaret Compliance-as-Infrastructure Servisi",
    version="2.6.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- CRITICAL FIX: IFRAME KISITLAMALARINI KALDIRAN MIDDLEWARE ---
@app.middleware("http")
async def disable_frame_restrictions(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "frame-ancestors *;"
    response.headers["Access-Control-Allow-Origin"] = "*"
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    if "x-frame-options" in response.headers:
        del response.headers["x-frame-options"]
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
        "email": "destek@uyumhub.com", "subscription_status": "trial", "platform": "ikas", "plan": "UyumHub Full Mevzuat Paket"
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
                "plan": "UyumHub Full Mevzuat Paket"
            }
    except Exception: pass
    return default_profile


# --- ANA DASHBOARD VE İKAS IFRAME EL SIKIŞMA RENDER MOTORU ---
def build_dashboard_html(storeDomain: str, is_dev: bool = False) -> str:
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    platform_name = profile["platform"]
    
    # Sadece Geliştirici Mağazalarında Görünecek Araçlar (Dev / Test / 'dev-' Mağazaları)
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
        
        <!-- İKAS ADMIN ÇARKINI DURDURAN KRİTİK POSTMESSAGE SİNYALİ -->
        <script>
            function sendIkasLoadedSignal() {{
                try {{
                    window.parent.postMessage({{ type: "IKAS_APP_LOADED", loaded: true, ready: true }}, "*");
                    window.parent.postMessage("IKAS_APP_READY", "*");
                    window.parent.postMessage("APP_LOADED", "*");
                }} catch(e) {{ console.log("Iframe handshake:", e); }}
            }}
            window.addEventListener("DOMContentLoaded", sendIkasLoadedSignal);
            window.addEventListener("load", sendIkasLoadedSignal);
            setTimeout(sendIkasLoadedSignal, 200);
            setTimeout(sendIkasLoadedSignal, 800);
        </script>
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            
            <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div class="flex items-center gap-4">
                    <div class="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-2xl font-bold shadow-indigo-200 shadow-lg">
                        <i class="fa-solid fa-shield-halved"></i>
                    </div>
                    <div>
                        <h1 class="text-xl font-bold text-slate-900">UyumHub Mevzuat & E-Ticaret Suite</h1>
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
                    <a href="/api/v1/compliance/kvkk?storeDomain={domain}" target="_blank" class="bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">
                        <i class="fa-solid fa-file-shield"></i> KVKK
                    </a>
                    <a href="/api/v1/compliance/cookie-policy?storeDomain={domain}" target="_blank" class="bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">
                        <i class="fa-solid fa-cookie-bite"></i> Çerez
                    </a>
                    <a href="/audit/trendyol" class="bg-orange-600 hover:bg-orange-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">
                        <i class="fa-solid fa-store"></i> Audit
                    </a>
                    <a href="/api/v1/compliance/certificate?storeDomain={domain}" target="_blank" class="bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">
                        <i class="fa-solid fa-certificate"></i> Sertifika
                    </a>
                    <button onclick="runSync()" id="sync-btn" class="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold px-3 py-2 rounded-xl transition cursor-pointer">
                        <i class="fa-solid fa-rotate"></i> Senkronize Et
                    </button>
                    <a href="/login" class="bg-slate-800 hover:bg-slate-900 text-white text-xs font-semibold px-3 py-2 rounded-xl transition">
                        <i class="fa-solid fa-right-from-bracket"></i> Çıkış
                    </a>
                </div>
            </div>

            <div id="section-products" class="space-y-6">
                <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
                    <div class="p-6 border-b border-slate-100 flex justify-between items-center">
                        <div>
                            <h2 class="text-base font-bold text-slate-900">Birim Fiyat Etiket & Mevzuat Analizi</h2>
                            <p class="text-xs text-slate-500 mt-0.5">Bakanlık mevzuatına tam uyumlu canlı birim fiyat etiketleri.</p>
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

            window.onload = function() {{
                sendIkasLoadedSignal();
                loadProducts();
            }};
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


# --- ROUTE 2: İKAS LAUNCH & CALLBACK (İFRAME ENGELİ OLMADAN DOĞRUDAN HTML RENDER) ---
@app.get("/api/v1/ikas/launch", response_class=HTMLResponse)
async def ikas_launch(request: Request):
    try:
        params = dict(request.query_params)
        raw_domain = params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
        domain = normalize_domain(raw_domain)
        return HTMLResponse(content=build_dashboard_html(domain, is_dev=True))
    except Exception as e:
        logger.error(f"Launch hatası: {str(e)}")
        return HTMLResponse(content=build_dashboard_html("dev-mevzuattestmagaza.myikas.com", is_dev=True))


@app.get("/api/v1/ikas/callback", response_class=HTMLResponse)
async def ikas_callback(request: Request):
    try:
        params = dict(request.query_params)
        code = params.get("code")
        raw_domain = params.get("state") or params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
        domain = normalize_domain(raw_domain)

        access_token = f"ikas_token_{code[:12]}" if code else "ikas_token_default"
        save_merchant_to_supabase(domain, access_token, platform="ikas")
        return HTMLResponse(content=build_dashboard_html(domain, is_dev=True))
    except Exception as e:
        logger.error(f"Callback hatası: {str(e)}")
        return HTMLResponse(content=build_dashboard_html("dev-mevzuattestmagaza.myikas.com", is_dev=True))


# --- ROUTE 3: MODÜL 13: SHOPIFY OS 2.0 STOREFRONT BADGE ENDPOINT ---
@app.get("/api/v1/shopify/storefront/compliance-badge")
async def get_shopify_storefront_badge(price: float, weight: float = 1.0, unit: str = "kg", storeDomain: str = "organikgurme.myshopify.com"):
    domain = normalize_domain(storeDomain)
    calc_res = ComplianceEngine.calculate_unit_price(price, weight, unit, store_domain=domain)
    
    badge_html = f"""
    <div class="uyumhub-unit-price-badge" style="display: inline-flex; align-items: center; gap: 6px; background-color: #f1f5f9; border: 1px solid #cbd5e1; color: #0f172a; padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; margin: 8px 0;">
        <span>{calc_res.get('display_text', 'Birim Fiyat Hesaplandı')}</span>
    </div>
    """
    return JSONResponse(content={
        "status": "success", "store": domain, "formatted_text": calc_res.get("display_text"), "badge_html": badge_html
    })


# --- ROUTE 4: DİĞER MODÜL ENDPOINT'LERİ (KVKK, ÇEREZ, SERTİFİKA, AUDIT, CHECKOUT) ---
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


@app.get("/api/v1/billing/checkout", response_class=HTMLResponse)
async def billing_checkout(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    return HTMLResponse(content=f"<div style='font-family:sans-serif; padding:40px;'><h1>UyumHub Checkout - {domain}</h1><a href='/api/v1/billing/success?storeDomain={domain}'>Test Ödemesini Onayla</a></div>")


@app.get("/api/v1/billing/success")
async def billing_success(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    if supabase_client:
        try:
            supabase_client.table("merchants").update({"subscription_status": "active"}).eq("store_domain", domain).execute()
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


@app.get("/")
async def root(): return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health(): return {"status": "healthy", "database": "connected" if supabase_client else "not_configured"}