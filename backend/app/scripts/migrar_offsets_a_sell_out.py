"""Migrate the legacy offsets (`offsets_ganancia`) to sell-out campaigns and sell-in cost bonuses (T15, T22, T25f).

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
  EXISTING group, as the legacy money path applies them: the group reaches its
  filters AND the products of its offsets (the operator builds it from both; it
  may have no filters), so the products its filters miss go to a NEW group with
  one `item_id` filter each, linked to the same campaign (one shared cap); each
  offset with a product gives it its own amount (`items`), the
  campaign's `monto_unit` is the first offset's (by id: what a sale reached only
  by the filters gets), the cap comes from the first offset with a limit, the
  dates span the group's. The first offset is the campaign's origin; the others
  are reported migrated in it. The group migrates whole or not at all: mixed
  types or currencies, a non-positive amount, a product given twice, an offset
  other than the first without a product, no user or a cap or channel a
  campaign cannot hold (below) keep every offset of the group in the review table;
- `monto` -> `monto_unit` in the offset's `moneda`; a USD campaign gets the
  service's default FX mode (`al_cobro`), the offset's rate is not kept;
- `max_unidades` -> `tope_unidades`; `max_monto_usd` -> `tope_monto` (USD);
- an EXPIRED offset (`fecha_hasta` before `--hoy`) migrates with its real dates:
  that changes the historical sell-out figures in Métricas ML, so its CSV row
  warns, the summary lists it (`vencidos_migrados`) and the run says so on stderr;
- a NULL `fecha_hasta` ends on `--fecha-hasta-default` (2026-12-31), with a
  warning so someone adjusts it.

Each `porcentaje_costo` offset becomes ONE sell-in cost bonus (T25f, rule 9:
`sell_in_bonos_marca` with `base='costo_venta'`, `tipo='porcentaje'`, ARS), the
legacy offset's exact equivalent (a % of each sale's cost without VAT, by sale
date). It takes the offset's STORED `porcentaje` as is with 'incluye IVA'
UNTICKED (S33: the stored value is already net of VAT), and is loaded with the
bonus service's own steps (`app.services.sell_in.bonos_crud`: `validar`, the
same fields, the audit row; its table's triggers queue it for the worker like a
bonus loaded from the screen). The API never takes `offset_origen_id` (T25d:
read-only), so the script passes it to `crear_bono` as a keyword argument:

- a brand alone -> `alcance='marca'`; a category alone -> 'categoria'; a product
  alone -> 'modelos' with that product. A subcategory, or more than one field
  (a legacy offset reaches ANY of them, a bonus holds one), goes to review;
- a group's offsets (all `porcentaje_costo`) become ONE 'modelos' bonus whose
  models are the group's reach FROZEN at migration time: the products its
  filters reach now UNION the products of its offsets (the same reach as the
  sell-out groups above). Each offset with a product gives it its own %; the
  bonus's % is the first offset's. The same rules as a campaign's group refuse
  it (a product given twice, an offset other than the first without a product,
  different periods), and its rows warn that the reach is frozen;
- the dates, caps (`max_unidades` -> `tope_unidades`; a USD cap or a skipped
  channel goes to review) and the expired / open-ended warnings are the
  campaigns' (an expired one changes the historical cost with sell in in
  Métricas ML: `bonos_vencidos_migrados` and stderr);
- an offset matching a sell-in % brand bonus loaded BY HAND (active, same
  brand, overlapping dates, no `offset_origen_id`) is never migrated: it stays
  in review as "ya cargado a mano como bono #N", warning when its percentage
  differs. A bonus whose `offset_origen_id` is the offset's (any offset of a
  group) means it was already migrated: "ya migrado a bono #N".

The CSV says "migrado a bono #N" ("se migraría a bono" in a dry run); the
summary adds `bonos_creados` and `bono_ids`.

Everything else is reported in the CSV and NOT migrated, each with its reason:
`monto_fijo` (no campaign type holds a fixed total), a non-positive
amount, no scope, no user (offset without `usuario_id` and no `--usuario-id`),
what a campaign cannot represent (active or expired, single or any offset of a
group: an ARS offset capped in USD, since a campaign in pesos holds no USD cap; an
offset that skipped some channel, since a campaign covers every channel:
migrating either would credit more than the offset did) and the service's
validation errors. An offset already migrated is reported as such with its
campaign (a group's, through any of its offsets): a re-run creates nothing. On a
re-run over a migrated group, an offset the campaign does not hold as it is now
(added to the group afterwards, or its amount changed) goes to review instead.

Under `--apply`, every offset left out is also kept, with its own detail and the
reason, in `offsets_migracion_pendientes` for the owner's review (T22a): one row
per offset, updated by a re-run, and removed once the offset migrates. The dry
run leaves the table as it is; its summary counts what `--apply` would keep there
(`pendientes`).

Dry run is the DEFAULT: it only validates (`validar_campos`, `validar` for a
group, `bonos_crud.validar` for a cost bonus,
and it plans the new group of the products outside the existing group's
filters, as `--apply` creates it) and writes nothing. A single offset's new
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
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_migracion_pendiente import OffsetMigracionPendiente
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoItem, SellInBonoMarca
from app.models.sell_out import SellOutCampana, SellOutCampanaItem
from app.schemas.sell_in_bonos import BASE_COSTO_VENTA, MODELOS_MAX, SellInBonoIn, SellInBonoModeloIn
from app.schemas.sell_out import ITEMS_MAX, NOMBRE_MAX, SellOutCampanaIn
from app.services.sell_in import bonos_crud
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
BONO_MIGRADO, BONO_YA_MIGRADO, BONO_MIGRARIA = "migrado a bono #{}", "ya migrado a bono #{}", "se migraría a bono"
BONO = "un bono sobre el costo"  # how `_irrepresentable` names a cost bonus
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
    bono: Optional[SellInBonoIn] = None  # a cost-percentage offset (or group) becomes this sell-in cost bonus
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
VENCIDO_SELL_IN = "Vencido el {}: migrarlo cambia el costo histórico con sell in en Métricas ML"


def _condiciones(
    plan: _Plan,
    offsets: list[OffsetGanancia],
    tope_de: Optional[OffsetGanancia],
    moneda: str,
    hoy,
    default,
    vencido: str = VENCIDO,
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
        plan.avisos.append(vencido.format(fecha_hasta.isoformat()))
    return {
        "fecha_desde": min(o.fecha_desde for o in offsets),
        "fecha_hasta": fecha_hasta,
        "tope_unidades": tope_de.max_unidades if tope_de is not None else None,
        "tope_monto": tope_monto,
    }


def _irrepresentable(
    offsets: list[OffsetGanancia], tope_de: Optional[OffsetGanancia], moneda: str, que: str = "una campaña"
) -> Optional[str]:
    """Why a campaign (or `que`: a cost bonus) cannot credit what these offsets credited, or None: one in pesos holds
    no USD cap, and it covers every channel. Migrating them anyway would credit more than the legacy offsets did."""
    motivos = []
    if moneda != "USD" and tope_de is not None and tope_de.max_monto_usd is not None:
        motivos.append(f"El tope en USD ({csv_money(tope_de.max_monto_usd)}) no se puede guardar en {que} en pesos")
    sin_canal = [label for col, label in _CANALES if any(getattr(o, col) is False for o in offsets)]
    if sin_canal:
        motivos.append(f"No aplicaba a: {', '.join(sin_canal)}; {que} aplica a todos los canales")
    return " | ".join(motivos) or None


# brand (trimmed, lower case) -> its active % bonuses as (id, percentage, fecha_desde, fecha_hasta), by id
_Bonos = dict[str, list[tuple[int, Decimal, date, date]]]


def _clave(marca: str) -> str:
    return marca.strip().lower()


def _bonos(db: Session) -> _Bonos:
    """The active sell-in brand bonuses of `porcentaje` type loaded BY HAND (no `offset_origen_id`): the 4 brand %
    offsets were loaded as these (2026-10-23), with no link back to the offset."""
    b = SellInBonoMarca
    rows = db.query(b.id, b.marca, b.porcentaje, b.fecha_desde, b.fecha_hasta).filter(
        b.tipo == "porcentaje", b.alcance == "marca", b.estado == "activa", b.offset_origen_id.is_(None)
    )
    salida: _Bonos = {}
    for bono_id, marca, porcentaje, desde, hasta in rows.order_by(b.id):
        salida.setdefault(_clave(marca), []).append((bono_id, Decimal(porcentaje), desde, hasta))
    return salida


def _pct(valor) -> str:
    return format(Decimal(str(valor)).normalize(), "f").replace(".", ",")


def _a_mano(offset: OffsetGanancia, bonos: _Bonos) -> Optional[_Plan]:
    """The review plan of an offset already loaded BY HAND as a bonus (it is never migrated: a new bonus would count
    twice), or None. Only a brand-alone scope has one (a brand bonus), and only a bonus whose dates overlap the
    offset's (both inclusive; an offset without end is open) can be the one loaded for it."""
    solo_marca = offset.marca is not None and all(getattr(offset, c) is None for c, _ in _ALCANCE if c != "marca")
    iguales = [
        (bono_id, porcentaje)
        for bono_id, porcentaje, desde, hasta in (bonos.get(_clave(offset.marca), []) if solo_marca else [])
        if desde <= (offset.fecha_hasta or desde) and offset.fecha_desde <= hasta
    ]
    if not iguales:
        return None
    nombres = ", ".join(f"#{bono_id}" for bono_id, _ in iguales)
    plan = _Plan(f"ya cargado a mano como bono{'s' if len(iguales) > 1 else ''} {nombres}")
    propio = Decimal(str(offset.porcentaje)) if offset.porcentaje is not None else None
    for bono_id, porcentaje in iguales:
        if porcentaje != propio:
            cual = f"el bono #{bono_id}" if len(iguales) > 1 else "el bono"
            plan.avisos.append(f"{cual} tiene {_pct(porcentaje)} % y el offset {_pct(offset.porcentaje)} %")
    return plan


