"""order_metrics config/statement-level enqueue triggers (ventas-ml-rediseno PR5)

Revision ID: 20260923_ml_order_metrics_triggers_config
Revises: 20260923_ml_order_metrics_triggers_orders
Create Date: 2026-09-23

Design D3 (statement-level scope), D11. Postgres-only: row-level triggers on
`etiquetas_envio` (INSERT/UPDATE OF <cols>/DELETE, same shape as PR4's
per-order tables) plus statement-level triggers with `REFERENCING OLD TABLE /
NEW TABLE` on the five config tables (`ml_venta_varios_pct`,
`logistica_costo_cordon`, `cp_cordones`, `configuracion`, `transportes`).

The DDL below is a FROZEN copy, inlined at authoring time, of what
`app/services/order_metrics/triggers_config.py::create_config_triggers`/
`drop_config_triggers` produced as of this revision -- it is NEVER imported
from that module, same immutability contract PR4's own migration documents
(`20260923_ml_order_metrics_triggers_orders.py`): `CREATE TRIGGER` is not
idempotent, so a later PR's DDL changes get their OWN migration, never an
edit to this file or to `triggers_config.py`'s frozen-at-this-revision
statement lists.

Requires `order_metrics_enqueue` (created by the PR4 migration this one
revises from) to already exist.

Applied via explicit `op.execute()` calls below, following this repo's own
convention (see the PR4 migration and `20251226_trigger_descuento_01.py`).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260923_ml_order_metrics_triggers_config"
down_revision: Union[str, None] = "20260923_ml_order_metrics_triggers_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ETIQUETAS_ENVIO_TRIGGER_SQL = """
-- Read set (design D3 scope, breakdown_service.py::_resolve_flex_cost_by_
-- shipping_id / _postal_code_for_cordon): shipping_id (join key to
-- ml_orders_ops), logistica_id + costo_override + fecha_envio (tariff
-- lookup), es_turbo/es_lluvia (surcharge), transporte_id (postal code
-- source for the cordon lookup). lat/lng-only writes (geocoding
-- enrichment) are NOT in the read set and must not fire.
CREATE OR REPLACE FUNCTION order_metrics_enqueue_etiquetas_envio() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
    old_ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops WHERE shipping_id::text = OLD.shipping_id;
        PERFORM order_metrics_enqueue(ids, 'etiquetas_envio_delete');
        RETURN OLD;
    END IF;

    SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_orders_ops WHERE shipping_id::text = NEW.shipping_id;

    IF TG_OP = 'UPDATE' AND OLD.shipping_id IS DISTINCT FROM NEW.shipping_id THEN
        SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO old_ids
        FROM ml_orders_ops WHERE shipping_id::text = OLD.shipping_id;
        ids := ids || old_ids;
    END IF;

    PERFORM order_metrics_enqueue(
        ids,
        CASE WHEN TG_OP = 'INSERT' THEN 'etiquetas_envio_insert' ELSE 'etiquetas_envio_update' END
    );
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_etiquetas_envio_insert
AFTER INSERT ON etiquetas_envio
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_etiquetas_envio();

CREATE TRIGGER trg_order_metrics_etiquetas_envio_update
AFTER UPDATE OF shipping_id, logistica_id, costo_override, fecha_envio, es_turbo, es_lluvia, transporte_id
ON etiquetas_envio
FOR EACH ROW WHEN (
    OLD.shipping_id IS DISTINCT FROM NEW.shipping_id
    OR OLD.logistica_id IS DISTINCT FROM NEW.logistica_id
    OR OLD.costo_override IS DISTINCT FROM NEW.costo_override
    OR OLD.fecha_envio IS DISTINCT FROM NEW.fecha_envio
    OR OLD.es_turbo IS DISTINCT FROM NEW.es_turbo
    OR OLD.es_lluvia IS DISTINCT FROM NEW.es_lluvia
    OR OLD.transporte_id IS DISTINCT FROM NEW.transporte_id
)
EXECUTE FUNCTION order_metrics_enqueue_etiquetas_envio();

