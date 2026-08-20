"""Add tn-publisher-module tables (PR-4 — measurement profiles)

Three additive tables that make the tn-publish-core blocking gate
survivable: `tn_measurement_profile` (reusable weight/width/height/depth
box profiles, seeded with the four de-facto GBP clusters), `tn_publish_override`
((ean, campo) operator overrides keyed by EAN, per design's `tn_publish_override`
decision), and `tn_category_profile_hint` (per-(categoria, subcategoria) usage-count
suggestion table, per design's suggestion-strength decision).

Also seeds the NEW permission `admin.gestionar_tn_perfiles` (D10) in the same
migration, distinct from `admin.gestionar_tn_publicacion`, following the exact
seeding pattern of `20260723_tn_publicacion_permiso.py`.

Revision ID: 20260818_add_tn_publisher_tables
Revises: 20260813_propuesta_corregida
Create Date: 2026-08-18 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260818_add_tn_publisher_tables"
down_revision = "20260813_propuesta_corregida"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tn_measurement_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("weight", sa.Numeric(10, 3), nullable=False),
        sa.Column("width", sa.Numeric(10, 2), nullable=False),
        sa.Column("height", sa.Numeric(10, 2), nullable=False),
        sa.Column("depth", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "tn_publish_override",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ean", sa.String(100), nullable=False, index=True),
        sa.Column("campo", sa.String(50), nullable=False),
        sa.Column("valor", sa.Text(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ean", "campo", name="uq_tn_publish_override_ean_campo"),
    )

    op.create_table(
        "tn_category_profile_hint",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("categoria", sa.String(150), nullable=False, index=True),
        sa.Column("subcategoria", sa.String(150), nullable=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("tn_measurement_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uso_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("categoria", "subcategoria", "profile_id", name="uq_tn_category_profile_hint"),
    )

    # created_at is deliberately omitted from the seed rows: the column's
    # server_default (func.now()) fills it DB-side, tz-aware. Seeding a
    # Python datetime here would inject a tz-naive value into a
    # timezone-aware column.
    profile_table = sa.table(
        "tn_measurement_profile",
        sa.column("name", sa.String),
        sa.column("weight", sa.Numeric),
        sa.column("width", sa.Numeric),
        sa.column("height", sa.Numeric),
        sa.column("depth", sa.Numeric),
    )
    op.bulk_insert(
        profile_table,
        [
            {"name": "30x20x20", "weight": 0.3, "width": 30, "height": 20, "depth": 20},
            {"name": "30x40x10", "weight": 0.4, "width": 30, "height": 40, "depth": 10},
            {"name": "50x40x20", "weight": 0.6, "width": 50, "height": 40, "depth": 20},
            {"name": "45x55x25", "weight": 0.8, "width": 45, "height": 55, "depth": 25},
        ],
    )

    # D10 — new permission, distinct from admin.gestionar_tn_publicacion,
    # following the exact seeding pattern of 20260723_tn_publicacion_permiso.py.
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('admin.gestionar_tn_perfiles', 'Gestionar perfiles de medidas TN', 'Crear/editar/eliminar perfiles de peso y dimensiones para publicación en Tienda Nube', 'administracion', 65, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'admin.gestionar_tn_perfiles'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'admin.gestionar_tn_perfiles'
        );
    """)
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'admin.gestionar_tn_perfiles';
    """)

    op.drop_table("tn_category_profile_hint")
    op.drop_table("tn_publish_override")
    op.drop_table("tn_measurement_profile")
