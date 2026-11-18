"""The cost of a PDF line from the ERP cost list (vpf-costo-d-erp, owner L3 fix B: "calcular desde la lista de costos
del ERP"), exactly as Ventas por Fuera (anterior) computes it (`app/scripts/agregar_metricas_fuera_ml.py`):

- unit cost = `iclh_price` of the item's last `tb_item_cost_list_history` row of list 1 (`coslis_id = 1`) created
  on or before the sale date (`iclh_cd <= fecha`, highest `iclh_id`); none -> 0;
- a cost in pesos (`curr_id` 1 or NULL) as is, any other currency x the USD rate of the sale date: `tipo_cambio`
  (USD `venta`, the latest `fecha <= fecha`), else `tb_cur_exch_history` (latest `ceh_cd <= fecha`), else 1.

The line's `precio_costo` = unit cost x `cantidad`, the Precio Costo WITHOUT the 6.5%: every screen applies Costo D
(x `COSTO_D_FACTOR`) on top, as before. The PDF's "Precio Costo" is not a cost any more; it stays in
`precio_costo_pdf` only as a reference. A line without product (`item_id` NULL) costs 0, like (anterior).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import Date, Integer

from app.models.venta_fuera_pdf import VentaFueraLineaOverride, VentaFueraOperacion, VentaFueraOperacionLinea

CERO = Decimal("0")
CENTAVO = Decimal("0.01")

# One row per (item_id, fecha): the unit cost in pesos, the rules of the module docstring. The sale date compares as
# midnight against the ERP timestamps, as (anterior) compares GBP's `ct_date` (always midnight).
_COSTOS_SQL = text(
    """
    SELECT x.item_id, x.fecha,
           COALESCE(h.iclh_price, 0)
           * CASE WHEN COALESCE(h.curr_id, 1) = 1 THEN 1 ELSE COALESCE(fx.cotizacion, 1) END AS costo_unitario
    FROM unnest(:items, :fechas) AS x(item_id, fecha)
    LEFT JOIN LATERAL (
        SELECT iclh_price, curr_id
        FROM tb_item_cost_list_history
        WHERE item_id = x.item_id AND coslis_id = 1 AND iclh_cd <= x.fecha
        ORDER BY iclh_id DESC
        LIMIT 1
    ) h ON true
    LEFT JOIN LATERAL (
        SELECT COALESCE(
            (SELECT tc.venta FROM tipo_cambio tc
             WHERE tc.moneda = 'USD' AND tc.fecha <= x.fecha ORDER BY tc.fecha DESC LIMIT 1)::numeric,
            (SELECT ceh_exchange FROM tb_cur_exch_history WHERE ceh_cd <= x.fecha ORDER BY ceh_cd DESC LIMIT 1)
        ) AS cotizacion
    ) fx ON true
    """
).bindparams(bindparam("items", type_=ARRAY(Integer)), bindparam("fechas", type_=ARRAY(Date)))


def costos_unitarios(db: Session, pares: Iterable[tuple[int, date]]) -> dict[tuple[int, date], Decimal]:
    """The ERP unit cost in pesos of each `(item_id, fecha)`, in one query."""
    unicos = sorted(set(pares))
    if not unicos:
        return {}
    filas = db.execute(_COSTOS_SQL, {"items": [p[0] for p in unicos], "fechas": [p[1] for p in unicos]})
    return {(f.item_id, f.fecha): Decimal(f.costo_unitario) for f in filas}


def precio_costo(costo_unitario: Optional[Decimal], cantidad: Decimal) -> Decimal:
    """The line's Precio Costo: unit cost x `cantidad`, to the cent (a credit note's negative quantity stays)."""
    if costo_unitario is None:
        return CERO
    return (Decimal(costo_unitario) * Decimal(cantidad)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def precio_costo_erp(db: Session, item_id: Optional[int], fecha: date, cantidad: Decimal) -> Decimal:
    """The Precio Costo of one line of product `item_id` sold on `fecha`; 0 without product."""
    if item_id is None:
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
    db: Session, desde: Optional[date] = None, hasta: Optional[date] = None, aplicar: bool = False
) -> list[Recosteo]:
    """The stored lines (sale date in `[desde, hasta]`, open ends allowed) whose `precio_costo` differs from the ERP
    cost list's, skipping the lines with a manual cost applied (`ventas_fuera_linea_overrides.costo_unitario`).
    `aplicar=False` (default) only reports. `aplicar=True` writes them and commits: T4's trigger on the lines queues
    each one in `sell_dirty`, so offsets and sell in / sell out are recomputed (owner L3: ask before doing it)."""
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
    filas = db.execute(query).all()
    costos = costos_unitarios(db, [(ln.item_id, fecha) for ln, fecha in filas if ln.item_id is not None])
    cambios = []
    for ln, fecha in filas:
        despues = precio_costo(costos.get((ln.item_id, fecha)), ln.cantidad) if ln.item_id is not None else CERO
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
            if aplicar:
                ln.precio_costo = despues
    if aplicar:
        db.commit()
    return cambios
