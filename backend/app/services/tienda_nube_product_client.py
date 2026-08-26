"""
TN product WRITE client (Slice 2 unpublish + Slice 3a publish infrastructure
of tn-reconcile-publish).

Slice 2 shipped ONLY `PUT /v1/{store_id}/products/{id}` (`set_published`).
Slice 3a adds the two writes `publish_product` needs: `POST /products`
(`create_product`) and `POST /products/{id}/images` (`add_product_image`).
A second Slice 3a follow-up (security review: close the TOCTOU/duplicate-
publish gap) adds the one LIVE READ this feature needed:
`get_product_by_sku` (`GET /products?sku=`) — restoring the
"reconcile-via-read" step Slice 2 couldn't do (it had authorization for no
live TN GET at all).

A later feature (`tn-image-normalizer`) adds image bytes, listing and
deletion: `add_product_image` grew an `attachment=<raw bytes>` mode
alongside the original `src=<url>` one, and `list_product_images` /
`delete_product_image` arrived with it. The byte mode exists because a
locally normalized image has NO public URL for TN to fetch, and this
backend mounts no StaticFiles — verified live against the real store on
2026-08-26 before the code was written. The `src` mode is unchanged and
still the one `tn_publish_service` uses.

Credentials come from `TN_STORE_ID`/`TN_ACCESS_TOKEN` (see `app/core/config.py`
settings and the existing `tienda_nube_order_client.py` convention). The auth
header is TN's own non-standard scheme: `Authentication: bearer <token>`
(note the header name is "Authentication", not the usual "Authorization").

Like `MLWebhookClient`'s write methods, this client NEVER collapses an error
to `None` — it always returns a structured `{ok, status_code, ambiguous,
body}` outcome so `tn_publish_service` can classify a timeout/5xx as
ambiguous (needs surfacing, no retry) vs. a definitive 4xx rejection.
"""

import base64
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Sentinel distinguishing "argument not passed" (fall back to settings) from
# an explicitly-passed `None` (a caller — mainly tests — deliberately
# simulating absent credentials, which must NOT silently fall back to
# whatever real settings happen to be configured).
_UNSET = object()

# TN paginates `GET /categories` (30 items/page by default, 200 max). 200 is
# TN's own ceiling — asking for more is rejected, not honoured.
CATEGORIES_PAGE_SIZE = 200
# Explicit walk bound: at 200/page this covers 10k categories, far beyond any
# real TN store tree, while guaranteeing the loop terminates if TN ever
# ignores `page` and keeps returning full pages forever. Reaching it is an
# error (see `fetch_categories`), never a silent truncation.
CATEGORIES_MAX_PAGES = 50


class TnRateLimited(Exception):
    """Raised on a 429 response (TN's Weighted Token Bucket exhausted).

    Categorically distinct from the `{ok, ambiguous, ...}` dict contract
    the write methods return for a timeout/5xx (design Decision 6/R1): a
    429 is a definitive REJECTION — nothing was created — so
    `tn_publish_core.batch.execute_batch` may safely wait and retry it,
    unlike an ambiguous 5xx/timeout which must NEVER be blind-retried (see
    this module's docstring). `retry_after` is TN's own `Retry-After`
    header value in seconds, or `None` when TN did not send one (the
    caller then falls back to its own exponential backoff).
    """

    def __init__(self, retry_after: Optional[float] = None):
        self.retry_after = retry_after
        super().__init__(f"TN rate limited (429), retry_after={retry_after!r}")


