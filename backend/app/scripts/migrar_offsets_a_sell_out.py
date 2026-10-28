"""Migrate the legacy offsets (`offsets_ganancia`) to sell-out campaigns (sell-in-sell-out T15, T22).

Owner: "Los offsets hay que migrar todo, lo que no se pueda migrar directo haceme
un detalle y guardamelo en una tabla". Each offset of type `monto_por_unidad`
with a positive amount becomes a `por_unidad` campaign, loaded through the
campaigns service (`app.services.sell_out.campanas`: the same validation, audit
row and `sell_out.drain` queueing as a campaign loaded from the screen) and
stamped with `offset_origen_id`:

- an offset without a group gets a new `offset_grupos` row with one
  `offset_grupo_filtros` row per non-null scope field (marca / categoria /
  subcategoria_id / item_id). A legacy offset reaches a product matching ANY of
  its fields and a group matches ANY of its rows, so the reach is the same;
- the offsets of one group (same `grupo_id`) become ONE campaign linked to that
  EXISTING group (its filters are the reach), as the legacy money path applies
  them: each offset with a product gives it its own amount (`items`), the
  campaign's `monto_unit` is the first offset's (by id: what a sale reached only
  by the filters gets), the cap comes from the first offset with a limit, the
  dates span the group's. The first offset is the campaign's origin; the others
  are reported migrated in it. The group migrates whole or not at all: mixed
  types or currencies, a non-positive amount, a product given twice, an offset
  other than the first without a product, a product outside the group's reach,
  no user or a cap or channel a campaign cannot hold (below) keep every offset of
  the group in the review table;
- `monto` -> `monto_unit` in the offset's `moneda`; a USD campaign gets the
  service's default FX mode (`al_cobro`), the offset's rate is not kept;
- `max_unidades` -> `tope_unidades`; `max_monto_usd` -> `tope_monto` (USD);
- an EXPIRED offset (`fecha_hasta` before `--hoy`) migrates with its real dates:
  that changes the historical sell-out figures in Métricas ML, so its CSV row
  warns, the summary lists it (`vencidos_migrados`) and the run says so on stderr;
- a NULL `fecha_hasta` ends on `--fecha-hasta-default` (2026-12-31), with a
  warning so someone adjusts it.

Everything else is reported in the CSV and NOT migrated, each with its reason:
`porcentaje_costo` (waits for the sell-in percentage, T3g), `monto_fijo` (no
campaign type holds a fixed total), a non-positive amount, no scope, no user
(offset without `usuario_id` and no `--usuario-id`), what a campaign cannot
represent (active or expired, single or any offset of a group: an ARS offset
capped in USD, since a campaign in pesos holds no USD cap; an offset that skipped
some channel, since a campaign covers every channel: migrating either would
credit more than the offset did) and the service's validation errors. An offset
already migrated is reported as such with its campaign (a group's, through any of
its offsets): a re-run creates nothing. On a re-run over a migrated group, an
offset the campaign does not hold as it is now (added to the group afterwards, or
its amount changed) goes to review instead.

Under `--apply`, every offset left out is also kept, with its own detail and the
reason, in `offsets_migracion_pendientes` for the owner's review (T22a): one row
per offset, updated by a re-run, and removed once the offset migrates. The dry
run leaves the table as it is; its summary counts what `--apply` would keep there
(`pendientes`).

Dry run is the DEFAULT: it only validates (`validar_campos`, `validar` for a
group, plus each per-product amount against the existing group's reach, as
`--apply` does when it stores them) and writes nothing. A single offset's new
group is built from its own scope and carries no per-product amount, so its reach
holds by construction. `--apply` loads each offset, or each group, in its own transaction
(its campaign and a new group commit together, or nothing does). Exits 1 when a
validation or database error left an offset out, 0 otherwise. Run from `backend/` with `-m`:
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.migrar_offsets_a_sell_out --csv /tmp/offsets.csv
    cd /var/www/html/pricing-app/backend && venv/bin/python -m app.scripts.migrar_offsets_a_sell_out --csv /tmp/offsets.csv --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import and_, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_migracion_pendiente import OffsetMigracionPendiente
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutCampanaItem
from app.schemas.sell_out import ITEMS_MAX, NOMBRE_MAX, SellOutCampanaIn
from app.services.sell_out import alcance, campanas
from app.utils.csv_cells import csv_money, csv_text

logger = logging.getLogger(__name__)

FECHA_HASTA_DEFAULT = date(2026, 12, 31)
ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")
COLUMNAS = [
    "offset_id",
    "tipo",
    "descripcion",
    "alcance",
    "valor",
    "moneda",
    "desde",
    "hasta",
    "resultado",
    "campana_id",
    "motivo",
    "avisos",
]
MIGRADO, NO_MIGRADO, YA_MIGRADO, MIGRARIA = "migrado", "no migrado", "ya migrado", "migraría (dry-run)"
# Scope fields as (column, CSV label), in the order the filter rows are created.
_ALCANCE = (
    ("marca", "marca"),
    ("categoria", "categoría"),
    ("subcategoria_id", "subcategoría"),
    ("item_id", "producto"),
)
_CANALES = (("aplica_ml", "ML"), ("aplica_fuera", "fuera de ML"), ("aplica_tienda_nube", "Tienda Nube"))
_GRUPO_NOMBRE_MAX = OffsetGrupo.__table__.c.nombre.type.length


@dataclass
class _Plan:
    """What one offset becomes: a campaign (`data`), or a reason not to migrate it (`error`: a value the
    campaign cannot hold, reported like a validation error)."""

    motivo: Optional[str] = None
    error: bool = False
    data: Optional[SellOutCampanaIn] = None
    usuario_id: Optional[int] = None
    avisos: list[str] = field(default_factory=list)
    vencido: bool = False  # ends before `--hoy`: migrating it changes the historical sell-out figures


def _texto(offset: OffsetGanancia) -> str:
    return (offset.descripcion or "").strip()


def _alcance(offset: OffsetGanancia) -> str:
    if offset.grupo_id is not None:
        return f"grupo #{offset.grupo_id}"
    return " o ".join(f"{label} {getattr(offset, col)}" for col, label in _ALCANCE if getattr(offset, col) is not None)


def _monto(valor: float) -> Decimal:
    return Decimal(str(valor))


VENCIDO = "Vencido el {}: migrarlo cambia las cifras históricas de sell out en Métricas ML"


def _condiciones(
    plan: _Plan, offsets: list[OffsetGanancia], tope_de: Optional[OffsetGanancia], moneda: str, hoy, default
) -> dict:
    """Caps (from `tope_de`), dates and the warnings shared by one offset and a group: the earliest start, the
    latest end (an open-ended offset ends on `default`). An expired end is kept as it is, with its warning."""
    tope_monto = None
    if tope_de is not None and tope_de.max_monto_usd is not None:
        tope_monto = _monto(tope_de.max_monto_usd)  # USD: `_irrepresentable` refused it in pesos
    con_tc = next((o for o in offsets if o.tipo_cambio is not None), None)
    if moneda == "USD" and con_tc is not None:
        plan.avisos.append(
            f"El tipo de cambio del offset ({csv_money(con_tc.tipo_cambio)}) no se migró: "
            "la campaña queda con tipo de cambio al cobro"
        )
    if any(o.fecha_hasta is None for o in offsets):
        fecha_hasta = default
        plan.avisos.append(f"Sin fecha hasta: se usó {fecha_hasta.isoformat()}, revisar")
    else:
        fecha_hasta = max(o.fecha_hasta for o in offsets)
        if fecha_hasta < hoy:
            plan.vencido = True
    if plan.vencido:
        plan.avisos.append(VENCIDO.format(fecha_hasta.isoformat()))
    return {
        "fecha_desde": min(o.fecha_desde for o in offsets),
        "fecha_hasta": fecha_hasta,
        "tope_unidades": tope_de.max_unidades if tope_de is not None else None,
        "tope_monto": tope_monto,
    }


def _irrepresentable(offsets: list[OffsetGanancia], tope_de: Optional[OffsetGanancia], moneda: str) -> Optional[str]:
    """Why a campaign cannot credit what these offsets credited, or None: a campaign in pesos holds no USD cap, and a
    campaign covers every channel. Migrating them anyway would credit more than the legacy offsets did."""
    motivos = []
    if moneda != "USD" and tope_de is not None and tope_de.max_monto_usd is not None:
        motivos.append(
            f"El tope en USD ({csv_money(tope_de.max_monto_usd)}) no se puede guardar en una campaña en pesos"
        )
    sin_canal = [label for col, label in _CANALES if any(getattr(o, col) is False for o in offsets)]
    if sin_canal:
        motivos.append(f"No aplicaba a: {', '.join(sin_canal)}; una campaña aplica a todos los canales")
    return " | ".join(motivos) or None


def _planear(offset: OffsetGanancia, hoy: date, fecha_hasta_default: date, usuario_id: Optional[int]) -> _Plan:
    if offset.tipo_offset == "porcentaje_costo":
        return _Plan("esperando sell-in % (T3g)")
    if offset.tipo_offset == "monto_fijo":
        return _Plan("Monto fijo: no tiene equivalente en una campaña por unidad")
    if offset.tipo_offset != "monto_por_unidad":
        return _Plan(f"Tipo de offset desconocido: {offset.tipo_offset}")
    if offset.monto is None or offset.monto <= 0:
        return _Plan("Monto negativo o cero")
    usuario = offset.usuario_id if offset.usuario_id is not None else usuario_id
    if usuario is None:
        return _Plan("Sin usuario: indicar --usuario-id")
    if not any(getattr(offset, col) is not None for col, _ in _ALCANCE):
        return _Plan("Sin alcance: no indica marca, categoría, subcategoría, producto ni grupo")

    moneda = offset.moneda or "ARS"
    motivo = _irrepresentable([offset], offset, moneda)
    if motivo is not None:
        return _Plan(motivo)
    plan = _Plan(usuario_id=usuario)
    condiciones = _condiciones(plan, [offset], offset, moneda, hoy, fecha_hasta_default)
    texto = _texto(offset)
    try:
        plan.data = SellOutCampanaIn(
            nombre=(texto or f"Offset #{offset.id}")[:NOMBRE_MAX],
            descripcion=f"Migrado del offset #{offset.id}" + (f": {texto}" if texto else ""),
            tipo="por_unidad",
            monto_unit=_monto(offset.monto),
            moneda=moneda,
            grupo_ids=[],  # its own new group, created under --apply
            **condiciones,
        )
    except ValidationError as exc:
        return _Plan(f"Valor no válido en: {_campos(exc)}", error=True)
    return plan


def _planear_grupo(
    grupo_id: int, offsets: list[OffsetGanancia], hoy: date, fecha_hasta_default: date, usuario_id: Optional[int]
) -> _Plan:
    """A group (its offsets by id) as ONE campaign linked to the group, as the legacy money path applies it
    (`_consumo_grupos`): each offset with a product gives that product its own amount, a sale reached only by the
    group's filters gets the first offset's amount, and the first offset with a limit caps the whole group."""
    g = f"Grupo #{grupo_id}"
    ref = offsets[0]
    tipos = sorted({o.tipo_offset for o in offsets})
    if tipos != ["monto_por_unidad"]:
        return _Plan(f"{g}: no todos sus offsets son monto por unidad ({', '.join(tipos)}); revisar a mano")
    monedas = sorted({o.moneda or "ARS" for o in offsets})
    if len(monedas) > 1:
        return _Plan(f"{g}: mezcla monedas ({', '.join(monedas)})")
    for o in offsets:
        if o.monto is None or o.monto <= 0:
            return _Plan(f"{g}: el offset #{o.id} tiene monto negativo o cero")
    for o in offsets[1:]:
        if o.item_id is None:
            return _Plan(f"{g}: el offset #{o.id} no indica producto (solo el primero del grupo puede no indicarlo)")
    con_item = [o for o in offsets if o.item_id is not None]
    vistos = set()
    for o in con_item:
        if o.item_id in vistos:
            return _Plan(f"{g}: el producto {o.item_id} tiene más de un offset")
        vistos.add(o.item_id)
    if len(con_item) > ITEMS_MAX:
        return _Plan(
            f"{g}: tiene {len(con_item)} productos con monto propio y una campaña admite hasta {ITEMS_MAX}; "
            "revisar a mano"
        )
    if len({(o.fecha_desde, o.fecha_hasta) for o in offsets}) > 1:
        # Each legacy offset applies only within its own dates: one campaign period would credit outside them.
        return _Plan(f"{g}: sus offsets tienen períodos distintos y una campaña tiene uno solo; revisar a mano")
    usuario = next((o.usuario_id for o in offsets if o.usuario_id is not None), usuario_id)
    if usuario is None:
        return _Plan(f"{g}: sin usuario; indicar --usuario-id")

    moneda = monedas[0]
    tope_de = next((o for o in offsets if o.max_unidades or o.max_monto_usd), None)
    motivo = _irrepresentable(offsets, tope_de, moneda)
    if motivo is not None:
        return _Plan(f"{g}: {motivo}")
    plan = _Plan(usuario_id=usuario)
    condiciones = _condiciones(plan, offsets, tope_de, moneda, hoy, fecha_hasta_default)
    texto = _texto(ref)
    origen = ", ".join(f"#{o.id}" for o in offsets)
    try:
        plan.data = SellOutCampanaIn(
            nombre=(texto or g)[:NOMBRE_MAX],
            descripcion=f"Migrado de los offsets {origen} del grupo #{grupo_id}" + (f": {texto}" if texto else ""),
            tipo="por_unidad",
            monto_unit=_monto(ref.monto),
            moneda=moneda,
            grupo_ids=[grupo_id],  # the existing group: its filters already define the reach
            items=[{"item_id": o.item_id, "monto_unit": _monto(o.monto)} for o in con_item],
            **condiciones,
        )
    except ValidationError as exc:
        return _Plan(f"{g}: Valor no válido en: {_campos(exc)}", error=True)
    return plan


def _campos(exc: ValidationError) -> str:
    """The fields a validation error names; a model-level error has none and names the whole campaign."""
    return ", ".join(dict.fromkeys(str(e["loc"][0]) if e["loc"] else "campaña" for e in exc.errors()))


def _nuevo_grupo(db: Session, offset: OffsetGanancia, usuario_id: int) -> int:
    """The offset's scope as a group: one filter row per field, so a product matching any of them is reached."""
    nombre = f"Offset #{offset.id}: {_texto(offset)}" if _texto(offset) else f"Offset #{offset.id}"
    grupo = OffsetGrupo(
        nombre=nombre[:_GRUPO_NOMBRE_MAX],
        descripcion=f"Alcance del offset #{offset.id}, migrado a sell out",
        usuario_id=usuario_id,
    )
    db.add(grupo)
    db.flush()
    for col, _ in _ALCANCE:
        if getattr(offset, col) is not None:
            db.add(OffsetGrupoFiltro(grupo_id=grupo.id, **{col: getattr(offset, col)}))
    db.flush()
    return grupo.id


