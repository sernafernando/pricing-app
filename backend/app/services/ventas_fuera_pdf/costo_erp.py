"""The cost of a PDF line: its product's costo SI on the sale date (sell-in-costo-si T3 PR 9; owner L6.2 "costo d va a
aplicar sobre costo si"), read through `app.services.costo_si.lote`, the one reader every consumer uses:

- unit cost = `lote.en_fechas` `costo_ars`: the costo SI in force on the sale date, in the product's cost currency
  (owner L18), in pesos at that date's USD rate; without costo SI the list cost (`fuente` 'lista', interface Q1);
  unknown (no cost, or a dollar cost without a rate) -> 0, as a line without cost always was;
- a combo that is not a PC = its components x quantity (the reader, S11), UNLESS the same document brings its
  breakdown (owner L19: "claro si el combo trae el desglose no tomarlo, si no lo trae sí"): when EVERY one of its
  components is also a line of that document, the combo line costs 0 and its components carry the cost; with only
  some of them the combo is costed whole and logged (`combos_desglosados`).

The line's `precio_costo` = unit cost x `cantidad`, the Precio Costo WITHOUT the 6.5%: every screen applies Costo D
(x `COSTO_D_FACTOR`) on top, as before. The PDF's "Precio Costo" is not a cost; it stays in `precio_costo_pdf` only as
a reference. A line without product (`item_id` NULL) costs 0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Iterable, Mapping, Optional, TypeVar

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.venta_fuera_pdf import VentaFueraLineaOverride, VentaFueraOperacion, VentaFueraOperacionLinea
from app.services.costo_si import lote

K = TypeVar("K")

logger = logging.getLogger(__name__)

CERO = Decimal("0")
CENTAVO = Decimal("0.01")


def costos_unitarios(db: Session, pares: Iterable[tuple[int, date]]) -> dict[tuple[int, date], Optional[Decimal]]:
    """The unit cost in pesos of each `(item_id, fecha)`, in one query: the reader's `costo_ars` (None = unknown,
    interface §7). An unknown cost is logged: the line's Precio Costo column is NOT NULL, so it is stored as 0, the
    existing "sin costo" value the screens keep out of the markup (a NULL column needs a migration: orchestrator)."""
    costos = {clave: costo.costo_ars for clave, costo in lote.en_fechas(db, pares).items()}
    for (item_id, fecha), costo in sorted(costos.items()):
        if costo is None:
            logger.warning(
                "ventas_fuera: unknown cost for item %s on %s: Precio Costo stays without cost", item_id, fecha
            )
    return costos


def combos_desglosados(
    db: Session, documentos: Mapping[K, Iterable[Optional[int]]], *, origen: str = "ventas_fuera"
) -> dict[K, set[int]]:
    """Owner L19: for each document (its products, keyed by its group id), the combos among them whose breakdown it
    brings, i.e. EVERY one of their components is another line of the same document (one loose unit of a component
    is not a breakdown). Quantities are not compared. PCs are never combos here (`lote.combos_con`).

    A combo with SOME but not all of its components as other lines (a partial breakdown) is costed whole and its
    loose components too; that possible double count is logged with the group id and the missing components (owner
    reply to the PR 9 doubt), never silent. One query for every document."""
    presentes = {k: {int(i) for i in items if i is not None} for k, items in documentos.items()}
    contienen = lote.combos_con(db, set().union(*presentes.values())) if presentes else {}
    candidatos = {combo for combos in contienen.values() for combo in combos}
    partes: dict[int, set[int]] = {}
    if candidatos:
        filas = db.execute(
            text("SELECT combo_item_id, componente_item_id FROM combo_componentes WHERE combo_item_id = ANY(:ids)"),
            {"ids": sorted(candidatos)},
        )
        for combo, componente in filas:
            partes.setdefault(int(combo), set()).add(int(componente))
    desglosados: dict[K, set[int]] = {}
    for k, items in presentes.items():
        desglosados[k] = set()
        for combo in sorted(items & candidatos):
            faltan = partes.get(combo, set()) - (items - {combo})
            if not faltan:
                desglosados[k].add(combo)
            elif faltan != partes.get(combo):
                logger.warning(
                    "%s: combo %s partially broken down in group %s (missing components %s): costed whole and its "
                    "loose components too",
                    origen,
                    combo,
                    k,
                    sorted(faltan),
                )
    return desglosados


def precio_costo(costo_unitario: Optional[Decimal], cantidad: Decimal) -> Decimal:
    """The line's Precio Costo: unit cost x `cantidad`, to the cent (a credit note's negative quantity stays)."""
    if costo_unitario is None:
        return CERO
    return (Decimal(costo_unitario) * Decimal(cantidad)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def precio_costo_erp(
    db: Session, item_id: Optional[int], fecha: date, cantidad: Decimal, *, desglosado: bool = False
) -> Decimal:
    """The Precio Costo of one line of product `item_id` sold on `fecha`; 0 without product, and 0 for a combo whose
    document brings its breakdown (`desglosado`, owner L19)."""
    if item_id is None or desglosado:
        return CERO
    return precio_costo(costos_unitarios(db, [(item_id, fecha)]).get((item_id, fecha)), cantidad)


@dataclass(frozen=True)
class Recosteo:
    """A stored line whose Precio Costo the ERP cost list changes: `antes` stored, `despues` from the ERP."""

    linea_id: int
    fecha: date
    item_id: Optional[int]
    cantidad: Decimal
    precio: Decimal
    antes: Decimal
    despues: Decimal


def recostear(
    db: Session,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    aplicar: bool = False,
    respaldo: Optional[Callable[[list[Recosteo]], None]] = None,
    *,
    items: Optional[Iterable[int]] = None,
    commit: bool = True,
) -> list[Recosteo]:
    """The stored lines (sale date in `[desde, hasta]`, open ends allowed; of the products `items` when given) whose
    `precio_costo` differs from their costo SI cost (module docstring), skipping the lines with a manual cost applied
    (`ventas_fuera_linea_overrides.costo_unitario`). `aplicar=False` (default) only reports. `aplicar=True` locks the
    lines (FOR UPDATE), hands the exact changes to `respaldo` BEFORE writing (if it raises, nothing is written), then
    writes them; the trigger on the lines queues each one in `sell_dirty`, so offsets and sell in / sell out follow.
    `commit=True` commits (and rolls back on failure); `commit=False` only flushes, inside the caller's transaction
    (the costo SI follow-up, `costo_si.despues.ventas_fuera`), which then commits or rolls back everything."""
    LN, OP, OV = VentaFueraOperacionLinea, VentaFueraOperacion, VentaFueraLineaOverride
    manual = (
        select(OV.id)
        .where(
            OV.empresa == OP.empresa,
            OV.tipo == OP.tipo,
            OV.letra == OP.letra,
            OV.punto_venta == OP.punto_venta,
            OV.numero == OP.numero,
            OV.renglon == LN.renglon,
            OV.costo_unitario.is_not(None),
            LN.override_estado == "aplicado",
        )
        .exists()
    )
    query = select(LN, OP.fecha).join(OP, OP.id == LN.operacion_id).where(~manual).order_by(OP.fecha, LN.id)
    if desde is not None:
        query = query.where(OP.fecha >= desde)
    if hasta is not None:
        query = query.where(OP.fecha <= hasta)
    if items is not None:
        query = query.where(LN.item_id.in_(sorted({int(i) for i in items})))
    if aplicar:
        query = query.with_for_update(of=LN)
    filas = db.execute(query).all()
    costos = costos_unitarios(db, [(ln.item_id, fecha) for ln, fecha in filas if ln.item_id is not None])
    # L19: every product of each document involved (not only the selected lines) tells which combos come broken down.
    operaciones = sorted({ln.operacion_id for ln, _ in filas})
    por_operacion: dict[int, list[Optional[int]]] = {op: [] for op in operaciones}
    if operaciones:
        for operacion_id, item_id in db.execute(
            select(LN.operacion_id, LN.item_id).where(LN.operacion_id.in_(operaciones))
        ):
            por_operacion[operacion_id].append(item_id)
    desglosados = combos_desglosados(db, por_operacion)
    cambios = []
    for ln, fecha in filas:
        if ln.item_id is None or ln.item_id in desglosados[ln.operacion_id]:
            despues = CERO
        else:
            despues = precio_costo(costos.get((ln.item_id, fecha)), ln.cantidad)
        if Decimal(ln.precio_costo) != despues:
            cambios.append(
                Recosteo(
                    ln.id,
                    fecha,
                    ln.item_id,
                    Decimal(ln.cantidad),
                    Decimal(ln.precio),
                    Decimal(ln.precio_costo),
                    despues,
                )
            )
    if not aplicar:
        return cambios
    try:
        if respaldo is not None:
            respaldo(cambios)
        por_id = {ln.id: ln for ln, _ in filas}
        for cambio in cambios:
            por_id[cambio.linea_id].precio_costo = cambio.despues
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        if commit:
            db.rollback()
        raise
    return cambios
