"""Statement triggers that feed `sell_out_dirty` (sell-in-sell-out T7 S4): the
changes that move a campaign's allocation but never pass through the app's own
writers (`queue`: `sell.drain` fan-out, the campaigns API, BNA). Each one queues
the affected campaigns and `pg_notify('sell_out_dirty')` in the transaction of
the change, with the queue's upsert (`ON CONFLICT DO UPDATE`, attempts reset),
and does NO allocation work: `sell_out.drain` rebuilds them.

- `offset_grupo_filtros` (the offsets API group filters): inserted or deleted
  rows, and updated rows whose `grupo_id`, `marca`, `categoria`,
  `subcategoria_id` or `item_id` changed, queue the ACTIVE campaigns of their
  old and new group (a group linked to a campaign cannot be deleted: RESTRICT).
- `productos_erp`: inserted or deleted products, and updated ones whose
  `marca`, `categoria` or `subcategoria_id` changed, queue the active campaigns
  reaching the old or the new product; a product whose `iva` alone changed
  queues only the ones whose amount depends on it (`monto_incluye_iva`, or a
  percentage on `precio_neto`, whose ML base carries VAT; `asignacion._base`).
- `ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`, updated rows
  whose `cust_id` or `costo_total` changed (the columns the sell-out reads that
  `sell_dirty` does not watch, `sell.queue.ALLOCATION_COLUMNS`):
  - `cust_id`: it decides which earlier sale a return reverses
    (`costing.resolver_objetivos`), and that return may fall in any campaign
    ending on or after the sale; it queues the campaigns holding the line plus
    the active ones reaching its product with `fecha_hasta` >= its UTC day;
  - `costo_total` (the per-unit cost base, `alcance.ventas`): it queues only
    the percentage campaigns on `costo` holding the line or reaching its
    product and covering its UTC day.
  Both versions of a row (old and new) are looked up. The UTC day is
  `fecha_venta AT TIME ZONE 'UTC'` (a timestamptz, so independent of the
  session TimeZone, like `costing.utc_date`); a sale without a day queues only
  the campaigns holding it. Every other change of a sale already reaches
  `sell_dirty` and the drain's fan-out.

FOR EACH STATEMENT with transition tables (`viejas` / `nuevas`): a bulk ERP
sync queues the campaign set of the WHOLE statement in ONE upsert ordered by
`campana_id`, the order every other writer locks in (`queue.enqueue`), so it
cannot deadlock with them (a row trigger locks in row order). Postgres allows
no column list, no WHEN and one event per trigger with transition tables, so
there is one trigger per event and the function compares the old and new rows
by key itself: a statement where nothing relevant changed never touches the
queue. Every function returns at once while no campaign is active.

A campaign that is not `activa` holds no rows (`asignacion.recalcular`) and is
never queued by reach. `sell_out_alcance(item, marca, categoria, subcategoria)`
mirrors `alcance._alcanzados` for ONE product (a filter row with nothing set
reaches nothing; within a row every set field must match).

`UPGRADE_SQL`/`DOWNGRADE_SQL` are the live definition; the migration
`20261109_sell_out_triggers` carries a frozen copy.
"""

from __future__ import annotations

from typing import List, Sequence

from app.services.sell_out.queue import CHANNEL

# Returns at once while no campaign is active: nothing can be reached or held.
_GATE = """
    IF NOT EXISTS (SELECT 1 FROM sell_out_campanas WHERE estado = 'activa') THEN
        RETURN NULL;
    END IF;"""

# Inserts the `campana_id`s selected by `{select}` in ONE statement sorted by id (the order every queue
# writer locks in, `queue.enqueue`) and notifies once if something was queued.
_ENQUEUE = f"""
    INSERT INTO sell_out_dirty (campana_id)
    SELECT DISTINCT q.campana_id FROM ({{select}}) AS q
    ORDER BY 1
    ON CONFLICT (campana_id) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;"""

_FILTROS_SELECT = """
        SELECT g.campana_id FROM sell_out_campana_grupos AS g
        JOIN sell_out_campanas AS c ON c.id = g.campana_id
        WHERE c.estado = 'activa' AND g.grupo_id = ANY(grupos)"""

_PRODUCTOS_SELECT = """
        SELECT a.campana_id
        FROM unnest(items, marcas, categorias, subcategorias, solo_iva) AS s(item_id, marca, categoria, sub, solo_iva)
        CROSS JOIN LATERAL sell_out_alcance(s.item_id, s.marca, s.categoria, s.sub) AS a
        JOIN sell_out_campanas AS c ON c.id = a.campana_id
        WHERE NOT s.solo_iva OR c.monto_incluye_iva OR (c.tipo = 'porcentaje' AND c.base_porcentaje = 'precio_neto')"""

