"""Per-order write-failure quarantine (2026-09-14 incident)

Revision ID: 20260914_cuarentena
Revises: 20260911_costo_congelado
Create Date: 2026-09-14

A `status_detail` payload shaped as a dict (instead of the expected
string) poisoned the whole batch transaction and stalled ingestion for
four days, because a single failed write inside a shared PostgreSQL
transaction aborts every other write queued behind it, and the drain
cursor only advances after a page is processed whole.

Adds `ml_orders_ops_cuarentena`: one row per order whose write failed,
keyed on `order_id`, carrying the untouched raw payload so an automatic
retry can re-attempt the write with zero HTTP calls once the underlying
bug is fixed.

Also widens `ml_ops_divergence.kind`'s CHECK constraint with
`'ingest_failed'`, reusing that existing table (per its own docstring
precedent of being shared across slices) so a quarantined order surfaces
on the divergences dashboard that already exists, instead of living only
in a log line nobody watches.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_cuarentena"
down_revision: Union[str, None] = "20260911_costo_congelado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_orders_ops_cuarentena",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("primera_falla_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ultimo_intento_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("order_id"),
    )

    op.drop_constraint("ck_ml_ops_divergence_kind", "ml_ops_divergence", type_="check")
    op.create_check_constraint(
        "ck_ml_ops_divergence_kind",
        "ml_ops_divergence",
        "kind IN ('missing_in_gbp', 'missing_in_ml', 'field_mismatch', 'out_of_window_update', "
        "'window_not_enumerable', 'unknown', 'ingest_failed')",
    )


def downgrade() -> None:
    op.execute("UPDATE ml_ops_divergence SET kind = 'unknown' WHERE kind = 'ingest_failed'")
    op.drop_constraint("ck_ml_ops_divergence_kind", "ml_ops_divergence", type_="check")
    op.create_check_constraint(
        "ck_ml_ops_divergence_kind",
        "ml_ops_divergence",
        "kind IN ('missing_in_gbp', 'missing_in_ml', 'field_mismatch', 'out_of_window_update', "
        "'window_not_enumerable', 'unknown')",
    )
    op.drop_table("ml_orders_ops_cuarentena")