def _fila(offset: OffsetGanancia, resultado: str, campana_id=None, motivo=None, avisos=()) -> dict:
    valor = offset.porcentaje if offset.tipo_offset == "porcentaje_costo" else offset.monto
    return {
        "offset_id": offset.id,
        "tipo": csv_text(offset.tipo_offset),
        "descripcion": csv_text(offset.descripcion),
        "alcance": csv_text(_alcance(offset)),
        "valor": csv_money(valor),
        "moneda": csv_text(offset.moneda),
        "desde": offset.fecha_desde.isoformat(),
        "hasta": offset.fecha_hasta.isoformat() if offset.fecha_hasta else "",
        "resultado": resultado,
        "campana_id": campana_id if campana_id is not None else "",
        "motivo": csv_text(motivo),
        "avisos": csv_text(" | ".join(avisos)),
    }


# The offset's own columns copied to the review table, as they are.
_DETALLE = (
    "tipo_offset",
    "descripcion",
    "marca",
    "categoria",
    "subcategoria_id",
    "item_id",
    "grupo_id",
    "monto",
    "porcentaje",
    "moneda",
    "tipo_cambio",
    "fecha_desde",
    "fecha_hasta",
    "max_unidades",
    "max_monto_usd",
    "aplica_ml",
    "aplica_fuera",
    "aplica_tienda_nube",
    "usuario_id",
)


