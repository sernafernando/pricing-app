"""
Write-safety orchestrator for TN product-publication writes (Slice 2
unpublish + Slice 3a publish infrastructure).

Slice 2 shipped `unpublish_product` only. This module now also has
`publish_product` (Slice 3a — backend publish infrastructure; the category
picker and description-editor UI that supply `category_id`/`description_html`
to it are Slice 3b/3c, not built yet). Both mirror the pattern in
`ml_promotions_write_service.py`:

  1. Fresh read BEFORE write — re-queries `tienda_nube_productos` for the
     product's CURRENT locally-known `published` state right before writing,
     never relying on state the caller may have loaded earlier.
  2. Idempotent no-op — if every local row for the product is already
     `published=False`, the write is skipped entirely (no redundant PUT for
     an already-unpublished product; a double-click is a safe no-op).
  3. Single-shot write, NO retry on an ambiguous outcome (timeout/5xx) — a
     blind retry could double-apply an in-flight write.
  4. Every outcome (submitted, rejected, ambiguous, already_unpublished,
     not_found) is audit-logged via the existing `auditoria` mechanism.

Reconcile-via-read limitation (documented, not hidden): unlike
`ml_promotions_write_service`, this slice has NO live TN GET client method in
scope — only `PUT /v1/{store_id}/products/{id}` was authorized for Slice 2
(POST/image-upload/DELETE have no consumer yet and are deliberately absent).
So an ambiguous outcome (timeout/5xx) cannot be reconciled against a live TN
read the way `ml_promotions_write_service.reconcile_write_outcome` does. It
is surfaced to the operator as `status="ambiguous"` and the local
`tienda_nube_productos.published` mirror is left UNCHANGED — the real state
is genuinely unknown until the next `sync_tienda_nube` run. A definitive 2xx
response DOES update the local mirror immediately (best-effort, logged on
failure) so the reconciliation view reflects the change without waiting for
the next sync.
"""

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import nh3
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_publish_override import TnPublishOverride
from app.models.usuario import Usuario
from app.services.tienda_nube_product_client import (
    TiendaNubeProductClient,
    TnProductLookupError,
    is_publicly_reachable_url,
)
from app.services.tn_publish_core.batch import execute_batch
from app.utils.async_bridge import resolve_maybe_async as _resolve

logger = logging.getLogger(__name__)

# Conservative allow-list for `sanitize_description_html` — basic
# formatting/structure only. No `<script>`, `<style>`, `<iframe>`, no
# event-handler attributes, no `javascript:`/`data:` URLs — nh3 (an ammonia/
# html5ever binding) strips anything not explicitly allowed here, including
# attributes, by default.
_DESCRIPTION_ALLOWED_TAGS = {
    "p",
    "br",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ul",
    "ol",
    "li",
    "a",
    "span",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}

# Only `href` on `<a>` is allowed through; nh3's `url_schemes` further
# restricts that `href` to http/https (never `javascript:`/`data:`/etc.).
_DESCRIPTION_ALLOWED_ATTRIBUTES = {"a": {"href"}}


class InvalidPublishPriceError(ValueError):
    """Raised by `_validate_publish_price` — absent/non-numeric/non-positive
    submitted price. `publish_product` catches this internally, audit-logs
    the rejection, and returns `status="rejected_invalid_price"`; the
    endpoint surfaces that status as a 4xx (see `tienda_nube_reconcile.py`).
    """


def _validate_publish_price(product_data: Dict[str, Any]) -> Decimal:
    """Containment guard for the money path (Slice 2), NOT verification.

    The offset used to compute `product_data["price"]` lives entirely in the
    frontend (a per-publish, operator-editable modal preset — see
    `TnPublishModal.jsx`); no server-side pricing constant exists to
    recompute it against. This guard therefore only rejects the
    CATEGORICALLY invalid — absent, non-numeric, non-finite, or non-positive
    — before the price ever reaches the TN create payload. It never verifies
    the price is the CORRECT one; only that it is a plausible one.

    Raises `InvalidPublishPriceError` (never returns) on any rejection.
    `Decimal(str(...))` at the boundary — a raw `float` must never reach the
    money value (see `precio_lista_ml`'s `Float` vs `precio_web_transferencia`'s
    `Numeric(15, 2)` mismatch documented in `tn_reconciliation_service`).
    """
    raw = product_data.get("price")
    if raw is None or raw == "":
        raise InvalidPublishPriceError(
            "El producto no tiene un precio de publicación. No se puede publicar sin precio."
        )
    try:
        price = Decimal(str(raw))
    except InvalidOperation as e:
        raise InvalidPublishPriceError(f"Precio de publicación inválido: {raw!r}") from e
    # `Decimal("NaN")`/`Decimal("Infinity")` parse without raising and would
    # otherwise slip past a naive `price <= 0` check (NaN compares False to
    # everything) — reject them explicitly by name rather than relying on
    # that comparison to catch them.
    if not price.is_finite():
        raise InvalidPublishPriceError(f"Precio de publicación inválido (no es un número finito): {raw!r}")
    if price <= 0:
        raise InvalidPublishPriceError(f"Precio de publicación inválido (debe ser mayor a cero): {raw!r}")
    return price


