from fastapi import APIRouter

from app.api.endpoints.productos_listing import router as listing_router
from app.api.endpoints.productos_detail import router as detail_router
from app.api.endpoints.productos_stats import router as stats_router
from app.api.endpoints.productos_pricing import router as pricing_router
from app.api.endpoints.productos_export import router as export_router
from app.api.endpoints.productos_colors import router as colors_router
from app.api.endpoints.productos_gremio import router as gremio_router
from app.api.endpoints.productos_metadata import router as metadata_router
from app.api.endpoints.productos_sync import router as sync_router

# Re-export schemas for backward compatibility
from app.api.endpoints.productos_shared import *  # noqa: F401, F403

router = APIRouter()
router.include_router(listing_router)
router.include_router(detail_router)
router.include_router(stats_router)
router.include_router(pricing_router)
router.include_router(export_router)
router.include_router(colors_router)
router.include_router(gremio_router)
router.include_router(metadata_router)
router.include_router(sync_router)