def _guardar_pendiente(db: Session, offset: OffsetGanancia, motivo: str, avisos: list[str]) -> None:
    """Keeps the offset for review, or refreshes its row: a re-run stores the offset as it is now."""
    values = {
        "offset_id": offset.id,
        **{col: getattr(offset, col) for col in _DETALLE},
        "motivo": motivo,
        "avisos": " | ".join(avisos) or None,
    }
    stmt = insert(OffsetMigracionPendiente).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[OffsetMigracionPendiente.offset_id],
        set_={**{k: stmt.excluded[k] for k in values if k != "offset_id"}, "registrado_en": func.now()},
    )
    db.execute(stmt)


def _quitar_pendiente(db: Session, offset_id: int) -> None:
    db.query(OffsetMigracionPendiente).filter(OffsetMigracionPendiente.offset_id == offset_id).delete()


def _ya_migrada(db: Session, offset_id: int) -> Optional[int]:
    return db.query(SellOutCampana.id).filter(SellOutCampana.offset_origen_id == offset_id).scalar()


@dataclass
class _Resultado:
    """One offset's CSV row and what the run does with it."""

    fila: dict
    offset: Optional[OffsetGanancia] = None
    error: Optional[str] = None
    pendiente: Optional[tuple[str, list[str]]] = None  # (reason, warnings) for the review table
    vencido: bool = False  # an expired offset that migrates (or, in a dry run, would)
    nueva: bool = False  # the row that names a new campaign once in the summary