# A single offset's scope as a bonus's: one field alone (a legacy offset reaches a product matching ANY of its fields).
_ALCANCE_BONO = {
    ("marca",): lambda o: {"alcance": "marca", "marca": o.marca},
    ("categoria",): lambda o: {"alcance": "categoria", "categoria": o.categoria},
    ("item_id",): lambda o: {"alcance": "modelos", "modelos": [o.item_id]},
}


def _con_bono(plan: _Plan, campos: dict, porcentaje, descripcion: str, condiciones: dict, prefijo: str = "") -> _Plan:
    """`plan` with its cost bonus (S33: the stored % as is, 'incluye IVA' unticked), or the value it cannot hold."""
    try:
        plan.bono = SellInBonoIn(
            **campos,
            tipo="porcentaje",
            porcentaje=_monto(porcentaje) if porcentaje is not None else None,
            moneda="ARS",
            base=BASE_COSTO_VENTA,
            incluye_iva=False,
            descripcion=descripcion,
            **condiciones,
        )
    except ValidationError as exc:
        return _Plan(f"{prefijo}Valor no válido en: {_campos(exc)}", error=True)
    return plan


def _planear_bono(offset: OffsetGanancia, hoy: date, fecha_hasta_default: date, usuario_id: Optional[int]) -> _Plan:
    """A cost-percentage offset as one cost bonus over its own scope, dates and unit cap (rule 9)."""
    usuario = offset.usuario_id if offset.usuario_id is not None else usuario_id
    if usuario is None:
        return _Plan("Sin usuario: indicar --usuario-id")
    dados = tuple(col for col, _ in _ALCANCE if getattr(offset, col) is not None)
    if not dados:
        return _Plan("Sin alcance: no indica marca, categoría, subcategoría, producto ni grupo")
    if dados not in _ALCANCE_BONO:
        return _Plan(
            f"Porcentaje sobre costo: un bono de sell in no puede tener este alcance ({_alcance(offset)}); revisar a mano"
        )
    motivo = _irrepresentable([offset], offset, "ARS", BONO)
    if motivo is not None:
        return _Plan(motivo)
    plan = _Plan(usuario_id=usuario)
    condiciones = _condiciones(plan, [offset], offset, "ARS", hoy, fecha_hasta_default, VENCIDO_SELL_IN)
    texto = _texto(offset)
    descripcion = f"Migrado del offset #{offset.id}" + (f": {texto}" if texto else "")
    return _con_bono(plan, _ALCANCE_BONO[dados](offset), offset.porcentaje, descripcion, condiciones)