# The daily sync rewrites every sale (`fecha_calculo`) one UPDATE per row: a statement where no
# `cust_id` / `costo_total` changed returns before the reach query (measured locally, 1 active
# campaign, 20k one-row UPDATEs: +64% without this exit, +22% with it). It MUST be a FULL JOIN:
# transition tables have no statistics, and an inner JOIN was planned as a nested loop (40 s for
# one 20k-row UPDATE); a FULL JOIN can only be a hash or merge join.
_VENTAS_SIN_CAMBIO = """
    IF NOT EXISTS (
        SELECT 1 FROM viejas AS o FULL JOIN nuevas AS n ON n.id = o.id
        WHERE o.id IS NULL OR n.id IS NULL
           OR (o.cust_id, o.costo_total) IS DISTINCT FROM (n.cust_id, n.costo_total)
    ) THEN
        RETURN NULL;
    END IF;"""

_VENTAS_SELECT = """
        SELECT y.campana_id FROM (
            WITH lados AS (
                SELECT v.ref, v.item_id, v.dia,
                       (o.id IS NULL OR n.id IS NULL OR o.cust_id IS DISTINCT FROM n.cust_id) AS cliente
                FROM viejas AS o FULL JOIN nuevas AS n ON n.id = o.id
                CROSS JOIN LATERAL (VALUES
                    (o.it_transaction, o.item_id, CAST(o.fecha_venta AT TIME ZONE 'UTC' AS DATE)),
                    (n.it_transaction, n.item_id, CAST(n.fecha_venta AT TIME ZONE 'UTC' AS DATE))
                ) AS v(ref, item_id, dia)
                WHERE v.ref IS NOT NULL
                  AND (o.id IS NULL OR n.id IS NULL
                       OR (o.cust_id, o.costo_total) IS DISTINCT FROM (n.cust_id, n.costo_total))
            )
            SELECT x.campana_id, l.cliente
            FROM lados AS l JOIN sell_out_consumos AS x ON x.canal = TG_ARGV[0] AND x.venta_ref = l.ref
            UNION ALL
            SELECT a.campana_id, l.cliente
            FROM lados AS l JOIN productos_erp AS p ON p.item_id = l.item_id
            CROSS JOIN LATERAL sell_out_alcance(p.item_id, p.marca, p.categoria, p.subcategoria_id) AS a
            WHERE l.dia IS NOT NULL AND l.dia <= a.fecha_hasta AND (l.cliente OR l.dia >= a.fecha_desde)
        ) AS y
        JOIN sell_out_campanas AS c ON c.id = y.campana_id
        WHERE y.cliente OR (c.tipo = 'porcentaje' AND c.base_porcentaje = 'costo')"""

_TRIGGER = """
CREATE TRIGGER trg_sell_out_{nombre}_{evento}
AFTER {evento_sql} ON {tabla}
REFERENCING {tablas}
FOR EACH STATEMENT EXECUTE FUNCTION {funcion}
"""
_TRANSICION = {
    "insert": "NEW TABLE AS nuevas",
    "update": "OLD TABLE AS viejas NEW TABLE AS nuevas",
    "delete": "OLD TABLE AS viejas",
}
_EVENTOS = ("insert", "update", "delete")


def _triggers(nombre: str, tabla: str, funcion: str, eventos: Sequence[str] = _EVENTOS) -> List[str]:
    return [
        _TRIGGER.format(
            nombre=nombre, evento=e, evento_sql=e.upper(), tabla=tabla, tablas=_TRANSICION[e], funcion=funcion
        )
        for e in eventos
    ]


def _drops(nombre: str, tabla: str, eventos: Sequence[str] = _EVENTOS) -> List[str]:
    return [f"DROP TRIGGER IF EXISTS trg_sell_out_{nombre}_{e} ON {tabla}" for e in reversed(eventos)]


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
CREATE OR REPLACE FUNCTION sell_out_enqueue_filtros() RETURNS TRIGGER AS $trg$
DECLARE
    grupos INTEGER[];
