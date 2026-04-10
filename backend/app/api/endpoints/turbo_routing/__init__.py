"""
Turbo Routing — hub que combina todos los sub-routers.

Módulos:
  _shared        – Schemas, helpers, cache compartido
  envios         – Envíos pendientes, vista admin, detalle
  motoqueros     – CRUD motoqueros
  zonas          – CRUD zonas + auto-generación K-Means
  asignaciones   – Asignación manual, automática, seguimiento diario
  estadisticas   – Estadísticas + invalidación de cache
  geocoding      – Geocodificación individual, batch Mapbox, batch ML
  banlist        – Banlist de envíos Turbo
"""

from fastapi import APIRouter

from .asignaciones import router as asignaciones_router
from .banlist import router as banlist_router
from .envios import router as envios_router
from .estadisticas import router as estadisticas_router
from .geocoding import router as geocoding_router
from .motoqueros import router as motoqueros_router
from .zonas import router as zonas_router

router = APIRouter()

router.include_router(envios_router)
router.include_router(motoqueros_router)
router.include_router(zonas_router)
router.include_router(asignaciones_router)
router.include_router(estadisticas_router)
router.include_router(geocoding_router)
router.include_router(banlist_router)
