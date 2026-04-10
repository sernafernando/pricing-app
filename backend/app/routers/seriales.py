"""
Router para traza de números de serie (módulo RMA)
Permite consultar el historial completo de movimientos de un serial.

Hub: incluye todos los sub-routers de seriales.
"""

from fastapi import APIRouter

from app.routers.seriales_claims import router as claims_router
from app.routers.seriales_messages import router as messages_router
from app.routers.seriales_traza import router as traza_router
from app.routers.seriales_traza_cliente import router as traza_cliente_router
from app.routers.seriales_traza_factura import router as traza_factura_router
from app.routers.seriales_traza_ml import router as traza_ml_router

router = APIRouter(prefix="/seriales", tags=["Seriales"])

router.include_router(traza_cliente_router)
router.include_router(traza_factura_router)
router.include_router(traza_router)
router.include_router(traza_ml_router)
router.include_router(claims_router)
router.include_router(messages_router)
