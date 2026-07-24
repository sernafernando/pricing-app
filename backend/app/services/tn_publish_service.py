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
from typing import Any, Dict, List, Optional

import nh3
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.usuario import Usuario
from app.services.tienda_nube_product_client import (
    TiendaNubeProductClient,
    TnProductLookupError,
    is_publicly_reachable_url,
)
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


def _audit_publish(db: Session, usuario: Usuario, item_id: Optional[int], outcome: Dict[str, Any]) -> None:
    """Same best-effort audit contract as `_audit`, for `TN_PUBLICAR`.

    `item_id` may be `None` for a rejected/ambiguous outcome where TN never
    returned a product id (nothing was created, so there is nothing to key
    the audit row to besides the action itself)."""
    try:
        db.add(
            Auditoria(
                item_id=item_id,
                usuario_id=usuario.id,
                tipo_accion=TipoAccion.TN_PUBLICAR,
                valores_anteriores=None,
                valores_nuevos={"product_id": item_id} if outcome.get("status") == "submitted" else None,
                comentario=f"TN publish: status={outcome.get('status')}",
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Audit log failed for TN publish item_id=%s: %s", item_id, e, exc_info=True)


def _upsert_publish_mirror(db: Session, product_id: Optional[int], ean: str, product_name: Optional[str]) -> None:
    """Best-effort local-mirror sync after ANY publish outcome that confirms
    a TN product exists for `ean` (a fresh create, an `already_exists` live
    pre-check hit, or a recovered-via-read-back ambiguous outcome). A
    logging failure here must never mask or reverse the outcome already
    computed by the caller.

    Updates the existing row if one is already keyed by `product_id`
    (e.g. discovered live but not yet locally known), otherwise inserts a
    new row — same shape `unpublish_product`'s success path assumes
    elsewhere in this module.
    """
    if product_id is None:
        return
    try:
        existing_row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == product_id).first()
        if existing_row is not None:
            existing_row.variant_sku = existing_row.variant_sku or ean
            existing_row.published = True
        else:
            db.add(
                TiendaNubeProducto(
                    product_id=product_id,
                    product_name=product_name,
                    variant_id=product_id,
                    variant_sku=ean,
                    published=True,
                )
            )
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
    """
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
        _upsert_publish_mirror(db, live_product_id, ean, product_name)
        _audit_publish(db, usuario, live_product_id, outcome)
        return outcome

    payload = dict(product_data)
    payload["categories"] = [category_id]
    # Server-side defense-in-depth (security review follow-up to sub-slice
    # 3a): sanitize BEFORE this ever reaches the TN payload, unconditionally
    # — see `sanitize_description_html`'s docstring for why this does not
    # wait on / depend on Slice 3c's frontend DOMPurify pass.
    payload["description"] = {"es": sanitize_description_html(description_html)}

    write_result = _resolve(active_client.create_product(payload))

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

    if write_result["ok"]:
        body = write_result.get("body") or {}
        product_id = body.get("id")
        skipped_srcs = _attach_images(product_id)

        outcome = {
            "submitted": True,
            "status": "submitted",
            "product_id": product_id,
            "skipped_image_srcs": skipped_srcs,
        }
        _upsert_publish_mirror(db, product_id, ean, product_name)
        _audit_publish(db, usuario, product_id, outcome)
        return outcome

    if not write_result["ambiguous"]:
        body = write_result.get("body")
        if body is not None and not isinstance(body, str):
            body = json.dumps(body, default=str)
        outcome = {
            "submitted": False,
            "status": "rejected_by_proxy",
            "status_code": write_result["status_code"],
            "detail": body,
        }
        _audit_publish(db, usuario, None, outcome)
        return outcome

    # Ambiguous create (timeout/5xx): attempt ONE read-back via
    # `get_product_by_sku` before surfacing "ambiguous" — this is a READ,
    # not a write-retry, so it does not violate the no-retry-on-ambiguous
    # rule. If TN actually completed the create despite the ambiguous
    # response, the read-back finds it and this recovers as a genuine
    # success; otherwise (confirmed absent, or the read-back itself fails)
    # it stays ambiguous and no local mirror row is created — safe to
    # manually retry.
    try:
        readback = _resolve(active_client.get_product_by_sku(ean))
    except TnProductLookupError:
        readback = None

    if readback is not None:
        recovered_product_id = readback.get("id")
        skipped_srcs = _attach_images(recovered_product_id)
        outcome = {
            "submitted": True,
            "status": "submitted",
            "product_id": recovered_product_id,
            "skipped_image_srcs": skipped_srcs,
            "detail": "Recovered via read-back after an ambiguous create outcome.",
        }
        _upsert_publish_mirror(db, recovered_product_id, ean, product_name)
        _audit_publish(db, usuario, recovered_product_id, outcome)
        return outcome

    outcome = {
        "submitted": False,
        "status": "ambiguous",
        "status_code": write_result["status_code"],
        "detail": (
            "TN create-product write timed out or returned 5xx; outcome unknown at TN's end. "
            "A read-back confirmed no product exists yet (or the read-back itself failed) — "
            "no local mirror row was created. Re-check TN directly before retrying to avoid a duplicate."
        ),
    }
    _audit_publish(db, usuario, None, outcome)
    return outcome
