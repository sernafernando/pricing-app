"""Costo SI (sell-in-costo-si T2): history + breakdown, backups, recompute queue with its triggers, daily available
stock photo, Mercado Libre Full operations kept, PM FX correction per invoice. New tables only; the triggers on the
sell-in / Compras tables only queue products (no column changes).

Frozen copy of `app.services.costo_si.queue.UPGRADE_SQL` / `DOWNGRADE_SQL` at this revision.

Revision ID: 20261125_costo_si
Revises: 20261117_permiso_promos_auto_aplicacion
Create Date: 2026-11-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125_costo_si"
down_revision: Union[str, None] = "20261117_permiso_promos_auto_aplicacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USD = sa.Numeric(18, 5)

UPGRADE_SQL = [
    """
CREATE OR REPLACE FUNCTION costo_si_encolar(p_item integer, p_desde date) RETURNS void AS $f$
BEGIN
    IF p_item IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO costo_si_dirty (item_id, desde) VALUES (p_item, p_desde)
    ON CONFLICT (item_id) DO UPDATE
    SET desde = CASE WHEN costo_si_dirty.desde IS NULL OR EXCLUDED.desde IS NULL THEN NULL
                     ELSE LEAST(costo_si_dirty.desde, EXCLUDED.desde) END,
        enqueued_at = now(), attempts = 0, last_error = NULL;
    PERFORM pg_notify('sell_dirty', '');
END
$f$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_trg_compra_item() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar(OLD.item_id, (SELECT fecha_compra FROM sell_in_compras WHERE id = OLD.compra_id));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar(NEW.item_id, (SELECT fecha_compra FROM sell_in_compras WHERE id = NEW.compra_id));
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_trg_compra() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar(ci.item_id, LEAST(OLD.fecha_compra, NEW.fecha_compra))
    FROM sell_in_compra_items ci WHERE ci.compra_id = NEW.id;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_encolar_compra(p_compra bigint) RETURNS void AS $f$
