"""ml_order_item_costos: TP-Link cost (cost list 8) columns

Revision ID: 20261025_tp_cost_columns
Revises: 20261025_sell_in_permisos
Create Date: 2026-10-15

metricas-ml-tplink-mode / P1. Adds the TP-Link cost frozen next to the
normal cost by `costeo_service.congelar()`: the CURRENT list-8 price
(`tb_item_cost_list.coslis_id = 8`) converted to ARS at the latest USD rate.

All six columns are NULLABLE ON PURPOSE: NULL means "no usable list-8 price"
and IS the "Total TP incomplete" flag -- never 0, never the normal cost.
`ck_..._tp_completo` keeps a TP cost all-or-nothing, `ck_..._tp_ars_sin_tc`
keeps the rate only for a USD price, and the partial index
lets P2 (history backfill and late-load worker) find the pending rows of one
product without scanning the table.

LOCK NOTE: ADD COLUMN of nullable columns with no default is metadata-only.
The CHECK constraints are validated against existing rows, which are all
NULL, and the partial index starts out covering every existing row; both
take a SHARE-level lock for seconds on this table. Same trade-off as
20260922_ix_producto_item_id.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_tp_cost_columns"
down_revision: Union[str, None] = "20261025_sell_in_permisos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ml_order_item_costos"
_INDEX = "ix_ml_order_item_costos_tp_pendiente"
_CK_NO_NEGATIVO = "ck_ml_order_item_costos_tp_no_negativo"
_CK_COMPLETO = "ck_ml_order_item_costos_tp_completo"
_CK_ARS_SIN_TC = "ck_ml_order_item_costos_tp_ars_sin_tc"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("costo_tp_origen", sa.Numeric(14, 4), nullable=True, comment="List-8 price in its own currency."),
    )
    op.add_column(_TABLE, sa.Column("costo_tp_moneda", sa.String(3), nullable=True))
    op.add_column(_TABLE, sa.Column("costo_tp_tipo_cambio", sa.Numeric(14, 4), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column(
            "costo_tp_unitario_ars",
            sa.Numeric(14, 4),
            nullable=True,
            comment="TP-Link unit cost in ARS. NULL = no usable list-8 price (Total TP incomplete).",
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "costo_tp_fuente",
            sa.String(30),
            nullable=True,
            comment="lista8_ingesta | lista8_ingesta_combo | lista8_historia | lista8_carga_posterior",
        ),
    )
    op.add_column(_TABLE, sa.Column("costo_tp_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        _CK_NO_NEGATIVO,
        _TABLE,
        "(costo_tp_origen IS NULL OR costo_tp_origen >= 0)"
        " AND (costo_tp_tipo_cambio IS NULL OR costo_tp_tipo_cambio >= 0)"
        " AND (costo_tp_unitario_ars IS NULL OR costo_tp_unitario_ars >= 0)",
    )
    op.create_check_constraint(
        _CK_COMPLETO,
        _TABLE,
        "(costo_tp_unitario_ars IS NULL) = (costo_tp_origen IS NULL)"
        " AND (costo_tp_unitario_ars IS NULL) = (costo_tp_moneda IS NULL)"
        " AND (costo_tp_unitario_ars IS NULL) = (costo_tp_fuente IS NULL)"
        " AND (costo_tp_unitario_ars IS NULL) = (costo_tp_at IS NULL)",
    )
    # The rate is kept only for a USD price: an ARS TP cost (an ARS list-8
    # price, or a combo sum already in ARS) carries none.
    op.create_check_constraint(
        _CK_ARS_SIN_TC,
        _TABLE,
        "costo_tp_moneda <> 'ARS' OR costo_tp_tipo_cambio IS NULL",
    )
    op.create_index(
        _INDEX,
        _TABLE,
        ["producto_item_id"],
        postgresql_where=sa.text("costo_tp_unitario_ars IS NULL"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE, if_exists=True)
    op.drop_constraint(_CK_ARS_SIN_TC, _TABLE, type_="check")
    op.drop_constraint(_CK_COMPLETO, _TABLE, type_="check")
    op.drop_constraint(_CK_NO_NEGATIVO, _TABLE, type_="check")
    for column in (
        "costo_tp_at",
        "costo_tp_fuente",
        "costo_tp_unitario_ars",
        "costo_tp_tipo_cambio",
        "costo_tp_moneda",
        "costo_tp_origen",
    ):
        op.drop_column(_TABLE, column)
