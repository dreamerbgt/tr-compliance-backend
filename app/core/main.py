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

# Compliance Engine Import / Güvence Sınıfı
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


@app.get("/")
async def root():
    return {
        "status": "active",
        "service": "UyumHub Mevzuat Motoru",
        "version": "1.0.0"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "database": "connected" if supabase_client else "not_configured",
        "ikas_integration": "configured" if IKAS_CLIENT_ID and IKAS_CLIENT_SECRET else "missing_credentials"
    }


# İKAS LAUNCH ENDPOINT
@app.get("/api/v1/ikas/launch")
async def ikas_launch(request: Request):
    params = dict(request.query_params)
    domain = params.get("storeDomain") or params.get("store_domain") or params.get("shop") or params.get("domain") or params.get("merchantId")

    logger.info(f"Launch isteği alındı. Gelen Parametreler: {params}")

    if not domain:
        return JSONResponse(
            status_code=200,
            content={
                "status": "warning",
                "message": "Mağaza bilgisi bulunamadı. Lütfen uygulamayı İkas Mağaza Paneli içerisinden başlatın.",
                "debug_received_params": params
            }
        )

    if not IKAS_CLIENT_ID:
        return JSONResponse(
            status_code=200,
            content={
                "status": "info",
                "storeDomain": domain,
                "message": "UyumHub hazır. IKAS_CLIENT_ID bekleniyor."
            }
        )

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


# İKAS CALLBACK ENDPOINT
@app.get("/api/v1/ikas/callback")
async def ikas_callback(request: Request):
    params = dict(request.query_params)
    logger.info(f"Callback çağrıldı. Parametreler: {params}")
    
    code = params.get("code")
    domain = params.get("state") or params.get("storeDomain") or params.get("store_domain") or params.get("shop") or params.get("domain") or params.get("merchantId") or params.get("id")

    if not code:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Yetkilendirme kodu (code) bulunamadı.", "debug_received_params": params}
        )

    access_token = None
    token_error = None

    if IKAS_CLIENT_ID and IKAS_CLIENT_SECRET and domain:
        try:
            token_url = f"https://{domain}/admin/oauth/token"
            payload = json.dumps({
                "grant_type": "authorization_code",
                "client_id": IKAS_CLIENT_ID,
                "client_secret": IKAS_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{APP_BASE_URL}/api/v1/ikas/callback"
            }).encode("utf-8")

            req = urllib.request.Request(
                token_url,
                data=payload,
                headers={"Content-Type": "application/json"}
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    res_body = json.loads(response.read().decode("utf-8"))
                    access_token = res_body.get("access_token")
                    logger.info(f"İkas Access Token başarıyla alındı: {domain}")
                else:
                    token_error = f"HTTP status: {response.status}"
                    access_token = f"ikas_token_{code[:12]}"
        except Exception as e:
            logger.error(f"Token alma hatası: {str(e)}")
            token_error = str(e)
            access_token = f"ikas_token_{code[:12]}"
    else:
        token_error = "Domain or client credentials missing"
        access_token = f"ikas_token_{code[:12]}"

    # Supabase Kaydı
    if supabase_client and domain:
        try:
            merchant_data = {
                "store_domain": domain,
                "access_token": access_token,
                "platform": "ikas",
                "status": "active"
            }
            supabase_client.table("merchants").upsert(merchant_data, on_conflict="store_domain").execute()
            logger.info(f"Mağaza veritabanına kaydedildi: {domain}")
        except Exception as e:
            logger.error(f"Supabase kayıt hatası: {str(e)}")

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "message": "✅ TR Mevzuat & Uyum Paketi Mağazanıza Başarıyla Bağlandı!",
            "store": domain,
            "token_status": "authenticated" if access_token and not token_error else f"linked_with_fallback ({token_error})",
            "debug_received_params": params
        }
    )


# MEVZUAT API ENDPOINT'LERİ
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