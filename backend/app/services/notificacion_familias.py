"""
Notification families: how /notificaciones and the bell group notification tipos into tabs.

- compras: every ``compras.*`` alert (item_id is the pedido id, not a product)
- markup: ``markup_bajo``
- tecnicas: technical alerts (``ml_bot.*``, ``tickets.*``)
- otras: everything else
"""

from __future__ import annotations

from typing import Literal, get_args

from sqlalchemy import ColumnElement, and_, not_, or_

from app.models.notificacion import Notificacion

Familia = Literal["compras", "markup", "tecnicas", "otras"]
FAMILIAS: tuple[str, ...] = get_args(Familia)

_PREFIJOS_TECNICAS = ("ml_bot.", "tickets.")


def familia_de_tipo(tipo: str) -> str:
    """Family of a notification tipo."""
    if tipo.startswith("compras."):
        return "compras"
    if tipo == "markup_bajo":
        return "markup"
    if tipo.startswith(_PREFIJOS_TECNICAS):
        return "tecnicas"
    return "otras"


def es_de_producto(tipo: str) -> bool:
    """Whether item_id of this tipo is a product (compras use the pedido id, technical alerts have none)."""
    return familia_de_tipo(tipo) in ("markup", "otras")


def _es_compras() -> ColumnElement[bool]:
    return Notificacion.tipo.like("compras.%")


def _es_tecnica() -> ColumnElement[bool]:
    return or_(*(Notificacion.tipo.like(f"{prefijo}%") for prefijo in _PREFIJOS_TECNICAS))


def filtro_familia(familia: str) -> ColumnElement[bool]:
    """SQL condition matching the notifications of a family."""
    if familia == "compras":
        return _es_compras()
    if familia == "markup":
        return Notificacion.tipo == "markup_bajo"
    if familia == "tecnicas":
        return _es_tecnica()
    if familia == "otras":
        return and_(not_(_es_compras()), Notificacion.tipo != "markup_bajo", not_(_es_tecnica()))
    raise ValueError(f"Unknown notification family: {familia}")


def conteo_por_familia(por_tipo: dict[str, int]) -> dict[str, int]:
    """Fold per-tipo counts into per-family counts (every family present, zero when empty)."""
    conteo = {familia: 0 for familia in FAMILIAS}
    for tipo, cantidad in por_tipo.items():
        conteo[familia_de_tipo(tipo)] += cantidad
    return conteo
