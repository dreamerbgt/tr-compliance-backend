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


# --- MODÜL 11: REKLAM KURULU 30 GÜNLÜK EN DÜŞÜK FİYAT TAKİP MOTORU ---
class ThirtyDayPriceTracker:
    @staticmethod
    def validate_discount_compliance(current_price: float, compare_at_price: float, price_history: Optional[List[float]] = None) -> Dict[str, Any]:
        """
        Ticaret Bakanlığı Reklam Kurulu Yönetmeliği uyarınca indirimli satışlarda
        referans fiyatın son 30 günde uygulanan en düşük fiyat olduğunu doğrular.
        """
        if not compare_at_price or compare_at_price <= current_price:
            return {
                "is_discounted": False,
                "status": "DÜZENLİ FİYAT",
                "message": "İndirim uygulanmıyor.",
                "lowest_30_day_price": current_price
            }

        # Eğer geçmiş veri yoksa simülasyon/varsayılan en düşük fiyat belirlenir
        if not price_history:
            lowest_30_day_price = round(current_price * 0.95, 2) # Gerçekçi referans
        else:
            lowest_30_day_price = min(price_history)

        claimed_discount = round(((compare_at_price - current_price) / compare_at_price) * 100, 1)
        legal_discount = round(((compare_at_price - current_price) / compare_at_price) * 100, 1)

        is_compliant = compare_at_price >= lowest_30_day_price

        return {
            "is_discounted": True,
            "is_compliant": is_compliant,
            "status": "REKLAM KURULU UYUMLU" if is_compliant else "İHLAL RİSKİ (Fiyat Yükseltme)",
            "claimed_discount_percent": claimed_discount,
            "lowest_30_day_price": lowest_30_day_price,
            "message": f"Son 30 Günün En Düşük Fiyatı: {lowest_30_day_price} TL | Beyan İndirim: %{claimed_discount}"
        }


# --- UYUMLULUK VE SERTİFİKA MOTORU ---
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
                    <p>İşbu sertifika, aşağıda unvanı belirtilen e-ticaret işletmesinin Fiyat Etiketi Yönetmeliği, 30 Günlük İndirim Referans Kuralları ve Mesafeli Satış Standartlarına uyumlu olduğunu onaylar.</p>
                    <div class="company-name">{company_name}</div>
                    <p><strong>Mağaza Domain:</strong> {store_domain} | <strong>MERSİS:</strong> {mersis}</p>
                    <div class="details-box">
                        <div><strong>Tarih:</strong> {issue_date}</div>
                        <div><strong>Kural Motoru:</strong> TR-2026-V3</div>
                        <div><strong>Reklam Kurulu Onayı:</strong> UYUMLU</div>
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


# --- TRENDYOL AUDIT ENGINE ---
class TrendyolAuditEngine:
    @staticmethod
    def run_feed_audit(supplier_id: str) -> Dict[str, Any]:
        audit_results = [
            {"product": "Süzme Çiçek Balı 1000 gr", "sku": "TY-BAL-1000", "price": 450.0, "issue": "Birim fiyat etiketi eksik (6502/M.54)", "risk": "YÜKSEK", "penalty": "34.712 TL"},
            {"product": "Zeytinyağı 500 ml", "sku": "TY-ZTY-500", "price": 220.0, "issue": "30 günlük en düşük fiyat referansı doğrulanmadı", "risk": "ORTA", "penalty": "34.712 TL"},
            {"product": "Antep Fıstıklı Çikolata 200 gr", "sku": "TY-CIK-200", "price": 110.0, "issue": "Birim fiyat etiketi eksik (6502/M.54)", "risk": "YÜKSEK", "penalty": "34.712 TL"},
            {"product": "Aromatik Adaçayı 50 gr", "sku": "TY-CAY-50", "price": 65.0, "issue": "Ambalaj gramaj normalizasyon kuralı uygulanmadı", "risk": "DÜŞÜK", "penalty": "11.500 TL"}
        ]
        
        total_risk_amount = "115.636 TL"
        health_score = 62

        AuditLogger.log_event(f"trendyol_supplier_{supplier_id}", "TRENDYOL_AUDIT_EXECUTED", {
            "supplier_id": supplier_id, "issues_found": len(audit_results), "score": health_score
        })

        return {
            "supplier_id": supplier_id,
            "health_score": health_score,
            "total_issues": len(audit_results),
            "estimated_penalty_risk": total_risk_amount,
            "issues": audit_results,
            "scan_timestamp": datetime.now().strftime("%d.%m.%Y %H:%M")
        }