def _planear(
    offset: OffsetGanancia,
    hoy: date,
    fecha_hasta_default: date,
    usuario_id: Optional[int],
    bonos: Optional[_Bonos] = None,
) -> _Plan:
    if offset.tipo_offset == "porcentaje_costo":
        return _a_mano(offset, bonos or {}) or _planear_bono(offset, hoy, fecha_hasta_default, usuario_id)
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
    motivo = _grupo_irregular(g, offsets, "monto")
    if motivo is not None:
        return _Plan(motivo)
    con_item = [o for o in offsets if o.item_id is not None]
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
            grupo_ids=[grupo_id],  # the existing group; products outside its filters get a second one (`_grupo`)
            items=[{"item_id": o.item_id, "monto_unit": _monto(o.monto)} for o in con_item],
            **condiciones,
        )
    except ValidationError as exc:
        return _Plan(f"{g}: Valor no válido en: {_campos(exc)}", error=True)
    return plan


def _grupo_irregular(g: str, offsets: list[OffsetGanancia], valor: str) -> Optional[str]:
    """What a group's offsets break of the legacy money path's shape, or None: each `valor` positive, a product in every
    offset but the first, once each."""
    for o in offsets:
        if getattr(o, valor) is None or getattr(o, valor) <= 0:
            return f"{g}: el offset #{o.id} tiene {valor} negativo o cero"
    for o in offsets[1:]:
        if o.item_id is None:
            return f"{g}: el offset #{o.id} no indica producto (solo el primero del grupo puede no indicarlo)"
    vistos = set()
    for o in offsets:
        if o.item_id is not None and o.item_id in vistos:
            return f"{g}: el producto {o.item_id} tiene más de un offset"
        vistos.add(o.item_id)
    return None


