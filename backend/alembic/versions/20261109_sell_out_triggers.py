"""sell out: row triggers that queue campaigns for changes outside the app's writers

Revision ID: 20261109_sell_out_triggers
Revises: 20261108_sell_out_consumos
Create Date: 2026-10-21

Sell in / sell out, T7 slice S4. `sell_out_dirty` is fed by the app's own
writers since S3 (`sell.drain` fan-out, the campaigns API, BNA); these row
triggers cover what never passes through them (owner scope, 2026-10-21):

- `offset_grupo_filtros`: a filter added, changed or removed through the
  offsets API moves the reach of the active campaigns of its group(s);
- `productos_erp`: a new or deleted product, or a change of `marca`,
  `categoria` or `subcategoria_id`, moves the reach of the active campaigns
  reaching the old or new product; a change of `iva` alone queues only the
  campaigns whose amount depends on it;
- `ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`: a `cust_id` or
  `costo_total` change (not in `sell_dirty`'s watched columns).

Each trigger queues campaign ids with the queue's upsert and notifies
`sell_out_dirty`; none does allocation work, and every UPDATE trigger has a
WHEN ... IS DISTINCT FROM so a rewrite with the same values fires nothing.
The SQL is a frozen copy of `app/services/sell_out/triggers.py`'s
`UPGRADE_SQL`/`DOWNGRADE_SQL` (that module is the live definition).

No backfill: a campaign whose reach moved before this revision is rebuilt by
its next queue event.

LOCK NOTE: CREATE TRIGGER takes a SHARE ROW EXCLUSIVE lock on
`offset_grupo_filtros`, `productos_erp`, `ventas_fuera_ml_metricas` and
`ventas_tienda_nube_metricas` for an instant (no rewrite, no scan).
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261109_sell_out_triggers"
down_revision: Union[str, None] = "20261108_sell_out_consumos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHANNEL = "sell_out_dirty"

# Inserts the `campana_id`s selected by `{select}` (sorted, like `queue.enqueue`) and notifies once.
_ENQUEUE = f"""
    INSERT INTO sell_out_dirty (campana_id)
    SELECT DISTINCT q.campana_id FROM ({{select}}) AS q
    ORDER BY 1
    ON CONFLICT (campana_id) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;"""

_VENTA_UPDATE = """
CREATE TRIGGER trg_sell_out_{canal}_update
AFTER UPDATE OF cust_id, costo_total ON {tabla}
FOR EACH ROW WHEN ((OLD.cust_id, OLD.costo_total) IS DISTINCT FROM (NEW.cust_id, NEW.costo_total))
EXECUTE FUNCTION sell_out_enqueue_venta('{canal}')
"""

UPGRADE_SQL: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_out_alcance(p_item INTEGER, p_marca TEXT, p_categoria TEXT, p_subcategoria INTEGER)
RETURNS TABLE (campana_id BIGINT, fecha_desde DATE, fecha_hasta DATE) AS $fn$
    SELECT DISTINCT c.id, c.fecha_desde, c.fecha_hasta
    FROM sell_out_campanas AS c
    JOIN sell_out_campana_grupos AS g ON g.campana_id = c.id
    JOIN offset_grupo_filtros AS f ON f.grupo_id = g.grupo_id
    WHERE c.estado = 'activa'
      AND (COALESCE(f.marca, '') <> '' OR COALESCE(f.categoria, '') <> ''
           OR COALESCE(f.subcategoria_id, 0) <> 0 OR COALESCE(f.item_id, 0) <> 0)
      AND (COALESCE(f.marca, '') = '' OR f.marca = p_marca)
      AND (COALESCE(f.categoria, '') = '' OR f.categoria = p_categoria)
      AND (COALESCE(f.subcategoria_id, 0) = 0 OR f.subcategoria_id = p_subcategoria)
      AND (COALESCE(f.item_id, 0) = 0 OR f.item_id = p_item)
$fn$ LANGUAGE sql STABLE
""",
    f"""
CREATE OR REPLACE FUNCTION sell_out_enqueue_filtro() RETURNS TRIGGER AS $trg$
DECLARE
    grupos INTEGER[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        grupos := ARRAY[NEW.grupo_id];
    ELSIF TG_OP = 'DELETE' THEN
        grupos := ARRAY[OLD.grupo_id];
    ELSE
        grupos := ARRAY[OLD.grupo_id, NEW.grupo_id];
    END IF;
{
        _ENQUEUE.format(
            select='''
        SELECT g.campana_id FROM sell_out_campana_grupos AS g
        JOIN sell_out_campanas AS c ON c.id = g.campana_id
        WHERE c.estado = 'activa' AND g.grupo_id = ANY(grupos)'''
        )
    }
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_out_enqueue_producto() RETURNS TRIGGER AS $trg$
DECLARE
    solo_iva BOOLEAN := TG_OP = 'UPDATE'
        AND (OLD.marca, OLD.categoria, OLD.subcategoria_id) IS NOT DISTINCT FROM (NEW.marca, NEW.categoria, NEW.subcategoria_id);
BEGIN
{
        _ENQUEUE.format(
            select='''
        SELECT a.campana_id FROM (
            SELECT * FROM sell_out_alcance(OLD.item_id, OLD.marca, OLD.categoria, OLD.subcategoria_id)
            WHERE TG_OP <> 'INSERT'
            UNION
            SELECT * FROM sell_out_alcance(NEW.item_id, NEW.marca, NEW.categoria, NEW.subcategoria_id)
            WHERE TG_OP <> 'DELETE'
        ) AS a
        JOIN sell_out_campanas AS c ON c.id = a.campana_id
        WHERE NOT solo_iva OR c.monto_incluye_iva OR (c.tipo = 'porcentaje' AND c.base_porcentaje = 'precio_neto')'''
        )
    }
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_out_enqueue_venta() RETURNS TRIGGER AS $trg$
DECLARE
    cliente BOOLEAN := OLD.cust_id IS DISTINCT FROM NEW.cust_id;
BEGIN
{
        _ENQUEUE.format(
            select='''
        SELECT x.campana_id FROM (
            SELECT s.campana_id, CAST(NULL AS DATE) AS dia, CAST(NULL AS DATE) AS desde, CAST(NULL AS DATE) AS hasta
            FROM sell_out_consumos AS s
            WHERE s.canal = TG_ARGV[0] AND s.venta_ref IN (OLD.it_transaction, NEW.it_transaction)
            UNION ALL
            SELECT a.campana_id, v.dia, a.fecha_desde, a.fecha_hasta
            FROM (VALUES (OLD.item_id, date(timezone('UTC', OLD.fecha_venta))),
                         (NEW.item_id, date(timezone('UTC', NEW.fecha_venta)))) AS v(item_id, dia)
            JOIN productos_erp AS p ON p.item_id = v.item_id
            CROSS JOIN LATERAL sell_out_alcance(p.item_id, p.marca, p.categoria, p.subcategoria_id) AS a
        ) AS x
        JOIN sell_out_campanas AS c ON c.id = x.campana_id
        WHERE (x.dia IS NULL OR x.dia <= x.hasta)
          AND (cliente OR ((x.dia IS NULL OR x.dia >= x.desde)
                           AND c.tipo = 'porcentaje' AND c.base_porcentaje = 'costo'))'''
        )
    }
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_out_filtros_insert_delete
AFTER INSERT OR DELETE ON offset_grupo_filtros
FOR EACH ROW EXECUTE FUNCTION sell_out_enqueue_filtro()
""",
    """
CREATE TRIGGER trg_sell_out_filtros_update
AFTER UPDATE OF grupo_id, marca, categoria, subcategoria_id, item_id ON offset_grupo_filtros
FOR EACH ROW WHEN (
    (OLD.grupo_id, OLD.marca, OLD.categoria, OLD.subcategoria_id, OLD.item_id)
    IS DISTINCT FROM (NEW.grupo_id, NEW.marca, NEW.categoria, NEW.subcategoria_id, NEW.item_id)
)
EXECUTE FUNCTION sell_out_enqueue_filtro()
""",
    """
CREATE TRIGGER trg_sell_out_productos_insert_delete
AFTER INSERT OR DELETE ON productos_erp
FOR EACH ROW EXECUTE FUNCTION sell_out_enqueue_producto()
""",
    """
CREATE TRIGGER trg_sell_out_productos_update
AFTER UPDATE OF marca, categoria, subcategoria_id, iva ON productos_erp
FOR EACH ROW WHEN (
    (OLD.marca, OLD.categoria, OLD.subcategoria_id, OLD.iva)
    IS DISTINCT FROM (NEW.marca, NEW.categoria, NEW.subcategoria_id, NEW.iva)
)
EXECUTE FUNCTION sell_out_enqueue_producto()
""",
    _VENTA_UPDATE.format(canal="fuera", tabla="ventas_fuera_ml_metricas"),
    _VENTA_UPDATE.format(canal="tn", tabla="ventas_tienda_nube_metricas"),
]

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_out_tn_update ON ventas_tienda_nube_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_out_fuera_update ON ventas_fuera_ml_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_out_productos_update ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_out_productos_insert_delete ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_out_filtros_update ON offset_grupo_filtros",
    "DROP TRIGGER IF EXISTS trg_sell_out_filtros_insert_delete ON offset_grupo_filtros",
    "DROP FUNCTION IF EXISTS sell_out_enqueue_venta()",
    "DROP FUNCTION IF EXISTS sell_out_enqueue_producto()",
    "DROP FUNCTION IF EXISTS sell_out_enqueue_filtro()",
    "DROP FUNCTION IF EXISTS sell_out_alcance(INTEGER, TEXT, TEXT, INTEGER)",
]


def _is_postgres() -> bool:
    # plpgsql triggers and pg_notify: Postgres only (SQLite test schemas skip them).
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        for statement in UPGRADE_SQL:
            op.execute(statement)


def downgrade() -> None:
    if _is_postgres():
        for statement in DOWNGRADE_SQL:
            op.execute(statement)
