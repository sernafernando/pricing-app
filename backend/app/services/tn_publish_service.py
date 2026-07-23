"""
Write-safety orchestrator for TN product-publication writes (Slice 2).

The sole consumer this slice is `unpublish_product` — publish is deferred to
Slice 3 (it depends on the category picker and description editor Slice 3
introduces; publishing without them would put uncategorised products with
raw ERP descriptions on the live store). This module mirrors the pattern in
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
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.usuario import Usuario
from app.services.tienda_nube_product_client import TiendaNubeProductClient
from app.utils.async_bridge import resolve_maybe_async as _resolve

logger = logging.getLogger(__name__)


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