BEGIN{_GATE}
    IF TG_OP = 'INSERT' THEN
        SELECT array_agg(DISTINCT n.grupo_id) INTO grupos FROM nuevas AS n;
    ELSIF TG_OP = 'DELETE' THEN
        SELECT array_agg(DISTINCT o.grupo_id) INTO grupos FROM viejas AS o;
    ELSE
        SELECT array_agg(DISTINCT v.grupo_id) INTO grupos
        FROM viejas AS o FULL JOIN nuevas AS n ON n.id = o.id
        CROSS JOIN LATERAL (VALUES (o.grupo_id), (n.grupo_id)) AS v(grupo_id)
        WHERE v.grupo_id IS NOT NULL
          AND (o.id IS NULL OR n.id IS NULL
               OR (o.grupo_id, o.marca, o.categoria, o.subcategoria_id, o.item_id)
                  IS DISTINCT FROM (n.grupo_id, n.marca, n.categoria, n.subcategoria_id, n.item_id));
    END IF;
    IF grupos IS NULL THEN
        RETURN NULL;
    END IF;
{_ENQUEUE.format(select=_FILTROS_SELECT)}
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_out_enqueue_productos() RETURNS TRIGGER AS $trg$
DECLARE
    items INTEGER[];
    marcas TEXT[];
    categorias TEXT[];
    subcategorias INTEGER[];
    solo_iva BOOLEAN[];
BEGIN{_GATE}
    IF TG_OP = 'INSERT' THEN
        SELECT array_agg(n.item_id), array_agg(n.marca), array_agg(n.categoria), array_agg(n.subcategoria_id),
               array_agg(false)
        INTO items, marcas, categorias, subcategorias, solo_iva FROM nuevas AS n;
    ELSIF TG_OP = 'DELETE' THEN
        SELECT array_agg(o.item_id), array_agg(o.marca), array_agg(o.categoria), array_agg(o.subcategoria_id),
               array_agg(false)
        INTO items, marcas, categorias, subcategorias, solo_iva FROM viejas AS o;
    ELSE
        SELECT array_agg(v.item_id), array_agg(v.marca), array_agg(v.categoria), array_agg(v.subcategoria_id),
               array_agg(o.item_id IS NOT NULL AND n.item_id IS NOT NULL
                         AND (o.marca, o.categoria, o.subcategoria_id)
                             IS NOT DISTINCT FROM (n.marca, n.categoria, n.subcategoria_id))
        INTO items, marcas, categorias, subcategorias, solo_iva
        FROM viejas AS o FULL JOIN nuevas AS n ON n.item_id = o.item_id
        CROSS JOIN LATERAL (VALUES (o.item_id, o.marca, o.categoria, o.subcategoria_id),
                                   (n.item_id, n.marca, n.categoria, n.subcategoria_id))
            AS v(item_id, marca, categoria, subcategoria_id)
        WHERE v.item_id IS NOT NULL
          AND (o.item_id IS NULL OR n.item_id IS NULL
               OR (o.marca, o.categoria, o.subcategoria_id, o.iva)
                  IS DISTINCT FROM (n.marca, n.categoria, n.subcategoria_id, n.iva));
    END IF;
    IF items IS NULL THEN
        RETURN NULL;
    END IF;
{_ENQUEUE.format(select=_PRODUCTOS_SELECT)}
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_out_enqueue_ventas() RETURNS TRIGGER AS $trg$
BEGIN{_GATE}{_VENTAS_SIN_CAMBIO}
{_ENQUEUE.format(select=_VENTAS_SELECT)}
END;
$trg$ LANGUAGE plpgsql
""",
    *_triggers("filtros", "offset_grupo_filtros", "sell_out_enqueue_filtros()"),
    *_triggers("productos", "productos_erp", "sell_out_enqueue_productos()"),
    *_triggers("fuera", "ventas_fuera_ml_metricas", "sell_out_enqueue_ventas('fuera')", ("update",)),
    *_triggers("tn", "ventas_tienda_nube_metricas", "sell_out_enqueue_ventas('tn')", ("update",)),
]

DOWNGRADE_SQL: List[str] = [
    *_drops("tn", "ventas_tienda_nube_metricas", ("update",)),
    *_drops("fuera", "ventas_fuera_ml_metricas", ("update",)),
    *_drops("productos", "productos_erp"),
    *_drops("filtros", "offset_grupo_filtros"),
    "DROP FUNCTION IF EXISTS sell_out_enqueue_ventas()",
    "DROP FUNCTION IF EXISTS sell_out_enqueue_productos()",
    "DROP FUNCTION IF EXISTS sell_out_enqueue_filtros()",
    "DROP FUNCTION IF EXISTS sell_out_alcance(INTEGER, TEXT, TEXT, INTEGER)",
]
