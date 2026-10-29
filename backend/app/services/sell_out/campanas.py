"""Sell-out campaigns: validate, load, edit, list, detail and void.

`validar` is the single place for the rules the database CHECKs also enforce
(`app.models.sell_out`), so the operator gets one readable message instead of
an integrity error. A campaign is edited by full replace while it is `activa`;
it is never deleted, only voided (`anulada`), once. Every load, edit and void
writes one audit row (`item_id` NULL, `campana_id` in the values).

Consumption, the shared cap, stacking and the ARS conversion (including the
current-BNA estimate of an `al_cobro` campaign whose rate is not set yet) are
applied by the allocator (T7); this module stores them and queues the campaign
for the `sell_out.drain` rebuild in the same transaction (`queue`). An edit also
queues the campaigns that shared products with it BEFORE the edit, since
afterwards the rebuild no longer finds them. A `por_unidad` campaign may give
products of its groups their own amount (`items`, T22b), replaced with the rest
on every edit and audited with it. A `monto_total` campaign (T26c, S34/S35)
carries one amount, split by hand among its products (`items` with a share,
`reparto_porcentaje` or `reparto_monto`); its split also changes on its own
(`repartir`, the PM's or an admin's split), where a PM only touches the
products of their brands and keeps the others' shares. The shares are checked
with the allocator's own rule (`reparto.validar`). The payment rate
of an `al_cobro` campaign is set with `definir_tipo_cambio`, never by an edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import TypeAdapter
from sqlalchemy import Numeric, func, or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_grupo import OffsetGrupo
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo, SellOutCampanaItem
from app.schemas.sell_out import SellOutCampanaIn, SellOutCampanaItemIn
from app.services.sell_in.compras import contiene
from app.services.sell_out import alcance, asignacion, queue, reparto

# Each NUMERIC column's scale as a quantum: `monto_unit` 0.01, `porcentaje` 0.0001, ...
_QUANTUM = {
    column.name: Decimal(1).scaleb(-column.type.scale)
    for column in SellOutCampana.__table__.columns
    if isinstance(column.type, Numeric)
}
# The shares' own columns (`sell_out_campana_items`, T26).
_QUANTUM.update(
    (column.name, Decimal(1).scaleb(-column.type.scale))
    for column in SellOutCampanaItem.__table__.columns
    if column.name in ("reparto_porcentaje", "reparto_monto")
)
_INSTANTE = TypeAdapter(datetime)

_CAMPOS = (
    "nombre",
    "descripcion",
    "fecha_desde",
    "fecha_hasta",
    "tipo",
    "monto_unit",
    "porcentaje",
    "base_porcentaje",
    "moneda",
    "tc_modo",
    "tipo_cambio",
    "tope_unidades",
    "tope_monto",
    "acumulable",
    "monto_incluye_iva",
)


class SellOutError(ValueError):
    """The request cannot be served as asked; the message is for the operator."""


class SellOutSinPermiso(SellOutError):
    """The user may not change what was asked (a PM splitting another brand's product)."""


class SellOutYaAnulada(SellOutError):
    """The campaign was already voided."""


class SellOutRecalculando(SellOutError):
    """A `sell_out.drain` batch is rebuilding the campaign; nothing was stored, retry shortly."""


def _encolar(db: Session, campana_ids: list[int]) -> None:
    """Queues the campaigns, waiting at most `queue.LOCK_TIMEOUT` for a queue row a running
    `sell_out.drain` batch holds; then the whole change is rolled back and refused, never left waiting."""
    try:
        with queue.lock_timeout(db, queue.LOCK_TIMEOUT):
            queue.enqueue(db, campana_ids)
    except DBAPIError as exc:
        if getattr(exc.orig, "pgcode", None) != "55P03":
            raise
        db.rollback()
        raise SellOutRecalculando("La campaña se está recalculando. Reintentar en unos segundos.") from exc


def _validar_tc(data: SellOutCampanaIn, actual: Optional[SellOutCampana]) -> None:
    """FX rules (see `app.models.sell_out`); `data.tc_modo` is already resolved."""
    if data.moneda == "ARS":
        if data.tc_modo is not None or data.tipo_cambio is not None:
            raise SellOutError("Una campaña en pesos no lleva tipo de cambio")
        return
    if data.tipo_cambio is not None and data.tipo_cambio <= 0:
        raise SellOutError("El tipo de cambio tiene que ser mayor a 0")
    if data.tc_modo == "fijo" and data.tipo_cambio is None:
        raise SellOutError("Con tipo de cambio fijo hay que indicar el tipo de cambio")
    if data.tc_modo == "dia_venta" and data.tipo_cambio is not None:
        raise SellOutError("Con tipo de cambio del día de venta no se indica un tipo de cambio")
    if data.tc_modo == "al_cobro" and data.tipo_cambio is not None:
        # An edit may echo the rate already set at payment; changing it goes through its own endpoint.
        ya_definido = actual is not None and actual.tc_modo == "al_cobro" and actual.tipo_cambio == data.tipo_cambio
        if not ya_definido:
            raise SellOutError(
                "Con tipo de cambio al cobro, el tipo de cambio se define cuando la marca paga, desde su propia acción"
            )


def validar(db: Session, data: SellOutCampanaIn, actual: Optional[SellOutCampana] = None) -> list[int]:
    """Raise `SellOutError` on the first broken rule; return the campaign's distinct group ids, in order.

    A USD campaign without `tc_modo` gets `al_cobro` (the default), set on `data` in place.
    """
    validar_campos(data, actual)
    grupo_ids = list(dict.fromkeys(data.grupo_ids))
    if not grupo_ids:
        raise SellOutError("Seleccione al menos un grupo de productos")
    existentes = {gid for (gid,) in db.query(OffsetGrupo.id).filter(OffsetGrupo.id.in_(grupo_ids))}
    for gid in grupo_ids:
        if gid not in existentes:
            raise SellOutError(f"El grupo {gid} no existe")
    return grupo_ids


def validar_campos(data: SellOutCampanaIn, actual: Optional[SellOutCampana] = None) -> None:
    """`validar` without its group checks: for a dry run whose groups do not exist yet (the offsets migration)."""
    if not data.nombre.strip():
        raise SellOutError("El nombre es obligatorio")
    if data.fecha_hasta < data.fecha_desde:
        raise SellOutError("La fecha hasta no puede ser anterior a la fecha desde")
    if data.tipo == "por_unidad":
        if data.monto_unit is None or data.monto_unit <= 0:
            raise SellOutError("Una campaña por unidad necesita un monto por unidad mayor a 0")
        if data.porcentaje is not None:
            raise SellOutError("Una campaña por unidad no lleva porcentaje")
        if data.monto_total is not None:
            raise SellOutError("Una campaña por unidad no lleva monto total")
    elif data.tipo == "monto_total":
        _validar_monto_total(data)
    else:
        if data.porcentaje is None or not 0 < data.porcentaje <= 100:
            raise SellOutError("El porcentaje tiene que ser mayor a 0 y hasta 100")
        if data.monto_unit is not None:
            raise SellOutError("Una campaña por porcentaje no lleva monto por unidad")
        if data.monto_total is not None:
            raise SellOutError("Una campaña por porcentaje no lleva monto total")
        # The percentage applies to a base already without VAT, so the flag would do nothing.
        if data.monto_incluye_iva:
            raise SellOutError(
                "Una campaña por porcentaje no lleva monto con IVA: el porcentaje se aplica sobre el neto sin IVA"
            )
    if data.moneda == "USD" and data.tc_modo is None:
        data.tc_modo = "al_cobro"
    _validar_tc(data, actual)
    if data.tope_unidades is not None and data.tope_unidades <= 0:
        raise SellOutError("El tope de unidades tiene que ser mayor a 0")
    if data.tope_monto is not None and data.tope_monto <= 0:
        raise SellOutError("El tope de monto tiene que ser mayor a 0")
    _validar_items(data.tipo, data.items)


def _validar_monto_total(data: SellOutCampanaIn) -> None:
    """A `monto_total` campaign: one amount, never 0 (negative: a deduction, S35), and nothing per unit or capped."""
    if data.monto_total is None or data.monto_total == 0:
        raise SellOutError("Una campaña por monto total necesita un monto total distinto de 0")
    if data.monto_unit is not None:
        raise SellOutError("Una campaña por monto total no lleva monto por unidad")
    if data.porcentaje is not None:
        raise SellOutError("Una campaña por monto total no lleva porcentaje")
    if data.tope_unidades is not None or data.tope_monto is not None:
        raise SellOutError("Una campaña por monto total no lleva topes: el monto total es el tope")


def _validar_items(tipo: str, items: Optional[list[SellOutCampanaItemIn]]) -> None:
    """The per-product amounts or shares, without the database; their reach is checked once the groups are stored,
    and the shares' sign and sum against the total once they are (`_validar_suma`)."""
    if items and tipo == "porcentaje":
        raise SellOutError("Una campaña por porcentaje no lleva montos por producto")
    vistos = set()
    for item in items or []:
        if item.item_id in vistos:
            que = "reparto" if tipo == "monto_total" else "monto"
            raise SellOutError(f"El producto {item.item_id} tiene más de un {que}")
        vistos.add(item.item_id)
        if tipo == "monto_total":
            _validar_reparto(item)
            continue
        if item.reparto_porcentaje is not None or item.reparto_monto is not None:
            raise SellOutError("Una campaña por unidad no lleva reparto por producto")
        if item.monto_unit is None or item.monto_unit <= 0:
            raise SellOutError(f"El monto del producto {item.item_id} tiene que ser mayor a 0")


def _validar_reparto(item: SellOutCampanaItemIn) -> None:
    """One share of a `monto_total` campaign: a % (over 0, up to 100) or a fixed amount (not 0), never both."""
    if item.monto_unit is not None:
        raise SellOutError("Una campaña por monto total no lleva montos por unidad por producto")
    porcentaje, monto = item.reparto_porcentaje, item.reparto_monto
    if porcentaje is None and monto is None:
        raise SellOutError(f"El producto {item.item_id} necesita un porcentaje o un monto de reparto")
    if porcentaje is not None and monto is not None:
        raise SellOutError(f"El producto {item.item_id} lleva un porcentaje o un monto de reparto, no los dos")
    if porcentaje is not None and not 0 < porcentaje <= 100:
        raise SellOutError("El porcentaje de reparto tiene que ser mayor a 0 y hasta 100")
    if monto is not None and monto == 0:
        raise SellOutError(f"El monto de reparto del producto {item.item_id} no puede ser 0")


def _a_escala(campo: str, valor):
    """`valor` rounded to its column's scale, as the database stores it (exact: the schema caps decimals)."""
    if campo in _QUANTUM and valor is not None:
        return valor.quantize(_QUANTUM[campo])
    return valor


def _utc(instante: Optional[datetime]) -> Optional[datetime]:
    """A `timestamptz` value in UTC; a naive one (SQLite drops the zone) is already UTC."""
    if instante is None:
        return None
    if instante.tzinfo is None:
        return instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc)


