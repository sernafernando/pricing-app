"""Row triggers that feed `sell_out_dirty` (sell-in-sell-out T7 S4): the changes
that move a campaign's allocation but never pass through the app's own writers
(`queue`: `sell.drain` fan-out, the campaigns API, BNA). Each one queues the
affected campaigns and `pg_notify('sell_out_dirty')` in the transaction of the
change, with the queue's upsert (`ON CONFLICT DO UPDATE`, attempts reset), and
does NO allocation work: `sell_out.drain` rebuilds them.

- `offset_grupo_filtros` (the offsets API group filters): an INSERT or DELETE,
  or an UPDATE that changes `grupo_id`, `marca`, `categoria`, `subcategoria_id`
  or `item_id`, queues the ACTIVE campaigns of the old and new group (a group
  linked to a campaign cannot be deleted: RESTRICT FK).
- `productos_erp`: an INSERT or DELETE, or an UPDATE of `marca`, `categoria` or
  `subcategoria_id`, queues the active campaigns reaching the old or the new
  product; an UPDATE of `iva` alone queues only the ones whose amount depends
  on it (`monto_incluye_iva`, or a percentage on `precio_neto`, whose ML base
  carries VAT; `asignacion._base`).
- `ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`, an UPDATE of the
  columns the sell-out reads that `sell_dirty` does not watch
  (`sell.queue.ALLOCATION_COLUMNS`):
  - `cust_id`: it decides which earlier sale a return reverses
    (`costing.resolver_objetivos`), and that return may fall in any campaign
    ending on or after the sale; it queues the campaigns holding the line plus
    the active ones reaching its product with `fecha_hasta` >= its UTC date;
  - `costo_total` (the per-unit cost base, `alcance.ventas`): it queues only
    the percentage campaigns on `costo` holding the line or reaching its
    product and covering its UTC date.
  Both rows (old and new) are looked up. Every other change of a sale already
  reaches `sell_dirty` and the drain's fan-out.

Every UPDATE trigger has a `WHEN ... IS DISTINCT FROM`, so the ERP sync
rewriting a row with the same values fires nothing. A campaign that is not
`activa` holds no rows (`asignacion.recalcular`) and is never queued by reach.

`sell_out_alcance(item, marca, categoria, subcategoria)` mirrors
`alcance._alcanzados` for ONE product (a filter row with nothing set reaches
nothing; within a row every set field must match). `UPGRADE_SQL`/`DOWNGRADE_SQL`
are the live definition; the migration `20261109_sell_out_triggers` carries a
frozen copy.
"""

from __future__ import annotations

from typing import List

from app.services.sell_out.queue import CHANNEL

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
