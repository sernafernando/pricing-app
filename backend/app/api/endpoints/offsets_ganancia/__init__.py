"""
Offsets Ganancia — hub module.

Combines all sub-routers into a single ``router`` that main.py includes.
Re-exports schemas so external code can still do:
    from app.api.endpoints.offsets_ganancia import OffsetGananciaResponse
"""

from fastapi import APIRouter

from ._grupos import router as _grupos_router
from ._filtros import router as _filtros_router
from ._offsets_crud import router as _offsets_crud_router
from ._utilidades import router as _utilidades_router
from ._consumo_grupos import router as _consumo_grupos_router
from ._consumo_individual import router as _consumo_individual_router

# Re-export all schemas for backward compatibility
from ._schemas import (  # noqa: F401
    OffsetGrupoFiltroCreate,
    OffsetGrupoFiltroResponse,
    OffsetGrupoCreate,
    OffsetGrupoResponse,
    OffsetGananciaCreate,
    OffsetGananciaUpdate,
    OffsetGananciaResponse,
    ProductoBusquedaGeneral,
    OffsetGrupoConsumoResponse,
    OffsetGrupoResumenResponse,
)

router = APIRouter()

router.include_router(_grupos_router)
router.include_router(_filtros_router)
router.include_router(_offsets_crud_router)
router.include_router(_utilidades_router)
router.include_router(_consumo_grupos_router)
router.include_router(_consumo_individual_router)
