"""compras 004 — compras_eventos (polimórfica, reemplaza pedido_compra_eventos)

Revision ID: compras_004_evt
Revises: compras_003_ped
Create Date: 2026-04-17

Tabla única polimórfica (D2) para eventos de pedidos Y órdenes de pago.
Append-only por convención de servicio: no se exponen endpoints PUT/DELETE.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "compras_004_evt"
down_revision: Union[str, None] = "compras_003_ped"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compras_eventos",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("entidad_tipo", sa.String(length=32), nullable=False),
        sa.Column("entidad_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=48), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_compras_eventos_usuario",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "entidad_tipo IN ('pedido_compra','orden_pago')",
            name="ck_compras_eventos_entidad_tipo",
        ),
    )
    op.create_index(
        "ix_compras_eventos_entidad",
        "compras_eventos",
        ["entidad_tipo", "entidad_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_compras_eventos_tipo", "compras_eventos", ["tipo"])


def downgrade() -> None:
    op.drop_index("ix_compras_eventos_tipo", table_name="compras_eventos")
    op.drop_index("ix_compras_eventos_entidad", table_name="compras_eventos")
    op.drop_table("compras_eventos")