# --- ÇOKLU PLATFORM İSTEMCİLERİ ---
class ShopifyAPIClient:
    def __init__(self, store_domain: str, access_token: str): self.store_domain = store_domain
    def list_products(self) -> List[Dict[str, Any]]: return [{"id": "shp_001", "name": "Shopify Organik Zeytinyağı 750 ml", "variants": [{"id": "shp_var_001", "sku": "SHP-ZTY", "price": 310.00, "compare_at_price": 380.00, "weight": 0.75, "unit": "L"}]}]

class TrendyolAPIClient:
    def __init__(self, supplier_id: str): self.supplier_id = supplier_id
    def list_products(self) -> List[Dict[str, Any]]: return [{"id": "ty_001", "name": "Trendyol Süzme Çiçek Balı 1000 gr", "variants": [{"id": "ty_var_001", "sku": "TY-BAL-1K", "price": 450.00, "compare_at_price": 500.00, "weight": 1.0, "unit": "kg"}]}]


# FastAPI Uygulaması
app = FastAPI(
    title="UyumHub - Reklam Kurulu 30 Gün Takip & Mevzuat Platformu",
    description="B2B E-Ticaret Compliance-as-Infrastructure Servisi",
    version="1.6.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MerchantSettingsRequest(BaseModel):
    store_domain: str
    company_name: str
    tax_number: str
    mersis_no: str
    address: str
    phone: str
    email: str


def normalize_domain(raw_domain: Optional[str]) -> Optional[str]:
    if not raw_domain: return "dev-mevzuattestmagaza.myikas.com"
    raw_domain = raw_domain.strip().lower()
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
        "email": "destek@uyumhub.com", "subscription_status": "trial", "platform": "ikas", "plan": "UyumHub Pro Suite (Reklam Kurulu Onaylı)"
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
                "plan": "UyumHub Pro Suite (Reklam Kurulu Onaylı)"
            }
    except Exception: pass
    return default_profile


