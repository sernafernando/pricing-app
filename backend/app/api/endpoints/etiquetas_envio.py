"""
Endpoints para gestión de etiquetas de envío flex.

Hub que incluye todos los sub-routers de etiquetas de envío.
Los endpoints están organizados en módulos por dominio:
- etiquetas_upload: carga de archivos ZPL, escaneo manual, borrado
- etiquetas_listing: listado con filtros y paginación, smart polling
- etiquetas_stats: estadísticas de distribución y por día
- etiquetas_export: exportación XLSX y XLS (Lightdata)
- etiquetas_assignments: logística, transporte, turbo, lluvia, flags, retornado
- etiquetas_manual: envíos manuales CRUD
- etiquetas_pistoleado: escaneo de paquetes en depósito
- etiquetas_enrichment: re-enrichment, geocodificación, impresión ZPL
"""

from fastapi import APIRouter

from app.api.endpoints.etiquetas_upload import router as upload_router
from app.api.endpoints.etiquetas_listing import router as listing_router
from app.api.endpoints.etiquetas_stats import router as stats_router
from app.api.endpoints.etiquetas_export import router as export_router
from app.api.endpoints.etiquetas_assignments import router as assignments_router
from app.api.endpoints.etiquetas_manual import router as manual_router
from app.api.endpoints.etiquetas_pistoleado import router as pistoleado_router
from app.api.endpoints.etiquetas_enrichment import router as enrichment_router

# Re-export schemas for backward compatibility
from app.api.endpoints.etiquetas_shared import *  # noqa: F401, F403

router = APIRouter()
router.include_router(upload_router)
router.include_router(listing_router)
router.include_router(stats_router)
router.include_router(export_router)
router.include_router(assignments_router)
router.include_router(manual_router)
router.include_router(pistoleado_router)
router.include_router(enrichment_router)
