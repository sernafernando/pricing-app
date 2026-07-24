"""
TN product WRITE client (Slice 2 unpublish + Slice 3a publish infrastructure
of tn-reconcile-publish).

Slice 2 shipped ONLY `PUT /v1/{store_id}/products/{id}` (`set_published`).
Slice 3a adds the two writes `publish_product` needs: `POST /products`
(`create_product`) and `POST /products/{id}/images` (`add_product_image`,
by `src` URL — TN fetches the image itself, we never upload bytes). A
second Slice 3a follow-up (security review: close the TOCTOU/duplicate-
publish gap) adds the one LIVE READ this feature needed:
`get_product_by_sku` (`GET /products?sku=`) — restoring the
"reconcile-via-read" step Slice 2 couldn't do (it had authorization for no
live TN GET at all). `DELETE` still has no consumer (Slice 4) and is
deliberately NOT added here — this feature already had speculative surface
rejected once during planning.

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


class TnProductLookupError(Exception):
    """Raised by `get_product_by_sku` when TN's existence CANNOT be
    confirmed (missing credentials, timeout, connection error, or a 5xx
    response). Deliberately NOT collapsed into the `{ok, ambiguous, ...}`
    dict contract the write methods use: the caller (`publish_product`)
    needs to distinguish "confirmed absent" (`None` return) from "couldn't
    check" (this exception) with zero risk of a careless `if not result`
    check silently treating "unknown" the same as "confirmed absent" — that
    confusion is exactly what would let a duplicate-publish slip through.
    """


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

    async def create_product(self, payload: Dict) -> Dict:
        """`POST /v1/{store_id}/products` — creates a new TN product.

        Args:
            payload: The full TN product-creation body (name, categories,
                variants, etc.) — this client does no validation of shape;
                the caller (`tn_publish_service.publish_product`) is
                responsible for assembling a valid payload.

        Returns:
            Same `{ok, status_code, ambiguous, body}` contract as
            `set_published` — 2xx is success (`body` carries the created
            product, including its TN `id`), 4xx a definitive rejection,
            timeout/5xx/connection-error ambiguous (never retried here).
        """
        if not self.base_url:
            logger.warning("TiendaNubeProductClient sin credenciales — create_product omitido")
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(f"{self.base_url}/products", headers=self.headers, json=payload)
        except Exception as e:
            logger.error("Error (ambiguo) creando producto TN: %s", e)
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        return self._classify_write_response(response)

    async def add_product_image(self, product_id: int, src: str) -> Dict:
        """`POST /v1/{store_id}/products/{id}/images` with `{"src": <src>}`.

        TN fetches the image from `src` itself (a publicly reachable URL) —
        this client never uploads image bytes. Callers MUST validate `src`
        is a well-formed public http(s) URL before calling this (see
        `is_publicly_reachable_url` in this module) since a private/internal/
        malformed URL will simply fail on TN's side with no useful signal
        back to the operator.

        Returns:
            Same `{ok, status_code, ambiguous, body}` contract as
            `set_published`/`create_product`.
        """
        if not self.base_url:
            logger.warning(
                "TiendaNubeProductClient sin credenciales — add_product_image omitido para product_id=%s", product_id
            )
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.base_url}/products/{product_id}/images",
                    headers=self.headers,
                    json={"src": src},
                )
        except Exception as e:
            logger.error("Error (ambiguo) agregando imagen a product_id=%s: %s", product_id, e)
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        return self._classify_write_response(response)

    async def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """`GET /v1/{store_id}/products/sku/{sku}` — the LIVE read primitive
        that restores the "reconcile-via-read" step `unpublish_product`
        (Slice 2) couldn't do, and that `publish_product`'s idempotency
        pre-check and ambiguous-outcome read-back both rely on.

        Returns:
            The matched product dict if TN has one for this SKU, or `None`
            if TN confirms none exists (a 404, or a 200 with an empty body).

        Raises:
            `TnProductLookupError` if existence CANNOT be confirmed either
            way — missing credentials, a connection error/timeout, or a 5xx
            response. Callers MUST treat this the same as "ambiguous" in the
            write-safety sense: never conclude "safe to create" from a
            failed lookup.
        """
        if not self.base_url:
            raise TnProductLookupError(f"TiendaNubeProductClient sin credenciales — no se puede verificar sku={sku}")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{self.base_url}/products/sku/{sku}", headers=self.headers)
        except Exception as e:
            raise TnProductLookupError(f"Error de transporte consultando sku={sku}: {e}") from e

        if response.status_code == 404:
            return None

        if response.status_code >= 500:
            raise TnProductLookupError(f"TN devolvió {response.status_code} consultando sku={sku}")

        if 200 <= response.status_code < 300:
            try:
                body = response.json()
            except Exception as e:
                raise TnProductLookupError(f"Respuesta ilegible consultando sku={sku}: {e}") from e

            if isinstance(body, list):
                return body[0] if body else None
            return body or None

        # Any other 4xx (not 404) — TN's own contract for this endpoint
        # only documents 404 as "not found"; treat anything else
        # unexpected as an inability to confirm rather than guessing.
        raise TnProductLookupError(f"TN devolvió {response.status_code} inesperado consultando sku={sku}")

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


def is_publicly_reachable_url(url: Optional[str]) -> bool:
    """Well-formed-URL GUARD, not a live reachability check.

    TN's `POST /products/{id}/images` fetches the image itself from `src` —
    it never receives uploaded bytes from us. If `src` is malformed, or
    points at a private/internal/loopback host, TN's own fetch will fail
    with no useful diagnostic surfaced back to the operator (flagged risk in
    the design doc). This function catches the cheap, local, no-network
    cases before we ever call `add_product_image`:

      - must parse as an absolute URL with an `http`/`https` scheme
      - must have a non-empty hostname
      - the hostname must not be a loopback/private/link-local/reserved
        literal IP (`127.0.0.1`, `10.x`, `192.168.x`, `169.254.x`, etc.)

    This is deliberately NOT a live network reachability check (no DNS
    resolution, no HTTP HEAD) — that would add latency/flakiness to the
    publish path and could itself be used to probe internal hosts from the
    server. A hostname like `localhost` or a private-range literal IP is
    rejected without any network call; a public-looking hostname that
    happens to be unreachable is TN's problem to report, not ours to predict.
    """
    if not url or not isinstance(url, str):
        return False

    from urllib.parse import urlparse

    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    if hostname.lower() == "localhost":
        return False

    import ipaddress

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # Not a literal IP — a normal DNS hostname, accepted.
        return True

    return not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast)