def sanitize_description_html(html: str) -> str:
    """Server-side defense-in-depth HTML sanitizer for `description_html`.

    Runs UNCONDITIONALLY in `publish_product`, regardless of any
    frontend-side sanitization (Slice 3c's planned DOMPurify pass) — this is
    a second, independent layer, not a replacement. The endpoint is
    reachable directly by anyone holding `admin.gestionar_tn_publicacion`
    (e.g. via a raw API call bypassing the frontend entirely), and
    `description_html` is written straight to the LIVE TN storefront, so an
    unsanitized value here is exploitable in isolation the moment this
    endpoint is deployed, independent of whether Slice 3c ever ships.

    Uses `nh3` (Rust/`ammonia`-backed, fast, actively maintained) with a
    CONSERVATIVE allow-list — see `_DESCRIPTION_ALLOWED_TAGS`/
    `_DESCRIPTION_ALLOWED_ATTRIBUTES` above. Everything else (`<script>`,
    `<style>`, `<iframe>`, event-handler attributes like `onerror`/`onload`/
    `onclick`, `javascript:`/`data:` URLs) is stripped, not escaped —
    `nh3.clean` removes disallowed tags/attributes entirely rather than
    HTML-entity-escaping them, so no attacker-controlled markup survives in
    a re-interpretable form.
    """
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=_DESCRIPTION_ALLOWED_TAGS,
        attributes=_DESCRIPTION_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https"},
    )