def _uno(db: Session, offset: OffsetGanancia, plan: _Plan, apply: bool) -> tuple[dict, Optional[str]]:
    """The CSV row of one planned offset and its validation error, if any. Under `apply` it commits."""
    try:
        if not apply:
            campanas.validar_campos(plan.data)  # its group does not exist yet
            return _fila(offset, MIGRARIA, avisos=plan.avisos), None
        plan.data.grupo_ids = [_nuevo_grupo(db, offset, plan.usuario_id)]
        campana = campanas.crear_campana(db, plan.data, plan.usuario_id, offset_origen_id=offset.id)
        return _fila(offset, MIGRADO, campana.id, avisos=plan.avisos), None
    except campanas.SellOutError as exc:
        db.rollback()  # drops the new group too
        return _fila(offset, NO_MIGRADO, motivo=str(exc), avisos=plan.avisos), str(exc)
    except SQLAlchemyError as exc:
        # One offset's database error must not cost the others, nor the report: it is rolled back and reported.
        db.rollback()
        logger.exception("Offset #%s: database error", offset.id)
        motivo = f"Error de base de datos: {type(exc).__name__}"
        return _fila(offset, NO_MIGRADO, motivo=motivo, avisos=plan.avisos), motivo


def _suelto(db: Session, offset: OffsetGanancia, hoy, default, usuario_id, apply: bool) -> list[_Resultado]:
    ya = _ya_migrada(db, offset.id)
    if ya is not None:
        return [_Resultado(_fila(offset, YA_MIGRADO, ya), offset)]
    plan = _planear(offset, hoy, default, usuario_id)
    if plan.data is None:
        fila = _fila(offset, NO_MIGRADO, motivo=plan.motivo, avisos=plan.avisos)
        return [_Resultado(fila, offset, plan.motivo if plan.error else None, (plan.motivo, plan.avisos))]
    fila, error = _uno(db, offset, plan, apply)
    if fila["resultado"] == NO_MIGRADO:
        return [_Resultado(fila, offset, error, (error or "No migrado", plan.avisos))]
    return [_Resultado(fila, offset, vencido=plan.vencido, nueva=True)]