def _texto(valor) -> Optional[str]:
    return None if valor is None else str(valor)


def _item_auditado(item: dict) -> dict:
    """A per-unit amount as before T26c; a share with both its columns."""
    if item["monto_unit"] is not None:
        return {"item_id": item["item_id"], "monto_unit": str(item["monto_unit"])}
    return {
        "item_id": item["item_id"],
        "reparto_porcentaje": _texto(item["reparto_porcentaje"]),
        "reparto_monto": _texto(item["reparto_monto"]),
    }


def _valores(campana: SellOutCampana, grupo_ids: list[int], items: list[dict]) -> dict:
    valores = {campo: getattr(campana, campo) for campo in _CAMPOS}
    if campana.tipo == "monto_total":  # the other types' audit rows keep their shape
        valores["monto_total"] = campana.monto_total
    for campo, valor in valores.items():
        if valor is not None and not isinstance(valor, (bool, int, str)):
            valores[campo] = str(valor)  # dates and decimals, JSON-safe
    # Serialized exactly as the API returns it (see `serializar`).
    definido = _INSTANTE.dump_python(_utc(campana.tc_definido_en), mode="json") if campana.tc_definido_en else None
    return {
        "campana_id": campana.id,
        **valores,
        "tc_definido_en": definido,
        "estado": campana.estado,
        "grupo_ids": grupo_ids,
        "items": [_item_auditado(i) for i in items],
    }