def _alcance_de_grupo(db: Session, grupo_id: int) -> set[int]:
    """Every product an existing group's filters reach now, with the campaigns' rule (`alcance.filtro_alcanza`)."""
    f, p = OffsetGrupoFiltro, ProductoERP
    rows = db.query(p.item_id).join(f, alcance.filtro_alcanza(f, p)).filter(f.grupo_id == grupo_id)
    return {i for (i,) in rows.distinct()}


def _planear_grupo_bono(
    db: Session,
    grupo_id: int,
    offsets: list[OffsetGanancia],
    hoy: date,
    fecha_hasta_default: date,
    usuario_id: Optional[int],
) -> _Plan:
    """A group of cost-percentage offsets as ONE 'modelos' cost bonus over the group's reach frozen now: its filters'
    products UNION its offsets' products (owner: "El grupo lo arma el operador..."). Each offset with a product gives
    it its own %; the bonus's % (a product reached only by the filters) is the first offset's."""
    g = f"Grupo #{grupo_id}"
    motivo = _grupo_irregular(g, offsets, "porcentaje")
    if motivo is not None:
        return _Plan(motivo)
    if len({(o.fecha_desde, o.fecha_hasta) for o in offsets}) > 1:
        return _Plan(f"{g}: sus offsets tienen períodos distintos y un bono tiene uno solo; revisar a mano")
    usuario = next((o.usuario_id for o in offsets if o.usuario_id is not None), usuario_id)
    if usuario is None:
        return _Plan(f"{g}: sin usuario; indicar --usuario-id")
    tope_de = next((o for o in offsets if o.max_unidades or o.max_monto_usd), None)
    motivo = _irrepresentable(offsets, tope_de, "ARS", BONO)
    if motivo is not None:
        return _Plan(f"{g}: {motivo}")
    propios = {o.item_id: o.porcentaje for o in offsets if o.item_id is not None}
    modelos = sorted(_alcance_de_grupo(db, grupo_id) | set(propios))
    if len(modelos) > MODELOS_MAX:
        return _Plan(
            f"{g}: alcanza {len(modelos)} productos y un bono por modelos admite hasta {MODELOS_MAX}; revisar a mano"
        )
    plan = _Plan(usuario_id=usuario)
    condiciones = _condiciones(plan, offsets, tope_de, "ARS", hoy, fecha_hasta_default, VENCIDO_SELL_IN)
    plan.avisos.append(
        f"{g}: alcance congelado en {len(modelos)} productos (sus filtros hoy y los productos de sus offsets); "
        "un producto que cambió de marca o categoría desde entonces puede no coincidir"
    )
    texto = _texto(offsets[0])
    origen = ", ".join(f"#{o.id}" for o in offsets)
    descripcion = f"Migrado de los offsets {origen} del grupo #{grupo_id}" + (f": {texto}" if texto else "")
    try:
        lista = [SellInBonoModeloIn(item_id=i, porcentaje=_monto(propios[i])) if i in propios else i for i in modelos]
    except ValidationError as exc:
        return _Plan(f"{g}: Valor no válido en: {_campos(exc)}", error=True)
    campos = {"alcance": "modelos", "modelos": lista}
    return _con_bono(plan, campos, offsets[0].porcentaje, descripcion, condiciones, f"{g}: ")


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
    nueva: bool = False  # the row that names a new campaign (or cost bonus) once in the summary
    cuenta: Optional[str] = None  # the summary counter, when `resultado` names a bonus (it holds its id)
    bono_id: Optional[int] = None  # a cost bonus created (or, with `cuenta`, holding the offset)


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