def _grupo_migrado(db: Session, grupo_id: int, offsets: list[OffsetGanancia], campana_id: int) -> list[_Resultado]:
    """A re-run over a group already migrated: an offset the campaign holds as it is now (its origin with the
    campaign's amount, or its product with that amount) is "ya migrado". One added to the group afterwards, or whose
    amount changed since, is not what the campaign credits, so it goes to review instead."""
    campana = db.get(SellOutCampana, campana_id)
    t = SellOutCampanaItem
    montos = {i: m for i, m in db.query(t.item_id, t.monto_unit).filter(t.campana_id == campana_id)}
    g = f"Grupo #{grupo_id}"
    salida = []
    for o in offsets:
        if o.id == campana.offset_origen_id:
            tenido = campana.monto_unit
        elif o.item_id is not None and o.item_id in montos:
            tenido = montos[o.item_id]
        else:
            motivo = f"{g}: el offset se agregó después de migrar el grupo a la campaña #{campana_id}; revisar a mano"
            salida.append(_Resultado(_fila(o, NO_MIGRADO, motivo=motivo), o, None, (motivo, [])))
            continue
        if o.monto is not None and _monto(o.monto) == tenido:
            salida.append(_Resultado(_fila(o, YA_MIGRADO, campana_id), o))
            continue
        motivo = (
            f"{g}: el monto del offset cambió después de migrar el grupo a la campaña #{campana_id} "
            f"(campaña {csv_money(tenido)}, offset {csv_money(o.monto)}); revisar a mano"
        )
        salida.append(_Resultado(_fila(o, NO_MIGRADO, motivo=motivo), o, None, (motivo, [])))
    return salida


