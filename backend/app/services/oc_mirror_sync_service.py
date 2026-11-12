"""On-demand OC sync into tb_purchase_order_* via gbp-parser (braID+pohID).

Does not touch recepciones (append-only). Fields cover detalle/saldos reads.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as dateutil_parser
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_oc import triples_for_pedido
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.purchase_order_header import PurchaseOrderHeader

logger = logging.getLogger(__name__)

# After depósito control started/finished, refreshing the OC mirror would drift
# saldos vs locked ingresos (controlado is terminal; con_faltantes still has counts).
ESTADOS_SYNC_OC_BLOQUEADOS: frozenset[str] = frozenset({"controlado", "con_faltantes"})

# Minimal columns for link validation + detalle/saldos (pod_qty / confirmed / item / stor).
_HEADER_PLAIN = {
    "supp_id": "supp_id",
    "poh_total": "poh_total",
    "poh_ACurrency": "poh_acurrency",
    "user_id": "user_id",
}
_HEADER_DT = {"poh_cd": "poh_cd", "poh_isEditingCd": "poh_iseditingcd"}
_HEADER_BOOL = {"poh_isEditing": "poh_isediting"}
_DETAIL_PLAIN = {
    "item_id": "item_id",
    "stor_id": "stor_id",
    "pod_qty": "pod_qty",
    "pod_price": "pod_price",
    "pod_confirmedQTY": "pod_confirmedqty",
    "pod_initQty": "pod_initqty",
    "pod_obs": "pod_obs",
}
_DETAIL_DT = {"pod_isEditingCd": "pod_iseditingcd"}
_DETAIL_BOOL = {
    "pod_isProcessed": "pod_isprocessed",
    "pod_isEditing": "pod_isediting",
}


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("T", " ").replace("Z", ""))
    except ValueError:
        pass
    try:
        return dateutil_parser.parse(val)
    except (ValueError, TypeError):
        return None


def _parse_bool(val: Any) -> bool | None:
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("true", "1", "t", "y", "yes", "si"):
        return True
    if s in ("false", "0", "f", "n", "no"):
        return False
    return None


def _map_record(
    record: dict[str, Any],
    *,
    pk: dict[str, Any],
    plain: dict[str, str],
    dts: dict[str, str],
    bools: dict[str, str],
) -> dict[str, Any]:
    out = dict(pk)
    for src, dest in plain.items():
        out[dest] = record.get(src)
    for src, dest in dts.items():
        out[dest] = _parse_dt(record.get(src))
    for src, dest in bools.items():
        out[dest] = _parse_bool(record.get(src))
    return out


def _fetch_gbp(params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(settings.GBP_PARSER_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("oc_mirror_sync: GBP fetch failed params=%s err=%s", params, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo sincronizar la OC desde el ERP (gbp-parser).",
        ) from exc
    return data if isinstance(data, list) else []


def _upsert(db: Session, *, model: type, filters: dict[str, Any], datos: dict[str, Any]) -> str:
    existente = db.query(model).filter_by(**filters).first()
    with db.begin_nested():
        if existente:
            for key, value in datos.items():
                setattr(existente, key, value)
        else:
            db.add(model(**datos))
        db.flush()
    return "updated" if existente else "created"


def sync_oc_triple(
    db: Session,
    *,
    oc_comp_id: int,
    oc_bra_id: int,
    oc_poh_id: int,
) -> dict[str, Any]:
    """Pull one OC from GBP and upsert header + detail for that triple.

    After upserting, deletes local detail rows whose ``pod_id`` is absent from
    the GBP payload so item replacements (new pod, old pod gone) do not leave
    stale products in the mirror.

    GBP quirks (verified live):
    - ``scriptPurchaseOrderHeader`` treats ``pohID`` as exclusive lower bound
      (``poh_id > pohID``), so we pass ``poh_id - 1`` and then filter exact.
    - ``scriptPurchaseOrderDetail`` treats ``pohID`` as inclusive
      (``poh_id >= pohID``); exact filter still applied.
    """
    header_poh_floor = max(int(oc_poh_id) - 1, 0)
    raw_headers = _fetch_gbp(
        {
            "strScriptLabel": "scriptPurchaseOrderHeader",
            "braID": int(oc_bra_id),
            "pohID": header_poh_floor,
        }
    )
    raw_details = _fetch_gbp(
        {"strScriptLabel": "scriptPurchaseOrderDetail", "braID": int(oc_bra_id), "pohID": int(oc_poh_id)}
    )

    def _match(r: dict[str, Any]) -> bool:
        return (
            int(r.get("comp_id") or 0) == int(oc_comp_id)
            and int(r.get("bra_id") or 0) == int(oc_bra_id)
            and int(r.get("poh_id") or 0) == int(oc_poh_id)
        )

    headers = [r for r in raw_headers if _match(r)]
    details = [r for r in raw_details if _match(r)]
    if not headers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OC ({oc_comp_id},{oc_bra_id},{oc_poh_id}) no encontrada en el ERP para sincronizar.",
        )

    pk = {"comp_id": oc_comp_id, "bra_id": oc_bra_id, "poh_id": oc_poh_id}
    header_counts = {"created": 0, "updated": 0, "error": 0}
    for record in headers:
        datos = _map_record(record, pk=pk, plain=_HEADER_PLAIN, dts=_HEADER_DT, bools=_HEADER_BOOL)
        key = _upsert(db, model=PurchaseOrderHeader, filters=pk, datos=datos)
        header_counts[key] = header_counts.get(key, 0) + 1

    detail_counts = {"created": 0, "updated": 0, "deleted": 0, "error": 0}
    seen_pod_ids: set[int] = set()
    for record in details:
        pod_id = record.get("pod_id")
        if pod_id is None:
            detail_counts["error"] += 1
            continue
        pod_id_int = int(pod_id)
        seen_pod_ids.add(pod_id_int)
        detail_pk = {**pk, "pod_id": pod_id_int}
        datos = _map_record(record, pk=detail_pk, plain=_DETAIL_PLAIN, dts=_DETAIL_DT, bools=_DETAIL_BOOL)
        key = _upsert(db, model=PurchaseOrderDetail, filters=detail_pk, datos=datos)
        detail_counts[key] = detail_counts.get(key, 0) + 1

    # GBP item swaps often retire the old pod_id and insert a new one. Upsert
    # alone would leave the stale item visible in the mirror forever.
    orphan_q = db.query(PurchaseOrderDetail).filter_by(**pk)
    if seen_pod_ids:
        orphan_q = orphan_q.filter(PurchaseOrderDetail.pod_id.notin_(seen_pod_ids))
    deleted = orphan_q.delete(synchronize_session=False)
    detail_counts["deleted"] = int(deleted or 0)
    if deleted:
        db.flush()

    return {
        "oc_comp_id": int(oc_comp_id),
        "oc_bra_id": int(oc_bra_id),
        "oc_poh_id": int(oc_poh_id),
        "header": header_counts,
        "detail": detail_counts,
        "detail_lines": len(details),
    }


def sync_ocs_for_pedido(
    db: Session,
    *,
    pedido_id: int,
    oc_comp_id: int | None = None,
    oc_bra_id: int | None = None,
    oc_poh_id: int | None = None,
) -> list[dict[str, Any]]:
    """Sync all linked OCs for a pedido, or one triple if provided.

    Blocked when the pedido is already under depósito control (`con_faltantes`
    or terminal `controlado`): mirror refresh would desync live saldos from
    append-only ingresos. `recibido` (arrival only) remains allowed.
    """
    pedido = db.get(PedidoCompra, pedido_id)
    if pedido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")

    if pedido.estado in ESTADOS_SYNC_OC_BLOQUEADOS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede actualizar la OC: el pedido ya tiene control de depósito "
                f"(estado='{pedido.estado}'). Revertí el control desde Depósito primero."
            ),
        )

    triples = triples_for_pedido(db, pedido)
    if not triples:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El pedido no tiene OC vinculada para sincronizar.",
        )

    if oc_comp_id is not None or oc_bra_id is not None or oc_poh_id is not None:
        if oc_comp_id is None or oc_bra_id is None or oc_poh_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="oc_comp_id, oc_bra_id y oc_poh_id deben ir juntos.",
            )
        target = (int(oc_comp_id), int(oc_bra_id), int(oc_poh_id))
        if target not in triples:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esa OC no está vinculada a este pedido.",
            )
        triples = [target]

    return [sync_oc_triple(db, oc_comp_id=c, oc_bra_id=b, oc_poh_id=p) for c, b, p in triples]
