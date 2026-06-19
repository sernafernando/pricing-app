"""Módulo de Cheques — tablas, constraints, índices y permiso seed.

Crea:
  - chequeras: libretas de cheques de banco propio.
  - cheques: esquema COMPLETO para todos los slices (no re-migrar entre slices).
  - orden_pago_cheque: enlace cheque↔OP.
  - cheque_evento: auditoría append-only.

Seed: permiso `tesoreria.gestionar_cheques` (sin asignar a rol — se asigna
vía override de usuario o asignación manual desde la UI de permisos).

Operación: no destructiva — no toca tablas existentes.
FKs nuevas referencian: bancos_empresa, usuarios, chequeras, ordenes_pago, proveedores.

Revision ID: 20260619_cheques_modulo
Revises: 20260618_recepcion_deposito
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "20260619_cheques_modulo"
down_revision = "20260618_recepcion_deposito"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────────
    # 1. TABLE chequeras
    # ──────────────────────────────────────────────────────────────────────
    op.create_table(
        "chequeras",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "banco_empresa_id",
            sa.Integer,
            sa.ForeignKey("bancos_empresa.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("descripcion", sa.String(120), nullable=True),
        sa.Column("instrumento", sa.String(10), nullable=False, server_default="fisico"),
        sa.Column("numero_desde", sa.BigInteger, nullable=True),
        sa.Column("numero_hasta", sa.BigInteger, nullable=True),
        sa.Column("proximo_numero", sa.BigInteger, nullable=True),
        sa.Column("activa", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.CheckConstraint("instrumento IN ('fisico', 'echeq')", name="ck_chequera_instrumento"),
    )
    op.create_index("ix_chequera_banco", "chequeras", ["banco_empresa_id"])

    # ──────────────────────────────────────────────────────────────────────
    # 2. TABLE cheques  (esquema COMPLETO — todos los slices)
    # ──────────────────────────────────────────────────────────────────────
    op.create_table(
        "cheques",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # Identidad
        sa.Column("tipo", sa.String(10), nullable=False),  # 'propio' | 'tercero'
        sa.Column("instrumento", sa.String(10), nullable=False, server_default="fisico"),
        sa.Column("estado", sa.String(20), nullable=False),
        # Datos del cheque
        sa.Column("numero", sa.String(40), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="ARS"),
        sa.Column("fecha_emision", sa.Date, nullable=False),
        sa.Column("fecha_pago", sa.Date, nullable=False),
        sa.Column("es_diferido", sa.Boolean, nullable=False, server_default="false"),
        # Propios
        sa.Column(
            "banco_empresa_id",
            sa.Integer,
            sa.ForeignKey("bancos_empresa.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "chequera_id",
            sa.BigInteger,
            sa.ForeignKey("chequeras.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        # Terceros
        sa.Column("banco_nombre", sa.String(120), nullable=True),
        sa.Column("cuit_librador", sa.String(13), nullable=True),
        sa.Column("librador_nombre", sa.String(160), nullable=True),
        # Pago / imputación
        sa.Column(
            "proveedor_id",
            sa.Integer,
            sa.ForeignKey("proveedores.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "orden_pago_id",
            sa.Integer,
            sa.ForeignKey("ordenes_pago.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Auditoría
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("motivo_anulacion", sa.Text, nullable=True),
        # Constraints
        sa.CheckConstraint("tipo IN ('propio', 'tercero')", name="ck_cheque_tipo"),
        sa.CheckConstraint("instrumento IN ('fisico', 'echeq')", name="ck_cheque_instrumento"),
        sa.CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_cheque_moneda"),
        sa.CheckConstraint("fecha_pago >= fecha_emision", name="ck_cheque_fechas"),
    )
    # Partial unique index: enforce uniqueness only where chequera_id IS NOT NULL
    op.create_index(
        "uq_cheque_chequera_numero",
        "cheques",
        ["chequera_id", "numero"],
        unique=True,
        postgresql_where=sa.text("chequera_id IS NOT NULL"),
    )
    op.create_index("ix_cheque_tipo_estado", "cheques", ["tipo", "estado"])
    op.create_index("ix_cheque_proveedor", "cheques", ["proveedor_id"])
    op.create_index("ix_cheque_estado_fecha_pago", "cheques", ["estado", "fecha_pago"])
    op.create_index("ix_cheque_banco_empresa", "cheques", ["banco_empresa_id"])

    # ──────────────────────────────────────────────────────────────────────
    # 3. TABLE orden_pago_cheque  (link cheque↔OP, Slice 1)
    # ──────────────────────────────────────────────────────────────────────
    op.create_table(
        "orden_pago_cheque",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "orden_pago_id",
            sa.Integer,
            sa.ForeignKey("ordenes_pago.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cheque_id",
            sa.BigInteger,
            sa.ForeignKey("cheques.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,  # un cheque cubre una sola OP activa
        ),
        sa.Column("monto_op_moneda", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_opc_orden_pago", "orden_pago_cheque", ["orden_pago_id"])

    # ──────────────────────────────────────────────────────────────────────
    # 4. TABLE cheque_evento  (append-only, auditoría + hook GL futuro)
    # ──────────────────────────────────────────────────────────────────────
    op.create_table(
        "cheque_evento",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "cheque_id",
            sa.BigInteger,
            sa.ForeignKey("cheques.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column(
            "usuario_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_cheque_evento_cheque", "cheque_evento", ["cheque_id"])

    # ──────────────────────────────────────────────────────────────────────
    # 5. Seed permiso tesoreria.gestionar_cheques
    #    Sin asignar a ningún rol — el SUPERADMIN lo asigna explícitamente.
    # ──────────────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'tesoreria.gestionar_cheques',
            'Gestionar cheques',
            'Emitir, anular y gestionar cheques propios y de terceros en el módulo de tesorería.',
            'tesoreria',
            300,
            true,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)


def downgrade() -> None:
    # Remove permission seed
    op.execute("DELETE FROM permisos WHERE codigo = 'tesoreria.gestionar_cheques'")

    # Drop tables in reverse dependency order
    op.drop_index("ix_cheque_evento_cheque", table_name="cheque_evento")
    op.drop_table("cheque_evento")

    op.drop_index("ix_opc_orden_pago", table_name="orden_pago_cheque")
    op.drop_table("orden_pago_cheque")

    op.drop_index("ix_cheque_banco_empresa", table_name="cheques")
    op.drop_index("ix_cheque_estado_fecha_pago", table_name="cheques")
    op.drop_index("ix_cheque_proveedor", table_name="cheques")
    op.drop_index("ix_cheque_tipo_estado", table_name="cheques")
    op.drop_index("uq_cheque_chequera_numero", table_name="cheques")
    op.drop_table("cheques")

    op.drop_index("ix_chequera_banco", table_name="chequeras")
    op.drop_table("chequeras")
