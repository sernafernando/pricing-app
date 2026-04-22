"""compras 019 — tabla compras_adjuntos (adjuntos polimórficos pedidos/OPs)

Revision ID: compras_019_adjuntos
Revises: compras_018_seed_retencion
Create Date: 2026-04-22

Crea la tabla `compras_adjuntos` para guardar archivos asociados a pedidos
de compra y órdenes de pago (facturas, presupuestos, comprobantes). Una
sola tabla polimórfica — discriminador `entidad_tipo` ∈
('pedido_compra', 'orden_pago'). Patrón consistente con `compras_eventos`
y `compras_papelera`.

Schema:
  - id BIGINT PK
  - entidad_tipo VARCHAR(32) NOT NULL — CHECK IN ('pedido_compra','orden_pago')
  - entidad_id BIGINT NOT NULL
  - nombre_archivo VARCHAR(255) NOT NULL — nombre original del archivo
  - path_archivo VARCHAR(500) NOT NULL — path relativo a COMPRAS_UPLOADS_DIR
  - mime_type VARCHAR(100) NULL — lo reporta el cliente, solo informativo
  - tamano_bytes INTEGER NULL
  - tipo VARCHAR(20) NULL — hint: 'factura'|'presupuesto'|'comprobante'|'otro'
  - descripcion TEXT NULL
  - subido_por_id INTEGER NULL FK usuarios ON DELETE SET NULL
  - created_at TIMESTAMPTZ NOT NULL DEFAULT now()

Índices:
  - (entidad_tipo, entidad_id) → listar adjuntos de una entidad
  - (created_at) → orden descendente en UI

NO FK sobre (entidad_tipo, entidad_id) porque es polimórfico. El servicio
valida que la entidad exista antes de insertar.

Los archivos físicos NO se tocan en esta migración: el service los crea
en disco al primer upload. Si en downgrade queda orfandad en disco, es
responsabilidad del operador limpiarla.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_019_adjuntos"
down_revision: Union[str, None] = "compras_018_seed_retencion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compras_adjuntos",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("entidad_tipo", sa.String(length=32), nullable=False),
        sa.Column("entidad_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=255), nullable=False),
        sa.Column("path_archivo", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("tamano_bytes", sa.Integer(), nullable=True),
        sa.Column("tipo", sa.String(length=20), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column(
            "subido_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "entidad_tipo IN ('pedido_compra','orden_pago')",
            name="ck_compras_adjuntos_entidad_tipo",
        ),
        sa.CheckConstraint(
            "tipo IS NULL OR tipo IN ('factura','presupuesto','comprobante','otro')",
            name="ck_compras_adjuntos_tipo",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_compras_adjuntos"),
    )

    op.create_index(
        "ix_compras_adjuntos_entidad",
        "compras_adjuntos",
        ["entidad_tipo", "entidad_id"],
    )
    op.create_index(
        "ix_compras_adjuntos_created_at",
        "compras_adjuntos",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_compras_adjuntos_created_at", table_name="compras_adjuntos")
    op.drop_index("ix_compras_adjuntos_entidad", table_name="compras_adjuntos")
    op.drop_table("compras_adjuntos")