def _grupo_ids(db: Session, campana_id: int) -> list[int]:
    rows = db.query(SellOutCampanaGrupo.grupo_id).filter(SellOutCampanaGrupo.campana_id == campana_id)
    return [gid for (gid,) in rows.order_by(SellOutCampanaGrupo.id)]


def _items(db: Session, campana_ids: list[int]) -> dict[int, list[dict]]:
    """`{campana_id: [{item_id, monto_unit, codigo, descripcion, reparto_porcentaje, reparto_monto}]}` by item_id, in
    one query; every asked campaign is present. The product's code and description are for the screen (the audit
    keeps only id and amount or share)."""
    salida: dict[int, list[dict]] = {i: [] for i in campana_ids}
    if campana_ids:
        t = SellOutCampanaItem
        rows = (
            db.query(
                t.campana_id,
                t.item_id,
                t.monto_unit,
                ProductoERP.codigo,
                ProductoERP.descripcion,
                t.reparto_porcentaje,
                t.reparto_monto,
            )
            .outerjoin(ProductoERP, ProductoERP.item_id == t.item_id)
            .filter(t.campana_id.in_(campana_ids))
        )
        for campana_id, item_id, monto, codigo, descripcion, porcentaje, reparto_monto in rows.order_by(t.item_id):
            salida[campana_id].append(
                {
                    "item_id": item_id,
                    "monto_unit": None if monto is None else Decimal(monto),
                    "codigo": codigo,
                    "descripcion": descripcion,
                    "reparto_porcentaje": None if porcentaje is None else Decimal(porcentaje),
                    "reparto_monto": None if reparto_monto is None else Decimal(reparto_monto),
                }
            )
    return salida


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


