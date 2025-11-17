from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from app.api.endpoints import sync, productos, pricing, admin, auth, usuarios, auditoria, sync_ml, marcas_pm, mla_banlist, ventas_ml, commercial_transactions, comisiones, calculos, configuracion, items_sin_mla, dashboard_ml, erp_sync

app = FastAPI(
    title="Pricing API",
    description="API para gestión de precios de productos",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(auth.router, prefix="/api", tags=["Autenticación"])
app.include_router(sync.router, prefix="/api", tags=["Sincronización"])
app.include_router(productos.router, prefix="/api", tags=["Productos"])
app.include_router(pricing.router, prefix="/api", tags=["Pricing"])
app.include_router(admin.router, prefix="/api", tags=["Admin"])
app.include_router(usuarios.router, prefix="/api", tags=["usuarios"])
app.include_router(auditoria.router, prefix="/api", tags=["auditoria"])
app.include_router(sync_ml.router, prefix="/api", tags=["sync-ml"])
app.include_router(marcas_pm.router, prefix="/api", tags=["marcas-pm"])
app.include_router(mla_banlist.router, prefix="/api", tags=["mla-banlist"])
app.include_router(ventas_ml.router, prefix="/api", tags=["ventas-ml"])
app.include_router(commercial_transactions.router, prefix="/api", tags=["commercial-transactions"])
app.include_router(comisiones.router, prefix="/api", tags=["comisiones"])
app.include_router(calculos.router, prefix="/api", tags=["calculos"])
app.include_router(configuracion.router, prefix="/api", tags=["configuracion"])
app.include_router(items_sin_mla.router, prefix="/api/items-sin-mla", tags=["items-sin-mla"])
app.include_router(dashboard_ml.router, prefix="/api", tags=["dashboard-ml"])
app.include_router(erp_sync.router, prefix="/api", tags=["erp-sync"])

@app.get("/")
async def root():
    return {
        "message": "Pricing API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    }

@app.on_event("startup")
async def startup_event():
    print("🚀 Pricing API iniciada")

@app.on_event("shutdown")
async def shutdown_event():
    print("👋 Pricing API detenida")
