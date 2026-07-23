"""
TN product WRITE client (Slice 2 of tn-reconcile-publish).

Scope is intentionally narrow: this slice's only write consumer is
unpublish, so ONLY `PUT /v1/{store_id}/products/{id}` (`set_published`) is
implemented. `POST /products`, image upload, and `DELETE` have no consumer
yet (they land in Slices 3/4) and are deliberately NOT added here — this
feature already had speculative surface rejected once during planning.

Credentials come from `TN_STORE_ID`/`TN_ACCESS_TOKEN` (see `app/core/config.py`
settings and the existing `tienda_nube_order_client.py` convention). The auth
header is TN's own non-standard scheme: `Authentication: bearer <token>`
(note the header name is "Authentication", not the usual "Authorization").

Like `MLWebhookClient`'s write methods, this client NEVER collapses an error
to `None` — it always returns a structured `{ok, status_code, ambiguous,
body}` outcome so `tn_publish_service` can classify a timeout/5xx as
ambiguous (needs surfacing, no retry) vs. a definitive 4xx rejection.
"""

import logging
from typing import Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Sentinel distinguishing "argument not passed" (fall back to settings) from
# an explicitly-passed `None` (a caller — mainly tests — deliberately
# simulating absent credentials, which must NOT silently fall back to
# whatever real settings happen to be configured).
_UNSET = object()


class TiendaNubeProductClient:
    """Client for authenticated TN product writes.

    Args:
        store_id: Overrides `settings.TN_STORE_ID`. Pass `None` explicitly
            (mainly in tests) to simulate absent credentials without falling
            back to real settings.
        access_token: Same contract as `store_id`, for `settings.TN_ACCESS_TOKEN`.

    Credentials are read fresh at construction time (not cached at module
    import), so a caller can construct a new instance per-call to pick up
    whatever `TN_STORE_ID`/`TN_ACCESS_TOKEN` are set at that moment.
    """

    def __init__(self, store_id: Optional[str] = _UNSET, access_token: Optional[str] = _UNSET):
        self.store_id = store_id if store_id is not _UNSET else settings.TN_STORE_ID
        self.access_token = access_token if access_token is not _UNSET else settings.TN_ACCESS_TOKEN

        if not self.store_id or not self.access_token:
            logger.warning("TN_STORE_ID o TN_ACCESS_TOKEN no configurados — TiendaNubeProductClient deshabilitado")
            self.base_url = None
        else:
            self.base_url = f"https://api.tiendanube.com/v1/{self.store_id}"

        self.headers = {
            "Authentication": f"bearer {self.access_token}",
            "User-Agent": "GAUSS Pricing App (pricing@gaussonline.com.ar)",
            "Content-Type": "application/json",
        }

    async def set_published(self, product_id: int, published: bool) -> Dict:
        """`PUT /v1/{store_id}/products/{id}` with `{"published": <published>}`.

        Returns:
            `{ok, status_code, ambiguous, body}`. `ambiguous=True` only on a
            timeout or connection error, or a 5xx response (outcome unknown
            at TN's end); a 4xx is a definitive rejection
            (`ok=False, ambiguous=False`); 2xx is success (`ok=True`).
        """
        if not self.base_url:
            logger.warning(
                "TiendaNubeProductClient sin credenciales — set_published omitido para product_id=%s", product_id
            )
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.put(
                    f"{self.base_url}/products/{product_id}",
                    headers=self.headers,
                    json={"published": published},
                )
        except Exception as e:
            logger.error("Error (ambiguo) publicando published=%s para product_id=%s: %s", published, product_id, e)
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        return self._classify_write_response(response)

    @staticmethod
    def _classify_write_response(response: httpx.Response) -> Dict:
        """2xx -> ok=True. 5xx -> ambiguous=True. 4xx -> definitive rejection."""
        try:
            body = response.json()
        except Exception:
            body = None

        if 200 <= response.status_code < 300:
            return {"ok": True, "status_code": response.status_code, "ambiguous": False, "body": body}

        if response.status_code >= 500:
            return {"ok": False, "status_code": response.status_code, "ambiguous": True, "body": body}

        return {"ok": False, "status_code": response.status_code, "ambiguous": False, "body": body}