def _comprobar_alcance(db: Session, grupo_id: int, items) -> None:
    """Dry run: refuses a per-product amount outside the EXISTING group's reach with the error `--apply` gets from the
    service (`campanas._asignar_items`). It resolves the group's filter rows to products the way `alcance._alcanzados`
    does (a row's set fields must all match, a product matching any row is reached, an empty row reaches nothing),
    read-only: that one starts from a stored campaign, which a dry run does not create."""
    if not items:
        return
    f, p = OffsetGrupoFiltro, ProductoERP
    algo = or_(
        func.coalesce(f.marca, "") != "",
        func.coalesce(f.categoria, "") != "",
        func.coalesce(f.subcategoria_id, 0) != 0,
        func.coalesce(f.item_id, 0) != 0,
    )
    coincide = and_(
        algo,
        alcance._texto(f.marca, p.marca),
        alcance._texto(f.categoria, p.categoria),
        alcance._numero(f.subcategoria_id, p.subcategoria_id),
        alcance._numero(f.item_id, p.item_id),
    )
    pedidos = [item.item_id for item in items]
    alcanzados = {
        i
        for (i,) in db.query(p.item_id)
        .join(f, coincide)
        .filter(f.grupo_id == grupo_id, p.item_id.in_(pedidos))
        .distinct()
    }
    for item_id in pedidos:
        if item_id not in alcanzados:
            raise campanas.SellOutError(f"El producto {item_id} no está en los grupos de la campaña")


