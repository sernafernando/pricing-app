"""tn publicacion permission (Slice 2 — write infrastructure, unpublish is
the only consumer this slice; publish lands in Slice 3)

One shared permission covers TN publication writes now (unpublish) and
later (publish) — matching the design's intent of a single write-gate
distinct from the Slice 1 read/banlist permissions, following the shipped
`admin.*` naming convention (not the older design doc's `tn.*` names).
`es_critico=True` because it authorizes a real write against the live
Tienda Nube storefront (unlike the local-only banlist permissions).

Revision ID: 20260723_tn_publicacion_permiso
Revises: 20260722_tn_producto_published
Create Date: 2026-07-23 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260723_tn_publicacion_permiso"
down_revision = "20260722_tn_producto_published"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('admin.gestionar_tn_publicacion', 'Gestionar publicación Tienda Nube', 'Publicar/despublicar productos en Tienda Nube', 'administracion', 64, true, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'admin.gestionar_tn_publicacion'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'admin.gestionar_tn_publicacion'
        );
    """)
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'admin.gestionar_tn_publicacion';
    """)
