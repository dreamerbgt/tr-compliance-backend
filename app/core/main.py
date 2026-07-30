import os
import logging
from typing import Optional, Dict, Any
from fastapi import FastAPI, Query, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
import requests

# App modülünden ComplianceEngine import ediliyor
try:
    from app.core.compliance import ComplianceEngine
except ImportError:
    # Eğer dizin yapısında lokal test yapılıyorsa
    from compliance import ComplianceEngine

# Logging Yapılandırması
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UyumHub")

# Environment Variables (Ortam Değişkenleri)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
IKAS_CLIENT_ID = os.getenv("IKAS_CLIENT_ID", "")
IKAS_CLIENT_SECRET = os.getenv("IKAS_CLIENT_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://tr-compliance-backend.onrender.com")

# Supabase İstemcisi Başlatma
supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase bağlantısı başarıyla oluşturuldu.")
    except Exception as e:
        logger.error(f"Supabase başlatma hatası: {str(e)}")

# FastAPI Uygulama Tanımı
app = FastAPI(
    title="UyumHub - TR Mevzuat & Uyum Paketi API",
    description="İkas, Shopify ve Trendyol için B2B E-Ticaret Mevzuat Uyum Servisi",
    version="1.0.0"
)

# CORS Ayarları (İkas iFrame ve dış istekler için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- PYDANTIC MODELLERİ ---
class UnitPriceRequest(BaseModel):
    price: float
    weight_or_volume: float
    unit: str = "kg"  # Varsayılan: kg, L, m2 vb.

class DistanceContractRequest(BaseModel):
    merchant_info: Dict[str, Any]
    customer_info: Dict[str, Any]
    cart_items: list


# --- SAĞLIK VE KONTROL ENDPOINT'LERİ ---
@app.get("/")
async def root():
    return {
        "status": "active",
        "service": "UyumHub Mevzuat Motoru",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected" if supabase_client else "not_configured"
    }


# --- İKAS OAUTH ENTEGRASYON ENDPOINT'LERİ ---
@app.get("/api/v1/ikas/launch")
async def ikas_launch(
    storeDomain: Optional[str] = Query(None),
    store_domain: Optional[str] = Query(None),
    shop: Optional[str] = Query(None)
):
    """
    İkas App Store üzerinden uygulama başlatıldığında tetiklenir.
    Parametre hatalarını engellemek için tüm olası domain isimleri Optional olarak tanımlanmıştır.
    """
    domain = storeDomain or store_domain or shop
    
    if not domain:
        logger.warning("Launch isteğinde mağaza domain bilgisi bulunamadı.")
        return JSONResponse(
            status_code=200,
            content={
                "status": "warning",
                "message": "Mağaza domain bilgisi (storeDomain) bulunamadı. Lütfen uygulamayı İkas Mağaza Paneli üzerinden başlatın."
            }
        )

    logger.info(f"Oturum açma isteği alındı: {domain}")

    # İkas Client ID tanımlı değilse doğrudan bilgilendirme ekranına yönlendir
    if not IKAS_CLIENT_ID:
        return JSONResponse(
            status_code=200,
            content={
                "status": "info",
                "storeDomain": domain,
                "message": "UyumHub altyapısı hazır. İkas Client ID tanımlandıktan sonra yetkilendirme otomatik başlayacaktır."
            }
        )

    # İkas OAuth Yetkilendirme Yönlendirmesi
    authorize_url = (
        f"https://{domain}/admin/oauth/authorize"
        f"?client_id={IKAS_CLIENT_ID}"
        f"&redirect_uri={APP_BASE_URL}/api/v1/ikas/callback"
        f"&response_type=code"
        f"&scope=read_products,write_products"
    )
    
    return RedirectResponse(url=authorize_url)


@app.get("/api/v1/ikas/callback")
async def ikas_callback(
    code: Optional[str] = Query(None),
    storeDomain: Optional[str] = Query(None),
    store_domain: Optional[str] = Query(None)
):
    """
    İkas OAuth yetkilendirme kütüphanesi geri dönüş adresi.
    """
    domain = storeDomain or store_domain
    
    if not code:
        raise HTTPException(status_code=400, detail="Yetkilendirme kodu (code) alınamadı.")

    logger.info(f"Callback yetkilendirme kodu alındı. Domain: {domain}")

    # Access Token alma simülasyonu / Supabase Kaydı
    access_token = f"ikas_token_{code[:10]}"  # İkas Token API çağrısı ile güncellenir

    if supabase_client and domain:
        try:
            # Supabase 'merchants' tablosuna mağazayı kaydet/güncelle
            data = {
                "store_domain": domain,
                "access_token": access_token,
                "platform": "ikas",
                "status": "active"
            }
            supabase_client.table("merchants").upsert(data, on_conflict="store_domain").execute()
            logger.info(f"Mağaza veritabanına kaydedildi: {domain}")
        except Exception as e:
            logger.error(f"Veritabanı kayıt hatası: {str(e)}")

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "message": "✅ TR Mevzuat & Uyum Paketi Başarıyla Bağlandı!",
            "store": domain
        }
    )


# --- MEVZUAT HESAPLAMA API ENDPOINT'LERİ ---
@app.post("/api/v1/compliance/calculate-unit-price")
async def calculate_unit_price(payload: UnitPriceRequest):
    """
    Fiyat Etiketi Yönetmeliği uyarınca birim fiyat hesaplar.
    """
    result = ComplianceEngine.calculate_unit_price(
        price=payload.price,
        weight_or_volume=payload.weight_or_volume,
        unit=payload.unit
    )
    return result


@app.post("/api/v1/compliance/generate-contract")
async def generate_contract(payload: DistanceContractRequest):
    """
    6502 sayılı Kanun uyarınca dinamik Mesafeli Satış Sözleşmesi oluşturur.
    """
    contract_html = ComplianceEngine.generate_distance_sales_contract(
        merchant_info=payload.merchant_info,
        customer_info=payload.customer_info,
        cart_items=payload.cart_items
    )
    return {"status": "success", "contract_html": contract_html}