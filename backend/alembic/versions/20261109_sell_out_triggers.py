"""sell out: statement triggers that queue campaigns for changes outside the app's writers

Revision ID: 20261109_sell_out_triggers
Revises: 20261108_sell_out_consumos
Create Date: 2026-10-21

Sell in / sell out, T7 slice S4. `sell_out_dirty` is fed by the app's own
writers since S3 (`sell.drain` fan-out, the campaigns API, BNA); these
triggers cover what never passes through them (owner scope, 2026-10-21):

- `offset_grupo_filtros`: a filter added, changed or removed through the
  offsets API moves the reach of the active campaigns of its group(s);
- `productos_erp`: a new or deleted product, or a change of `marca`,
  `categoria` or `subcategoria_id`, moves the reach of the active campaigns
  reaching the old or new product; a change of `iva` alone queues only the
  campaigns whose amount depends on it;
- `ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`: a `cust_id` or
  `costo_total` change (not in `sell_dirty`'s watched columns).

FOR EACH STATEMENT with transition tables: each statement queues its whole
campaign set in ONE upsert ordered by `campana_id` (the order every queue
writer locks in, so a bulk ERP sync cannot deadlock with them) and notifies
`sell_out_dirty`; none does allocation work, and a statement where nothing
relevant changed never touches the queue. The SQL is a frozen copy of
`app/services/sell_out/triggers.py`'s `UPGRADE_SQL`/`DOWNGRADE_SQL` (that
module is the live definition).

No backfill: a campaign whose reach moved before this revision is rebuilt by
its next queue event.

LOCK NOTE: CREATE/DROP TRIGGER takes a SHARE ROW EXCLUSIVE lock on
`offset_grupo_filtros`, `productos_erp`, `ventas_fuera_ml_metricas` and
`ventas_tienda_nube_metricas` (no rewrite, no scan). Behind an open writer
(an ERP sync or ingest transaction) it would queue and block every new writer
of the table, so upgrade and downgrade run with `lock_timeout = '5s'`: they
fail fast (55P03, lock_not_available) and the deploy is retried. `env.py`
runs all pending revisions in ONE transaction (no `transaction_per_migration`),
so the transaction-local setting is restored to its previous value afterwards
instead of leaking into the next revisions.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261109_sell_out_triggers"
down_revision: Union[str, None] = "20261108_sell_out_consumos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHANNEL = "sell_out_dirty"
LOCK_TIMEOUT = "5s"

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
BEGIN{_GATE}
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


def _is_postgres() -> bool:
    # plpgsql triggers and pg_notify: Postgres only (SQLite test schemas skip them).
    return op.get_bind().dialect.name == "postgresql"


def _run(statements: List[str]) -> None:
    # `env.py` runs every pending revision in ONE transaction, so the previous value (session or
    # transaction) is saved in a custom setting and restored, not reset to DEFAULT. Plain SQL, so it
    # also works in offline (`--sql`) mode.
    op.execute("SELECT set_config('sell_out.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('sell_out.lock_timeout_previo'), true)")


def upgrade() -> None:
    if _is_postgres():
        _run(UPGRADE_SQL)


def downgrade() -> None:
    if _is_postgres():
        _run(DOWNGRADE_SQL)
