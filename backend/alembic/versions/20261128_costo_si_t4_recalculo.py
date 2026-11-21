"""Costo SI T4: one-shot history recalc fired on deploy (owner L17: "cuando deployamos se debería disparar").

Revision ID: 20261128_costo_si_t4_recalculo
Revises: 20261127_ml_costo_si
Create Date: 2026-11-21

Data only, seconds: it snapshots and enqueues, the existing drain (`sell.drain` -> `costo_si.queue.drenar` ->
`despues.despachar`) does the work, one product per transaction, every area callback backing up its own rows first.
Plan handoffs/sell-in-costo-si-t4-plan.md §1; orchestrator G3 (option A) and G4.

1. Snapshot (G4): a full copy of every table the recalc re-costs, `costo_si_t4_respaldo_<table>`, taken before
   anything changes. `IF NOT EXISTS`: a second run keeps the first (pre-T4) copy.
2. Queue the scope for a whole-history recompute: the products of `costo_si.queue.productos_vigentes` (SQL frozen
   here as of this revision), `desde` NULL and a fresh retry budget. Rows already queued outside the scope stay.
3. Option A (plan §1.3): back up every queued-for-whole-history product's stored steps in `costo_si_backups`
   (motivo `t4 reset`) and delete them, so the recompute always sees a change and every callback re-costs from the
   product's first step, even when the stored history is already the current one.
4. Marker `costo_si_t4_encolado_at` in `configuracion` (first run only) and `pg_notify('sell_dirty')`.

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
)

# `costo_si.queue._VIGENTES_SQL` as of this revision
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
"""


def upgrade() -> None:
    for tabla in RESPALDADAS:
        op.execute(f"CREATE TABLE IF NOT EXISTS costo_si_t4_respaldo_{tabla} AS TABLE {tabla}")
    op.execute(f"""
        INSERT INTO costo_si_dirty (item_id, desde)
        SELECT item_id, NULL FROM ({_ALCANCE_SQL}) alcance
        ON CONFLICT (item_id) DO UPDATE SET desde = NULL, enqueued_at = now(), attempts = 0, last_error = NULL
    """)
    op.execute("""
        INSERT INTO costo_si_backups (item_id, desde, motivo, pasos)
        SELECT p.item_id, min(p.fecha), 't4 reset', jsonb_agg(to_jsonb(p) ORDER BY p.orden)
        FROM costo_si_pasos p JOIN costo_si_dirty d ON d.item_id = p.item_id AND d.desde IS NULL
        GROUP BY p.item_id
    """)
    op.execute("""
        DELETE FROM costo_si_pasos p USING costo_si_dirty d WHERE d.item_id = p.item_id AND d.desde IS NULL
    """)
    op.execute("""
        INSERT INTO configuracion (clave, valor, descripcion, tipo, fecha_modificacion)
        VALUES ('costo_si_t4_encolado_at', now()::text, 'Costo SI T4 history recalc queued (one-shot)', 'string', now())
        ON CONFLICT (clave) DO NOTHING
    """)
    op.execute("SELECT pg_notify('sell_dirty', '')")


def downgrade() -> None:
    pass
