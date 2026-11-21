"""Shared by the costo SI follow-ups `costo_si.despues.ventas_fuera_ml_metricas` and
`costo_si.despues.ventas_tienda_nube_metricas` (one module per registered name). After a costo SI recompute: re-cost the stored ventas fuera ML and Tienda Nube metrics of the product from that date
on (owner L15: "se tienen que recalcular todos los costos posteriores"; sell-in-costo-si T3 PR 9).

The metrics crons only re-read their window; this callback re-costs the stored rows (`ventas_fuera_ml_metricas`,
`ventas_tienda_nube_metricas`) of GBP sales dated on or after the first changed date whose line is the product or a
combo that contains it (`lote.combos_con`, S11), or belongs to a GBP group holding one, with no window. Other products
of the same invoice keep their stored cost (a manual one included). It runs inline in the recompute's transaction (like
the legacy ML metrics of T3 PR 8, `metricas_ml_legacy`):

1. the new cost of those sales comes from the cron's own query (`obtener_*` restricted to their transactions), so
   combos, association groups, L19 breakdowns, Costo D, product currency, the sale date's rate and an unknown cost
   (NULL, never 0, interface §7, logged by the query) follow exactly the cron's rule;
2. then ONE set-based statement per table: the rows whose cost, currency or rate differ from what is stored have their
   previous values backed up first in `costo_si_backups` (motivo = the table name), then their cost, currency, rate,
   ganancia and markup are rewritten with the cron's formulas; the sale itself (amounts, commission) is untouched
   (D4).

A second call with nothing changed matches no row: it writes nothing, no backup either.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Callable, Sequence

from sqlalchemy import BigInteger, Numeric, String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.scripts import agregar_metricas_fuera_ml as cron_fuera
from app.scripts import agregar_metricas_tienda_nube as cron_tn
from app.services import ventas_gbp_costo_si as costo_si_gbp
from app.services.costo_si import lote

FUERA, TN = "ventas_fuera_ml_metricas", "ventas_tienda_nube_metricas"
_HASTA_SIEMPRE = datetime(9999, 12, 31, 23, 59, 59)

# markup_porcentaje is NUMERIC(10, 2): the crons clamp it to this range
_MARKUP_MAX = "99999999.99"

# The crons' ganancia and markup (`process_and_insert`), on the stored sale and the new cost `v.total`.
_FORMULAS = {
    FUERA: (
        "m.monto_total - v.total",
        f"CASE WHEN v.total > 0 THEN LEAST(GREATEST((m.monto_total / v.total - 1) * 100, -{_MARKUP_MAX}),"
        f" {_MARKUP_MAX}) END",
    ),
    TN: (
        "m.monto_total - v.total - m.comision_monto",
        "CASE WHEN v.total + m.comision_monto > 0 AND m.signo > 0 THEN LEAST(GREATEST((m.monto_total /"
        f" (v.total + m.comision_monto) - 1) * 100, -{_MARKUP_MAX}), {_MARKUP_MAX}) END",
    ),
}

# The stored lines whose cost depends on the product: its own lines (or a combo of it), and every line of a GBP group
# (the crons' group: `it_isassociationgroup` lines of one transaction) holding one. Other products of the same invoice
# keep their stored cost, a manual one included.
_LINEAS = """
SELECT m.ct_transaction, m.it_transaction FROM {tabla} m
JOIN tb_item_transactions tit ON tit.it_transaction = m.it_transaction
WHERE m.fecha_venta >= :desde
  AND ({item} = ANY(:items)
       OR (tit.it_isassociationgroup IS TRUE
           AND EXISTS (SELECT 1 FROM tb_item_transactions g
                       WHERE g.ct_transaction = tit.ct_transaction AND g.it_isassociationgroup IS TRUE
                         AND {item_g} = ANY(:items))))"""

_RECOSTEO = """
WITH n AS (
    SELECT * FROM unnest(:its, :unitarios, :totales, :monedas, :tcs) AS n(it, unitario, total, moneda, tc)
),
v AS (
    SELECT m.id, m.it_transaction, m.costo_unitario AS unitario_viejo, m.costo_total AS total_viejo,
           m.moneda_costo AS moneda_vieja, m.cotizacion_dolar AS tc_viejo, m.ganancia AS ganancia_vieja,
           m.markup_porcentaje AS markup_viejo, n.unitario, n.total, n.moneda, NULLIF(n.tc, 0) AS tc
    FROM {tabla} m
    JOIN n ON n.it = m.it_transaction
    WHERE m.costo_unitario IS DISTINCT FROM round(n.unitario, 6)
       OR m.costo_total IS DISTINCT FROM round(n.total, 2)
       OR m.moneda_costo IS DISTINCT FROM n.moneda
       OR m.cotizacion_dolar IS DISTINCT FROM round(NULLIF(n.tc, 0), 4)
),
bk AS (
    INSERT INTO costo_si_backups (item_id, desde, motivo, pasos)
    SELECT :item_id, :desde, '{tabla}', (SELECT jsonb_agg(jsonb_build_object(
               'id', v.id, 'it_transaction', v.it_transaction, 'costo_unitario', v.unitario_viejo,
               'costo_total', v.total_viejo, 'moneda_costo', v.moneda_vieja, 'cotizacion_dolar', v.tc_viejo,
               'ganancia', v.ganancia_vieja, 'markup_porcentaje', v.markup_viejo) ORDER BY v.id) FROM v)
    WHERE EXISTS (SELECT 1 FROM v)
    RETURNING id
)
UPDATE {tabla} m
SET costo_unitario = v.unitario, costo_total = v.total, moneda_costo = v.moneda, cotizacion_dolar = v.tc,
    ganancia = {ganancia}, markup_porcentaje = {markup}
