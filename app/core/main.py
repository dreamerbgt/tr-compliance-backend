import os
import httpx
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
from app.core.compliance import ComplianceEngine

load_dotenv()

app = FastAPI(title="TR Compliance Hub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
IKAS_CLIENT_ID = os.getenv("IKAS_CLIENT_ID", "")
IKAS_CLIENT_SECRET = os.getenv("IKAS_CLIENT_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://tr-compliance-api.onrender.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

@app.get("/")
def read_root():
    return {"status": "online", "service": "TR Compliance Hub API"}

# ---------------------------------------------------------
# İKAS OAUTH & APPS ENTEGRASYONU
# ---------------------------------------------------------

@app.get("/api/v1/ikas/launch")
def ikas_launch(store_domain: str = Query(..., alias="storeDomain")):
    """
    Mağaza sahibi İkas panelinden uygulamaya tıkladığında çalışır.
    İkas OAuth izin sayfasına yönlendirir.
    """
    authorize_url = (
        f"https://{store_domain}/admin/oauth/authorize"
        f"?client_id={IKAS_CLIENT_ID}"
        f"&redirect_uri={APP_BASE_URL}/api/v1/ikas/callback"
        f"&response_type=code"
        f"&scope=read_products,write_products"
    )
    return RedirectResponse(url=authorize_url)


@app.get("/api/v1/ikas/callback")
async def ikas_callback(code: str, store_domain: str = Query(..., alias="storeDomain")):
    """
    Mağaza izin verdikten sonra İkas'ın authorization code ile döndüğü endpoint.
    Access token alır ve Supabase'e kaydeder.
    """
    token_url = f"https://{store_domain}/admin/oauth/token"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": IKAS_CLIENT_ID,
                "client_secret": IKAS_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{APP_BASE_URL}/api/v1/ikas/callback"
            }
        )
        
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="İkas Token alınamadı.")
        
    token_data = response.json()
    access_token = token_data.get("access_token")

    # Supabase'e Mağazayı Kaydet
    if supabase:
        supabase.table("merchants").upsert({
            "platform": "ikas",
            "store_domain": store_domain,
            "access_token": access_token,
            "is_active": True
        }, on_conflict="store_domain").execute()

    # İkas iframe içinde görünecek yönlendirme / yönetim arayüzü
    return HTMLResponse(content=f"""
        <html>
            <head><title>TR Uyum Paketi</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h2 style="color: #10B981;">✅ TR Mevzuat & Uyum Paketi Başarıyla Bağlandı!</h2>
                <p><b>{store_domain}</b> mağazanız için Fiyat Etiketi ve Yasal Sözleşme modülleri aktif edildi.</p>
                <div style="background: #F3F4F6; padding: 20px; border-radius: 8px; margin-top: 20px;">
                    <p>Birim Fiyat Otomasyonu: <b>Aktif</b></p>
                    <p>Mesafeli Satış Sözleşmesi: <b>Aktif</b></p>
                </div>
            </body>
        </html>
    """)

# ---------------------------------------------------------
# MEVZUAT HESAPLAMA ENDPOINT
# ---------------------------------------------------------

@app.post("/api/v1/calculate-unit-price")
def calculate_unit_price(price: float, amount: float, unit: str):
    result = ComplianceEngine.calculate_unit_price(price, amount, unit)
    if result.get("has_error"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result