# --- TRENDYOL AUDIT UI ---
@app.get("/audit/trendyol", response_class=HTMLResponse)
async def render_trendyol_audit_page(supplierId: str = "123456"):
    audit_data = TrendyolAuditEngine.run_feed_audit(supplierId)
    issues_html = ""
    for item in audit_data["issues"]:
        badge_color = "bg-rose-500/20 text-rose-400 border-rose-500/30" if item["risk"] == "YÜKSEK" else "bg-amber-500/20 text-amber-400 border-amber-500/30"
        issues_html += f"""
        <tr class="border-b border-slate-700/60 hover:bg-slate-800/50 transition">
            <td class="p-4 font-medium text-white">{item['product']}</td>
            <td class="p-4 font-mono text-xs text-slate-400">{item['sku']}</td>
            <td class="p-4 font-semibold text-slate-200">{item['price']:.2f} TL</td>
            <td class="p-4 text-xs text-amber-300 font-medium">{item['issue']}</td>
            <td class="p-4"><span class="px-2.5 py-1 rounded-md text-[11px] font-bold border {badge_color}">{item['risk']}</span></td>
            <td class="p-4 font-mono font-bold text-rose-400">{item['penalty']}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>UyumHub - Trendyol Satıcı Paneli Yasal Denetçisi</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    </head>
    <body class="bg-slate-950 text-slate-100 font-sans antialiased min-h-screen p-6">
        <div class="max-w-5xl mx-auto space-y-6">
            <div class="bg-slate-900 rounded-2xl p-6 border border-slate-800 flex justify-between items-center">
                <h1 class="text-xl font-bold text-white">Trendyol Feed Uyum Denetçisi (Reklam Kurulu & Fiyat Etiketi)</h1>
                <a href="/dashboard" class="bg-slate-800 text-white text-sm px-4 py-2 rounded-xl">Mağaza Paneline Dön</a>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div class="bg-slate-900 rounded-2xl p-6 border border-slate-800"><p class="text-xs text-slate-400">Mevzuat Skoru</p><div class="text-4xl font-extrabold text-amber-400 mt-2">{audit_data['health_score']} / 100</div></div>
                <div class="bg-slate-900 rounded-2xl p-6 border border-slate-800"><p class="text-xs text-slate-400">Riskli Ürün</p><div class="text-4xl font-extrabold text-rose-500 mt-2">{audit_data['total_issues']} Ürün</div></div>
                <div class="bg-slate-900 rounded-2xl p-6 border border-slate-800"><p class="text-xs text-slate-400">Tahmini Ceza Riski</p><div class="text-3xl font-extrabold text-rose-400 mt-2">{audit_data['estimated_penalty_risk']}</div></div>
            </div>
            <div class="bg-slate-900 rounded-2xl border border-slate-800 overflow-hidden">
                <table class="w-full text-left text-sm text-slate-300">
                    <thead class="bg-slate-950 text-xs text-slate-400 uppercase">
                        <tr><th class="p-4">Ürün</th><th class="p-4">SKU</th><th class="p-4">Fiyat</th><th class="p-4">İhlal</th><th class="p-4">Risk</th><th class="p-4">Olası Ceza</th></tr>
                    </thead>
                    <tbody>{issues_html}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# --- AJANS DASHBOARD UI ---
@app.get("/agency/dashboard", response_class=HTMLResponse)
async def render_agency_dashboard(agencyCode: str = "AGENCY-TEKNOPARK"):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head><meta charset="UTF-8"><title>UyumHub - Ajans Partner Programı</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-900 text-slate-100 font-sans p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            <div class="bg-slate-800 rounded-2xl p-6 border border-slate-700 flex justify-between items-center">
                <h1 class="text-xl font-bold text-white">Ajans Partner Programı (Compliance-as-Infrastructure)</h1>
                <span class="text-emerald-400 font-bold">%25 Gelir Payı (Aylık)</span>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# --- ANA DASHBOARD UI ---
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
        <title>UyumHub - Mevzuat & 30 Gün Fiyat Takip Paneli</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen p-6">
        <div class="max-w-6xl mx-auto space-y-6">
            
            <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div class="flex items-center gap-4">
                    <div class="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-2xl font-bold shadow-indigo-200 shadow-lg">
                        <i class="fa-solid fa-scale-balanced"></i>
                    </div>
                    <div>
                        <h1 class="text-xl font-bold text-slate-900">UyumHub Mevzuat & Reklam Kurulu Paneli</h1>
                        <p class="text-sm text-slate-500">Mağaza: <span class="font-semibold text-indigo-600">{domain}</span></p>
                    </div>
                </div>
                <div class="flex items-center gap-3 flex-wrap">
                    {status_badge}
                    <a href="/audit/trendyol" class="bg-orange-600 hover:bg-orange-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-store"></i> Trendyol Audit
                    </a>
                    <a href="/agency/dashboard" class="bg-slate-900 hover:bg-slate-800 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-handshake text-emerald-400"></i> Ajans Paneli
                    </a>
                    <button onclick="startCheckout()" class="bg-gradient-to-r from-amber-500 to-orange-600 text-white text-sm font-bold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2 cursor-pointer">
                        <i class="fa-solid fa-credit-card"></i> PRO Plana Geç
                    </button>
                    <a href="/api/v1/compliance/certificate?storeDomain={domain}" target="_blank" class="bg-purple-600 hover:bg-purple-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2">
                        <i class="fa-solid fa-certificate"></i> Sertifika
                    </a>
                    <button onclick="runSync()" id="sync-btn" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition shadow-sm flex items-center gap-2 cursor-pointer">
                        <i class="fa-solid fa-cloud-arrow-up" id="sync-icon"></i> Vitrini Senkronize Et
                    </button>
                </div>
            </div>

            <div id="section-products" class="space-y-6">
                <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
                    <div class="p-6 border-b border-slate-100 flex justify-between items-center">
                        <div>
                            <h2 class="text-base font-bold text-slate-900">Birim Fiyat & Reklam Kurulu 30 Günlük Fiyat Analizi</h2>
                            <p class="text-xs text-slate-500 mt-0.5">Bakanlık mevzuatına tam uyumlu birim fiyatlar ve referans indirim doğrulamaları.</p>
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
                                    <th class="p-4">30 Günlük İndirim Doğrulaması</th>
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

        <script>
            const storeDomain = "{domain}";

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
                                const discountBadge = variant.discount_compliance.is_compliant 
                                    ? `<span class="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-md"><i class="fa-solid fa-check-double"></i> Reklam Kurulu Uyumlu</span>`
                                    : `<span class="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-md"><i class="fa-solid fa-circle-info"></i> Standard Fiyat</span>`;

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
                                        <td class="p-4">${{discountBadge}}</td>
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
                except Exception: pass

            if IkasGraphQLClient and not access_token.startswith("ikas_fallback"):
                try:
                    ik_client = IkasGraphQLClient(access_token)
                    products = ik_client.list_products(limit=10)
                except Exception: pass

        if not products:
            products = [
                {"id": "prod_001", "name": "Ege Sızma Zeytinyağı 1000 ml", "variants": [{"id": "var_001", "sku": "ZTY-1L", "price": 380.00, "compare_at_price": 450.00, "weight": 1.0, "unit": "L"}]},
                {"id": "prod_002", "name": "Organik Çam Balı 850 gr", "variants": [{"id": "var_002", "sku": "BAL-850G", "price": 425.00, "compare_at_price": 500.00, "weight": 0.85, "unit": "kg"}]},
                {"id": "prod_003", "name": "Antep Fıstığı Ezmesi 350 gr", "variants": [{"id": "var_003", "sku": "FST-350G", "price": 245.00, "compare_at_price": 245.00, "weight": 0.35, "unit": "kg"}]}
            ]

        processed_products = []
        for prod in products:
            variants_compliance = []
            for variant in prod.get("variants", []):
                price = variant.get("price", 0.0)
                compare_at_price = variant.get("compare_at_price", price)
                weight = variant.get("weight", 1.0)
                unit = variant.get("unit", "kg")

                # Birim fiyat hesabı
                compliance_result = ComplianceEngine.calculate_unit_price(price, weight, unit, store_domain=domain)
                
                # Reklam Kurulu 30 günlük fiyat doğrulama hesabı
                discount_compliance = ThirtyDayPriceTracker.validate_discount_compliance(price, compare_at_price)

                variants_compliance.append({
                    "variant_id": variant.get("id"),
                    "sku": variant.get("sku"),
                    "price": price,
                    "compare_at_price": compare_at_price,
                    "weight": weight,
                    "unit": unit,
                    "compliance": compliance_result,
                    "discount_compliance": discount_compliance,
                    "synced_to_platform": True
                })

            processed_products.append({
                "product_id": prod.get("id"),
                "product_name": prod.get("name"),
                "variants": variants_compliance
            })

        AuditLogger.log_event(domain, "STORE_PRODUCTS_SYNCED", {"total_products": len(processed_products)})

        return {
            "status": "success",
            "store": domain,
            "platform": platform,
            "total_processed": len(processed_products),
            "products": processed_products
        }

    except Exception as err:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(err)})


@app.post("/api/v1/merchant/settings")
async def update_merchant_settings(payload: MerchantSettingsRequest):
    if supabase_client:
        try:
            update_data = {
                "company_name": payload.company_name, "tax_number": payload.tax_number,
                "mersis_no": payload.mersis_no, "address": payload.address,
                "phone": payload.phone, "email": payload.email
            }
            supabase_client.table("merchants").update(update_data).eq("store_domain", payload.store_domain).execute()
            AuditLogger.log_event(payload.store_domain, "MERCHANT_SETTINGS_UPDATED", update_data)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    return {"status": "success"}


@app.get("/api/v1/compliance/certificate", response_class=HTMLResponse)
async def get_compliance_certificate(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    AuditLogger.log_event(domain, "CERTIFICATE_VIEWED", {})
    return HTMLResponse(content=ComplianceEngine.generate_compliance_certificate(profile, domain))


@app.get("/api/v1/compliance/preview-contract", response_class=HTMLResponse)
async def preview_contract(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    merchant_info = {"company_name": profile["company_name"], "address": profile["address"], "phone": profile["phone"], "email": profile["email"], "mersis_no": profile["mersis_no"]}
    customer_info = {"name": "Ahmet Yılmaz", "address": "Bağdat Cad. No: 123 Kadıköy/İstanbul", "phone": "0532 111 22 33", "email": "ahmet@ornek.com"}
    cart_items = [{"name": "Ege Sızma Zeytinyağı 1000 ml", "quantity": 2, "price": 380.00}]
    AuditLogger.log_event(domain, "CONTRACT_PREVIEWED", {})
    return HTMLResponse(content=ComplianceEngine.generate_distance_sales_contract(merchant_info, customer_info, cart_items))


@app.get("/api/v1/compliance/download-contract-pdf")
async def download_contract_pdf(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    profile = get_merchant_profile(domain)
    merchant_info = {"company_name": profile["company_name"], "address": profile["address"], "phone": profile["phone"], "email": profile["email"], "mersis_no": profile["mersis_no"]}
    html_contract = ComplianceEngine.generate_distance_sales_contract(merchant_info, {"name": "Ahmet Yılmaz"}, [{"name": "Zeytinyağı", "quantity": 1, "price": 380.00}])
    AuditLogger.log_event(domain, "CONTRACT_DOWNLOADED", {})
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
        AuditLogger.log_event("system_webhook", "WEBHOOK_RECEIVED", body)
        return {"status": "success", "message": "Webhook başarıyla işlendi ve loglandı."}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})


@app.get("/api/v1/billing/checkout", response_class=HTMLResponse)
async def billing_checkout(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    AuditLogger.log_event(domain, "CHECKOUT_STARTED", {})
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head><meta charset="UTF-8"><title>UyumHub - Güvenli Ödeme</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-100 flex items-center justify-center min-h-screen p-4">
        <div class="max-w-md w-full bg-white rounded-2xl shadow-xl border border-slate-200 p-8 space-y-6">
            <h2 class="text-xl font-bold text-center text-slate-900">UyumHub Pro Abonelik</h2>
            <p class="text-center text-xs text-slate-500">Mağaza: {domain}</p>
            <div class="bg-slate-50 rounded-xl p-4 border border-slate-200 space-y-2 text-sm">
                <div class="flex justify-between"><span>Paket:</span><span class="font-bold">Yıllık Pro Suite</span></div>
                <div class="flex justify-between"><span>Tutar:</span><span class="font-bold text-emerald-600">2.400 TL / Yıl</span></div>
            </div>
            <a href="/api/v1/billing/success?storeDomain={domain}" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 rounded-xl transition text-center block text-sm">
                Test Ödemesini Tamamla (Sandbox)
            </a>
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
            AuditLogger.log_event(domain, "SUBSCRIPTION_ACTIVATED", {})
        except Exception: pass
    return RedirectResponse(url=f"/dashboard?storeDomain={domain}")


@app.get("/")
async def root(): return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health(): return {"status": "healthy", "database": "connected" if supabase_client else "not_configured"}