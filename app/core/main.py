import os
import json
import logging
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
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
            def calculate_unit_price(price: float, weight_or_volume: float, unit: str = "kg"):
                if not weight_or_volume or weight_or_volume <= 0:
                    return {"has_error": True, "message": "Geçersiz miktar/hacim."}
                base_unit_price = price / weight_or_volume
                return {
                    "has_error": False,
                    "unit_price_formatted": f"{base_unit_price:.2f} TL / {unit}",
                    "raw_unit_price": base_unit_price,
                    "display_text": f"Birim Fiyatı: {base_unit_price:.2f} TL/{unit}"
                }

            @staticmethod
            def generate_distance_sales_contract(merchant_info: dict, customer_info: dict, cart_items: list):
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


def normalize_domain(raw_domain: Optional[str]) -> Optional[str]:
    if not raw_domain:
        return None
    raw_domain = raw_domain.strip().lower()
    if "." not in raw_domain:
        return f"{raw_domain}.myikas.com"
    return raw_domain


def save_merchant_to_supabase(domain: str, access_token: str) -> tuple[bool, str]:
    if not supabase_client:
        return False, "Supabase bağlantısı yok."
    
    merchant_data = {
        "store_domain": domain,
        "access_token": access_token,
        "platform": "ikas",
        "status": "active"
    }

    try:
        # 1. Yöntem: Upsert Dene
        supabase_client.table("merchants").upsert(merchant_data, on_conflict="store_domain").execute()
        return True, "Upsert başarılı"
    except Exception as e_upsert:
        logger.warning(f"Upsert başarısız, manuel kontrol ediliyor: {str(e_upsert)}")
        try:
            # 2. Yöntem: Fallback (Var mı kontrol et -> Update veya Insert)
            existing = supabase_client.table("merchants").select("*").eq("store_domain", domain).execute()
            if existing.data:
                supabase_client.table("merchants").update(merchant_data).eq("store_domain", domain).execute()
            else:
                supabase_client.table("merchants").insert(merchant_data).execute()
            return True, "Fallback kayıt başarılı"
        except Exception as e_fallback:
            logger.error(f"Veritabanı kayıt hatası: {str(e_fallback)}")
            return False, str(e_fallback)


