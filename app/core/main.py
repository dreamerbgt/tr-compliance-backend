import os
import json
import logging
import traceback
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UyumHub")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase bağlantısı kuruldu.")
    except Exception as e:
        logger.error(f"Supabase hatası: {str(e)}")


app = FastAPI(title="UyumHub Mevzuat Platformu", version="2.5.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# IFRAME KISITLAMALARINI TAMAMEN KALDIRAN MIDDLEWARE
@app.middleware("http")
async def remove_iframe_locks(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "frame-ancestors *;"
    response.headers["Access-Control-Allow-Origin"] = "*"
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    if "x-frame-options" in response.headers:
        del response.headers["x-frame-options"]
    return response


def normalize_domain(raw_domain: Optional[str]) -> str:
    if not raw_domain: 
        return "dev-mevzuattestmagaza.myikas.com"
    raw_domain = str(raw_domain).strip().lower()
    if "." not in raw_domain:
        return f"{raw_domain}.myikas.com"
    return raw_domain


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


def render_fail_safe_dashboard(domain: str, is_dev: bool = False) -> str:
    profile = get_merchant_profile(domain)
    is_developer = is_dev or ("dev-" in domain) or ("test" in domain)

    dev_btn = ""
    if is_developer:
        dev_btn = '<a href="/agency/dashboard" target="_blank" style="background:#0f172a; color:#34d399; padding:6px 12px; border-radius:8px; font-size:12px; text-decoration:none; font-weight:bold; border:1px solid #059669;">Dev: Ajans Paneli</a>'

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>UyumHub Mevzuat Paneli</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            // ikas iframe çarkını anında durduran sinyal
            function notifyIkas() {{
                try {{
                    window.parent.postMessage({{ type: "IKAS_APP_LOADED", loaded: true }}, "*");
                    window.parent.postMessage("IKAS_APP_READY", "*");
                }} catch(e) {{}}
            }}
            window.onload = notifyIkas;
            setTimeout(notifyIkas, 100);
        </script>
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans p-6">
        <div class="max-w-5xl mx-auto space-y-6">
            <div class="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex justify-between items-center">
                <div>
                    <h1 class="text-xl font-bold text-slate-900">UyumHub TR Mevzuat & Birim Fiyat Suite</h1>
                    <p class="text-sm text-slate-500">Mağaza: <span class="font-semibold text-indigo-600">{domain}</span></p>
                </div>
                <div class="flex items-center gap-3">
                    <span class="px-3 py-1 rounded-full text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">İKAS AKTİF</span>
                    {dev_btn}
                    <button onclick="loadProducts()" class="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold px-4 py-2 rounded-xl">Yenile</button>
                </div>
            </div>

            <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
                <h2 class="text-base font-bold text-slate-900 mb-4">Birim Fiyat Etiket Analizi</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm">
                        <thead class="bg-slate-50 text-slate-500 uppercase text-xs border-b">
                            <tr>
                                <th class="p-3">Ürün Adı</th>
                                <th class="p-3">SKU</th>
                                <th class="p-3">Satış Fiyatı</th>
                                <th class="p-3">Miktar</th>
                                <th class="p-3">Birim Fiyat Etiketi</th>
                            </tr>
                        </thead>
                        <tbody id="products-list">
                            <tr><td colspan="5" class="p-4 text-center text-slate-400">Yükleniyor...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            async function loadProducts() {{
                const el = document.getElementById("products-list");
                try {{
                    const res = await fetch("/api/v1/compliance/sync-products?storeDomain={domain}");
                    const data = await res.json();
                    if (data.products) {{
                        el.innerHTML = "";
                        data.products.forEach(p => {{
                            p.variants.forEach(v => {{
                                el.innerHTML += `
                                    <tr class="border-b hover:bg-slate-50">
                                        <td class="p-3 font-semibold text-slate-800">${{p.product_name}}</td>
                                        <td class="p-3 text-xs font-mono text-slate-500">${{v.sku}}</td>
                                        <td class="p-3">${{v.price}} TL</td>
                                        <td class="p-3">${{v.weight}} ${{v.unit}}</td>
                                        <td class="p-3"><span class="bg-indigo-50 text-indigo-700 border border-indigo-200 text-xs font-bold px-2.5 py-1 rounded-md">${{v.compliance.display_text}}</span></td>
                                    </tr>
                                `;
                            }});
                        }});
                    }}
                }} catch(e) {{
                    el.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-red-500">Veri yüklenemedi.</td></tr>';
                }}
            }}
            loadProducts();
        </script>
    </body>
    </html>
    """


# --- KESİNTİSİZ LAUNCH VE CALLBACK ENDPOINTLERİ ---
@app.get("/api/v1/ikas/launch", response_class=HTMLResponse)
async def ikas_launch(request: Request):
    try:
        params = dict(request.query_params)
        logger.info(f"IKAS LAUNCH GELEN PARAMS: {params}")
        raw_domain = params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
        domain = normalize_domain(raw_domain)
        return HTMLResponse(content=render_fail_safe_dashboard(domain, is_dev=True))
    except Exception as err:
        logger.error(f"IKAS LAUNCH HATA: {traceback.format_exc()}")
        return HTMLResponse(content=render_fail_safe_dashboard("dev-mevzuattestmagaza.myikas.com", is_dev=True))


@app.get("/api/v1/ikas/callback", response_class=HTMLResponse)
async def ikas_callback(request: Request):
    try:
        params = dict(request.query_params)
        raw_domain = params.get("state") or params.get("storeName") or params.get("storeDomain") or params.get("shop") or "dev-mevzuattestmagaza.myikas.com"
        domain = normalize_domain(raw_domain)
        return HTMLResponse(content=render_fail_safe_dashboard(domain, is_dev=True))
    except Exception as err:
        return HTMLResponse(content=render_fail_safe_dashboard("dev-mevzuattestmagaza.myikas.com", is_dev=True))


@app.get("/dashboard", response_class=HTMLResponse)
async def render_dashboard(request: Request, storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    is_dev = request.query_params.get("dev") == "true"
    return HTMLResponse(content=render_fail_safe_dashboard(domain, is_dev=is_dev))


@app.get("/api/v1/compliance/sync-products")
async def sync_products(storeDomain: str = "dev-mevzuattestmagaza.myikas.com"):
    domain = normalize_domain(storeDomain)
    return {
        "status": "success",
        "products": [
            {"product_name": "Ege Sızma Zeytinyağı 1000 ml", "variants": [{"sku": "ZTY-1L", "price": 380.0, "weight": 1.0, "unit": "L", "compliance": {"display_text": "Birim Fiyatı: 380.00 TL/L"}}]},
            {"product_name": "Organik Çam Balı 850 gr", "variants": [{"sku": "BAL-850G", "price": 425.0, "weight": 0.85, "unit": "kg", "compliance": {"display_text": "Birim Fiyatı: 500.00 TL/kg"}}]}
        ]
    }

@app.get("/agency/dashboard", response_class=HTMLResponse)
async def agency_dashboard():
    return HTMLResponse(content="<div style='font-family:sans-serif; padding:40px;'><h1>Ajans Partner Paneli</h1><p>Komisyon Oranı: %25</p></div>")

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(content="<div style='font-family:sans-serif; padding:40px;'><h1>UyumHub Giriş</h1><a href='/dashboard'>Panele Git</a></div>")

@app.get("/")
async def root(): return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health(): return {"status": "healthy"}