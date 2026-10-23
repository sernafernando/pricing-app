"""Bonuses: validate, load, edit, list, detail and void (sell-in-sell-out T3c-3; scopes and % in T3e-3).

A bonus reaches a brand, a category, some models (`sell_in_bono_items`, replaced
on edit) or one Compras operation (`alcance`), and pays an amount per invoiced
unit or a percentage of the invoiced net (`tipo`); each carries only its own
fields, so a field of another scope or kind is refused, never dropped.

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

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.pedido_compra import PedidoCompra
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoItem, SellInBonoMarca, SellInCompra, SellInCompraItem
from app.schemas.sell_in_bonos import SellInBonoIn

_CAMPOS = (
    "alcance",
    "marca",
    "categoria",
    "pedido_id",
    "tipo",
    "monto_unit",
    "porcentaje",
    "moneda",
    "fecha_desde",
    "fecha_hasta",
    "descripcion",
)
# How each scope is named in a message, and the request field that belongs to it.
_ALCANCES = {"marca": "por marca", "categoria": "por categoría", "modelos": "por modelos", "factura": "por factura"}
_CAMPO_DE_ALCANCE = {"marca": "marca", "categoria": "categoria", "modelos": "modelos", "factura": "pedido_id"}
_NOMBRE_CAMPO = {"marca": "marca", "categoria": "categoría", "modelos": "modelos", "pedido_id": "pedido de compra"}


class SellInBonoError(ValueError):
    """The request cannot be served as asked; the message is for the operator."""


class SellInBonoYaAnulado(SellInBonoError):
    """The bonus was already voided."""


@dataclass(frozen=True)
class Campos:
    """The validated scope and kind fields, normalized (trimmed text, models once each and sorted)."""

    marca: Optional[str]
    categoria: Optional[str]
    modelos: list[int]
    pedido_id: Optional[int]
    monto_unit: Optional[Decimal]
    porcentaje: Optional[Decimal]


def _texto(valor: Optional[str]) -> Optional[str]:
    return (valor or "").strip() or None


def _validar_alcance(db: Session, data: SellInBonoIn) -> tuple[Optional[str], Optional[str], list[int], Optional[int]]:
    marca, categoria = _texto(data.marca), _texto(data.categoria)
    modelos = sorted(set(data.modelos))
    dados = {"marca": marca, "categoria": categoria, "modelos": modelos, "pedido_id": data.pedido_id}
    propio = _CAMPO_DE_ALCANCE[data.alcance]
    for campo, valor in dados.items():
        if campo != propio and valor:
            raise SellInBonoError(f"Un bono {_ALCANCES[data.alcance]} no lleva {_NOMBRE_CAMPO[campo]}")
    if data.alcance == "marca":
        if marca is None:
            raise SellInBonoError("Falta la marca del bono")
        if not db.query(ProductoERP.item_id).filter(ProductoERP.marca == marca).limit(1).first():
            raise SellInBonoError(f"No hay productos de la marca {marca}")
    elif data.alcance == "categoria":
        if categoria is None:
            raise SellInBonoError("Falta la categoría del bono")
        if not db.query(ProductoERP.item_id).filter(ProductoERP.categoria == categoria).limit(1).first():
            raise SellInBonoError(f"No hay productos de la categoría {categoria}")
    elif data.alcance == "modelos":
        if not modelos:
            raise SellInBonoError("Elegí al menos un modelo")
        existen = {i for (i,) in db.query(ProductoERP.item_id).filter(ProductoERP.item_id.in_(modelos))}
        faltan = [i for i in modelos if i not in existen]
        if faltan:
            raise SellInBonoError(f"No existen los items: {', '.join(str(i) for i in faltan)}")
    else:
        if data.pedido_id is None:
            raise SellInBonoError("Falta el pedido de compra del bono")
        if db.get(PedidoCompra, data.pedido_id) is None:
            raise SellInBonoError(f"No existe el pedido de compra {data.pedido_id}")
    return marca, categoria, modelos, data.pedido_id


def validar(db: Session, data: SellInBonoIn) -> Campos:
    """The rules the operator can break, in one readable message each; returns the normalized fields."""
    marca, categoria, modelos, pedido_id = _validar_alcance(db, data)
    if data.tipo == "por_unidad":
        if data.porcentaje is not None:
            raise SellInBonoError("Un bono por unidad no lleva porcentaje")
        if data.monto_unit is None:
            raise SellInBonoError("Falta el monto por unidad del bono")
        if data.monto_unit <= 0:
            raise SellInBonoError("El monto por unidad debe ser mayor que cero")
    else:
        if data.monto_unit is not None:
            raise SellInBonoError("Un bono por porcentaje no lleva monto por unidad")
        if data.porcentaje is None:
            raise SellInBonoError("Falta el porcentaje del bono")
        if data.porcentaje <= 0:
            raise SellInBonoError("El porcentaje debe ser mayor que cero")
        if data.porcentaje > 100:
            raise SellInBonoError("El porcentaje no puede superar 100")
    if data.fecha_desde > data.fecha_hasta:
        raise SellInBonoError("La fecha desde no puede ser posterior a la fecha hasta")
    return Campos(
        marca=marca,
        categoria=categoria,
        modelos=modelos,
        pedido_id=pedido_id,
        monto_unit=data.monto_unit.quantize(Decimal("0.01")) if data.monto_unit is not None else None,
        porcentaje=data.porcentaje.quantize(Decimal("0.0001")) if data.porcentaje is not None else None,
    )


def _modelos(db: Session, bono_ids: list[int]) -> dict[int, list[int]]:
    modelos: dict[int, list[int]] = {}
    for bono_id, item_id in (
        db.query(SellInBonoItem.bono_id, SellInBonoItem.item_id)
        .filter(SellInBonoItem.bono_id.in_(bono_ids))
        .order_by(SellInBonoItem.bono_id, SellInBonoItem.item_id)
    ):
        modelos.setdefault(bono_id, []).append(item_id)
    return modelos


def _valores(bono: SellInBonoMarca, modelos: list[int]) -> dict:
    valores = {campo: getattr(bono, campo) for campo in _CAMPOS}
    for campo, valor in valores.items():
        if isinstance(valor, (date, Decimal)):
            valores[campo] = str(valor)  # JSON-safe
    return {"bono_id": bono.id, **valores, "modelos": list(modelos), "estado": bono.estado}


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


def _asignar(db: Session, bono: SellInBonoMarca, data: SellInBonoIn, campos: Campos) -> None:
    for campo in ("alcance", "tipo", "moneda", "fecha_desde", "fecha_hasta", "descripcion"):
        setattr(bono, campo, getattr(data, campo))
    for campo in ("marca", "categoria", "pedido_id", "monto_unit", "porcentaje"):
        setattr(bono, campo, getattr(campos, campo))
    db.flush()
    # The model list, replaced: rows that stay are kept, so their trigger queues only a real change.
    actuales = {item.item_id: item for item in db.query(SellInBonoItem).filter(SellInBonoItem.bono_id == bono.id)}
    for item_id, item in actuales.items():
        if item_id not in campos.modelos:
            db.delete(item)
    db.add_all(SellInBonoItem(bono_id=bono.id, item_id=i) for i in campos.modelos if i not in actuales)
    db.flush()


def crear_bono(db: Session, data: SellInBonoIn, usuario_id: int) -> SellInBonoMarca:
    campos = validar(db, data)
    bono = SellInBonoMarca(usuario_id=usuario_id, estado="activa")
    db.add(bono)
    _asignar(db, bono, data, campos)
    _audit(db, TipoAccion.SELL_IN_BONO_CREADO, usuario_id, None, _valores(bono, campos.modelos))
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
    campos = validar(db, data)
    antes = _valores(bono, _modelos(db, [bono.id]).get(bono.id, []))
    _asignar(db, bono, data, campos)
    _audit(db, TipoAccion.SELL_IN_BONO_EDITADO, usuario_id, antes, _valores(bono, campos.modelos))
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
    _audit(
        db,
        TipoAccion.SELL_IN_BONO_ANULADO,
        usuario_id,
        None,
        _valores(bono, _modelos(db, [bono.id]).get(bono.id, [])),
        motivo,
    )
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
    """Bonuses with their models (code and description), operation number and what they generated (active
    purchases, units, amount per currency): 6 queries per page."""
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
    unidades: dict[int, int] = {}
    montos: dict[int, dict[str, Decimal]] = {}
    for bono_id, moneda, cantidad, monto in (
        db.query(
            SellInCompra.bono_id,
            SellInCompra.moneda,
            func.coalesce(func.sum(SellInCompraItem.cantidad), 0),
            func.coalesce(func.sum(SellInCompraItem.monto_asignado), 0),
        )
        .join(SellInCompraItem, SellInCompraItem.compra_id == SellInCompra.id)
        .filter(SellInCompra.bono_id.in_(ids), activa)
        .group_by(SellInCompra.bono_id, SellInCompra.moneda)
    ):
        unidades[bono_id] = unidades.get(bono_id, 0) + int(cantidad)
        montos.setdefault(bono_id, {})[moneda] = Decimal(str(monto)).quantize(Decimal("0.01"))
    modelos = _modelos(db, ids)
    productos = {
        p.item_id: p
        for p in db.query(ProductoERP.item_id, ProductoERP.codigo, ProductoERP.descripcion).filter(
            ProductoERP.item_id.in_({i for items in modelos.values() for i in items})
        )
    }
    pedido_ids = {b.pedido_id for b in bonos if b.pedido_id is not None}
    numeros = (
        dict(db.query(PedidoCompra.id, PedidoCompra.numero).filter(PedidoCompra.id.in_(pedido_ids)))
        if pedido_ids
        else {}
    )
    filas = []
    for bono in bonos:
        por_moneda = montos.get(bono.id, {})
        filas.append(
            {
                **{col: getattr(bono, col) for col in _COLUMNAS},
                "modelos": [
                    {
                        "item_id": i,
                        "codigo": productos[i].codigo if i in productos else None,
                        "descripcion": productos[i].descripcion if i in productos else None,
                    }
                    for i in modelos.get(bono.id, [])
                ],
                "pedido_numero": numeros.get(bono.pedido_id),
                "compras_activas": int(compras.get(bono.id, 0)),
                "unidades": unidades.get(bono.id, 0),
                # Only the bonus's own currency: a purchase left in another one is listed apart, never added.
                "monto_generado": por_moneda.get(bono.moneda, Decimal("0.00")),
                "montos_generados": [{"moneda": m, "monto": v} for m, v in sorted(por_moneda.items())],
            }
        )
    return filas


_COLUMNAS = (
    "id",
    "alcance",
    "marca",
    "categoria",
    "pedido_id",
    "tipo",
    "monto_unit",
    "porcentaje",
    "moneda",
    "fecha_desde",
    "fecha_hasta",
    "descripcion",
    "estado",
    "usuario_id",
    "created_at",
    "updated_at",
)
