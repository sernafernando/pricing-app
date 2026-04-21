"""compras 016 — tabla compras_papelera (hard-delete auditable)

Revision ID: compras_016_papelera
Revises: compras_015_pedidos_tc
Create Date: 2026-04-21

Crea la tabla `compras_papelera` para el hard-delete auditable de basura
(pedidos borrador/cancelados sin movimiento y OPs anuladas sin imputaciones
activas). Estrategia: al eliminar físicamente la entidad de su tabla, se
guarda un snapshot JSONB completo + metadata de auditoría en esta tabla.

Campos clave:
  - entidad_tipo: 'pedido_compra' | 'orden_pago'
  - entidad_id_original: ID que tenía en su tabla (no es FK, la fila fue borrada)
  - snapshot: JSONB con TODOS los campos + eventos copiados (opción B)
  - eliminado_por_id: FK a usuarios (RESTRICT — no perdemos trazabilidad)
  - motivo: texto libre obligatorio (validado en service)
  - challenge_palabra: palabra random que el usuario tipeó al confirmar
  - estado_original: estado que tenía la entidad al momento del borrado

APPEND-ONLY: esta tabla es append-only (igual que compras_eventos). No hay
endpoints PUT/DELETE sobre ella. Si alguna vez hay que limpiar >1 año,
hacerlo vía cron que logee qué se borró.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "compras_016_papelera"
down_revision: Union[str, None] = "compras_015_pedidos_tc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compras_papelera",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("entidad_tipo", sa.String(length=32), nullable=False),
        sa.Column("entidad_id_original", sa.BigInteger(), nullable=False),
        sa.Column("numero", sa.String(length=32), nullable=True),
        sa.Column(
            "empresa_id",
            sa.Integer(),
            sa.ForeignKey("empresas.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column(
            "eliminado_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("challenge_palabra", sa.String(length=64), nullable=True),
        sa.Column("estado_original", sa.String(length=24), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "entidad_tipo IN ('pedido_compra','orden_pago')",
            name="ck_compras_papelera_entidad_tipo",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_compras_papelera"),
    )

    op.create_index(
        "ix_compras_papelera_entidad",
        "compras_papelera",
        ["entidad_tipo", "entidad_id_original"],
    )
    op.create_index(
        "ix_compras_papelera_created",
        "compras_papelera",
        ["created_at"],
    )
    op.create_index(
        "ix_compras_papelera_proveedor",
        "compras_papelera",
        ["proveedor_id"],
        postgresql_where=sa.text("proveedor_id IS NOT NULL"),
    )
    op.create_index(
        "ix_compras_papelera_eliminado_por",
        "compras_papelera",
        ["eliminado_por_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_compras_papelera_eliminado_por", table_name="compras_papelera")
    op.drop_index("ix_compras_papelera_proveedor", table_name="compras_papelera")
    op.drop_index("ix_compras_papelera_created", table_name="compras_papelera")
    op.drop_index("ix_compras_papelera_entidad", table_name="compras_papelera")
    op.drop_table("compras_papelera")
