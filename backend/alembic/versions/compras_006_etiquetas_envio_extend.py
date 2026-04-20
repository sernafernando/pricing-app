"""compras 006 — etiquetas_envio extend (retiro proveedor)

Revision ID: compras_006_et
Revises: compras_005_op
Create Date: 2026-04-17

Agrega 4 columnas a `etiquetas_envio` para soportar envíos de retiro
en proveedor (`tipo_envio='retiro_proveedor'`). Migración en 1 paso
porque la verificación COMPRAS-0.4 confirmó que `cliente_id` NO existe
como columna en la tabla actual (no hay que hacer DROP NOT NULL).

Backward-compatible: `tipo_envio` tiene DEFAULT 'cliente' y las FKs
nuevas son nullables, así que filas existentes quedan con la semántica
original sin cambios.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_006_et"
down_revision: Union[str, None] = "compras_005_op"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "etiquetas_envio",
        sa.Column(
            "tipo_envio",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'cliente'"),
        ),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("proveedor_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("proveedor_direccion_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("pedido_compra_id", sa.BigInteger(), nullable=True),
    )

    # Backfill explícito (aunque el default ya lo cubre) para auditoría.
    op.execute("UPDATE etiquetas_envio SET tipo_envio = 'cliente' WHERE tipo_envio IS NULL")

    op.create_foreign_key(
        "fk_etiquetas_envio_proveedor",
        "etiquetas_envio",
        "proveedores",
        ["proveedor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_etiquetas_envio_proveedor_direccion",
        "etiquetas_envio",
        "proveedor_direcciones",
        ["proveedor_direccion_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_etiquetas_envio_pedido_compra",
        "etiquetas_envio",
        "pedidos_compra",
        ["pedido_compra_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_etiqueta_envio_tipo_envio",
        "etiquetas_envio",
        "tipo_envio IN ('cliente','retiro_proveedor')",
    )
    op.create_check_constraint(
        "chk_etiqueta_envio_tipo_coherencia",
        "etiquetas_envio",
        "(tipo_envio = 'cliente' "
        "AND proveedor_id IS NULL "
        "AND proveedor_direccion_id IS NULL "
        "AND pedido_compra_id IS NULL) "
        "OR (tipo_envio = 'retiro_proveedor' "
        "AND proveedor_id IS NOT NULL "
        "AND pedido_compra_id IS NOT NULL)",
    )

    op.create_index(
        "ix_etiquetas_envio_pedido",
        "etiquetas_envio",
        ["pedido_compra_id"],
        postgresql_where=sa.text("pedido_compra_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_etiquetas_envio_pedido", table_name="etiquetas_envio")
    op.drop_constraint(
        "chk_etiqueta_envio_tipo_coherencia",
        "etiquetas_envio",
        type_="check",
    )
    op.drop_constraint("ck_etiqueta_envio_tipo_envio", "etiquetas_envio", type_="check")
    op.drop_constraint(
        "fk_etiquetas_envio_pedido_compra",
        "etiquetas_envio",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_etiquetas_envio_proveedor_direccion",
        "etiquetas_envio",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_etiquetas_envio_proveedor",
        "etiquetas_envio",
        type_="foreignkey",
    )
    op.drop_column("etiquetas_envio", "pedido_compra_id")
    op.drop_column("etiquetas_envio", "proveedor_direccion_id")
    op.drop_column("etiquetas_envio", "proveedor_id")
    op.drop_column("etiquetas_envio", "tipo_envio")
