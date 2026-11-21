"""Costo SI T4: one-shot history recalc fired on deploy (owner L17: "cuando deployamos se debería disparar").

Revision ID: 20261128_costo_si_t4_recalculo
Revises: 20261127_ml_costo_si
Create Date: 2026-11-21

Data only: it snapshots and enqueues, the existing drain (`sell.drain` -> `costo_si.queue.drenar` ->
`despues.despachar`) does the work, one product per transaction, every area callback backing up its own rows first.
Plan handoffs/sell-in-costo-si-t4-plan.md §1; orchestrator G3 (option A) and G4.

1. Snapshot (G4): a full copy of every table the recalc re-costs, `costo_si_t4_respaldo_<table>`, taken before
   anything changes. `IF NOT EXISTS`: a second run keeps the first (pre-T4) copy. The copy is the migration's slow
   part (about 170 MB on prod by 2026-11-21 sizes) and takes that much disk until the snapshots are dropped by hand;
   `alembic.env` keeps them out of autogenerate (`app.core.alembic_autogenerate`).
2. Queue the scope for a whole-history recompute: the products of `costo_si.queue.productos_vigentes` (SQL frozen
   here as of this revision): every product, sell in or not (L21), `desde` NULL and a fresh retry budget. Rows
   already queued outside the scope stay.
3. Option A (plan §1.3, G3), as an invalidation: the stored steps of every product that has them are backed up in
   `costo_si_backups` (motivo `t4 reset`) and the first step of each history gets `fuente_tc = 't4_reset'`, a value
   the engine never writes. The recompute compares `fuente_tc` (`recompute._COLUMNAS`), so it always sees a change
   from the first step and every callback re-costs from the product's first date, even when the history is the
   current one, and also when the engine now computes no history at all (sell in gone, a combo, a sell in without an
   invoice yet: the sales go back to list cost, exactly as without T4; verification F1). The readers of the cost
   (`lote`) read `promedio_usd`, `moneda`, `fecha` and `orden` only, so until the drain reaches a product it keeps
   showing its pre-T4 cost (no list-cost window).
4. Marker `costo_si_t4_encolado_at` in `configuracion` (first run only) and `pg_notify('sell_dirty')`.

Fail-closed note: a product the drain cannot recompute parks after `queue.MAX_ATTEMPTS` (logged `costo_si: product ...
parked`) and keeps its pre-T4 steps and cost. Check after the drain: `SELECT item_id, last_error FROM costo_si_dirty
WHERE attempts >= 5`; fix the cause, then `REENCOLAR_SQL` (`:item`): invalidated again and queued, the drain
re-dispatches from the first step (F2). Gate before deploying: the dry-run reports 0 products not computed.

Rollback: `ROLLBACK_SQL`, in order (verification F3/F4): stop the queue (every queued product: the daily
`encolar_vigentes` re-queues the live ones), restore every re-costed value by id from the snapshots (only the columns
the callbacks write, and only where they differ), the offset resumenes by the difference their consumos are restored
by (later increments stay), the steps from the oldest `t4 reset` backup. Then recompute the D2 sale-cost bonuses of
those products (`sell_in.bonos_costo.recalcular`): `sell_in_bono_consumos` is derived and its snapshot is for audit.
Known limits: a value another job legitimately rewrote after the deploy (a markup after a price change, a ganancia
after a new `monto_limpio`) is set back to its snapshot too, so run the rollback soon after the deploy; consumo rows
`recalcular_consumo_grupos` deleted and re-created since the deploy have new ids and are not restored.

Downgrade: nothing. Undoing a recalc is restoring the snapshots by hand, a deliberate step.
"""

from alembic import op

revision = "20261128_costo_si_t4_recalculo"
down_revision = "20261127_ml_costo_si"
branch_labels = None
depends_on = None

