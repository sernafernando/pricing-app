"""Shared, side-effect-free helpers for `tienda_nube_productos` writers.

`tienda_nube_productos` has TWO writers: the cron script
(`scripts/sync_tienda_nube.py`) and `POST /api/tienda-nube/sync`
(`app/api/endpoints/tienda_nube.py`). Both must map TN's product-level
`published` boolean onto every per-variant row identically. This lives in
its own module — not in `scripts/sync_tienda_nube.py` — because that script
has module-level env-var validation that calls `sys.exit(1)` on
misconfiguration; importing it from application code (an endpoint module
loaded at FastAPI startup) would make an app boot crash on a missing env var
that script never needed the app itself to have.
"""

from typing import Optional


def extract_published_flag(product: dict) -> Optional[bool]:
    """Extract TN's product-level `published` flag for one /products entry.

    Missing/absent/non-bool `published` maps to `None` (unknown), never
    `False` — a writer that then blindly overwrites the stored value with
    `False` would silently and incorrectly report a real product as
    unpublished. Both writers additionally protect an existing non-null
    stored value from being nulled by a later `None` (COALESCE in the SQL
    writer, an explicit `if published is not None` guard in the ORM writer)
    — this function only produces the correctly-typed extracted value, it
    does not by itself guarantee that protection.
    """
    published = product.get("published")
    if not isinstance(published, bool):
        return None
    return published