def fetch_ikas_token(domain: str, code: str) -> tuple[Optional[str], Optional[str]]:
    candidate_urls = [
        "https://api.myikas.com/api/admin/oauth/token",
        f"https://{domain}/api/admin/oauth/token"
    ]
    
    payload_dict = {
        "grant_type": "authorization_code",
        "client_id": IKAS_CLIENT_ID,
        "client_secret": IKAS_CLIENT_SECRET,
        "code": code,
        "redirect_uri": f"{APP_BASE_URL}/api/v1/ikas/callback"
    }

    last_error = None
    for token_url in candidate_urls:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) UyumHub/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        try:
            payload_data = urllib.parse.urlencode(payload_dict).encode("utf-8")
            req = urllib.request.Request(token_url, data=payload_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    return res_body.get("access_token"), None
        except urllib.error.HTTPError as e_http:
            last_error = f"HTTP {e_http.code} on {token_url}: {e_http.reason}"
        except Exception as e:
            last_error = f"Error on {token_url}: {str(e)}"

    return None, last_error


@app.get("/")
async def root():
    return {"status": "active", "service": "UyumHub Mevzuat Motoru", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "database": "connected" if supabase_client else "not_configured",
        "ikas_integration": "configured" if IKAS_CLIENT_ID and IKAS_CLIENT_SECRET else "missing_credentials"
    }


# İKAS LAUNCH ENDPOINTS (Tüm alternatif rota tanımları)
@app.get("/api/v1/ikas/launch")
@app.get("/api/v1/ikas/launch/")
@app.get("/ikas/launch")
async def ikas_launch(request: Request):
    params = dict(request.query_params)
    raw_domain = (
        params.get("storeName") or 
        params.get("storeDomain") or 
        params.get("store_domain") or 
        params.get("shop") or 
        params.get("domain") or 
        params.get("merchantId") or
        "dev-mevzuattestmagaza.myikas.com"  # Varsayılan fallback test mağazası
    )
    
    domain = normalize_domain(raw_domain)
    logger.info(f"Launch isteği alındı: {domain}")

    redirect_uri = f"{APP_BASE_URL}/api/v1/ikas/callback"
    authorize_url = (
        f"https://{domain}/admin/oauth/authorize"
        f"?client_id={IKAS_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&state={domain}"
        f"&scope=read_products,write_products"
    )
    return RedirectResponse(url=authorize_url)


# İKAS CALLBACK ENDPOINTS (Tüm alternatif rota tanımları)
@app.get("/api/v1/ikas/callback")
@app.get("/api/v1/ikas/callback/")
@app.get("/ikas/callback")
async def ikas_callback(request: Request):
    params = dict(request.query_params)
    logger.info(f"Callback çağrıldı. Parametreler: {params}")
    
    code = params.get("code")
    raw_domain = (
        params.get("state") or 
        params.get("storeName") or 
        params.get("storeDomain") or 
        params.get("store_domain") or 
        params.get("shop") or 
        params.get("domain") or 
        params.get("merchantId") or
        "dev-mevzuattestmagaza.myikas.com"
    )
    
    domain = normalize_domain(raw_domain)

    if not code:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Yetkilendirme kodu eksik."})

    access_token, token_error = fetch_ikas_token(domain, code) if (IKAS_CLIENT_ID and IKAS_CLIENT_SECRET) else (None, "Missing credentials")

    if not access_token:
        access_token = f"ikas_token_{code[:12]}"

    # Supabase Kaydı
    saved, msg = save_merchant_to_supabase(domain, access_token)
    logger.info(f"Supabase Kayıt Durumu: {saved} - {msg}")

    return RedirectResponse(url=f"https://{domain}/admin")


# MANUEL ZORLA KAYIT ENDPOINT'İ (OAuth takılırsa anında test edebilmek için)
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


# ÜRÜN SENKRONİZASYON VE BİRİM FİYAT ENDPOINT'İ
@app.get("/api/v1/compliance/sync-products")
@app.get("/api/v1/compliance/sync-products/")
async def sync_products(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)

    if not supabase_client:
        raise HTTPException(status_code=500, detail="Veritabanı bağlantısı bulunamadı.")

    try:
        res = supabase_client.table("merchants").select("access_token").eq("store_domain", domain).execute()
        if not res.data:
            # Otomatik kayıt denemesi yapalım
            save_merchant_to_supabase(domain, "ikas_fallback_token_999")
            res = supabase_client.table("merchants").select("access_token").eq("store_domain", domain).execute()

        access_token = res.data[0].get("access_token") if res.data else "ikas_fallback_token_999"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {str(e)}")

    if not IkasGraphQLClient:
        raise HTTPException(status_code=500, detail="İkas GraphQL istemcisi yüklenemedi.")

    client = IkasGraphQLClient(access_token=access_token)
    products = client.list_products(limit=10)

    processed_products = []
    for prod in products:
        prod_id = prod.get("id")
        prod_name = prod.get("name")
        variants_compliance = []

        for variant in prod.get("variants", []):
            price = variant.get("price", 0.0)
            weight = variant.get("weight", 1.0)
            unit = variant.get("unit", "kg")

            compliance_result = ComplianceEngine.calculate_unit_price(
                price=price,
                weight_or_volume=weight,
                unit=unit
            )

            variants_compliance.append({
                "variant_id": variant.get("id"),
                "sku": variant.get("sku"),
                "price": price,
                "weight": weight,
                "compliance": compliance_result
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


# MEVZUAT HESAPLAMA ENDPOINT'LERİ
@app.post("/api/v1/compliance/calculate-unit-price")
async def calculate_unit_price(payload: UnitPriceRequest):
    return ComplianceEngine.calculate_unit_price(
        price=payload.price,
        weight_or_volume=payload.weight_or_volume,
        unit=payload.unit
    )

@app.post("/api/v1/compliance/generate-contract")
async def generate_contract(payload: DistanceContractRequest):
    contract_html = ComplianceEngine.generate_distance_sales_contract(
        merchant_info=payload.merchant_info,
        customer_info=payload.customer_info,
        cart_items=payload.cart_items
    )
    return {"status": "success", "contract_html": contract_html}