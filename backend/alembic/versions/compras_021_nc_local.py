"""compras 021 — tabla notas_credito_local (v2 NCs cargadas en pricing-app)

Revision ID: compras_021_nc_local
Revises: compras_020_ajustar_monto
Create Date: 2026-04-22

Crea la tabla `notas_credito_local` para gestionar NCs de proveedor cargadas
manualmente en el pricing-app, con workflow de aprobación análogo a
`pedidos_compra`. Las NCs se imputan a pedidos/facturas via la tabla
`imputaciones` (combo nuevo `('nota_credito_local', '*')` agregado en el
servicio en este mismo batch).

Schema:
  - id BIGINT PK
  - numero VARCHAR(32) NOT NULL UNIQUE — generado vía numeracion_service
    (formato `NC-XX-YYYY-NNNNN`)
  - empresa_id INTEGER NOT NULL FK empresas
  - proveedor_id INTEGER NOT NULL FK proveedores
  - moneda VARCHAR(3) NOT NULL CHECK IN ('ARS','USD')
  - monto NUMERIC(18,2) NOT NULL CHECK > 0
  - tipo_cambio NUMERIC(18,6) NULL — solo USD
  - fecha_emision DATE NOT NULL — fecha en que el proveedor emitió la NC
  - numero_nc_proveedor VARCHAR(50) NULL — clave de matching contra ERP
  - motivo TEXT NOT NULL
  - observaciones TEXT NULL
  - ct_transaction_id BIGINT NULL — FK lógica a tb_commercial_transactions
  - estado VARCHAR(24) NOT NULL DEFAULT 'borrador'
  - creado_por_id INTEGER NOT NULL FK usuarios ON DELETE RESTRICT
  - aprobado_por_id INTEGER NULL FK usuarios ON DELETE SET NULL
  - created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  - updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

Índices:
  - (empresa_id, estado) → listados con filtro
  - (proveedor_id, estado) → listados por proveedor
  - (proveedor_id, numero_nc_proveedor) WHERE numero_nc_proveedor IS NOT NULL
    → matching automático contra ERP
  - (ct_transaction_id) WHERE ct_transaction_id IS NOT NULL
    → reverse lookup desde sync ERP

Estados (state machine documentada en `ncs_locales_service.transicionar`):
  borrador → pendiente_aprobacion → aprobado → aplicada_parcial → aplicada
                                  → rechazado → borrador (reabrir) | cancelado
                                  → cancelado (cancelar_aprobado: revierte imps)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_021_nc_local"
down_revision: Union[str, None] = "compras_020_ajustar_monto"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notas_credito_local",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("numero", sa.String(length=32), nullable=False),
        sa.Column(
            "empresa_id",
            sa.Integer(),
            sa.ForeignKey("empresas.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("fecha_emision", sa.Date(), nullable=False),
        sa.Column("numero_nc_proveedor", sa.String(length=50), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("ct_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "estado",
            sa.String(length=24),
            nullable=False,
            server_default="borrador",
        ),
        sa.Column(
            "creado_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "aprobado_por_id",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("numero", name="uq_notas_credito_local_numero"),
        sa.CheckConstraint("moneda IN ('ARS','USD')", name="ck_ncs_local_moneda"),
        sa.CheckConstraint("monto > 0", name="ck_ncs_local_monto_positivo"),
        sa.CheckConstraint(
            "estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',"
            "'cancelado','aplicada_parcial','aplicada')",
            name="ck_ncs_local_estado",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notas_credito_local"),
    )

    op.create_index(
        "ix_ncs_local_empresa_estado",
        "notas_credito_local",
        ["empresa_id", "estado"],
    )
    op.create_index(
        "ix_ncs_local_proveedor_estado",
        "notas_credito_local",
        ["proveedor_id", "estado"],
    )
    op.create_index(
        "ix_ncs_local_numero_nc_prov",
        "notas_credito_local",
        ["proveedor_id", "numero_nc_proveedor"],
        postgresql_where=sa.text("numero_nc_proveedor IS NOT NULL"),
    )
    op.create_index(
        "ix_ncs_local_ct_transaction",
        "notas_credito_local",
        ["ct_transaction_id"],
        postgresql_where=sa.text("ct_transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ncs_local_ct_transaction", table_name="notas_credito_local")
    op.drop_index("ix_ncs_local_numero_nc_prov", table_name="notas_credito_local")
    op.drop_index("ix_ncs_local_proveedor_estado", table_name="notas_credito_local")
    op.drop_index("ix_ncs_local_empresa_estado", table_name="notas_credito_local")
    op.drop_table("notas_credito_local")
