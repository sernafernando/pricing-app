"""After a costo SI recompute: re-cost the legacy ML metrics (`ml_ventas_metricas`) of the product from that date on.

Owner L15: "si alguien edita por alguna razón el sell in de cualquier factura o loyalty o lo que fuera, se tienen que
recalcular todos los costos posteriores y los promedios claramente". The metrics crons only re-read their window (10
minutes, today, 7 and 30 days); this callback re-costs every stored ML sale of the product, and of every combo that
contains it (S11), with a sale date on or after the first changed date, with no window. The orchestrator decided it
runs inline as ONE set-based statement (no queue, no cron, no migration), in the recompute's transaction:

1. the rows whose cost changes, with the cost in force on their sale date (`lote.sql_en_fecha`, the crons' rule:
   pesos at the sale date's rate; an unknown cost (no cost, or a USD cost without a rate) is NULL, never 0 (interface
   §7), and so are its ganancia and markup, its cost-percentage offset consumptions stay as they were, and it is logged;
2. their previous values (and the offset consumptions that move) into `costo_si_backups`, motivo 'ml_ventas_metricas';
3. the new cost, ganancia and markup (the formulas of `utils.ml_metrics_calculator`); price, commission, shipping and
   `monto_limpio` untouched (D4);
4. the `porcentaje_costo` offset consumptions of those sales (the only offset type that depends on the cost), rounded
   to the cent as their columns store them, and their group / individual summaries, by the same difference.

A second call with nothing changed matches no row: it writes nothing, no backup either.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Integer, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.services.costo_si import lote
from app.services.costo_si.despues import registrar
from app.services.ml_ventas_metricas_costo import sin_costo

MOTIVO = "ml_ventas_metricas"

# markup_porcentaje is NUMERIC(10, 2): the calculator clamps it to this range
_MARKUP_MAX = "99999999.99"

_CONSUMOS = """
    SELECT '{tabla}' AS tabla, c.id, c.{clave} AS clave, c.monto_offset_aplicado AS ars_viejo,
           c.monto_offset_usd AS usd_viejo,
           round(v.total * COALESCE(o.porcentaje, 0)::numeric / 100, 2) AS ars,
           CASE WHEN c.cotizacion_dolar > 0
                THEN round(v.total * COALESCE(o.porcentaje, 0)::numeric / 100 / c.cotizacion_dolar, 2) ELSE 0 END AS usd
    FROM {tabla} c
    JOIN v ON v.id_operacion = c.id_operacion
    JOIN offsets_ganancia o ON o.id = c.offset_id
    WHERE c.tipo_venta = 'ml' AND o.tipo_offset = 'porcentaje_costo' AND v.total IS NOT NULL"""

_RESUMEN = """
    UPDATE {tabla} r
    SET total_monto_ars = COALESCE(r.total_monto_ars, 0) + d.ars, total_monto_usd = COALESCE(r.total_monto_usd, 0) + d.usd
    FROM (SELECT clave, SUM(ars - ars_viejo) AS ars, SUM(usd - COALESCE(usd_viejo, 0)) AS usd
          FROM cv WHERE tabla = '{consumo}' GROUP BY clave) d
    WHERE r.{clave} = d.clave
    RETURNING r.id"""

_SQL = text(
    f"""
WITH v AS (
    SELECT m.id, m.id_operacion, m.costo_unitario_sin_iva AS unitario_viejo, m.costo_total_sin_iva AS total_viejo,
           m.ganancia AS ganancia_vieja, m.markup_porcentaje AS markup_viejo, m.item_id, m.fecha_venta::date AS fecha,
           cs.costo_si_ars AS unitario,
           cs.costo_si_ars * m.cantidad AS total
    FROM ml_ventas_metricas m
    LEFT JOIN LATERAL ({lote.sql_en_fecha("m.item_id", "m.fecha_venta::date")}) cs ON true
    WHERE m.item_id = ANY(:items)
      AND m.fecha_venta::date >= :desde
      AND m.costo_unitario_sin_iva IS DISTINCT FROM round(cs.costo_si_ars, 6)
),
cv AS (
    {_CONSUMOS.format(tabla="offset_grupo_consumo", clave="grupo_id")}
    UNION ALL
    {_CONSUMOS.format(tabla="offset_individual_consumo", clave="offset_id")}
),
bk AS (
    INSERT INTO costo_si_backups (item_id, desde, motivo, pasos)
    SELECT :item_id, :desde, '{MOTIVO}', jsonb_build_object(
        'ventas', (SELECT jsonb_agg(jsonb_build_object(
                       'id', v.id, 'id_operacion', v.id_operacion, 'costo_unitario_sin_iva', v.unitario_viejo,
                       'costo_total_sin_iva', v.total_viejo, 'ganancia', v.ganancia_vieja,
                       'markup_porcentaje', v.markup_viejo) ORDER BY v.id) FROM v),
        'consumos', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                       'tabla', cv.tabla, 'id', cv.id, 'monto_offset_aplicado', cv.ars_viejo,
                       'monto_offset_usd', cv.usd_viejo) ORDER BY cv.tabla, cv.id) FROM cv), '[]'::jsonb))
    WHERE EXISTS (SELECT 1 FROM v)
    RETURNING id
),
u AS (
    UPDATE ml_ventas_metricas m
    SET costo_unitario_sin_iva = v.unitario,
        costo_total_sin_iva = v.total,
        ganancia = m.monto_limpio - v.total,
        markup_porcentaje = CASE WHEN v.total IS NULL THEN NULL WHEN v.total > 0
            THEN LEAST(GREATEST((m.monto_limpio / v.total - 1) * 100, -{_MARKUP_MAX}), {_MARKUP_MAX}) ELSE 0 END,
        updated_at = now()
    FROM v
    WHERE m.id = v.id
    RETURNING m.id
),
gc AS (
    UPDATE offset_grupo_consumo c SET monto_offset_aplicado = cv.ars, monto_offset_usd = cv.usd
    FROM cv WHERE cv.tabla = 'offset_grupo_consumo' AND c.id = cv.id
    RETURNING c.id
),
ic AS (
    UPDATE offset_individual_consumo c SET monto_offset_aplicado = cv.ars, monto_offset_usd = cv.usd
    FROM cv WHERE cv.tabla = 'offset_individual_consumo' AND c.id = cv.id
    RETURNING c.id
),
gr AS ({_RESUMEN.format(tabla="offset_grupo_resumen", consumo="offset_grupo_consumo", clave="grupo_id")}),
ir AS ({_RESUMEN.format(tabla="offset_individual_resumen", consumo="offset_individual_consumo", clave="offset_id")})
SELECT v.item_id, v.fecha FROM v WHERE v.unitario IS NULL ORDER BY v.id
"""
).bindparams(bindparam("items", type_=ARRAY(Integer)))


def recostear(db: Session, item_id: int, desde: date) -> None:
    """Re-cost the stored ML sales of `item_id` and of the combos that contain it, sold on or after `desde`; the
    statement returns the sales left without a cost, which are logged."""
    items = [item_id, *lote.combos_con(db, [item_id]).get(item_id, [])]
    for sin_dato in db.execute(_SQL, {"items": items, "desde": desde, "item_id": item_id}):
        sin_costo(sin_dato.item_id, sin_dato.fecha)


registrar("metricas_ml_legacy", recostear)
