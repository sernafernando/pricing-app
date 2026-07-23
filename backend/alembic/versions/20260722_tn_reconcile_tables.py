"""tn reconcile tables + permission (Slice 1 — read-only reconciliation view)

Revision ID: 20260722_tn_reconcile_tables
Revises: 20260722_ml_bot_messages_responder_permiso
Create Date: 2026-07-22 17:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260722_tn_reconcile_tables"
down_revision = "20260722_ml_bot_messages_responder_permiso"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tn_reconcile_banlist",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("ean", sa.String(length=100), nullable=False, unique=True, index=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "tn_marked_for_deletion",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("ean", sa.String(length=100), nullable=False, unique=True, index=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "tn_reconcile_resolution",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("ean", sa.String(length=100), nullable=False, unique=True, index=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Read permission for Slice 1. Write permissions (`tn.publicar`,
    # `tn.eliminar`) are added in Slices 2 and 4.
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('admin.ver_tn_reconciliacion', 'Ver reconciliación Tienda Nube', 'Ver el reporte de reconciliación GBP vs Tienda Nube', 'administracion', 62, false, NOW()),
            ('admin.gestionar_tn_reconcile_banlist', 'Gestionar banlist de reconciliación TN', 'Agregar y quitar EANs de la banlist de reconciliación Tienda Nube', 'administracion', 63, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo IN ('admin.ver_tn_reconciliacion', 'admin.gestionar_tn_reconcile_banlist')
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos
            WHERE codigo IN ('admin.ver_tn_reconciliacion', 'admin.gestionar_tn_reconcile_banlist')
        );
    """)
    op.execute("""
        DELETE FROM permisos
        WHERE codigo IN ('admin.ver_tn_reconciliacion', 'admin.gestionar_tn_reconcile_banlist');
    """)

    op.drop_table("tn_reconcile_resolution")
    op.drop_table("tn_marked_for_deletion")
    op.drop_table("tn_reconcile_banlist")