CREATE TRIGGER trg_order_metrics_etiquetas_envio_delete
AFTER DELETE ON etiquetas_envio
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_etiquetas_envio();
"""

_VARIOS_VENTA_PCT_TRIGGER_SQL = """
-- `VariosDeduccion.resolve_bulk` (deducciones.py) picks the version VIGENTE
-- at `date_created` -- the affected orders are those whose date falls in
-- the UNION of the OLD and NEW [fecha_desde, fecha_hasta) window of every
-- touched row (both sides: narrowing a window must recompute the orders
-- that just left it, design D3 statement-level scope).
CREATE OR REPLACE FUNCTION order_metrics_enqueue_varios_venta_pct() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops o
        JOIN old_table t ON true
        WHERE o.date_created::date >= t.fecha_desde
          AND (t.fecha_hasta IS NULL OR o.date_created::date <= t.fecha_hasta);
        PERFORM order_metrics_enqueue(ids, 'varios_venta_pct_delete');
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops o
        JOIN new_table t ON true
        WHERE o.date_created::date >= t.fecha_desde
          AND (t.fecha_hasta IS NULL OR o.date_created::date <= t.fecha_hasta);
        PERFORM order_metrics_enqueue(ids, 'varios_venta_pct_insert');
        RETURN NULL;
    END IF;

    -- UPDATE: only rows whose read columns actually changed -- a bulk
    -- rewrite of identical values must enqueue nothing (design D3 rev 5,
    -- applied here at statement scope since a row-level WHEN cannot exist).
    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_orders_ops o
    JOIN (
        SELECT n.fecha_desde, n.fecha_hasta FROM new_table n
        JOIN old_table od ON od.id = n.id
        WHERE od.porcentaje IS DISTINCT FROM n.porcentaje
           OR od.fecha_desde IS DISTINCT FROM n.fecha_desde
           OR od.fecha_hasta IS DISTINCT FROM n.fecha_hasta
        UNION
        SELECT od.fecha_desde, od.fecha_hasta FROM old_table od
        JOIN new_table n ON n.id = od.id
        WHERE od.porcentaje IS DISTINCT FROM n.porcentaje
           OR od.fecha_desde IS DISTINCT FROM n.fecha_desde
           OR od.fecha_hasta IS DISTINCT FROM n.fecha_hasta
    ) ranges ON true
    WHERE o.date_created::date >= ranges.fecha_desde
      AND (ranges.fecha_hasta IS NULL OR o.date_created::date <= ranges.fecha_hasta);

    PERFORM order_metrics_enqueue(ids, 'varios_venta_pct_update');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql;