def _asignar(db: Session, campana: SellOutCampana, data: SellOutCampanaIn, grupo_ids: list[int]) -> None:
    previo = (campana.tc_modo, campana.tipo_cambio, campana.tc_definido_en)
    for campo in _CAMPOS:
        setattr(campana, campo, _a_escala(campo, getattr(data, campo)))
    campana.monto_total = _a_escala("monto_total", data.monto_total)
    if campana.tc_modo == "al_cobro" and previo[0] == "al_cobro":
        campana.tipo_cambio, campana.tc_definido_en = previo[1], previo[2]  # an edit keeps the payment rate
    else:
        campana.tc_definido_en = None
    campana.nombre = data.nombre.strip()
    db.flush()
    db.query(SellOutCampanaGrupo).filter(
        SellOutCampanaGrupo.campana_id == campana.id, SellOutCampanaGrupo.grupo_id.notin_(grupo_ids)
    ).delete(synchronize_session=False)
    tenidos = set(_grupo_ids(db, campana.id))
    db.add_all(SellOutCampanaGrupo(campana_id=campana.id, grupo_id=g) for g in grupo_ids if g not in tenidos)
    db.flush()
    _asignar_items(db, campana, data)


def _asignar_items(db: Session, campana: SellOutCampana, data: SellOutCampanaIn) -> None:
    """Replace the per-product amounts or shares with `data.items`, refusing (and rolling back) one SENT outside the
    reach of the groups just stored. `data.items` None keeps the stored ones as they are, unless they no longer fit
    the campaign's type (they must be cleared explicitly with `[]`). A kept amount whose product left the reach (a
    group or filter change) is credited nothing: the allocator only reaches the groups' products; re-sending it is
    refused until the user removes it, which the panel shows. A `monto_total` campaign's shares, sent or kept, are
    then checked against its (maybe new) total (`_validar_suma`)."""
    if data.items is None:
        _validar_tenidos(db, campana, data.tipo)
    else:
        _validar_alcance(db, campana, [item.item_id for item in data.items])
        _guardar_items(db, campana, {item.item_id: _fila(item) for item in data.items})
    if data.tipo == "monto_total":
        _validar_suma(db, campana)


def _validar_tenidos(db: Session, campana: SellOutCampana, tipo: str) -> None:
    """The stored rows still fit the campaign's type: amounts only per unit, shares only on a fixed total."""
    t = SellOutCampanaItem
    filas = db.query(t.id).filter(t.campana_id == campana.id)
    if tipo == "porcentaje":
        mensaje = (
            "Una campaña por porcentaje no lleva montos por producto: quitá los montos por producto para cambiarla"
        )
        ajenas = filas
    elif tipo == "por_unidad":
        mensaje = "Una campaña por unidad no lleva reparto por producto: quitá el reparto para cambiarla"
        ajenas = filas.filter(t.monto_unit.is_(None))
    else:
        mensaje = (
            "Una campaña por monto total no lleva montos por unidad por producto: "
            "quitá los montos por producto para cambiarla"
        )
        ajenas = filas.filter(t.monto_unit.isnot(None))
    if ajenas.first() is not None:
        db.rollback()
        raise SellOutError(mensaje)