def _bono_migrado(db: Session, offset_ids: list[int]) -> Optional[SellInBonoMarca]:
    return (
        db.query(SellInBonoMarca)
        .filter(SellInBonoMarca.offset_origen_id.in_(offset_ids))
        .order_by(SellInBonoMarca.id)
        .first()
    )


def _anulado(bono: SellInBonoMarca) -> list[str]:
    return [f"El bono #{bono.id} está anulado"] if bono.estado == "anulada" else []


def _uno_bono(
    db: Session, offset: OffsetGanancia, plan: _Plan, apply: bool
) -> tuple[dict, Optional[str], Optional[int]]:
    """The CSV row of one planned cost bonus (an offset's, or a group's at its first offset), its error and the new
    bonus's id. Under `apply` it commits; a failure rolls the bonus and its models back."""
    try:
        if not apply:
            bonos_crud.validar(db, plan.bono)
            return _fila(offset, BONO_MIGRARIA, avisos=plan.avisos), None, None
        bono = bonos_crud.crear_bono(db, plan.bono, plan.usuario_id, offset_origen_id=offset.id)
        return _fila(offset, BONO_MIGRADO.format(bono.id), avisos=plan.avisos), None, bono.id
    except bonos_crud.SellInBonoError as exc:
        db.rollback()
        return _fila(offset, NO_MIGRADO, motivo=str(exc), avisos=plan.avisos), str(exc), None
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Offset #%s: database error", offset.id)
        motivo = f"Error de base de datos: {type(exc).__name__}"
        return _fila(offset, NO_MIGRADO, motivo=motivo, avisos=plan.avisos), motivo, None


def _suelto(
    db: Session, offset: OffsetGanancia, hoy, default, usuario_id, apply: bool, bonos: _Bonos
) -> list[_Resultado]:
    ya = _ya_migrada(db, offset.id)
    if ya is not None:
        return [_Resultado(_fila(offset, YA_MIGRADO, ya), offset)]
    bono = _bono_migrado(db, [offset.id])
    if bono is not None:
        fila = _fila(offset, BONO_YA_MIGRADO.format(bono.id), avisos=_anulado(bono))
        return [_Resultado(fila, offset, cuenta="ya_migrados", bono_id=bono.id)]
    plan = _planear(offset, hoy, default, usuario_id, bonos)
    if plan.bono is not None:
        fila, error, bono_id = _uno_bono(db, offset, plan, apply)
        if error is not None:
            return [_Resultado(fila, offset, error, (error, plan.avisos))]
        cuenta = "migrados" if apply else "migrarian"
        return [_Resultado(fila, offset, vencido=plan.vencido, nueva=True, cuenta=cuenta, bono_id=bono_id)]
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
            avisos = [f"La campaña #{campana_id} está anulada"] if campana.estado == "anulada" else []
            salida.append(_Resultado(_fila(o, YA_MIGRADO, campana_id, avisos=avisos), o))
            continue
        motivo = (
            f"{g}: el monto del offset cambió después de migrar el grupo a la campaña #{campana_id} "
            f"(campaña {csv_money(tenido)}, offset {csv_money(o.monto)}); revisar a mano"
        )
        salida.append(_Resultado(_fila(o, NO_MIGRADO, motivo=motivo), o, None, (motivo, [])))
    return salida


def _fuera_de_filtros(db: Session, grupo_id: int, items) -> list[int]:
    """The per-product amounts the EXISTING group's filters do not reach, in offset order. The operator builds a group
    from filters and from the products of its offsets, and the legacy money path reaches both (`_consumo_grupos`),
    so these products belong to the group even when no filter covers them (a group may have no filters at all)."""
    if not items:
        return []
    pedidos = [item.item_id for item in items]
    alcanzados = alcance.productos_de_grupo(db, grupo_id, pedidos)
    return [item_id for item_id in pedidos if item_id not in alcanzados]