FROM v
WHERE m.id = v.id"""


def _sql(tabla: str):
    ganancia, markup = _FORMULAS[tabla]
    return text(_RECOSTEO.format(tabla=tabla, ganancia=ganancia, markup=markup)).bindparams(
        bindparam("its", type_=ARRAY(BigInteger)),
        bindparam("unitarios", type_=ARRAY(Numeric)),
        bindparam("totales", type_=ARRAY(Numeric)),
        bindparam("monedas", type_=ARRAY(String)),
        bindparam("tcs", type_=ARRAY(Numeric)),
    )


_SQL = {tabla: _sql(tabla) for tabla in (FUERA, TN)}
_SQL_LINEAS = {
    tabla: text(
        _LINEAS.format(
            tabla=tabla, item=costo_si_gbp.GBP_ITEM.format(t="tit"), item_g=costo_si_gbp.GBP_ITEM.format(t="g")
        )
    ).bindparams(bindparam("items", type_=ARRAY(BigInteger)))
    for tabla in (FUERA, TN)
}


def _recostear(db: Session, item_id: int, desde: date, *, tabla: str, obtener: Callable[..., Sequence[Any]]) -> None:
    items = [item_id, *lote.combos_con(db, [item_id]).get(item_id, [])]
    lineas = db.execute(_SQL_LINEAS[tabla], {"desde": desde, "items": items}).all()
    if not lineas:
        return
    cts = sorted({ln.ct_transaction for ln in lineas})
    its = {ln.it_transaction for ln in lineas}
    nuevas = {
        fila.it_transaction: fila
        for fila in obtener(db, datetime.combine(desde, time.min), _HASTA_SIEMPRE, cts)
        if fila.it_transaction in its
    }
    if not nuevas:
        return
    filas = list(nuevas.values())
    db.execute(
        _SQL[tabla],
        {
            "its": [f.it_transaction for f in filas],
            "unitarios": [f.costo_unitario for f in filas],
            "totales": [f.costo_total for f in filas],
            "monedas": [f.moneda_costo for f in filas],
            "tcs": [f.cotizacion_dolar for f in filas],
            "item_id": item_id,
            "desde": desde,
        },
    )


def recostear_fuera(db: Session, item_id: int, desde: date) -> None:
    """Re-cost the stored ventas fuera ML metrics of `item_id` (and its combos) sold on or after `desde`."""
    _recostear(db, item_id, desde, tabla=FUERA, obtener=cron_fuera.obtener_ventas_fuera_ml)


def recostear_tn(db: Session, item_id: int, desde: date) -> None:
    """Re-cost the stored Tienda Nube metrics of `item_id` (and its combos) sold on or after `desde`."""
    _recostear(db, item_id, desde, tabla=TN, obtener=cron_tn.obtener_ventas_tienda_nube)
