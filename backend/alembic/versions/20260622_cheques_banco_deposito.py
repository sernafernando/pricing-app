"""add banco_deposito_id to cheques (Slice 4 conciliacion)

Revision ID: 20260622_cheques_banco_deposito
Revises: 20260619_cheques_modulo
Create Date: 2026-06-22

Agrega banco_deposito_id a la tabla cheques para registrar en qué cuenta
bancaria de la empresa se depositó un cheque de tercero (necesario para
generar el banco_movimiento de ingreso al acreditar).
"""

from alembic import op
import sqlalchemy as sa

revision = "20260622_cheques_banco_deposito"
down_revision = "20260619_cheques_modulo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cheques",
        sa.Column(
            "banco_deposito_id",
            sa.Integer(),
            sa.ForeignKey("bancos_empresa.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_cheque_banco_deposito", "cheques", ["banco_deposito_id"])


def downgrade() -> None:
    op.drop_index("ix_cheque_banco_deposito", table_name="cheques")
    op.drop_column("cheques", "banco_deposito_id")