BEGIN
    PERFORM costo_si_encolar(ci.item_id, c.fecha_compra)
    FROM sell_in_compra_items ci JOIN sell_in_compras c ON c.id = ci.compra_id WHERE ci.compra_id = p_compra;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_compra_pedido() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_compra(OLD.compra_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_compra(NEW.compra_id);
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_encolar_bono(r sell_in_bonos_marca) RETURNS void AS $f$
BEGIN
    IF r.base = 'costo_venta' AND r.tipo = 'porcentaje' THEN
        PERFORM costo_si_encolar(p.item_id, r.fecha_desde)
        FROM productos_erp p
        WHERE (r.alcance = 'marca' AND p.marca = r.marca AND (r.categoria IS NULL OR p.categoria = r.categoria))
           OR (r.alcance = 'categoria' AND p.categoria = r.categoria)
           OR (r.alcance = 'modelos' AND p.item_id IN (SELECT bi.item_id FROM sell_in_bono_items bi WHERE bi.bono_id = r.id));
    END IF;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_bono() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_bono(OLD);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_bono(NEW);
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_trg_bono_item() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar(OLD.item_id, (SELECT fecha_desde FROM sell_in_bonos_marca WHERE id = OLD.bono_id));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar(NEW.item_id, (SELECT fecha_desde FROM sell_in_bonos_marca WHERE id = NEW.bono_id));
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_encolar_factura(p_ct bigint) RETURNS void AS $f$
BEGIN
    PERFORM costo_si_encolar(it.item_id, ct.ct_date::date)
    FROM tb_item_transactions it JOIN tb_commercial_transactions ct ON ct.ct_transaction = it.ct_transaction
    WHERE it.ct_transaction = p_ct;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_factura() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_factura((to_jsonb(OLD) ->> TG_ARGV[0])::bigint);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_factura((to_jsonb(NEW) ->> TG_ARGV[0])::bigint);
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_trg_pedido_tc() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar_factura(pf.ct_transaction_id) FROM pedido_compra_facturas pf WHERE pf.pedido_id = NEW.id;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_trg_producto() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar(NEW.item_id, NULL);
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_encolar_imputacion(
    p_origen_tipo text, p_origen_id bigint, p_destino_tipo text, p_destino_id bigint
) RETURNS void AS $f$
BEGIN
    IF p_origen_tipo NOT IN ('nota_credito_erp', 'nota_credito_local') THEN
        RETURN;
    END IF;
    IF p_destino_tipo = 'factura_erp' THEN
        PERFORM costo_si_encolar_factura(p_destino_id);
    END IF;
    PERFORM costo_si_encolar_factura(CASE WHEN p_origen_tipo = 'nota_credito_erp' THEN p_origen_id
        ELSE (SELECT ncl.ct_transaction_id FROM notas_credito_local ncl WHERE ncl.id = p_origen_id) END);
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_imputacion() RETURNS TRIGGER AS $t$
DECLARE
    o record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_imputacion(OLD.origen_tipo, OLD.origen_id, OLD.destino_tipo, OLD.destino_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_imputacion(NEW.origen_tipo, NEW.origen_id, NEW.destino_tipo, NEW.destino_id);
        IF NEW.reimputada_desde_id IS NOT NULL THEN
            SELECT origen_tipo, origen_id, destino_tipo, destino_id INTO o
            FROM imputaciones WHERE id = NEW.reimputada_desde_id;
            IF FOUND THEN
                PERFORM costo_si_encolar_imputacion(o.origen_tipo, o.origen_id, o.destino_tipo, o.destino_id);
            END IF;
        END IF;
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION costo_si_trg_nc_local() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar_factura(OLD.ct_transaction_id);
    PERFORM costo_si_encolar_imputacion(i.origen_tipo, i.origen_id, i.destino_tipo, i.destino_id)
    FROM imputaciones i WHERE i.origen_tipo = 'nota_credito_local' AND i.origen_id = NEW.id;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    "CREATE TRIGGER costo_si_compra_item AFTER INSERT OR UPDATE OR DELETE ON sell_in_compra_items FOR EACH ROW EXECUTE FUNCTION costo_si_trg_compra_item()",
    "CREATE TRIGGER costo_si_compra AFTER UPDATE ON sell_in_compras FOR EACH ROW EXECUTE FUNCTION costo_si_trg_compra()",
    "CREATE TRIGGER costo_si_compra_pedido AFTER INSERT OR UPDATE OR DELETE ON sell_in_compra_pedidos FOR EACH ROW EXECUTE FUNCTION costo_si_trg_compra_pedido()",
    "CREATE TRIGGER costo_si_bono AFTER INSERT OR UPDATE OR DELETE ON sell_in_bonos_marca FOR EACH ROW EXECUTE FUNCTION costo_si_trg_bono()",
    "CREATE TRIGGER costo_si_bono_item AFTER INSERT OR UPDATE OR DELETE ON sell_in_bono_items FOR EACH ROW EXECUTE FUNCTION costo_si_trg_bono_item()",
    "CREATE TRIGGER costo_si_factura AFTER INSERT OR UPDATE OR DELETE ON pedido_compra_facturas FOR EACH ROW EXECUTE FUNCTION costo_si_trg_factura('ct_transaction_id')",
    "CREATE TRIGGER costo_si_factura_tc AFTER INSERT OR UPDATE OR DELETE ON costo_si_factura_tc FOR EACH ROW EXECUTE FUNCTION costo_si_trg_factura('ct_transaction')",
    "CREATE TRIGGER costo_si_pedido_tc AFTER UPDATE OF tipo_cambio, tipo_cambio_manual ON pedidos_compra FOR EACH ROW WHEN (OLD.tipo_cambio IS DISTINCT FROM NEW.tipo_cambio OR OLD.tipo_cambio_manual IS DISTINCT FROM NEW.tipo_cambio_manual) EXECUTE FUNCTION costo_si_trg_pedido_tc()",
    "CREATE TRIGGER costo_si_producto AFTER UPDATE OF marca, categoria ON productos_erp FOR EACH ROW WHEN (OLD.marca IS DISTINCT FROM NEW.marca OR OLD.categoria IS DISTINCT FROM NEW.categoria) EXECUTE FUNCTION costo_si_trg_producto()",
    "CREATE TRIGGER costo_si_imputacion AFTER INSERT OR UPDATE OR DELETE ON imputaciones FOR EACH ROW EXECUTE FUNCTION costo_si_trg_imputacion()",
    "CREATE TRIGGER costo_si_nc_local AFTER UPDATE OF ct_transaction_id ON notas_credito_local FOR EACH ROW WHEN (OLD.ct_transaction_id IS DISTINCT FROM NEW.ct_transaction_id) EXECUTE FUNCTION costo_si_trg_nc_local()",
]

DOWNGRADE_SQL = [
    "DROP TRIGGER IF EXISTS costo_si_compra_item ON sell_in_compra_items",
    "DROP TRIGGER IF EXISTS costo_si_compra ON sell_in_compras",
    "DROP TRIGGER IF EXISTS costo_si_compra_pedido ON sell_in_compra_pedidos",
    "DROP TRIGGER IF EXISTS costo_si_bono ON sell_in_bonos_marca",
    "DROP TRIGGER IF EXISTS costo_si_bono_item ON sell_in_bono_items",
    "DROP TRIGGER IF EXISTS costo_si_factura ON pedido_compra_facturas",
    "DROP TRIGGER IF EXISTS costo_si_factura_tc ON costo_si_factura_tc",
    "DROP TRIGGER IF EXISTS costo_si_pedido_tc ON pedidos_compra",
    "DROP TRIGGER IF EXISTS costo_si_producto ON productos_erp",
    "DROP TRIGGER IF EXISTS costo_si_imputacion ON imputaciones",
    "DROP TRIGGER IF EXISTS costo_si_nc_local ON notas_credito_local",
    "DROP FUNCTION IF EXISTS costo_si_trg_nc_local()",
    "DROP FUNCTION IF EXISTS costo_si_trg_imputacion()",
    "DROP FUNCTION IF EXISTS costo_si_encolar_imputacion(text, bigint, text, bigint)",
    "DROP FUNCTION IF EXISTS costo_si_trg_producto()",
    "DROP FUNCTION IF EXISTS costo_si_trg_pedido_tc()",
    "DROP FUNCTION IF EXISTS costo_si_encolar_compra(bigint)",
    "DROP FUNCTION IF EXISTS costo_si_trg_factura()",
    "DROP FUNCTION IF EXISTS costo_si_encolar_factura(bigint)",
    "DROP FUNCTION IF EXISTS costo_si_trg_bono_item()",
    "DROP FUNCTION IF EXISTS costo_si_trg_bono()",
    "DROP FUNCTION IF EXISTS costo_si_encolar_bono(sell_in_bonos_marca)",
    "DROP FUNCTION IF EXISTS costo_si_trg_compra_pedido()",
    "DROP FUNCTION IF EXISTS costo_si_trg_compra()",
    "DROP FUNCTION IF EXISTS costo_si_trg_compra_item()",
    "DROP FUNCTION IF EXISTS costo_si_encolar(integer, date)",
]


def upgrade() -> None:
    op.create_table(
        "costo_si_pasos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(8), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("ct_transaction", sa.BigInteger(), nullable=True),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("costo_neto_usd", USD, nullable=True),
        sa.Column("sell_ins", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sell_in_pct", sa.Numeric(9, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("costo_neto_neto_usd", USD, nullable=True),
        sa.Column("stock_antes", sa.Integer(), nullable=False),
        sa.Column("stock_base", sa.Integer(), nullable=False),
        sa.Column("stock_despues", sa.Integer(), nullable=False),
        sa.Column("promedio_usd", USD, nullable=True),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("fuente_tc", sa.String(16), nullable=True),
        sa.Column("en_compras", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("calculado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("item_id", "orden", name="uq_costo_si_pasos_item_orden"),
    )
    op.create_index("ix_costo_si_pasos_item_fecha", "costo_si_pasos", ["item_id", "fecha"])
    op.create_table(
        "costo_si_backups",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("desde", sa.Date(), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("pasos", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_costo_si_backups_item", "costo_si_backups", ["item_id", "created_at"])
    op.create_table(
        "costo_si_dirty",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("desde", sa.Date(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "costo_si_stock_diario",
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("principal", sa.Integer(), nullable=False),
        sa.Column("full", sa.Integer(), nullable=False),
        sa.Column("tomado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("fecha", "item_id", name="pk_costo_si_stock_diario"),
    )
    op.create_table(
        "costo_si_full_operaciones",
        sa.Column("operation_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("inventory_id", sa.Text(), nullable=False),
        sa.Column("date_created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("disponible", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_costo_si_full_operaciones_inv_fecha", "costo_si_full_operaciones", ["inventory_id", "date_created"]
    )
    op.create_table(
        "costo_si_full_cobertura",
        sa.Column("inventory_id", sa.Text(), primary_key=True),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "costo_si_factura_tc",
        sa.Column("ct_transaction", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "costo_si_nc_sin_asignar",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("nc_ct", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("importe", USD, nullable=False),
        sa.Column("curr_id", sa.Integer(), nullable=True),
        sa.Column("motivo", sa.String(32), nullable=False),
        sa.Column("calculado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
    for table in (
        "costo_si_nc_sin_asignar",
        "costo_si_factura_tc",
        "costo_si_full_cobertura",
        "costo_si_full_operaciones",
        "costo_si_stock_diario",
        "costo_si_dirty",
        "costo_si_backups",
        "costo_si_pasos",
    ):
        op.drop_table(table)
