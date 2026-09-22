"""compras_044: pipeline tipo, responsable, factura rows

Revision ID: compras_044_pipeline_tipo_responsable_facturas
Revises: compras_043_oc_match_doc_refs_aplicado
Create Date: 2026-09-22

PR1 of compras-ops-pipeline-ux. Main already consumed compras_042 / compras_043
for doc-refs; this revision is the pipeline schema (was design.md compras_042).

  * pedidos_compra.tipo IN (mercaderia, servicio), default mercaderia
  * pedidos_compra.responsable_id FK usuarios, backfill creado_por_id, NOT NULL
  * pedidos_compra.faltantes_resuelto_en (nullable TZ) for later eje_procesal
  * pedido_factura_documentos + seed from facturas_documento ';' tokens
  * raw facturas_documento is kept; pedidos_documento is not used as identity
"""

from typing import Optional, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "compras_044_pipeline_tipo_responsable_facturas"
down_revision: Union[str, None] = "compras_043_oc_match_doc_refs_aplicado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _split_facturas_documento_tokens(raw: Optional[str]) -> list[str]:
    """Split `facturas_documento` on `;`, trim, drop empties (mirrors service)."""
    if not raw:
        return []
    return [part.strip() for part in raw.split(";") if part.strip()]


def upgrade() -> None:
    op.add_column(
        "pedidos_compra",
        sa.Column(
            "tipo",
            sa.String(length=16),
            nullable=False,
            server_default="mercaderia",
        ),
    )
    op.create_check_constraint(
        "ck_pedidos_compra_tipo",
        "pedidos_compra",
        "tipo IN ('mercaderia','servicio')",
    )

    op.add_column(
        "pedidos_compra",
        sa.Column("responsable_id", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE pedidos_compra SET responsable_id = creado_por_id WHERE responsable_id IS NULL")
    op.alter_column("pedidos_compra", "responsable_id", nullable=False)
    op.create_foreign_key(
        "fk_pedidos_compra_responsable_id",
        "pedidos_compra",
        "usuarios",
        ["responsable_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_pedidos_compra_responsable_id",
        "pedidos_compra",
        ["responsable_id"],
    )

    op.add_column(
        "pedidos_compra",
        sa.Column("faltantes_resuelto_en", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "pedido_factura_documentos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("pedido_id", sa.BigInteger(), nullable=False),
        sa.Column("numero", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pedido_id"],
            ["pedidos_compra.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["usuarios.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_pedido_factura_documentos_pedido_id",
        "pedido_factura_documentos",
        ["pedido_id"],
    )
    op.create_index(
        "ix_pedido_factura_documentos_id",
        "pedido_factura_documentos",
        ["id"],
    )

    bind = op.get_bind()
    source_rows = bind.execute(sa.text("SELECT id, facturas_documento, creado_por_id FROM pedidos_compra")).fetchall()
    seed_params: list[dict[str, object]] = []
    for pedido_id, raw, creado_por_id in source_rows:
        for numero in _split_facturas_documento_tokens(raw):
            seed_params.append(
                {
                    "pedido_id": pedido_id,
                    "numero": numero,
                    "created_by_id": creado_por_id,
                }
            )
    if seed_params:
        bind.execute(
            sa.text(
                "INSERT INTO pedido_factura_documentos "
                "(pedido_id, numero, created_by_id) "
                "VALUES (:pedido_id, :numero, :created_by_id)"
            ),
            seed_params,
        )


def downgrade() -> None:
    op.drop_index("ix_pedido_factura_documentos_id", table_name="pedido_factura_documentos")
    op.drop_index("ix_pedido_factura_documentos_pedido_id", table_name="pedido_factura_documentos")
    op.drop_table("pedido_factura_documentos")
    op.drop_column("pedidos_compra", "faltantes_resuelto_en")
    op.drop_index("ix_pedidos_compra_responsable_id", table_name="pedidos_compra")
    op.drop_constraint("fk_pedidos_compra_responsable_id", "pedidos_compra", type_="foreignkey")
    op.drop_column("pedidos_compra", "responsable_id")
    op.drop_constraint("ck_pedidos_compra_tipo", "pedidos_compra", type_="check")
    op.drop_column("pedidos_compra", "tipo")
