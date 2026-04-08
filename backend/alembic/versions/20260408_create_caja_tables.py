"""Create caja tables — cash register module

Creates 7 tables for the administration caja module:
- cajas: cash register headers (per empresa + moneda)
- caja_movimientos: income/expense movements with running balance
- caja_categorias: movement categories (global)
- caja_tipo_documentos: configurable document types
- caja_documentos: documents linked to movements (N:M)
- caja_documento_movimientos: junction table for document-movement links
- caja_archivos: file attachments on documents

Revision ID: 20260408_caja
Revises: 20260407_doc_fecha
Create Date: 2026-04-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260408_caja"
down_revision = "20260407_doc_fecha"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cajas ─────────────────────────────────────────────────────
    op.create_table(
        "cajas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("empresas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("moneda", sa.String(10), nullable=False, server_default="ARS"),
        sa.Column("saldo_inicial", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("saldo_actual", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("nombre", "empresa_id", name="uq_caja_nombre_empresa"),
    )
    op.create_index("ix_cajas_empresa_id", "cajas", ["empresa_id"])

    # ── caja_categorias ──────────────────────────────────────────
    op.create_table(
        "caja_categorias",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(100), nullable=False, unique=True),
        sa.Column("tipo_aplicable", sa.String(20), nullable=False, server_default="ambos"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── caja_movimientos ─────────────────────────────────────────
    op.create_table(
        "caja_movimientos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("caja_id", sa.Integer(), sa.ForeignKey("cajas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("saldo_posterior", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "categoria_id",
            sa.Integer(),
            sa.ForeignKey("caja_categorias.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("origen", sa.String(20), nullable=False, server_default="manual"),
        sa.Column(
            "registrado_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("monto > 0", name="ck_caja_mov_monto_positivo"),
    )
    op.create_index("ix_caja_mov_caja_fecha", "caja_movimientos", ["caja_id", "fecha"])
    op.create_index("ix_caja_mov_caja_tipo", "caja_movimientos", ["caja_id", "tipo"])
    op.create_index("ix_caja_mov_categoria", "caja_movimientos", ["categoria_id"])

    # ── caja_tipo_documentos ─────────────────────────────────────
    op.create_table(
        "caja_tipo_documentos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(100), nullable=False, unique=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── caja_documentos ──────────────────────────────────────────
    op.create_table(
        "caja_documentos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tipo_documento_id",
            sa.Integer(),
            sa.ForeignKey("caja_tipo_documentos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("numero", sa.String(255), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("fecha_documento", sa.Date(), nullable=True),
        sa.Column("monto_documento", sa.Numeric(18, 2), nullable=True),
        sa.Column("entidad_tipo", sa.String(50), nullable=True),
        sa.Column("entidad_id", sa.Integer(), nullable=True),
        sa.Column(
            "registrado_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_caja_doc_tipo_documento_id", "caja_documentos", ["tipo_documento_id"])
    op.create_index("ix_caja_doc_entidad", "caja_documentos", ["entidad_tipo", "entidad_id"])

    # ── caja_documento_movimientos (junction N:M) ────────────────
    op.create_table(
        "caja_documento_movimientos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "documento_id",
            sa.Integer(),
            sa.ForeignKey("caja_documentos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "movimiento_id",
            sa.Integer(),
            sa.ForeignKey("caja_movimientos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("documento_id", "movimiento_id", name="uq_caja_doc_mov"),
    )
    op.create_index("ix_caja_doc_mov_documento_id", "caja_documento_movimientos", ["documento_id"])
    op.create_index("ix_caja_doc_mov_movimiento_id", "caja_documento_movimientos", ["movimiento_id"])

    # ── caja_archivos ────────────────────────────────────────────
    op.create_table(
        "caja_archivos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "documento_id",
            sa.Integer(),
            sa.ForeignKey("caja_documentos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nombre_archivo", sa.String(500), nullable=False),
        sa.Column("ruta_archivo", sa.String(1000), nullable=False),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamanio_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "registrado_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_caja_archivos_documento_id", "caja_archivos", ["documento_id"])


def downgrade() -> None:
    op.drop_table("caja_archivos")
    op.drop_table("caja_documento_movimientos")
    op.drop_table("caja_documentos")
    op.drop_table("caja_tipo_documentos")
    op.drop_table("caja_movimientos")
    op.drop_table("caja_categorias")
    op.drop_table("cajas")
