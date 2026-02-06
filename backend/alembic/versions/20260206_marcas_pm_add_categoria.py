"""add categoria column to marcas_pm and change unique constraint from (marca) to (marca, categoria)

Revision ID: 20260206_marcas_pm_cat
Revises: 20260206_comp_banlist
Create Date: 2026-02-06 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '20260206_marcas_pm_cat'
down_revision = '20260206_comp_banlist'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Agregar columna categoria (nullable temporalmente para la migración de datos)
    op.add_column('marcas_pm', sa.Column('categoria', sa.String(100), nullable=True))

    # 2. Quitar constraint UNIQUE viejo de solo marca
    op.drop_constraint('marcas_pm_marca_key', 'marcas_pm', type_='unique')

    # 3. Migrar datos: expandir cada marca a sus pares (marca, categoria) desde productos_erp
    #    Cada registro existente se elimina y se reemplaza por N registros (uno por categoría)
    conn = op.get_bind()

    # Crear tabla temporal con pares expandidos
    conn.execute(text("""
        CREATE TEMP TABLE _marcas_pm_expanded AS
        SELECT DISTINCT
            mp.marca,
            p.categoria,
            mp.usuario_id,
            mp.fecha_asignacion,
            mp.fecha_modificacion
        FROM marcas_pm mp
        JOIN productos_erp p ON UPPER(p.marca) = UPPER(mp.marca)
        WHERE p.categoria IS NOT NULL
    """))

    # Borrar registros viejos
    conn.execute(text("DELETE FROM marcas_pm"))

    # Insertar los expandidos
    conn.execute(text("""
        INSERT INTO marcas_pm (marca, categoria, usuario_id, fecha_asignacion, fecha_modificacion)
        SELECT marca, categoria, usuario_id, fecha_asignacion, fecha_modificacion
        FROM _marcas_pm_expanded
    """))

    # Limpiar
    conn.execute(text("DROP TABLE _marcas_pm_expanded"))

    # 4. Hacer categoria NOT NULL
    op.alter_column('marcas_pm', 'categoria', nullable=False)

    # 5. Agregar constraint UNIQUE nuevo (marca, categoria)
    op.create_unique_constraint('marcas_pm_marca_categoria_key', 'marcas_pm', ['marca', 'categoria'])

    # 6. Agregar índice para categoria
    op.create_index('idx_marcas_pm_categoria', 'marcas_pm', ['categoria'])


def downgrade():
    # ADVERTENCIA: downgrade pierde datos (colapsa categorías de vuelta a solo marcas)
    # Se mantiene un solo registro por marca (el primero encontrado)

    # 1. Quitar índice y constraint nuevo
    op.drop_index('idx_marcas_pm_categoria', table_name='marcas_pm')
    op.drop_constraint('marcas_pm_marca_categoria_key', 'marcas_pm', type_='unique')

    # 2. Colapsar: quedarse con un registro por marca (el de menor id)
    conn = op.get_bind()
    conn.execute(text("""
        DELETE FROM marcas_pm
        WHERE id NOT IN (
            SELECT MIN(id) FROM marcas_pm GROUP BY marca
        )
    """))

    # 3. Quitar columna categoria
    op.drop_column('marcas_pm', 'categoria')

    # 4. Restaurar constraint UNIQUE original
    op.create_unique_constraint('marcas_pm_marca_key', 'marcas_pm', ['marca'])
