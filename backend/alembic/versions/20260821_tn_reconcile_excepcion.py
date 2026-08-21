"""tn_reconcile_excepcion: accepted anomalies, bound to their evidence

Revision ID: 20260821_tn_reconcile_excepcion
Revises: 20260820_merge_tn_publisher_y_tickets
Create Date: 2026-08-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_tn_reconcile_excepcion"
down_revision: Union[str, None] = "20260820_merge_tn_publisher_y_tickets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tn_reconcile_excepcion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ean", sa.String(length=100), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        # The real key: the fingerprint of the exact situation reviewed.
        # Binding to the EAN would silence a product forever; binding to
        # the evidence means a changed SKU revives the anomaly.
        sa.Column("evidencia", sa.Text(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidencia", name="uq_tn_reconcile_excepcion_evidencia"),
    )
    # Only `ean` gets its own index: the PRIMARY KEY already indexes `id`,
    # and the UNIQUE constraint on `evidencia` already creates the btree
    # that lookups by fingerprint use. Adding either again would be two
    # extra indexes to maintain on every INSERT for nothing.
    op.create_index("ix_tn_reconcile_excepcion_ean", "tn_reconcile_excepcion", ["ean"])

    # Its OWN permission, not the ban list's. Accepting an exception
    # silences a data-quality anomaly — a more consequential call than
    # deciding not to publish something — so it must be grantable to fewer
    # people without taking the rest away.
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES ('admin.gestionar_tn_reconcile_excepciones', 'Gestionar excepciones de reconciliación TN',
                'Aceptar como intencional una anomalía revisada (SKU distinto a propósito, duplicado deliberado)',
                'administracion', 64, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'admin.gestionar_tn_reconcile_excepciones'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'admin.gestionar_tn_reconcile_excepciones'
        );
    """)
    op.execute("DELETE FROM permisos WHERE codigo = 'admin.gestionar_tn_reconcile_excepciones';")
    op.drop_index("ix_tn_reconcile_excepcion_ean", table_name="tn_reconcile_excepcion")
    op.drop_table("tn_reconcile_excepcion")