def _inexistentes(db: Session, item_ids: list[int]) -> list[int]:
    """The products a legacy offset names that no longer exist (a legacy table may lack the product FK). An existing
    product is always reached by a row holding only its `item_id` (`alcance.filtro_alcanza` is a plain match), so with
    this check the dry run plans exactly the products' group `--apply` stores."""
    if not item_ids:
        return []
    existen = {i for (i,) in db.query(ProductoERP.item_id).filter(ProductoERP.item_id.in_(item_ids))}
    return [i for i in item_ids if i not in existen]


def _grupo_de_productos(db: Session, grupo_id: int, item_ids: list[int], usuario_id: int) -> int:
    """A new group with one `item_id` filter per product, linked to the same campaign so the campaign reaches what the
    legacy group reached. The operator's group is left as it is: new filter rows there would change what the legacy
    screens show."""
    grupo = OffsetGrupo(
        nombre=f"Grupo #{grupo_id}: productos de sus offsets"[:_GRUPO_NOMBRE_MAX],
        descripcion=f"Productos de los offsets del grupo #{grupo_id} fuera de sus filtros, migrado a sell out",
        usuario_id=usuario_id,
    )
    db.add(grupo)
    db.flush()
    for item_id in item_ids:
        db.add(OffsetGrupoFiltro(grupo_id=grupo.id, item_id=item_id))
    db.flush()
    return grupo.id


def _grupo_bono_migrado(db: Session, grupo_id: int, offsets: list[OffsetGanancia], bono) -> list[_Resultado]:
    """A re-run over a group already migrated to a cost bonus: an offset the bonus holds as it is now (its origin with
    the bonus's %, or its product with that %) is "ya migrado"; one added afterwards or whose % changed goes to review."""
    t = SellInBonoItem
    propios = {i: p for i, p in db.query(t.item_id, t.porcentaje).filter(t.bono_id == bono.id)}
    g = f"Grupo #{grupo_id}"
    salida = []
    for o in offsets:
        if o.id == bono.offset_origen_id:
            tenido = bono.porcentaje
        elif o.item_id is not None and o.item_id in propios:
            tenido = propios[o.item_id] if propios[o.item_id] is not None else bono.porcentaje
        else:
            motivo = f"{g}: el offset se agregó después de migrar el grupo al bono #{bono.id}; revisar a mano"
            salida.append(_Resultado(_fila(o, NO_MIGRADO, motivo=motivo), o, None, (motivo, [])))
            continue
        if o.porcentaje is not None and _monto(o.porcentaje) == tenido:
            fila = _fila(o, BONO_YA_MIGRADO.format(bono.id), avisos=_anulado(bono))
            salida.append(_Resultado(fila, o, cuenta="ya_migrados", bono_id=bono.id))
            continue
        motivo = (
            f"{g}: el porcentaje del offset cambió después de migrar el grupo al bono #{bono.id} "
            f"(bono {_pct(tenido)} %, offset {_pct(o.porcentaje)} %); revisar a mano"
        )
        salida.append(_Resultado(_fila(o, NO_MIGRADO, motivo=motivo), o, None, (motivo, [])))
    return salida


def _grupo_bono(db: Session, offsets: list[OffsetGanancia], hoy, default, usuario_id, apply: bool) -> list[_Resultado]:
    """Every cost-percentage offset of one group (by id): one cost bonus, loaded in ONE transaction, or none."""
    grupo_id = offsets[0].grupo_id
    plan = _planear_grupo_bono(db, grupo_id, offsets, hoy, default, usuario_id)
    if plan.bono is None:
        error = plan.motivo if plan.error else None
        return [
            _Resultado(
                _fila(o, NO_MIGRADO, motivo=plan.motivo, avisos=plan.avisos), o, error, (plan.motivo, plan.avisos)
            )
            for o in offsets
        ]
    fila, error, bono_id = _uno_bono(db, offsets[0], plan, apply)
    if error is not None:
        motivo = f"Grupo #{grupo_id}: {error}"
        return [
            _Resultado(_fila(o, NO_MIGRADO, motivo=motivo, avisos=plan.avisos), o, motivo, (motivo, plan.avisos))
            for o in offsets
        ]
    otro = f"migrado en el bono #{bono_id} del grupo #{grupo_id}" if apply else f"en el bono del grupo #{grupo_id}"
    return [
        _Resultado(
            _fila(o, fila["resultado"], avisos=plan.avisos if i == 0 else [otro, *plan.avisos]),
            o,
            vencido=plan.vencido,
            nueva=i == 0,
            cuenta="migrados" if apply else "migrarian",
            bono_id=bono_id,
        )
        for i, o in enumerate(offsets)
    ]