def _parse_retry_after(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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

    async def add_product_image(
        self,
        product_id: int,
        src: Optional[str] = None,
        attachment: Optional[bytes] = None,
        filename: Optional[str] = None,
    ) -> Dict:
        """`POST /v1/{store_id}/products/{id}/images`.

        Two mutually-exclusive upload modes, matching TN's own API:

        - `src=<url>` (unchanged, pre-existing behaviour): TN fetches the
          image itself from a publicly reachable URL — this client never
          uploads bytes in this mode. Callers MUST validate `src` is a
          well-formed public http(s) URL before calling this (see
          `is_publicly_reachable_url` in this module) since a private/
          internal/malformed URL will simply fail on TN's side with no
          useful signal back to the operator. `tn_publish_service` relies
          on this exact mode/shape today — untouched by the byte-upload
          addition below.
        - `attachment=<raw bytes>` + `filename=<name>`: this client
          base64-encodes the bytes itself (TN's upload endpoint expects
          `{"attachment": <base64>, "filename": <name>}`) so callers hand
          over raw bytes, never a pre-encoded string.

        Returns:
            Same `{ok, status_code, ambiguous, body}` contract as
            `set_published`/`create_product`, plus `created_image_id` — the
            TN image id parsed from `body["id"]` on a 2xx response, or
            `None` when the response was 2xx but had no parseable id (an
            INCONCLUSIVE outcome a caller must not treat as a confirmed
            creation, e.g. by re-uploading blindly).
        """
        # Caller mistakes fail HERE, before a request is spent. This module
        # exists to tell a definitive rejection apart from an ambiguous one; a
        # malformed payload that reaches TN comes back as a 4xx that is
        # indistinguishable from TN rejecting a legitimate image.
        if (src is None) == (attachment is None):
            raise ValueError("add_product_image requires exactly one of src= or attachment=")
        if attachment is not None and not filename:
            raise ValueError("add_product_image(attachment=...) requires a non-empty filename=")

        if not self.base_url:
            logger.warning(
                "TiendaNubeProductClient sin credenciales — add_product_image omitido para product_id=%s", product_id
            )
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        if attachment is not None:
            payload = {"attachment": base64.b64encode(attachment).decode("ascii"), "filename": filename}
        else:
            payload = {"src": src}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.base_url}/products/{product_id}/images",
                    headers=self.headers,
                    json=payload,
                )
        except Exception as e:
            logger.error("Error (ambiguo) agregando imagen a product_id=%s: %s", product_id, e)
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        outcome = self._classify_write_response(response)
        created_image_id = None
        if outcome["ok"] and isinstance(outcome["body"], dict):
            created_image_id = outcome["body"].get("id")
        outcome["created_image_id"] = created_image_id
        return outcome

    async def list_product_images(self, product_id: int) -> Dict:
        """`GET /v1/{store_id}/products/{id}/images` — lists a product's images.

        A READ, not a write, so it does NOT go through
        `_classify_write_response`. Its return shape is deliberately
        distinct from the write contract so a caller can tell "listed
        successfully (possibly with zero images)" apart from "could not
        list" — load-bearing for a later baseline-read step that must
        abort on a failed list rather than silently treat it as "no
        images".

        Returns:
            `{ok, status_code, ambiguous, images}`. `ok=True` with
            `images=[]` means TN confirmed the product simply has no
            images. `ok=False` means the list could NOT be obtained
            (missing credentials, timeout/connection error, non-2xx, or
            an unparseable body) — `images` is `None` in that case, never
            an empty list, so the two cases are never confusable.

        Raises:
            `TnRateLimited` on a 429 — same handling as the write methods.
        """
        if not self.base_url:
            logger.warning(
                "TiendaNubeProductClient sin credenciales — list_product_images omitido para product_id=%s",
                product_id,
            )
            return {"ok": False, "status_code": None, "ambiguous": True, "images": None}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/products/{product_id}/images",
                    headers=self.headers,
                )
        except Exception as e:
            logger.error("Error (ambiguo) listando imagenes de product_id=%s: %s", product_id, e)
            return {"ok": False, "status_code": None, "ambiguous": True, "images": None}

        self._raise_if_rate_limited(response)

        if 200 <= response.status_code < 300:
            try:
                body = response.json()
            except Exception as e:
                logger.error("list_product_images: respuesta ilegible para product_id=%s: %s", product_id, e)
                return {"ok": False, "status_code": response.status_code, "ambiguous": True, "images": None}

            if not isinstance(body, list):
                logger.warning(
                    "list_product_images: forma de respuesta inesperada para product_id=%s (esperaba lista, "
                    "recibió %s)",
                    product_id,
                    type(body).__name__,
                )
                return {"ok": False, "status_code": response.status_code, "ambiguous": True, "images": None}

            return {"ok": True, "status_code": response.status_code, "ambiguous": False, "images": body}

        ambiguous = response.status_code >= 500
        return {"ok": False, "status_code": response.status_code, "ambiguous": ambiguous, "images": None}

    async def delete_product_image(self, product_id: int, image_id: int) -> Dict:
        """`DELETE /v1/{store_id}/products/{id}/images/{image_id}`.

        TN returns **200** (not 204) with an empty body `{}` on success —
        `_classify_write_response` already treats any 2xx as `ok=True`.

        Returns:
            Same `{ok, status_code, ambiguous, body}` contract as the other
            write methods.
        """
        if not self.base_url:
            logger.warning(
                "TiendaNubeProductClient sin credenciales — delete_product_image omitido para "
                "product_id=%s image_id=%s",
                product_id,
                image_id,
            )
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.delete(
                    f"{self.base_url}/products/{product_id}/images/{image_id}",
                    headers=self.headers,
                )
        except Exception as e:
            logger.error("Error (ambiguo) borrando imagen image_id=%s de product_id=%s: %s", image_id, product_id, e)
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

    async def fetch_categories(self) -> Optional[List[Dict[str, Any]]]:
        """`GET /v1/{store_id}/categories` — the WHOLE flat TN category list,
        each item shaped roughly `{"id": int, "name": {...lang: str},
        "parent": Optional[int], ...}` (feeds
        `tn_category_embedding_service.sync_category_embeddings`).

        TN paginates this endpoint (30 items/page by default). Requesting it
        unparameterized — as this method used to — returned only the FIRST
        page, so the mirror in `tn_category_embedding` silently held a
        fraction of the tree, alphabetically biased towards whichever branch
        TN happened to return first. Every downstream picker then had
        nothing else to offer, no matter how many rows the read endpoint was
        willing to hand back. So: walk the pages until one comes back short
        (or empty), bounded by an explicit `CATEGORIES_MAX_PAGES`.

        Unlike the write methods above, this is a best-effort READ: it
        returns `None` (never raises) on missing credentials, any HTTP
        error/timeout, a non-2xx response, or an unexpected (non-list) body
        shape — the sync service simply skips the refresh and logs, exactly
        like `embed_passages` returning `None` on embedder failure.

        Partial results are NEVER returned. A failure on page 3 yields
        `None`, not pages 1-2: the sync REPLACES the mirror wholesale, so
        handing it a truncated list would re-create the very defect this
        pagination exists to fix, while destroying a previously complete
        mirror. Failing closed leaves the last good mirror standing.
        """
        if not self.base_url:
            logger.warning("TiendaNubeProductClient sin credenciales — fetch_categories omitido")
            return None

        categories: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for page in range(1, CATEGORIES_MAX_PAGES + 1):
                    response = await client.get(
                        f"{self.base_url}/categories",
                        headers=self.headers,
                        params={"page": page, "per_page": CATEGORIES_PAGE_SIZE},
                    )

                    if not (200 <= response.status_code < 300):
                        logger.warning(
                            "fetch_categories: respuesta no-2xx de TN (status=%s, page=%s) — sync omitido",
                            response.status_code,
                            page,
                        )
                        return None

                    try:
                        body = response.json()
                    except Exception as e:
                        logger.error("fetch_categories: respuesta no es JSON válido (page=%s): %s", page, e)
                        return None

                    if not isinstance(body, list):
                        logger.warning(
                            "fetch_categories: forma de respuesta inesperada en page=%s "
                            "(esperaba una lista, recibió %s)",
                            page,
                            type(body).__name__,
                        )
                        return None

                    categories.extend(body)

                    # A short page is TN's end-of-collection signal; an empty
                    # one ends it too (exact multiple of the page size).
                    if len(body) < CATEGORIES_PAGE_SIZE:
                        return categories
        except Exception as e:
            logger.error("Error obteniendo categorías de TN: %s", e)
            return None

        # Cap reached without ever seeing a short page: either the catalog is
        # bigger than this method is willing to walk, or TN ignored `page`
        # and we would loop forever. Either way what we hold is a truncation
        # — report nothing rather than mirror a partial tree.
        logger.error(
            "fetch_categories: se alcanzó CATEGORIES_MAX_PAGES=%s sin fin de catálogo — sync omitido "
            "(subí el cap si el catálogo realmente creció)",
            CATEGORIES_MAX_PAGES,
        )
        return None

    @staticmethod
    def _raise_if_rate_limited(response: httpx.Response) -> None:
        """Raises `TnRateLimited` on a 429, otherwise a no-op.

        The single choke point EVERY method — read or write — routes
        through before classifying a response any other way: a per-method
        check is exactly what let 429 handling be forgotten on
        `set_published`/`add_product_image` while only `create_product` had
        it (the original defect that motivated centralizing this in
        `_classify_write_response` in the first place). `list_product_images`
        is a GET with no write classification to fall through to, but a
        429 there is just as real — an unhandled one would silently look
        like "the product has no images" instead of "could not check",
        which downstream turns into a false `aborted_no_baseline`.
        """
        if response.status_code == 429:
            raise TnRateLimited(_parse_retry_after(response))

    @staticmethod
    def _classify_write_response(response: httpx.Response) -> Dict:
        """2xx -> ok=True. 5xx -> ambiguous=True. 4xx -> definitive rejection.

        429 is checked via `_raise_if_rate_limited` HERE, uniformly, rather
        than per write method — every write method (including any added
        later) routes through this single choke point, so a 429 is always
        raised as `TnRateLimited` instead of silently falling through and
        being classified as a definitive 4xx rejection.
        """
        TiendaNubeProductClient._raise_if_rate_limited(response)

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
