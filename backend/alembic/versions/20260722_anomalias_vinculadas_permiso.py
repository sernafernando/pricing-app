"""add admin.ver_anomalias_vinculadas permiso

Revision ID: 20260722_anomalias_vinc
Revises: 20260721_ml_publication_links
Create Date: 2026-07-22 00:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260722_anomalias_vinc"
down_revision = "20260721_ml_publication_links"
branch_labels = None
depends_on = None


def upgrade():
    # Insertar el nuevo permiso para el tab de anomalías vinculadas
    # (productos-catalog-family-tree, tramo de cierre)
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('admin.ver_anomalias_vinculadas', 'Ver anomalías vinculadas', 'Ver publicaciones ML vinculadas con item_id cruzado o irresolubles (mispublicaciones a corregir)', 'administracion', 62, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Asignar el permiso a ADMIN y GERENTE, igual que admin.ver_comparacion_listas_ml
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo IN ('ADMIN', 'GERENTE')
        AND p.codigo = 'admin.ver_anomalias_vinculadas'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'admin.ver_anomalias_vinculadas'
        );
    """)

    op.execute("""
        DELETE FROM permisos WHERE codigo = 'admin.ver_anomalias_vinculadas';
    """)