def _grupo(db: Session, offsets: list[OffsetGanancia], hoy, default, usuario_id, apply: bool) -> list[_Resultado]:
    """Every offset of one group (by id): one campaign, loaded in ONE transaction, or none of them migrates (a group
    of cost-percentage offsets: one cost bonus, `_grupo_bono`)."""
    grupo_id = offsets[0].grupo_id
    bono = _bono_migrado(db, [o.id for o in offsets])
    if bono is not None:
        return _grupo_bono_migrado(db, grupo_id, offsets, bono)
    if all(o.tipo_offset == "porcentaje_costo" for o in offsets):
        return _grupo_bono(db, offsets, hoy, default, usuario_id, apply)
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
    avisos = list(plan.avisos)  # the moved products are only reported when the campaign is (or would be) created
    try:
        fuera = _fuera_de_filtros(db, grupo_id, plan.data.items)
        inexistentes = _inexistentes(db, fuera)
        if inexistentes:
            # `--apply` would fail on the new group's product FK; both runs refuse it the same way, before writing.
            motivo = f"Grupo #{grupo_id}: el producto {', '.join(map(str, inexistentes))} de sus offsets no existe; "
            motivo += "revisar a mano"
            return [
                _Resultado(_fila(o, NO_MIGRADO, motivo=motivo, avisos=avisos), o, None, (motivo, avisos))
                for o in offsets
            ]
        if fuera:
            avisos.append(
                f"Grupo #{grupo_id}: los productos {', '.join(map(str, fuera))} no están en sus filtros "
                "(venían de sus offsets): van a un grupo nuevo de la misma campaña"
            )
        if apply:
            if fuera:
                plan.data.grupo_ids = [grupo_id, _grupo_de_productos(db, grupo_id, fuera, plan.usuario_id)]
            campana_id = campanas.crear_campana(db, plan.data, plan.usuario_id, offset_origen_id=offsets[0].id).id
        else:
            campanas.validar(db, plan.data)  # the group exists: its id is checked too
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
            _fila(o, resultado, campana_id, avisos=avisos if i == 0 else [otro, *avisos]),
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
        bonos = _bonos(db)
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
        "bonos_creados": 0,
        "bono_ids": [],
        "bonos_vencidos_migrados": [],
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
                    resultados = _suelto(db, offset, hoy, fecha_hasta_default, usuario_id, apply, bonos)
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
            summary[r.cuenta or contador[fila["resultado"]]] += 1
            if tabla and r.pendiente is not None:
                summary["pendientes"] += 1
            if r.error is not None:
                summary["con_error"].append(fila["offset_id"])
            if r.nueva and fila["resultado"] == MIGRADO:
                summary["campana_ids"].append(fila["campana_id"])
            if r.nueva and r.cuenta == "migrados":
                summary["bonos_creados"] += 1
                summary["bono_ids"].append(r.bono_id)
            if r.vencido:
                summary["bonos_vencidos_migrados" if r.cuenta else "vencidos_migrados"].append(fila["offset_id"])
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
        description="Migrate the legacy offsets to sell-out campaigns and sell-in cost bonuses (dry run by default)."
    )
    parser.add_argument("--csv", required=True, help="Where to write the report (CSV).")
    parser.add_argument(
        "--apply", action="store_true", help="Create the campaigns and cost bonuses; without it nothing is written."
    )
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
    if summary["bonos_vencidos_migrados"]:
        ids = ", ".join(str(i) for i in summary["bonos_vencidos_migrados"])
        hecho = "migrado(s)" if args.apply else "se migrarían"
        print(
            f"AVISO: {len(summary['bonos_vencidos_migrados'])} offset(s) vencido(s) {hecho} a bono ({ids}): "
            "cambian el costo histórico con sell in en Métricas ML",
            file=sys.stderr,
        )
    return 1 if summary["con_error"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