def _validar_alcance(db: Session, campana: SellOutCampana, item_ids: list[int]) -> None:
    """Every product sent is inside the reach of the campaign's stored groups (T22b)."""
    if item_ids:
        alcanzados = alcance.productos(db, [campana.id]).get(campana.id, {})
        for item_id in item_ids:
            if item_id not in alcanzados:
                db.rollback()
                raise SellOutError(f"El producto {item_id} no está en los grupos de la campaña")


def _fila(item: SellOutCampanaItemIn) -> dict:
    """The row's three money columns at their scale (exactly one is set, `_validar_items`)."""
    return {
        "monto_unit": _a_escala("monto_unit", item.monto_unit),
        "reparto_porcentaje": _a_escala("reparto_porcentaje", item.reparto_porcentaje),
        "reparto_monto": _a_escala("reparto_monto", item.reparto_monto),
    }


def _guardar_items(
    db: Session, campana: SellOutCampana, pedidos: dict[int, dict], conservar: frozenset = frozenset()
) -> None:
    """Store `pedidos` (`item_id -> _fila`) as the campaign's rows: the other stored rows are deleted, except the
    ones in `conservar`, kept as they are."""
    t = SellOutCampanaItem
    tenidos = {fila.item_id: fila for fila in db.query(t).filter(t.campana_id == campana.id)}
    for item_id, fila in tenidos.items():
        if item_id in conservar:
            continue
        if item_id not in pedidos:
            db.delete(fila)
            continue
        for columna, valor in pedidos[item_id].items():
            if getattr(fila, columna) != valor:
                setattr(fila, columna, valor)
    db.add_all(t(campana_id=campana.id, item_id=i, **fila) for i, fila in pedidos.items() if i not in tenidos)
    db.flush()


def _validar_suma(db: Session, campana: SellOutCampana) -> None:
    """The stored shares can be split as they stand, by the allocator's own rule (`reparto.validar`): a fixed share
    has the total's sign and |sum of shares| <= |total|. Otherwise everything is rolled back."""
    repartos = asignacion.repartos_item(db, [campana]).get(campana.id, {})
    try:
        reparto.validar(reparto.MontoTotal(Decimal(campana.monto_total), repartos))
    except reparto.RepartoInvalido as exc:
        db.rollback()
        if exc.item_id is not None:
            raise SellOutError(
                f"El reparto del producto {exc.item_id} tiene que tener el signo del monto total"
            ) from exc
        exceso = abs(exc.suma) - abs(exc.total)
        raise SellOutError(f"El reparto ({exc.suma}) supera el monto total ({exc.total}) en {exceso}") from exc


def crear_campana(
    db: Session, data: SellOutCampanaIn, usuario_id: int, *, offset_origen_id: Optional[int] = None
) -> SellOutCampana:
    """`offset_origen_id`: the legacy offset it migrates (only `app.scripts.migrar_offsets_a_sell_out`)."""
    grupo_ids = validar(db, data)
    campana = SellOutCampana(usuario_id=usuario_id, offset_origen_id=offset_origen_id)
    db.add(campana)
    _asignar(db, campana, data, grupo_ids)
    valores = _valores(campana, grupo_ids, _items(db, [campana.id])[campana.id])
    if offset_origen_id is not None:
        valores["offset_origen_id"] = offset_origen_id
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_CREADA, usuario_id, None, valores)
    _encolar(db, [campana.id])
    db.commit()
    db.refresh(campana)
    return campana


def _bloquear(db: Session, campana_id: int) -> Optional[SellOutCampana]:
    campana = db.query(SellOutCampana).filter(SellOutCampana.id == campana_id).with_for_update().first()
    if campana is not None and campana.estado == "anulada":
        raise SellOutYaAnulada(f"La campaña {campana_id} está anulada")
    return campana


def editar_campana(db: Session, campana_id: int, data: SellOutCampanaIn, usuario_id: int) -> Optional[SellOutCampana]:
    """Full replace of an active campaign. None when it does not exist; `SellOutYaAnulada` when voided."""
    campana = _bloquear(db, campana_id)
    if campana is None:
        return None
    grupo_ids = validar(db, data, campana)
    antes = _valores(campana, _grupo_ids(db, campana_id), _items(db, [campana_id])[campana_id])
    compartian = asignacion.vinculadas(db, [campana_id])  # before the edit unlinks them
    _asignar(db, campana, data, grupo_ids)
    despues = _valores(campana, grupo_ids, _items(db, [campana_id])[campana_id])
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_EDITADA, usuario_id, antes, despues)
    _encolar(db, [campana_id, *compartian])
    db.commit()
    db.refresh(campana)
    return campana