def _grupo(db: Session, offsets: list[OffsetGanancia], hoy, default, usuario_id, apply: bool) -> list[_Resultado]:
    """Every offset of one group (by id): one campaign, loaded in ONE transaction, or none of them migrates."""
    grupo_id = offsets[0].grupo_id
    ya = (
        db.query(SellOutCampana.id)
        .filter(SellOutCampana.offset_origen_id.in_([o.id for o in offsets]))
        .order_by(SellOutCampana.id)
        .first()
    )
    if ya is not None:
        return _grupo_migrado(db, grupo_id, offsets, ya[0])
    plan = _planear_grupo(grupo_id, offsets, hoy, default, usuario_id)
    error = plan.motivo if plan.error else None
    if plan.data is None:
        return [
            _Resultado(
                _fila(o, NO_MIGRADO, motivo=plan.motivo, avisos=plan.avisos), o, error, (plan.motivo, plan.avisos)
            )
            for o in offsets
        ]
    campana_id = None
    try:
        if apply:
            campana_id = campanas.crear_campana(db, plan.data, plan.usuario_id, offset_origen_id=offsets[0].id).id
        else:
            campanas.validar(db, plan.data)  # the group exists: its id is checked too
            _comprobar_alcance(db, grupo_id, plan.data.items)
    except (campanas.SellOutError, SQLAlchemyError) as exc:
        db.rollback()
        if isinstance(exc, SQLAlchemyError):
            logger.exception("Group #%s: database error", grupo_id)
            motivo = f"Grupo #{grupo_id}: Error de base de datos: {type(exc).__name__}"
        else:
            motivo = f"Grupo #{grupo_id}: {exc}"
        return [
            _Resultado(_fila(o, NO_MIGRADO, motivo=motivo, avisos=plan.avisos), o, motivo, (motivo, plan.avisos))
            for o in offsets
        ]
    resultado = MIGRADO if apply else MIGRARIA
    otro = (
        f"migrado en la campaña #{campana_id} del grupo #{grupo_id}"
        if apply
        else f"en la campaña del grupo #{grupo_id}"
    )
    return [
        _Resultado(
            _fila(o, resultado, campana_id, avisos=plan.avisos if i == 0 else [otro, *plan.avisos]),
            o,
            vencido=plan.vencido,
            nueva=i == 0,
        )
        for i, o in enumerate(offsets)
    ]


def _fila_sola(offset_id: int, motivo: str) -> dict:
    """The row of an offset whose detail could not be read: its id and the reason."""
    return {**dict.fromkeys(COLUMNAS, ""), "offset_id": offset_id, "resultado": NO_MIGRADO, "motivo": motivo}


