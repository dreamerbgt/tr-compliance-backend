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
        return "dev-mevzuattestmagaza.myikas.com"
    raw_domain = raw_domain.strip().lower()
    if "." not in raw_domain:
        return f"{raw_domain}.myikas.com"
    return raw_domain


def save_merchant_to_supabase(domain: str, access_token: str) -> tuple[bool, str]:
    if not supabase_client:
        return False, "Supabase bağlantısı yok."
    
    # Sadece veritabanında kesin var olan temel alanlar gönderiliyor
    merchant_data = {
        "store_domain": domain,
        "access_token": access_token
    }

    try:
        supabase_client.table("merchants").upsert(merchant_data, on_conflict="store_domain").execute()
        return True, "Upsert başarılı"
    except Exception as e_upsert:
        try:
            existing = supabase_client.table("merchants").select("*").eq("store_domain", domain).execute()
            if existing.data:
                supabase_client.table("merchants").update(merchant_data).eq("store_domain", domain).execute()
            else:
                supabase_client.table("merchants").insert(merchant_data).execute()
            return True, "Fallback kayıt başarılı"
        except Exception as e_fallback:
            return False, str(e_fallback)


# --- KÖK VE SAĞLIK KONTROLÜ ENDPOINT'LERİ ---
@app.get("/")
async def root():
    return {
        "status": "active",
        "service": "UyumHub Mevzuat Motoru",
        "version": "1.0.0",
        "available_endpoints": [
            "/health",
            "/api/v1/ikas/force-register",
            "/api/v1/compliance/sync-products",
            "/api/v1/ikas/launch",
            "/docs"
        ]
    }

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


# --- ÜRÜN SENKRONİZASYON VE BİRİM FİYAT ENDPOINT'İ ---
@app.get("/api/v1/compliance/sync-products")
async def sync_products(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
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


# --- İKAS LAUNCH & CALLBACK ENDPOINT'LERİ ---
@app.get("/api/v1/ikas/launch")
async def ikas_launch(request: Request):
    params = dict(request.query_params)
    raw_domain = params.get("storeDomain") or params.get("store_domain") or params.get("shop")
    domain = normalize_domain(raw_domain)

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

@app.get("/api/v1/ikas/callback")
async def ikas_callback(request: Request):
    params = dict(request.query_params)
    code = params.get("code")
    raw_domain = params.get("state") or params.get("storeDomain") or params.get("shop")
    domain = normalize_domain(raw_domain)

    access_token = f"ikas_token_{code[:12]}" if code else "ikas_token_default"
    save_merchant_to_supabase(domain, access_token)
    return RedirectResponse(url=f"https://{domain}/admin")


# --- MEVZUAT HESAPLAMA ENDPOINT'LERİ ---
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