def anular_campana(db: Session, campana_id: int, usuario_id: int, motivo: Optional[str]) -> Optional[SellOutCampana]:
    """Void a campaign. None when it does not exist; `SellOutYaAnulada` on a second call."""
    campana = _bloquear(db, campana_id)
    if campana is None:
        return None
    campana.estado = "anulada"
    valores = _valores(campana, _grupo_ids(db, campana_id), _items(db, [campana_id])[campana_id])
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_ANULADA, usuario_id, None, valores, motivo)
    _encolar(db, [campana_id])  # its rebuild drops its rows and rebuilds the campaigns sharing its products
    db.commit()
    db.refresh(campana)
    return campana


def definir_tipo_cambio(
    db: Session, campana_id: int, tipo_cambio: Decimal, usuario_id: int
) -> Optional[SellOutCampana]:
    """Set (or change) the rate of an `al_cobro` campaign when the brand pays, also after it ended.

    None when it does not exist; `SellOutYaAnulada` when voided. Every change is audited and queued.
    """
    campana = _bloquear(db, campana_id)
    if campana is None:
        return None
    if campana.tc_modo != "al_cobro":
        raise SellOutError("Solo las campañas en USD con tipo de cambio al cobro definen el tipo de cambio después")
    if tipo_cambio <= 0:
        raise SellOutError("El tipo de cambio tiene que ser mayor a 0")
    grupo_ids = _grupo_ids(db, campana_id)
    items = _items(db, [campana_id])[campana_id]
    antes = _valores(campana, grupo_ids, items)
    campana.tipo_cambio = _a_escala("tipo_cambio", tipo_cambio)
    campana.tc_definido_en = datetime.now(timezone.utc)
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_TC_DEFINIDO, usuario_id, antes, _valores(campana, grupo_ids, items))
    _encolar(db, [campana_id])
    db.commit()
    db.refresh(campana)
    return campana


def _de_sus_marcas(db: Session, item_ids: list[int], pares: set) -> tuple[set, dict]:
    """The products among `item_ids` whose (marca, categoria) is one of the PM's `pares` (upper-cased by the
    database, like `pm_scope`), and every product's code, for the messages. A product off the catalog is no one's."""
    propios, codigos = set(), {}
    if item_ids:
        p = ProductoERP
        rows = db.query(p.item_id, p.codigo, func.upper(p.marca), func.upper(p.categoria)).filter(
            p.item_id.in_(set(item_ids))
        )
        for item_id, codigo, marca, categoria in rows:
            codigos[item_id] = codigo
            if (marca, categoria) in pares:
                propios.add(item_id)
    return propios, codigos


def solo_sus_marcas(db: Session, fila: dict, pares: Optional[set]) -> dict:
    """A serialized campaign as a brand-scoped PM may see it: only the shares of the products of their `pares`
    (None: every brand, unchanged). The summary stays the campaign's, aggregated (no per-product amount)."""
    if pares is None:
        return fila
    propios, _ = _de_sus_marcas(db, [i["item_id"] for i in fila["items"]], pares)
    return {**fila, "items": [i for i in fila["items"] if i["item_id"] in propios]}