def run_migracion(
    *,
    session_factory: Callable[[], Session],
    apply: bool = False,
    hoy: date,
    fecha_hasta_default: date = FECHA_HASTA_DEFAULT,
    usuario_id: Optional[int] = None,
) -> tuple[dict, list[dict]]:
    """`(summary, CSV rows)`: every offset in id order, each (or each group, at its first offset) in its own
    session."""
    with session_factory() as db:
        ids = [oid for (oid,) in db.query(OffsetGanancia.id).order_by(OffsetGanancia.id)]
    summary = {
        "dry_run": not apply,
        "offsets": len(ids),
        "migrados": 0,
        "migrarian": 0,
        "ya_migrados": 0,
        "no_migrados": 0,
        "con_error": [],
        "campana_ids": [],
        "pendientes": 0,
        "vencidos_migrados": [],
    }
    contador = {MIGRADO: "migrados", MIGRARIA: "migrarian", YA_MIGRADO: "ya_migrados", NO_MIGRADO: "no_migrados"}
    filas = []
    hechos: set[int] = set()  # the offsets of a group already reported with it
    for offset_id in ids:
        if offset_id in hechos:
            continue
        with session_factory() as db:
            resultados: list[_Resultado] = []
            miembros = [offset_id]
            tabla = True  # the review table took this run's rows (or, in a dry run, would)
            try:
                offset = db.get(OffsetGanancia, offset_id)
                if offset is None:  # deleted after the ids were read: no detail left to keep
                    resultados = [_Resultado(_fila_sola(offset_id, "El offset ya no existe"))]
                elif offset.grupo_id is None:
                    resultados = _suelto(db, offset, hoy, fecha_hasta_default, usuario_id, apply)
                else:
                    grupo = (
                        db.query(OffsetGanancia)
                        .filter(OffsetGanancia.grupo_id == offset.grupo_id)
                        .order_by(OffsetGanancia.id)
                        .all()
                    )
                    miembros = [o.id for o in grupo]
                    hechos.update(miembros)
                    resultados = _grupo(db, grupo, hoy, fecha_hasta_default, usuario_id, apply)
                if apply:
                    # A failed campaign was already rolled back: what commits here is the review rows alone.
                    for r in resultados:
                        if r.offset is None:
                            continue
                        if r.pendiente is not None:
                            _guardar_pendiente(db, r.offset, *r.pendiente)
                        else:
                            _quitar_pendiente(db, r.offset.id)
                    db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                logger.exception("Offset #%s: database error", offset_id)
                motivo = f"Error de base de datos: {type(exc).__name__}"
                tabla = False
                if not resultados:
                    # Reading failed: reported with the ids alone, the run and the report go on.
                    resultados = [_Resultado(_fila_sola(i, motivo), error=motivo) for i in miembros]
                else:
                    # Updating the review table failed: the CSV keeps its rows and says the table missed them.
                    aviso = f"No se actualizó la tabla de revisión ({motivo})"
                    for r in resultados:
                        r.error = r.error or motivo
                        r.fila["avisos"] = csv_text(" | ".join(filter(None, [r.fila["avisos"], aviso])))
            finally:
                if not apply:
                    db.rollback()
        for r in resultados:
            fila = r.fila
            filas.append(fila)
            summary[contador[fila["resultado"]]] += 1
            if tabla and r.pendiente is not None:
                summary["pendientes"] += 1
            if r.error is not None:
                summary["con_error"].append(fila["offset_id"])
            if r.nueva and fila["resultado"] == MIGRADO:
                summary["campana_ids"].append(fila["campana_id"])
            if r.vencido:
                summary["vencidos_migrados"].append(fila["offset_id"])
    return summary, filas


def escribir_csv(path: str, filas: list[dict]) -> None:
    # `;` and a BOM, like the app's other exports: Excel opens it in the Spanish locale with its accents.
    with open(path, "w", encoding="utf-8-sig", newline="") as archivo:
        writer = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        writer.writeheader()
        writer.writerows(filas)


def _fecha(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value!r}") from None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate the legacy offsets to sell-out campaigns (dry run by default)."
    )
    parser.add_argument("--csv", required=True, help="Where to write the report (CSV).")
    parser.add_argument("--apply", action="store_true", help="Create the campaigns; without it nothing is written.")
    parser.add_argument("--usuario-id", type=int, default=None, help="User for the offsets that have none.")
    parser.add_argument(
        "--fecha-hasta-default", type=_fecha, default=FECHA_HASTA_DEFAULT, help="End date for open-ended offsets."
    )
    parser.add_argument("--hoy", type=_fecha, default=None, help="Business date (default: today in Argentina).")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    from app.core import database  # resolved at call time, so tests can point it elsewhere

    # The report is the only record of the warnings: an unwritable path stops the run before anything is created.
    open(args.csv, "w", encoding="utf-8-sig").close()
    summary, filas = run_migracion(
        session_factory=database.SessionLocal,
        apply=args.apply,
        hoy=args.hoy or datetime.now(ARGENTINA).date(),
        fecha_hasta_default=args.fecha_hasta_default,
        usuario_id=args.usuario_id,
    )
    escribir_csv(args.csv, filas)
    print(json.dumps(summary, ensure_ascii=False, default=str))
    if summary["vencidos_migrados"]:
        # On stderr, so stdout stays one JSON line: the owner must see it, Métricas ML's history changes.
        ids = ", ".join(str(i) for i in summary["vencidos_migrados"])
        hecho = "migrado(s)" if args.apply else "se migrarían"
        print(
            f"AVISO: {len(summary['vencidos_migrados'])} offset(s) vencido(s) {hecho} ({ids}): "
            "cambian las cifras históricas de sell out en Métricas ML",
            file=sys.stderr,
        )
    return 1 if summary["con_error"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