RESPALDADAS = (
    "productos_pricing",
    "ml_order_item_costos",
    "ml_ventas_metricas",
    "offset_grupo_consumo",
    "offset_individual_consumo",
    "offset_grupo_resumen",
    "offset_individual_resumen",
    "ventas_fuera_operacion_lineas",
    "ventas_tienda_nube_metricas",
    "ventas_fuera_ml_metricas",
    "sell_in_bono_consumos",
)

# `costo_si.queue._VIGENTES_SQL` as of this revision: the products with a live reason or stored steps
_ALCANCE_SQL = """
    SELECT DISTINCT item_id FROM costo_si_pasos
    UNION SELECT ci.item_id FROM sell_in_compra_items ci
          JOIN sell_in_compras c ON c.id = ci.compra_id AND c.estado = 'activa'
    UNION SELECT p.item_id FROM sell_in_bonos_marca b JOIN productos_erp p
            ON (b.alcance = 'marca' AND p.marca = b.marca AND (b.categoria IS NULL OR p.categoria = b.categoria))
            OR (b.alcance = 'categoria' AND p.categoria = b.categoria)
          WHERE b.estado = 'activa' AND b.base = 'costo_venta' AND b.tipo IN ('porcentaje', 'por_unidad')
    UNION SELECT bi.item_id FROM sell_in_bono_items bi JOIN sell_in_bonos_marca b ON b.id = bi.bono_id
          WHERE b.estado = 'activa' AND b.base = 'costo_venta' AND b.tipo IN ('porcentaje', 'por_unidad')
    UNION SELECT item_id FROM productos_erp
"""
# The last branch is L21 (owner: "pero costo si tiene que ponderar las facturas por mas que no tengan s8"): a product
# no sell in reaches gets a costo SI from 2026-11-01, so the deploy re-costs every product. Added before this
# revision ever ran on prod.

# The invalidation of a stored history (option A): its first step gets a `fuente_tc` the engine never writes.
INVALIDO = "t4_reset"


# After a parked product's cause is fixed (`:item`): its history invalidated again and queued for its whole history,
# so the drain re-dispatches every callback from its first step.
REENCOLAR_SQL = f"""
    WITH invalidado AS (UPDATE costo_si_pasos SET fuente_tc = '{INVALIDO}' WHERE item_id = :item AND orden = 0
                        RETURNING 1)
    INSERT INTO costo_si_dirty (item_id, desde) VALUES (:item, NULL)
    ON CONFLICT (item_id) DO UPDATE SET desde = NULL, enqueued_at = now(), attempts = 0, last_error = NULL
"""

_MARKUPS = (
    "markup_calculado",
    "markup_rebate",
    "markup_oferta",
    "markup_web_real",
    "markup_pvp",
    "markup_pvp_3_cuotas",
    "markup_pvp_6_cuotas",
    "markup_pvp_9_cuotas",
    "markup_pvp_12_cuotas",
)  # `recalcular_markups_service.MARKUPS_GUARDADOS` as of this revision
# table -> (key, the columns the recalc's callbacks write)
_COSTOS = {
    "ml_ventas_metricas": ("id", ("costo_unitario_sin_iva", "costo_total_sin_iva", "ganancia", "markup_porcentaje")),
    "ml_order_item_costos": (
        "id",
        ("costo_origen", "moneda", "tipo_cambio", "tipo_cambio_fecha", "costo_unitario_ars", "fuente", "costo_fecha"),
    ),
    "ventas_fuera_operacion_lineas": ("id", ("precio_costo",)),
    "ventas_tienda_nube_metricas": (
        "id",
        ("costo_unitario", "costo_total", "moneda_costo", "cotizacion_dolar", "ganancia", "markup_porcentaje"),
    ),
    "ventas_fuera_ml_metricas": (
        "id",
        ("costo_unitario", "costo_total", "moneda_costo", "cotizacion_dolar", "ganancia", "markup_porcentaje"),
    ),
    "productos_pricing": ("item_id", _MARKUPS),
    "offset_grupo_consumo": ("id", ("monto_offset_aplicado", "monto_offset_usd")),
    "offset_individual_consumo": ("id", ("monto_offset_aplicado", "monto_offset_usd")),
}


