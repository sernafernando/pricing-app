"""
Rentabilidad module - Hub file.

Routes are split across focused modules:
- rentabilidad_shared.py    — Shared filter helpers (aplicar_filtro_marcas_pm, aplicar_filtro_tienda_oficial)
- rentabilidad_schemas.py   — Pydantic models (CardRentabilidad, RentabilidadResponse, etc.)
- rentabilidad_dashboard.py — GET /rentabilidad (main dashboard endpoint)
- rentabilidad_buscar.py    — GET /rentabilidad/buscar-productos
- rentabilidad_filtros.py   — GET /rentabilidad/filtros
"""

from fastapi import APIRouter

from app.api.endpoints.rentabilidad_dashboard import router as dashboard_router
from app.api.endpoints.rentabilidad_buscar import router as buscar_router
from app.api.endpoints.rentabilidad_filtros import router as filtros_router

router = APIRouter()
router.include_router(dashboard_router)
router.include_router(buscar_router)
router.include_router(filtros_router)