def _audit(db: Session, usuario: Usuario, product_id: int, outcome: Dict[str, Any]) -> None:
    """Best-effort audit log — a logging failure must never mask or reverse
    the TN write outcome already computed and about to be returned."""
    # Only a genuinely-submitted write actually flipped `published` to False.
    # A rejected/ambiguous/already-unpublished/not-found outcome changed
    # nothing, so recording a True->False transition on those would make the
    # structured audit fields contradict what really happened (the money-path
    # audit trail must not lie — the `comentario` already carries the status).
    changed = outcome.get("status") == "submitted"
    try:
        db.add(
            Auditoria(
                item_id=product_id,
                usuario_id=usuario.id,
                tipo_accion=TipoAccion.TN_DESPUBLICAR,
                valores_anteriores={"published": True} if changed else None,
                valores_nuevos={"published": False} if changed else None,
                comentario=f"TN unpublish product_id={product_id}: status={outcome.get('status')}",
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Audit log failed for TN unpublish product_id=%s: %s", product_id, e, exc_info=True)


def _classify(write_result: Dict[str, Any]) -> Dict[str, Any]:
    """Classifies a single-shot PUT result. 2xx -> submitted. 4xx ->
    definitive rejection, no reconciliation attempted. timeout/5xx ->
    ambiguous (see module docstring for why this cannot be reconciled via a
    live read in this slice)."""
    if write_result["ok"]:
        return {"submitted": True, "status": "submitted", "status_code": write_result["status_code"]}

    if not write_result["ambiguous"]:
        # `detail` is typed `Optional[str]` on the endpoint's response model,
        # but TN's rejection body is usually a parsed JSON dict — serialize it
        # so returning the outcome can never 500 on model validation.
        body = write_result.get("body")
        if body is not None and not isinstance(body, str):
            body = json.dumps(body, default=str)
        return {
            "submitted": False,
            "status": "rejected_by_proxy",
            "status_code": write_result["status_code"],
            "detail": body,
        }

    return {
        "submitted": False,
        "status": "ambiguous",
        "status_code": write_result["status_code"],
        "detail": (
            "TN write timed out or returned 5xx; outcome unknown at TN's "
            "end. The local published mirror is left unchanged until the "
            "next sync — re-check before retrying."
        ),
    }


def unpublish_product(
    db: Session, usuario: Usuario, product_id: int, client: Optional[TiendaNubeProductClient] = None
) -> Dict[str, Any]:
    """Unpublishes a single TN product (`published: false`).

    Permission gating happens at the endpoint layer — this function assumes
    the caller already authorized the operator via `verificar_permiso`.

    Args:
        db: An active SQLAlchemy session (also used to commit the audit row
            and, on success, the local `published` mirror update).
        usuario: The operator triggering the action (for the audit log).
        product_id: TN's product id (shared by all of that product's
            variant rows in `tienda_nube_productos`).
        client: Optional injected `TiendaNubeProductClient` (tests only); a
            fresh one is constructed from current settings otherwise.

    Returns:
        `{submitted, status, ...}` — see `_classify` for the write-outcome
        shapes, plus `status="rejected_not_found"` (no local rows for this
        product_id) and `status="already_unpublished"` (idempotent no-op).
    """
    rows = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == product_id).all()

    if not rows:
        outcome: Dict[str, Any] = {
            "submitted": False,
            "status": "rejected_not_found",
            "detail": f"No local tienda_nube_productos rows found for product_id={product_id}",
        }
        _audit(db, usuario, product_id, outcome)
        return outcome

    if all(row.published is False for row in rows):
        outcome = {"submitted": False, "status": "already_unpublished", "detail": None}
        _audit(db, usuario, product_id, outcome)
        return outcome

    active_client = client if client is not None else TiendaNubeProductClient()
    write_result = _resolve(active_client.set_published(product_id, False))
    outcome = _classify(write_result)

    if outcome["status"] == "submitted":
        for row in rows:
            row.published = False
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(
                "Local published-mirror update failed after successful TN unpublish product_id=%s: %s",
                product_id,
                e,
                exc_info=True,
            )

    _audit(db, usuario, product_id, outcome)
    return outcome


def _audit_publish(
    db: Session,
    usuario: Usuario,
    item_id: Optional[int],
    outcome: Dict[str, Any],
    submitted_price: Optional[str] = None,
    offset_percent: Optional[float] = None,
    price_base_source: Optional[str] = None,
) -> None:
    """Same best-effort audit contract as `_audit`, for `TN_PUBLICAR`.

    `item_id` may be `None` for a rejected/ambiguous outcome where TN never
    returned a product id (nothing was created, so there is nothing to key
    the audit row to besides the action itself).

    Money-path traceability (Slice 2, R2.5): on a `submitted` outcome,
    `valores_nuevos` ALSO records `submitted_price` and `offset_percent`/
    `price_base_source` — since the backend cannot recompute the price (the
    surcharge offset lives entirely in the frontend), this audit row is the
    ONLY artifact able to answer "why did this product go live at this
    number?" after the fact. Recording the base source alongside the value
    is what makes the trail reconstructable: the price alone cannot
    distinguish an intended web-transfer price from a mistakenly-seeded
    Clásica one.
    """
    valores_nuevos = None
    if outcome.get("status") == "submitted":
        valores_nuevos = {"product_id": item_id}
        if submitted_price is not None:
            valores_nuevos["submitted_price"] = submitted_price
        if offset_percent is not None:
            valores_nuevos["offset_percent"] = offset_percent
        if price_base_source is not None:
            valores_nuevos["price_base_source"] = price_base_source
    try:
        db.add(
            Auditoria(
                item_id=item_id,
                usuario_id=usuario.id,
                tipo_accion=TipoAccion.TN_PUBLICAR,
                valores_anteriores=None,
                valores_nuevos=valores_nuevos,
                comentario=f"TN publish: status={outcome.get('status')}",
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Audit log failed for TN publish item_id=%s: %s", item_id, e, exc_info=True)


def _upsert_publish_overrides(db: Session, usuario: Usuario, ean: str, overrides: Optional[Dict[str, str]]) -> None:
    """PC5/D8 (design Decision 5, task 5.4/5.5): persist every
    operator-edited field into `tn_publish_override`, one row per `(ean,
    campo)`. Called ONLY after a `submitted` outcome — never on a
    rejected/ambiguous/blocked publish, so a failed attempt can never leave
    behind an override the operator never actually confirmed went live.

    D8 is enforced structurally, not by convention: this function has no
    GBP/ERP write client on its call path at all — it only ever touches
    `tn_publish_override` via the ORM session already passed in.

    Best-effort like every other audit-adjacent write in this module: a
    failure here must never mask or reverse the TN write outcome the caller
    already computed and is about to return.
    """
    if not overrides:
        return
    try:
        existing_by_campo = {
            row.campo: row for row in db.query(TnPublishOverride).filter(TnPublishOverride.ean == ean).all()
        }
        for campo, valor in overrides.items():
            row = existing_by_campo.get(campo)
            if row is not None:
                row.valor = valor
                row.usuario_id = usuario.id
            else:
                db.add(TnPublishOverride(ean=ean, campo=campo, valor=valor, usuario_id=usuario.id))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Override upsert failed for ean=%s: %s", ean, e, exc_info=True)


def _extract_variant_id(product_body: Optional[Dict[str, Any]]) -> Optional[int]:
    """Extract the REAL per-variant TN id from a full product response body.

    `create_product`/`get_product_by_sku` both return TN's product shape —
    `{"id": <product_id>, "variants": [{"id": <variant_id>, ...}], ...}` —
    the same shape `tienda_nube_sync_shared.extract_variantes` reads from
    the catalog sync. Returns `None` when the body has no usable variant
    data, so the caller never falls back to fabricating a value (e.g. the
    product id) in its place.
    """
    if not isinstance(product_body, dict):
        return None
    variants = product_body.get("variants")
    if not isinstance(variants, list) or not variants:
        return None
    first_variant = variants[0]
    if not isinstance(first_variant, dict):
        return None
    variant_id = first_variant.get("id")
    return variant_id if isinstance(variant_id, int) else None


def _upsert_publish_mirror(
    db: Session,
    product_id: Optional[int],
    ean: str,
    product_name: Optional[str],
    variant_id: Optional[int] = None,
) -> None:
    """Best-effort local-mirror sync after ANY publish outcome that confirms
    a TN product exists for `ean` (a fresh create, an `already_exists` live
    pre-check hit, or a recovered-via-read-back ambiguous outcome). A
    logging failure here must never mask or reverse the outcome already
    computed by the caller.

    Updates the existing row if one is already keyed by `product_id`
    (e.g. discovered live but not yet locally known), otherwise inserts a
    new row — same shape `unpublish_product`'s success path assumes
    elsewhere in this module.

    `variant_id` (the REAL id, from `_extract_variant_id`) is REQUIRED to
    insert a new row: `TiendaNubeProducto.variant_id` is NOT NULL, so this
    can't leave it null/pending the way the nullable `published` column
    does. When `variant_id` is unknown, the insert is skipped entirely
    (logged, not fatal) rather than fabricating one (e.g. `product_id`) —
    the row is created correctly by the next full catalog sync instead.
    """
    if product_id is None:
        return
    try:
        existing_row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == product_id).first()
        if existing_row is not None:
            existing_row.variant_sku = existing_row.variant_sku or ean
            existing_row.published = True
        elif variant_id is not None:
            db.add(
                TiendaNubeProducto(
                    product_id=product_id,
                    product_name=product_name,
                    variant_id=variant_id,
                    variant_sku=ean,
                    published=True,
                )
            )
        else:
            logger.warning(
                "Local mirror insert skipped for product_id=%s ean=%s: TN's response carried no "
                "usable variant id, and variant_id is NOT NULL — the row will be created correctly "
                "by the next full catalog sync instead of being fabricated.",
                product_id,
                ean,
            )
            return
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Local mirror upsert failed for product_id=%s ean=%s: %s", product_id, ean, e, exc_info=True)


def publish_product(
    db: Session,
    usuario: Usuario,
    ean: str,
    product_data: Dict[str, Any],
    category_id: int,
    description_html: str,
    image_srcs: List[str],
    client: Optional[TiendaNubeProductClient] = None,
    offset_percent: Optional[float] = None,
    price_base_source: Optional[str] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Creates a single TN product from GBP-derived data (Slice 3a).

    Explicit single-item action — never bulk, never automatic, mirroring
    `unpublish_product`'s non-goal.

    Args:
        db: Active SQLAlchemy session (audit + best-effort local mirror row).
        usuario: The operator triggering the action (for the audit log).
        ean: The GBP `Código` / join key. Used for the idempotency
            check-before-POST (see below) and stored on the local mirror row
            this creates on success.
        product_data: The GBP-derived TN product payload fragment (name,
            variants, price, etc. — assembled by the caller/Slice 3b; this
            function does not validate its shape beyond merging in
            `categories`/`description`).
        category_id: TN category id (Slice 3b's embedder-suggested,
            operator-confirmed category — this function trusts it as given).
        description_html: HTML that will ALSO be sanitized on the frontend
            (Slice 3c's planned DOMPurify pass), but treated as untrusted
            here regardless — this function always runs
            `sanitize_description_html` on it before it reaches the TN
            payload. See the "Defense in depth" note below.
        image_srcs: Ordered list of publicly-reachable image URLs (GBP's
            image1..image10 columns, in order). Each is checked with
            `is_publicly_reachable_url` before being sent to TN — an
            obviously private/malformed URL is silently skipped (not sent,
            not fatal to the publish) and reported back in
            `skipped_image_srcs` so the operator can see what didn't make it.
        client: Optional injected `TiendaNubeProductClient` (tests only).

    Idempotency (check-before-POST, local-mirror-only): before creating,
    this checks whether ANY `tienda_nube_productos` row already has this EAN
    as its `variant_sku`. If so, it returns `status="already_published"`
    without ever calling TN — prevents duplicate-product creation on a
    double submit. Same documented limitation as `unpublish_product`: no
    live TN GET is in scope this slice, so this is best-effort against the
    LOCAL mirror, not a live TN lookup; a product created directly in TN
    (outside this app) between syncs would not be caught until the next
    `sync_tienda_nube` run populates the mirror.

    Single-shot POST, NO retry on ambiguous (timeout/5xx) — same rule as
    `unpublish_product`; a blind retry on `POST /products` risks creating
    TWO products for one submission, which is worse than a single ambiguous
    outcome the operator has to manually verify.

    Defense in depth (security review follow-up, added after initial 3a
    ship): `description_html` is UNCONDITIONALLY run through
    `sanitize_description_html` (nh3, conservative allow-list) before it is
    placed into the TN create-product payload — regardless of whether the
    frontend's planned DOMPurify pass (Slice 3c) has shipped yet. This
    endpoint is reachable directly by anyone holding
    `admin.gestionar_tn_publicacion` (a raw API call bypassing the frontend
    entirely), and an unsanitized `description_html` is written straight to
    the LIVE TN storefront — so relying solely on frontend sanitization left
    this exploitable in isolation the moment the endpoint was deployed. Both
    layers (frontend DOMPurify + this backend pass) are intentionally kept;
    neither replaces the other.

    Money-path guard (Slice 2, containment NOT verification): `product_data`
    MUST carry a `price` — absent, non-numeric, non-finite, or non-positive
    is rejected with `status="rejected_invalid_price"` BEFORE anything else
    in this function runs (no local-mirror query, no live TN call). The
    backend cannot recompute the price itself (the surcharge offset is a
    frontend-only preset — see `TnPublishModal.jsx`), so this only rejects
    the categorically invalid; see `_validate_publish_price`'s docstring.
    `offset_percent`/`price_base_source` are recorded on the audit row
    alongside the submitted price for after-the-fact traceability (R2.5) —
    they play no role in this validation.
    """
    try:
        price = _validate_publish_price(product_data)
    except InvalidPublishPriceError as e:
        outcome: Dict[str, Any] = {
            "submitted": False,
            "status": "rejected_invalid_price",
            "detail": str(e),
        }
        _audit_publish(db, usuario, None, outcome)
        return outcome
    submitted_price = str(price)

    existing = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_sku == ean).first()
    if existing is not None:
        outcome: Dict[str, Any] = {
            "submitted": False,
            "status": "already_published",
            "detail": f"A tienda_nube_productos row already exists locally for ean={ean}",
        }
        _audit_publish(db, usuario, existing.product_id, outcome)
        return outcome

    active_client = client if client is not None else TiendaNubeProductClient()
    product_name = product_data.get("name", {}).get("es") if isinstance(product_data.get("name"), dict) else None

    # LIVE pre-check (security review follow-up): the authority for
    # idempotency, restoring the reconcile-via-read step Slice 2 couldn't do
    # (it had no live TN GET at all). The local-mirror check above is only a
    # cheap early gate for the common case; this is what actually decides.
    try:
        live_existing = _resolve(active_client.get_product_by_sku(ean))
    except TnProductLookupError as e:
        outcome = {
            "submitted": False,
            "status": "precheck_failed",
            "detail": (
                f"Could not confirm via TN whether ean={ean} already exists ({e}); "
                "refusing to create to avoid a possible duplicate. Retry once TN is reachable."
            ),
        }
        _audit_publish(db, usuario, None, outcome)
        return outcome

    if live_existing is not None:
        live_product_id = live_existing.get("id")
        outcome = {
            "submitted": False,
            "status": "already_exists",
            "product_id": live_product_id,
            "detail": f"TN already has a product for ean={ean} (found via live pre-check).",
        }
        # Best-effort: bring the local mirror in sync with what TN actually
        # has, even though this call didn't create it.
        _upsert_publish_mirror(db, live_product_id, ean, product_name, _extract_variant_id(live_existing))
        _audit_publish(db, usuario, live_product_id, outcome)
        return outcome

    # Bugfix (out-of-band, post-Slice-3a): the price MUST live on the
    # variant, not the product root — this repo's own TN READ path
    # (`tienda_nube_sync_shared.py`) only ever reads `variant["price"]`, so a
    # root-level `price` may simply be ignored by TN on create. Worse, a
    # product created with no `sku` at all breaks this module's entire
    # write-safety design: both the idempotency pre-check above
    # (`get_product_by_sku`) and the ambiguous-outcome read-back below
    # depend on TN being able to find the product by SKU. Built here
    # (server-side) rather than trusted from the caller, because `ean` is
    # authoritative at this point (already used for the pre-check) and this
    # keeps a single variant shape regardless of what `product_data` looked
    # like historically.
    #
    # We have not verified against the live TN API that a root-level
    # `price` is ignored or that `variants: [{sku, price}]` is accepted on
    # create — this aligns the create payload with the shape TN
    # demonstrably RETURNS on read, and with what the idempotency/read-back
    # calls in this module already depend on.
    #
    # `sku`/`price` are MERGED into an incoming variant rather than replacing
    # it: a caller that starts sending stock/weight/dimensions on the variant
    # would otherwise have them silently discarded here. This function still
    # owns `sku` and `price` — those two it overwrites deliberately, since the
    # EAN and the validated price are authoritative at this point.
    payload = dict(product_data)
    payload.pop("price", None)
    incoming_variants = payload.get("variants")
    base_variant = dict(incoming_variants[0]) if isinstance(incoming_variants, list) and incoming_variants else {}
    base_variant["sku"] = ean
    base_variant["price"] = submitted_price
    payload["variants"] = [base_variant]
    payload["categories"] = [category_id]
    # Server-side defense-in-depth (security review follow-up to sub-slice
    # 3a): sanitize BEFORE this ever reaches the TN payload, unconditionally
    # — see `sanitize_description_html`'s docstring for why this does not
    # wait on / depend on Slice 3c's frontend DOMPurify pass.
    payload["description"] = {"es": sanitize_description_html(description_html)}

    def _attach_images(product_id: Any) -> List[str]:
        reachable_srcs = [src for src in image_srcs if is_publicly_reachable_url(src)]
        skipped_srcs = [src for src in image_srcs if src not in reachable_srcs]
        if skipped_srcs:
            logger.warning(
                "publish_product: %d image src(s) skipped (failed is_publicly_reachable_url) for product_id=%s",
                len(skipped_srcs),
                product_id,
            )
        for src in reachable_srcs:
            # Best-effort: an individual image failing to attach does not
            # roll back the already-created product — TN products with
            # missing images are visibly incomplete but not broken the way a
            # duplicate/ambiguous product create would be.
            image_result = _resolve(active_client.add_product_image(product_id, src))
            if not image_result.get("ok"):
                logger.warning(
                    "publish_product: add_product_image failed for product_id=%s src=%s: %s",
                    product_id,
                    src,
                    image_result,
                )
        return skipped_srcs

    # PR-5b (design Decision 6, task 5.18): the live single-item write goes
    # through `execute_batch([item])` — the SAME execution path a future
    # bulk publish will use, per "batch is the only execution path" (no
    # second code path for bulk to grow into). `TnRateLimited` is no longer
    # caught here directly; `execute_batch` owns that classification.
    #
    # `max_rate_limit_attempts=0`: an interactive single-item click must
    # surface a structured `rate_limited` outcome immediately rather than
    # block synchronously for the multi-second backoff window a bulk job
    # can afford (see `batch.py`'s docstring on this parameter) — the
    # classification/audit contract is identical either way, only the wait
    # budget differs. A future bulk endpoint calling `execute_batch`
    # directly is free to use the default (real backoff, real retries).
    call_detail: Dict[str, Any] = {}

    def _do_create(_item: Dict[str, Any]) -> Dict[str, Any]:
        write_result = _resolve(active_client.create_product(payload))  # may raise TnRateLimited

        if write_result["ok"]:
            body = write_result.get("body") or {}
            product_id = body.get("id")
            skipped_srcs = _attach_images(product_id)
            _upsert_publish_mirror(db, product_id, ean, product_name, _extract_variant_id(body))
            call_detail["skipped_image_srcs"] = skipped_srcs
            return {"status": "submitted", "product_id": product_id}

        if not write_result["ambiguous"]:
            body = write_result.get("body")
            if body is not None and not isinstance(body, str):
                body = json.dumps(body, default=str)
            call_detail["status_code"] = write_result["status_code"]
            return {"status": "rejected_by_proxy", "detail": body}

        # Ambiguous create (timeout/5xx): attempt ONE read-back via
        # `get_product_by_sku` before surfacing "ambiguous" — this is a
        # READ, not a write-retry, so it does not violate the
        # no-retry-on-ambiguous rule. If TN actually completed the create
        # despite the ambiguous response, the read-back finds it and this
        # recovers as a genuine success; otherwise (confirmed absent, or
        # the read-back itself fails) it stays ambiguous and no local
        # mirror row is created — safe to manually retry.
        call_detail["status_code"] = write_result["status_code"]
        try:
            readback = _resolve(active_client.get_product_by_sku(ean))
        except TnProductLookupError:
            readback = None

        if readback is not None:
            recovered_product_id = readback.get("id")
            skipped_srcs = _attach_images(recovered_product_id)
            _upsert_publish_mirror(db, recovered_product_id, ean, product_name, _extract_variant_id(readback))
            call_detail["skipped_image_srcs"] = skipped_srcs
            return {
                "status": "submitted",
                "product_id": recovered_product_id,
                "detail": "Recovered via read-back after an ambiguous create outcome.",
            }

        return {
            "status": "ambiguous",
            "detail": (
                "TN create-product write timed out or returned 5xx; outcome unknown at TN's end. "
                "A read-back confirmed no product exists yet (or the read-back itself failed) — "
                "no local mirror row was created. Re-check TN directly before retrying to avoid a duplicate."
            ),
        }

    batch_outcomes = execute_batch(
        [{"ean": ean}],
        _do_create,
        max_rate_limit_attempts=0,
    )
    item_outcome = batch_outcomes[0]

    if item_outcome.status == "rate_limited":
        outcome = {
            "submitted": False,
            "status": "rate_limited",
            "status_code": 429,
            "detail": item_outcome.detail or "TN rate limit (429) — nothing was created. Wait a moment and retry.",
        }
        _audit_publish(db, usuario, None, outcome)
        return outcome

    if item_outcome.status == "submitted":
        outcome = {
            "submitted": True,
            "status": "submitted",
            "product_id": item_outcome.product_id,
            "skipped_image_srcs": call_detail.get("skipped_image_srcs", []),
        }
        if item_outcome.detail:
            outcome["detail"] = item_outcome.detail
        _audit_publish(
            db,
            usuario,
            item_outcome.product_id,
            outcome,
            submitted_price=submitted_price,
            offset_percent=offset_percent,
            price_base_source=price_base_source,
        )
        _upsert_publish_overrides(db, usuario, ean, overrides)
        return outcome

    if item_outcome.status == "rejected_by_proxy":
        outcome = {
            "submitted": False,
            "status": "rejected_by_proxy",
            "status_code": call_detail.get("status_code"),
            "detail": item_outcome.detail,
        }
        _audit_publish(db, usuario, None, outcome)
        return outcome

    outcome = {
        "submitted": False,
        "status": "ambiguous",
        "status_code": call_detail.get("status_code"),
        "detail": item_outcome.detail,
    }
    _audit_publish(db, usuario, None, outcome)
    return outcome