def _restaurar(tabla: str) -> str:
    clave, columnas = _COSTOS[tabla]
    sets = ", ".join(f"{c} = r.{c}" for c in columnas)
    distinto = " OR ".join(f"t.{c} IS DISTINCT FROM r.{c}" for c in columnas)
    return (
        f"UPDATE {tabla} t SET {sets} FROM costo_si_t4_respaldo_{tabla} r WHERE r.{clave} = t.{clave} AND ({distinto})"
    )


def _resumen(resumen: str, consumo: str, clave: str) -> str:
    """The resumen moves by what its consumos are about to be restored by (as the ML legacy callback moved it)."""
    return f"""
    UPDATE {resumen} r
    SET total_monto_ars = COALESCE(r.total_monto_ars, 0) + d.ars, total_monto_usd = COALESCE(r.total_monto_usd, 0) + d.usd
    FROM (SELECT c.{clave} AS clave,
                 SUM(COALESCE(s.monto_offset_aplicado, 0) - COALESCE(c.monto_offset_aplicado, 0)) AS ars,
                 SUM(COALESCE(s.monto_offset_usd, 0) - COALESCE(c.monto_offset_usd, 0)) AS usd
          FROM {consumo} c JOIN costo_si_t4_respaldo_{consumo} s ON s.id = c.id
          GROUP BY c.{clave}) d
    WHERE r.{clave} = d.clave AND (d.ars <> 0 OR d.usd <> 0)"""


# The documented rollback, in order (see the module docstring).
ROLLBACK_SQL = (
    "DELETE FROM costo_si_dirty",
    _resumen("offset_grupo_resumen", "offset_grupo_consumo", "grupo_id"),
    _resumen("offset_individual_resumen", "offset_individual_consumo", "offset_id"),
    *(_restaurar(tabla) for tabla in _COSTOS),
    """DELETE FROM costo_si_pasos p USING costo_si_backups b WHERE b.item_id = p.item_id AND b.motivo = 't4 reset'""",
    """INSERT INTO costo_si_pasos
    SELECT (jsonb_populate_record(NULL::costo_si_pasos, e.paso)).*
    FROM (SELECT DISTINCT ON (item_id) pasos FROM costo_si_backups WHERE motivo = 't4 reset'
          ORDER BY item_id, created_at, id) b
    CROSS JOIN LATERAL jsonb_array_elements(b.pasos) AS e(paso)""",
)


def upgrade() -> None:
    for tabla in RESPALDADAS:
        op.execute(f"CREATE TABLE IF NOT EXISTS costo_si_t4_respaldo_{tabla} AS TABLE {tabla}")
    op.execute(f"""
        INSERT INTO costo_si_dirty (item_id, desde)
        SELECT item_id, NULL FROM ({_ALCANCE_SQL}) alcance
        ON CONFLICT (item_id) DO UPDATE SET desde = NULL, enqueued_at = now(), attempts = 0, last_error = NULL
    """)
    op.execute(f"""
        INSERT INTO costo_si_backups (item_id, desde, motivo, pasos)
        SELECT p.item_id, min(p.fecha), 't4 reset', jsonb_agg(to_jsonb(p) ORDER BY p.orden)
        FROM costo_si_pasos p
        WHERE NOT EXISTS (SELECT 1 FROM costo_si_pasos i
                          WHERE i.item_id = p.item_id AND i.orden = 0 AND i.fuente_tc = '{INVALIDO}')
        GROUP BY p.item_id
    """)
    op.execute(f"UPDATE costo_si_pasos SET fuente_tc = '{INVALIDO}' WHERE orden = 0")
    op.execute("""
        INSERT INTO configuracion (clave, valor, descripcion, tipo, fecha_modificacion)
        VALUES ('costo_si_t4_encolado_at', now()::text, 'Costo SI T4 history recalc queued (one-shot)', 'string', now())
        ON CONFLICT (clave) DO NOTHING
    """)
    op.execute("SELECT pg_notify('sell_dirty', '')")


def downgrade() -> None:
    pass