def repartir(
    db: Session, campana_id: int, repartos: list[SellOutCampanaItemIn], usuario_id: int, pares: Optional[set]
) -> Optional[SellOutCampana]:
    """Set the split of an active `monto_total` campaign among its products (S34). None when it does not exist.

    `pares`: None for a user who sees every brand (an admin, `sell_out.gestionar`), whose `repartos` replace the
    whole split; else the PM's (MARCA, CATEGORIA) pairs (`pm_scope`): a share of another brand's product is
    refused (`SellOutSinPermiso`, nothing stored) and the stored shares of the products they cannot see are kept,
    so `repartos` replace only theirs. The resulting split is checked as a whole (`_validar_suma`), audited (before
    and after) and queued for `sell_out.drain`.
    """
    campana = db.query(SellOutCampana).filter(SellOutCampana.id == campana_id).with_for_update().first()
    if campana is None:
        return None
    if campana.estado == "anulada":
        raise SellOutError(f"La campaña {campana_id} está anulada")
    if campana.tipo != "monto_total":
        raise SellOutError("Solo las campañas por monto total se reparten por producto")
    _validar_items("monto_total", repartos)
    t = SellOutCampanaItem
    tenidos = [i for (i,) in db.query(t.item_id).filter(t.campana_id == campana_id)]
    conservar: frozenset = frozenset()
    if pares is not None:
        propios, codigos = _de_sus_marcas(db, [r.item_id for r in repartos] + tenidos, pares)
        for item in repartos:
            if item.item_id not in propios:
                codigo = f" ({codigos[item.item_id]})" if codigos.get(item.item_id) else ""
                raise SellOutSinPermiso(f"El producto {item.item_id}{codigo} no es de tus marcas")
        conservar = frozenset(i for i in tenidos if i not in propios)
    _validar_alcance(db, campana, [r.item_id for r in repartos])
    grupo_ids = _grupo_ids(db, campana_id)
    antes = _valores(campana, grupo_ids, _items(db, [campana_id])[campana_id])
    _guardar_items(db, campana, {r.item_id: _fila(r) for r in repartos}, conservar)
    _validar_suma(db, campana)
    despues = _valores(campana, grupo_ids, _items(db, [campana_id])[campana_id])
    _audit(db, TipoAccion.SELL_OUT_CAMPANA_EDITADA, usuario_id, antes, despues, "Reparto del monto total")
    _encolar(db, [campana_id])
    db.commit()
    db.refresh(campana)
    return campana


@dataclass(frozen=True)
class FiltrosCampanas:
    estado: Optional[str] = None
    vigente_en: Optional[date] = None  # campaigns whose date range includes this day
    q: Optional[str] = None  # name or description
    grupo_id: Optional[int] = None
    tipo: Optional[str] = None


def listar_campanas(
    db: Session, filtros: FiltrosCampanas, *, page: int = 1, page_size: int = 50
) -> tuple[list[SellOutCampana], int]:
    """One page of campaigns, latest start date first."""
    query = db.query(SellOutCampana)
    if filtros.estado:
        query = query.filter(SellOutCampana.estado == filtros.estado)
    if filtros.tipo:
        query = query.filter(SellOutCampana.tipo == filtros.tipo)
    if filtros.vigente_en:
        query = query.filter(
            SellOutCampana.fecha_desde <= filtros.vigente_en, SellOutCampana.fecha_hasta >= filtros.vigente_en
        )
    if filtros.q and filtros.q.strip():
        q = filtros.q.strip()
        query = query.filter(or_(contiene(SellOutCampana.nombre, q), contiene(SellOutCampana.descripcion, q)))
    if filtros.grupo_id is not None:
        en_grupo = db.query(SellOutCampanaGrupo.campana_id).filter(SellOutCampanaGrupo.grupo_id == filtros.grupo_id)
        query = query.filter(SellOutCampana.id.in_(en_grupo))
    total = query.count()
    campanas = (
        query.order_by(SellOutCampana.fecha_desde.desc(), SellOutCampana.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return campanas, total


def serializar(db: Session, campanas: list[SellOutCampana]) -> list[dict]:
    """Each campaign with its groups (id and name, in link order) and its per-product amounts (by item_id),
    in one query each for the whole page."""
    ids = [c.id for c in campanas]
    grupos: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        rows = (
            db.query(SellOutCampanaGrupo.campana_id, OffsetGrupo.id, OffsetGrupo.nombre)
            .join(OffsetGrupo, OffsetGrupo.id == SellOutCampanaGrupo.grupo_id)
            .filter(SellOutCampanaGrupo.campana_id.in_(ids))
            .order_by(SellOutCampanaGrupo.id)
        )
        for campana_id, gid, nombre in rows:
            grupos[campana_id].append({"id": gid, "nombre": nombre})
    items = _items(db, ids)
    salida = []
    for c in campanas:
        fila = {campo: getattr(c, campo) for campo in _CAMPOS}
        fila.update(
            tc_definido_en=_utc(c.tc_definido_en),
            id=c.id,
            estado=c.estado,
            usuario_id=c.usuario_id,
            offset_origen_id=c.offset_origen_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        fila["monto_total"] = c.monto_total  # returned for `monto_total` campaigns only (the schema drops it)
        fila["grupos"] = grupos[c.id]
        fila["items"] = items[c.id]
        salida.append(fila)
    return salida