-- Postgres forbids transition tables on a trigger with MORE THAN ONE event
-- ("transition tables cannot be specified for triggers with more than one
-- event") -- one trigger per event, sharing the same function, each
-- REFERENCING only the transition table(s) that event actually populates.
CREATE TRIGGER trg_order_metrics_varios_venta_pct_insert
AFTER INSERT ON ml_venta_varios_pct
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_varios_venta_pct();

CREATE TRIGGER trg_order_metrics_varios_venta_pct_update
AFTER UPDATE ON ml_venta_varios_pct
REFERENCING OLD TABLE AS old_table NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_varios_venta_pct();

CREATE TRIGGER trg_order_metrics_varios_venta_pct_delete
AFTER DELETE ON ml_venta_varios_pct
REFERENCING OLD TABLE AS old_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_varios_venta_pct();
"""

_LOGISTICA_COSTO_CORDON_TRIGGER_SQL = """
-- `_resolve_flex_cost_by_shipping_id` (breakdown_service.py) resolves the
-- tariff by (logistica_id, cordon, vigente_desde <= fecha_envio) for every
-- self_service (Flex) label whose `logistica_id` matches -- the affected
-- set is every self_service order whose label carries that logistica_id
-- (design D3 statement-level scope).
CREATE OR REPLACE FUNCTION order_metrics_enqueue_logistica_costo_cordon() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops o
        JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
        JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
        JOIN old_table lcc ON lcc.logistica_id = e.logistica_id
        WHERE s.logistic_type = 'self_service';
        PERFORM order_metrics_enqueue(ids, 'logistica_costo_cordon_delete');
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops o
        JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
        JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
        JOIN new_table lcc ON lcc.logistica_id = e.logistica_id
        WHERE s.logistic_type = 'self_service';
        PERFORM order_metrics_enqueue(ids, 'logistica_costo_cordon_insert');
        RETURN NULL;
    END IF;

    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_orders_ops o
    JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
    JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
    JOIN (
        SELECT n.logistica_id FROM new_table n
        JOIN old_table od ON od.id = n.id
        WHERE od.logistica_id IS DISTINCT FROM n.logistica_id
           OR od.cordon IS DISTINCT FROM n.cordon
           OR od.costo IS DISTINCT FROM n.costo
           OR od.costo_turbo IS DISTINCT FROM n.costo_turbo
           OR od.vigente_desde IS DISTINCT FROM n.vigente_desde
        UNION
        SELECT od.logistica_id FROM old_table od
        JOIN new_table n ON n.id = od.id
        WHERE od.logistica_id IS DISTINCT FROM n.logistica_id
           OR od.cordon IS DISTINCT FROM n.cordon
           OR od.costo IS DISTINCT FROM n.costo
           OR od.costo_turbo IS DISTINCT FROM n.costo_turbo
           OR od.vigente_desde IS DISTINCT FROM n.vigente_desde
    ) lcc ON lcc.logistica_id = e.logistica_id
    WHERE s.logistic_type = 'self_service';

    PERFORM order_metrics_enqueue(ids, 'logistica_costo_cordon_update');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_logistica_costo_cordon_insert
AFTER INSERT ON logistica_costo_cordon
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_logistica_costo_cordon();

CREATE TRIGGER trg_order_metrics_logistica_costo_cordon_update
AFTER UPDATE ON logistica_costo_cordon
REFERENCING OLD TABLE AS old_table NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_logistica_costo_cordon();

CREATE TRIGGER trg_order_metrics_logistica_costo_cordon_delete
AFTER DELETE ON logistica_costo_cordon
REFERENCING OLD TABLE AS old_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_logistica_costo_cordon();
"""

_CODIGOS_POSTALES_TRIGGER_SQL = """
-- `_postal_code_for_cordon` (breakdown_service.py) resolves the cordon's
-- postal code as coalesce(transporte.cp, manual_zip_code, shipment
-- receiver_address zip_code) -- the affected set is every self_service
-- order whose resolved postal code equals the changed `cp_cordones` row.
CREATE OR REPLACE FUNCTION order_metrics_enqueue_codigos_postales() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops o
        JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
        JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
        LEFT JOIN transportes t ON t.id = e.transporte_id
        JOIN old_table cp ON cp.codigo_postal = COALESCE(t.cp, e.manual_zip_code, s.receiver_address ->> 'zip_code')
        WHERE s.logistic_type = 'self_service';
        PERFORM order_metrics_enqueue(ids, 'codigos_postales_delete');
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops o
        JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
        JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
        LEFT JOIN transportes t ON t.id = e.transporte_id
        JOIN new_table cp ON cp.codigo_postal = COALESCE(t.cp, e.manual_zip_code, s.receiver_address ->> 'zip_code')
        WHERE s.logistic_type = 'self_service';
        PERFORM order_metrics_enqueue(ids, 'codigos_postales_insert');
        RETURN NULL;
    END IF;

    -- UPDATE: only rows whose `cordon` actually changed.
    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_orders_ops o
    JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
    JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id
    LEFT JOIN transportes t ON t.id = e.transporte_id
    JOIN (
        SELECT n.codigo_postal FROM new_table n
        JOIN old_table od ON od.codigo_postal = n.codigo_postal
        WHERE od.cordon IS DISTINCT FROM n.cordon
    ) cp ON cp.codigo_postal = COALESCE(t.cp, e.manual_zip_code, s.receiver_address ->> 'zip_code')
    WHERE s.logistic_type = 'self_service';

    PERFORM order_metrics_enqueue(ids, 'codigos_postales_update');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_codigos_postales_insert
AFTER INSERT ON cp_cordones
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_codigos_postales();

CREATE TRIGGER trg_order_metrics_codigos_postales_update
AFTER UPDATE ON cp_cordones
REFERENCING OLD TABLE AS old_table NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_codigos_postales();

CREATE TRIGGER trg_order_metrics_codigos_postales_delete
AFTER DELETE ON cp_cordones
REFERENCING OLD TABLE AS old_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_codigos_postales();
"""

_CONFIGURACION_TRIGGER_SQL = """
-- `get_lluvia_config` (logistica_costo_service.py) reads exactly
-- `clave IN ('lluvia_offset_tipo', 'lluvia_offset_valor')`. The rain
-- surcharge only ever changes a label's Flex cost when `es_lluvia = true`,
-- so that is the affected set (design D3: key filtering lives inside the
-- function, since a statement-level WHEN cannot read row values).
CREATE OR REPLACE FUNCTION order_metrics_enqueue_configuracion() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM old_table c WHERE c.clave IN ('lluvia_offset_tipo', 'lluvia_offset_valor')) THEN
            SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
            FROM ml_orders_ops o
            JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
            WHERE e.es_lluvia = true;
            PERFORM order_metrics_enqueue(ids, 'configuracion_delete');
        END IF;
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM new_table c WHERE c.clave IN ('lluvia_offset_tipo', 'lluvia_offset_valor')) THEN
            SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
            FROM ml_orders_ops o
            JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
            WHERE e.es_lluvia = true;
            PERFORM order_metrics_enqueue(ids, 'configuracion_insert');
        END IF;
        RETURN NULL;
    END IF;

    -- UPDATE: only when one of the two lluvia keys actually changed value.
    IF EXISTS (
        SELECT 1 FROM new_table n
        JOIN old_table od ON od.clave = n.clave
        WHERE n.clave IN ('lluvia_offset_tipo', 'lluvia_offset_valor')
          AND od.valor IS DISTINCT FROM n.valor
    ) THEN
        SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
        FROM ml_orders_ops o
        JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
        WHERE e.es_lluvia = true;
        PERFORM order_metrics_enqueue(ids, 'configuracion_update');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_configuracion_insert
