"""Brand bonuses: validate, load, edit, list, detail and void (sell-in-sell-out T3c-3).

A bonus is edited by full replace while it is `activa`; it is never deleted,
only voided (`anulada`), once. Every load, edit and void writes one audit row
(`item_id` NULL, `bono_id` in the values), like the sell-out campaigns.

Nothing here touches purchases: the `sell_in_bonos_marca` triggers queue the
bonus and the `sell_in.bono` worker (`app.services.sell_in.bonos`) applies,
updates or voids what it generates. The detail reports what it generated so
far (active purchases, their units and amount).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem
from app.schemas.sell_in_bonos import SellInBonoIn

_CAMPOS = ("marca", "monto_unit", "moneda", "fecha_desde", "fecha_hasta", "descripcion")


class SellInBonoError(ValueError):
    """The request cannot be served as asked; the message is for the operator."""


class SellInBonoYaAnulado(SellInBonoError):
    """The bonus was already voided."""


def validar(db: Session, data: SellInBonoIn) -> str:
    """The rules the operator can break, in one readable message each; returns the trimmed brand."""
    marca = data.marca.strip()
    if not marca:
        raise SellInBonoError("Falta la marca del bono")
    if not db.query(ProductoERP.item_id).filter(ProductoERP.marca == marca).limit(1).first():
        raise SellInBonoError(f"No hay productos de la marca {marca}")
    if data.monto_unit <= 0:
        raise SellInBonoError("El monto por unidad debe ser mayor que cero")
    if data.fecha_desde > data.fecha_hasta:
        raise SellInBonoError("La fecha desde no puede ser posterior a la fecha hasta")
    return marca


def _valores(bono: SellInBonoMarca) -> dict:
    valores = {campo: getattr(bono, campo) for campo in _CAMPOS}
    for campo, valor in valores.items():
        if isinstance(valor, (date, Decimal)):
            valores[campo] = str(valor)  # JSON-safe
    return {"bono_id": bono.id, **valores, "estado": bono.estado}


def _audit(db: Session, tipo: TipoAccion, usuario_id: int, antes: Optional[dict], despues: dict, motivo=None) -> None:
    db.add(
        Auditoria(
            item_id=None,
            usuario_id=usuario_id,
            tipo_accion=tipo,
            valores_anteriores=antes,
            valores_nuevos=despues,
            es_masivo=False,
            comentario=motivo,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )


def _asignar(bono: SellInBonoMarca, data: SellInBonoIn, marca: str) -> None:
    for campo in _CAMPOS:
        setattr(bono, campo, getattr(data, campo))
    bono.marca = marca
    bono.monto_unit = data.monto_unit.quantize(Decimal("0.01"))


def crear_bono(db: Session, data: SellInBonoIn, usuario_id: int) -> SellInBonoMarca:
    marca = validar(db, data)
    bono = SellInBonoMarca(usuario_id=usuario_id, estado="activa")
    _asignar(bono, data, marca)
    db.add(bono)
    db.flush()
    _audit(db, TipoAccion.SELL_IN_BONO_CREADO, usuario_id, None, _valores(bono))
    db.commit()
    db.refresh(bono)
    return bono


def _bloquear(db: Session, bono_id: int) -> Optional[SellInBonoMarca]:
    bono = db.query(SellInBonoMarca).filter(SellInBonoMarca.id == bono_id).with_for_update().first()
    if bono is not None and bono.estado == "anulada":
        raise SellInBonoYaAnulado(f"El bono {bono_id} está anulado")
    return bono


def editar_bono(db: Session, bono_id: int, data: SellInBonoIn, usuario_id: int) -> Optional[SellInBonoMarca]:
    """Full replace of an active bonus. None when it does not exist; `SellInBonoYaAnulado` when voided."""
    bono = _bloquear(db, bono_id)
    if bono is None:
        return None
    marca = validar(db, data)
    antes = _valores(bono)
    _asignar(bono, data, marca)
    db.flush()
    _audit(db, TipoAccion.SELL_IN_BONO_EDITADO, usuario_id, antes, _valores(bono))
    db.commit()
    db.refresh(bono)
    return bono


def anular_bono(db: Session, bono_id: int, usuario_id: int, motivo: Optional[str]) -> Optional[SellInBonoMarca]:
    """Void a bonus (the worker then voids what it generated). None when it does not exist;
    `SellInBonoYaAnulado` on a second call."""
    bono = _bloquear(db, bono_id)
    if bono is None:
        return None
    bono.estado = "anulada"
    db.flush()
    _audit(db, TipoAccion.SELL_IN_BONO_ANULADO, usuario_id, None, _valores(bono), motivo)
    db.commit()
    db.refresh(bono)
    return bono


@dataclass(frozen=True)
class FiltrosBonos:
    estado: Optional[str] = None
    marca: Optional[str] = None


def listar_bonos(
    db: Session, filtros: FiltrosBonos, *, page: int = 1, page_size: int = 50
) -> tuple[list[SellInBonoMarca], int]:
    """One page of bonuses, newest first."""
    query = db.query(SellInBonoMarca)
    if filtros.estado is not None:
        query = query.filter(SellInBonoMarca.estado == filtros.estado)
    if filtros.marca:
        query = query.filter(SellInBonoMarca.marca == filtros.marca.strip())
    total = query.count()
    bonos = query.order_by(SellInBonoMarca.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return bonos, total


def serializar(db: Session, bonos: list[SellInBonoMarca]) -> list[dict]:
    """Bonuses with what they generated (active purchases, units, amount): 2 queries per page."""
    if not bonos:
        return []
    ids = [b.id for b in bonos]
    activa = SellInCompra.estado == "activa"
    compras = dict(
        db.query(SellInCompra.bono_id, func.count(SellInCompra.id))
        .filter(SellInCompra.bono_id.in_(ids), activa)
        .group_by(SellInCompra.bono_id)
        .all()
    )
    lineas = {
        bono_id: (int(unidades), Decimal(str(monto)))
        for bono_id, unidades, monto in db.query(
            SellInCompra.bono_id,
            func.coalesce(func.sum(case((activa, SellInCompraItem.cantidad), else_=0)), 0),
            func.coalesce(func.sum(case((activa, SellInCompraItem.monto_asignado), else_=0)), 0),
        )
        .join(SellInCompraItem, SellInCompraItem.compra_id == SellInCompra.id)
        .filter(SellInCompra.bono_id.in_(ids))
        .group_by(SellInCompra.bono_id)
    }
    filas = []
    for bono in bonos:
        unidades, monto = lineas.get(bono.id, (0, Decimal("0")))
        filas.append(
            {
                **{col: getattr(bono, col) for col in _COLUMNAS},
                "compras_activas": int(compras.get(bono.id, 0)),
                "unidades": unidades,
                "monto_generado": monto.quantize(Decimal("0.01")),
            }
        )
    return filas


_COLUMNAS = (
    "id",
    "marca",
    "monto_unit",
    "moneda",
    "fecha_desde",
    "fecha_hasta",
    "descripcion",
    "estado",
    "usuario_id",
    "created_at",
    "updated_at",
)
