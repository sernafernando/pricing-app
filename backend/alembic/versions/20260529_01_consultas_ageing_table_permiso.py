"""Crear tabla productos_ageing y permiso consultas.ver_ranking (ADMIN only)

Revision ID: 20260529_01_consultas_ageing_table_permiso
Revises: compras_036_ncs_sync_dedup
Create Date: 2026-05-29

Crea la tabla ``productos_ageing`` para almacenar el ageing proveniente del ERP
(independiente de productos_erp para no interferir con hash_datos ni con la
cadencia de sync de cada tabla).

Inserta el permiso ``consultas.ver_ranking`` y lo asigna al rol ADMIN.

ADR-3: tabla separada con PK = item_id (FK lógica a productos_erp.item_id),
ageing_dias INT nullable + ageing_payload JSONB nullable para tolerar respuesta
escalar o multi-bucket de scriptAgeing.

El ranking hace LEFT JOIN a esta tabla — la tabla vacía al lanzar el feature es
comportamiento esperado (las celdas renderizán "—" en FE).

Ver también: 20260529_02_consultas_tit_indexes.py (indexes CONCURRENTLY).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260529_01_consultas_ageing_table_permiso"
down_revision = "compras_036_ncs_sync_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Tabla productos_ageing                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "productos_ageing",
        sa.Column("item_id", sa.Integer(), primary_key=True),
        sa.Column("ageing_dias", sa.Integer(), nullable=True),
        sa.Column("ageing_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fecha_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        comment=(
            "Ageing por ítem proveniente del ERP (sync_ageing.py). "
            "PK = item_id (FK lógica a productos_erp.item_id). "
            "La tabla puede estar vacía en el lanzamiento inicial — el ranking hace LEFT JOIN."
        ),
    )

    # ------------------------------------------------------------------ #
    # 2. Permiso consultas.ver_ranking                                     #
    # ------------------------------------------------------------------ #
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'consultas.ver_ranking',
            'Ver ranking de productos',
            'Acceso a la página de ranking de productos (Consultas): días sin venta, ageing ERP, stock, valuación.',
            'consultas',
            100,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 3. Asignar solo a ADMIN; otros roles se configuran manualmente.
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'consultas.ver_ranking'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    # 1. Limpiar asignaciones de rol
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'consultas.ver_ranking'
        );
    """)

    # 2. Limpiar overrides de usuario (si hay)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'consultas.ver_ranking'
        );
    """)

    # 3. Eliminar el permiso
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'consultas.ver_ranking';
    """)

    # 4. Eliminar la tabla
    op.drop_table("productos_ageing")