AFTER INSERT ON configuracion
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_configuracion();

CREATE TRIGGER trg_order_metrics_configuracion_update
AFTER UPDATE ON configuracion
REFERENCING OLD TABLE AS old_table NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_configuracion();

CREATE TRIGGER trg_order_metrics_configuracion_delete
AFTER DELETE ON configuracion
REFERENCING OLD TABLE AS old_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_configuracion();
"""

_TRANSPORTES_TRIGGER_SQL = """
-- Only `transportes.cp` is in the read set (`_postal_code_for_cordon`,
-- breakdown_service.py). Only UPDATE needs a trigger: a brand-new
-- `Transporte` row has no label referencing it yet (design D3 scope note),
-- so INSERT needs no fan-out. Declared with NO column list (Postgres
-- forbids combining `UPDATE OF <cols>` with transition tables), so the `cp`
-- filter lives inside the function.
CREATE OR REPLACE FUNCTION order_metrics_enqueue_transportes() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_orders_ops o
    JOIN etiquetas_envio e ON e.shipping_id::text = o.shipping_id::text
    JOIN (
        SELECT n.id FROM new_table n
        JOIN old_table od ON od.id = n.id
        WHERE od.cp IS DISTINCT FROM n.cp
    ) t ON t.id = e.transporte_id;

    PERFORM order_metrics_enqueue(ids, 'transportes_update');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_transportes
AFTER UPDATE ON transportes
REFERENCING OLD TABLE AS old_table NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_transportes();
"""


# Order matters: functions before the triggers that call them; each table's
# own function before its own triggers. `etiquetas_envio` first because the
# five config tables' functions JOIN it. FROZEN at this revision -- never
# edited after release; a later PR's DDL changes get their OWN migration.
_CREATE_STATEMENTS = [
    _ETIQUETAS_ENVIO_TRIGGER_SQL,
    _VARIOS_VENTA_PCT_TRIGGER_SQL,
    _LOGISTICA_COSTO_CORDON_TRIGGER_SQL,
    _CODIGOS_POSTALES_TRIGGER_SQL,
    _CONFIGURACION_TRIGGER_SQL,
    _TRANSPORTES_TRIGGER_SQL,
]

_DROP_STATEMENTS = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_transportes ON transportes",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_transportes()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_configuracion_delete ON configuracion",
    "DROP TRIGGER IF EXISTS trg_order_metrics_configuracion_update ON configuracion",
    "DROP TRIGGER IF EXISTS trg_order_metrics_configuracion_insert ON configuracion",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_configuracion()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_codigos_postales_delete ON cp_cordones",
    "DROP TRIGGER IF EXISTS trg_order_metrics_codigos_postales_update ON cp_cordones",
    "DROP TRIGGER IF EXISTS trg_order_metrics_codigos_postales_insert ON cp_cordones",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_codigos_postales()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_logistica_costo_cordon_delete ON logistica_costo_cordon",
    "DROP TRIGGER IF EXISTS trg_order_metrics_logistica_costo_cordon_update ON logistica_costo_cordon",
    "DROP TRIGGER IF EXISTS trg_order_metrics_logistica_costo_cordon_insert ON logistica_costo_cordon",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_logistica_costo_cordon()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_varios_venta_pct_delete ON ml_venta_varios_pct",
    "DROP TRIGGER IF EXISTS trg_order_metrics_varios_venta_pct_update ON ml_venta_varios_pct",
    "DROP TRIGGER IF EXISTS trg_order_metrics_varios_venta_pct_insert ON ml_venta_varios_pct",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_varios_venta_pct()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_etiquetas_envio_delete ON etiquetas_envio",
    "DROP TRIGGER IF EXISTS trg_order_metrics_etiquetas_envio_update ON etiquetas_envio",
    "DROP TRIGGER IF EXISTS trg_order_metrics_etiquetas_envio_insert ON etiquetas_envio",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_etiquetas_envio()",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _CREATE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _DROP_STATEMENTS:
        op.execute(statement)
