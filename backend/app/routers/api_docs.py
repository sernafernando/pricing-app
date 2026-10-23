"""OpenAPI schema for the in-app API docs page (`/api-docs` in the frontend).

FastAPI's own `/api/docs`, `/api/redoc` and `/api/openapi.json` stay disabled outside
development/testing (`_docs_urls` in `app.main`), and a browser navigation to them carries no
Bearer token, so no permission could be checked there. The frontend page fetches the schema
from this endpoint with the user's token instead, in every environment, behind
`admin.ver_api_docs`.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_permiso

PERMISO_API_DOCS = "admin.ver_api_docs"

router = APIRouter()


@router.get(
    "/dev/openapi.json",
    response_model=dict[str, Any],
    include_in_schema=False,
    dependencies=[Depends(require_permiso(PERMISO_API_DOCS))],
)
async def openapi_schema(request: Request) -> dict[str, Any]:
    """Return the full OpenAPI schema of the app, the same one `/api/openapi.json` serves in dev.

    `app.openapi()` builds it once and caches it, whether or not FastAPI's own docs routes are
    mounted. The endpoint is left out of the schema so the docs only list business endpoints.
    """
    return request.app.openapi()
