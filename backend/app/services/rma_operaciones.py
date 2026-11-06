"""The ML operation behind an RMA case, read from the ML orders we already store (never a live ML call).

A case's `ml_id` is free text: usually the ML order id the trace copied into it, but a user may type the pack id or
the shipment number instead. It is matched like the ML trace matches one value
(`seriales_traza_ml.QUERY_MLO_CANDIDATES_BY_INPUT`: header order id, header ml_id, pack id, or a shipping row's
shipment), for a whole page at once. The operation is the pack when the order belongs to one (a cart: one order per
article, one shipment), else the order itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.mercadolibre_order_header import MercadoLibreOrderHeader as Header
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping as Shipping


@dataclass(frozen=True)
class OperacionML:
    operacion: str
    numero_envio: str | None


def _id(value: str | None) -> str | None:
    """A stored id, or None for the empty and '0' placeholders the ERP mirror leaves."""
    value = (value or "").strip()
    return value if value and value != "0" else None


def resolver_operaciones(db: Session, valores: Iterable[str]) -> dict[str, OperacionML]:
    """Each value that names a stored ML sale, mapped to its operation and shipping number. Two queries for any
    number of values; a value with no stored sale is left out."""
    buscados = {v for v in valores if v}
    if not buscados:
        return {}

    por_envio = select(Shipping.mlo_id).where(Shipping.mlshippingid.in_(buscados))
    headers = db.execute(
        select(Header.mlo_id, Header.mlorder_id, Header.ml_id, Header.ml_pack_id, Header.mlshippingid)
        .where(
            or_(
                Header.mlorder_id.in_(buscados),
                Header.ml_id.in_(buscados),
                Header.ml_pack_id.in_(buscados),
                Header.mlo_id.in_(por_envio),
            )
        )
        # Newest first, so a value that several rows name (a pack) always resolves to the same row.
        .order_by(Header.mlo_id.desc())
    ).all()
    if not headers:
        return {}

    envios: dict[int, list[str]] = {}
    for mlo_id, envio in db.execute(
        select(Shipping.mlo_id, Shipping.mlshippingid)
        .where(Shipping.mlo_id.in_([h.mlo_id for h in headers]))
        .order_by(Shipping.mlm_id.desc())
    ).all():
        if _id(envio):
            envios.setdefault(mlo_id, []).append(_id(envio))

    resueltas: dict[str, OperacionML] = {}
    for h in headers:
        operacion = _id(h.ml_pack_id) or _id(h.mlorder_id) or _id(h.ml_id)
        if not operacion:
            continue
        de_envio = envios.get(h.mlo_id, [])
        # The shipping row wins over the header's own column, like the trace's COALESCE.
        numero_envio = de_envio[0] if de_envio else _id(h.mlshippingid)
        nombres = {_id(h.mlorder_id), _id(h.ml_id), _id(h.ml_pack_id), _id(h.mlshippingid), *de_envio}
        for valor in buscados & nombres:
            resueltas.setdefault(valor, OperacionML(operacion=operacion, numero_envio=numero_envio))
    return resueltas
