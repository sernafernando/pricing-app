"""add granular permissions for exports, modals, and admin roles

Revision ID: 20251216_roles_03
Revises: 20251216_roles_02
Create Date: 2025-12-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251216_roles_03'
down_revision = '20251216_roles_02'
branch_labels = None
depends_on = None

# Nuevos permisos granulares
NUEVOS_PERMISOS = [
    # =========================================================================
    # EXPORTACIÓN PRODUCTOS
    # =========================================================================
    ("productos.exportar_vista_actual", "Exportar vista actual", "Exportar la vista actual de productos a Excel", "productos", 12, False),
    ("productos.exportar_rebate", "Exportar rebate ML", "Exportar lista de rebate para MercadoLibre", "productos", 13, False),
    ("productos.exportar_web_transferencia", "Exportar web transferencia", "Exportar lista de web transferencia", "productos", 14, False),
    ("productos.exportar_clasica", "Exportar clásica/cuotas", "Exportar lista de precios clásica con cuotas", "productos", 15, False),

    # =========================================================================
    # EXPORTACIÓN TIENDA
    # =========================================================================
    ("tienda.exportar_lista_gremio", "Exportar lista gremio", "Exportar lista de precios gremio", "productos", 16, False),
    ("tienda.exportar_lista_tienda", "Exportar lista tienda", "Exportar lista de precios tienda", "productos", 17, False),

    # =========================================================================
    # MODAL INFO PRODUCTO (TABS)
    # =========================================================================
    ("productos.ver_info_basica", "Ver info básica producto", "Acceso al tab de información básica en modal de producto", "productos", 20, False),
    ("productos.ver_info_mercadolibre", "Ver info MercadoLibre", "Acceso al tab de MercadoLibre en modal de producto", "productos", 21, False),
    ("productos.ver_info_ventas", "Ver info ventas producto", "Acceso al tab de ventas en modal de producto", "productos", 22, False),
    ("productos.ver_info_compras", "Ver info compras/proveedor", "Acceso al tab de compras y proveedor en modal de producto", "productos", 23, False),
    ("productos.ver_info_pricing", "Ver info pricing", "Acceso al tab de pricing en modal de producto", "productos", 24, False),

    # =========================================================================
    # EDICIÓN GRANULAR PRODUCTOS
    # =========================================================================
    ("productos.editar_precio_clasica", "Editar precio clásica", "Modificar precio de lista clásica", "productos", 30, False),
    ("productos.editar_precio_cuotas", "Editar precios cuotas", "Modificar precios de cuotas (3, 6, 12)", "productos", 31, False),
    ("productos.toggle_rebate", "Activar/desactivar rebate", "Cambiar estado de rebate individual", "productos", 32, False),
    ("productos.toggle_web_transferencia", "Activar/desactivar web transf", "Cambiar estado de web transferencia individual", "productos", 33, False),
    ("productos.toggle_out_of_cards", "Marcar out of cards", "Marcar/desmarcar producto como out of cards", "productos", 34, False),
    ("productos.marcar_color", "Asignar color individual", "Asignar color a producto individual", "productos", 35, False),
    ("productos.marcar_color_lote", "Asignar color en lote", "Asignar color a múltiples productos", "productos", 36, False),
    ("productos.calcular_web_masivo", "Cálculo web masivo", "Ejecutar cálculo web transferencia masivo", "productos", 37, True),

    # =========================================================================
    # TIENDA - EDICIÓN GRANULAR
    # =========================================================================
    ("tienda.editar_precio_gremio", "Editar precio gremio", "Modificar precio gremio en tienda", "productos", 40, False),
    ("tienda.editar_precio_web_transf", "Editar precio web transf", "Modificar precio web transferencia en tienda", "productos", 41, False),
    ("tienda.toggle_ocultar", "Ocultar productos tienda", "Ocultar/mostrar productos en vista tienda", "productos", 42, False),

    # =========================================================================
    # FILTROS Y VISTAS
    # =========================================================================
    ("productos.ver_filtros_avanzados", "Acceso filtros avanzados", "Usar filtros avanzados en productos", "productos", 50, False),
    ("productos.filtrar_por_auditoria", "Filtrar por auditoría", "Filtrar productos por fecha/usuario de modificación", "productos", 51, False),
    ("productos.ver_costos_detallados", "Ver costos detallados", "Ver desglose completo de costos", "productos", 52, False),

    # =========================================================================
    # ADMINISTRACIÓN DE ROLES
    # =========================================================================
    ("admin.ver_roles", "Ver roles", "Ver configuración de roles del sistema", "administracion", 58, False),
    ("admin.gestionar_roles", "Gestionar roles", "Crear, editar y eliminar roles", "administracion", 59, True),
]


def upgrade():
    # Insertar nuevos permisos
    for codigo, nombre, descripcion, categoria, orden, es_critico in NUEVOS_PERMISOS:
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
            VALUES ('{codigo}', '{nombre}', '{descripcion}', '{categoria}', {orden}, {str(es_critico).lower()})
            ON CONFLICT (codigo) DO NOTHING
        """)

    # Asignar nuevos permisos a roles existentes
    # ADMIN y SUPERADMIN tendrán todos los nuevos permisos (SUPERADMIN es automático en código)

    # Obtener IDs de roles y permisos
    op.execute("""
        -- ADMIN obtiene todos los permisos de exportación, info, edición
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo IN (
            'productos.exportar_vista_actual',
            'productos.exportar_rebate',
            'productos.exportar_web_transferencia',
            'productos.exportar_clasica',
            'tienda.exportar_lista_gremio',
            'tienda.exportar_lista_tienda',
            'productos.ver_info_basica',
            'productos.ver_info_mercadolibre',
            'productos.ver_info_ventas',
            'productos.ver_info_compras',
            'productos.ver_info_pricing',
            'productos.editar_precio_clasica',
            'productos.editar_precio_cuotas',
            'productos.toggle_rebate',
            'productos.toggle_web_transferencia',
            'productos.toggle_out_of_cards',
            'productos.marcar_color',
            'productos.marcar_color_lote',
            'productos.calcular_web_masivo',
            'tienda.editar_precio_gremio',
            'tienda.editar_precio_web_transf',
            'tienda.toggle_ocultar',
            'productos.ver_filtros_avanzados',
            'productos.filtrar_por_auditoria',
            'productos.ver_costos_detallados',
            'admin.ver_roles',
            'admin.gestionar_roles'
        )
        ON CONFLICT DO NOTHING
    """)

    op.execute("""
        -- PRICING obtiene permisos de edición y exportación relevantes
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'PRICING'
        AND p.codigo IN (
            'productos.exportar_vista_actual',
            'productos.exportar_rebate',
            'productos.exportar_web_transferencia',
            'productos.exportar_clasica',
            'productos.ver_info_basica',
            'productos.ver_info_mercadolibre',
            'productos.ver_info_ventas',
            'productos.ver_info_pricing',
            'productos.editar_precio_clasica',
            'productos.editar_precio_cuotas',
            'productos.toggle_rebate',
            'productos.toggle_web_transferencia',
            'productos.toggle_out_of_cards',
            'productos.marcar_color',
            'productos.calcular_web_masivo',
            'productos.ver_filtros_avanzados',
            'productos.filtrar_por_auditoria'
        )
        ON CONFLICT DO NOTHING
    """)

    op.execute("""
        -- GERENTE obtiene permisos de visualización y exportación
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'GERENTE'
        AND p.codigo IN (
            'productos.exportar_vista_actual',
            'productos.exportar_clasica',
            'tienda.exportar_lista_gremio',
            'tienda.exportar_lista_tienda',
            'productos.ver_info_basica',
            'productos.ver_info_mercadolibre',
            'productos.ver_info_ventas',
            'productos.ver_info_compras',
            'productos.ver_info_pricing',
            'productos.ver_filtros_avanzados',
            'productos.ver_costos_detallados'
        )
        ON CONFLICT DO NOTHING
    """)

    op.execute("""
        -- VENTAS obtiene permisos básicos de visualización
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'VENTAS'
        AND p.codigo IN (
            'productos.ver_info_basica',
            'productos.ver_info_mercadolibre'
        )
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    # Eliminar asignaciones de permisos nuevos
    for codigo, _, _, _, _, _ in NUEVOS_PERMISOS:
        op.execute(f"""
            DELETE FROM roles_permisos_base
            WHERE permiso_id = (SELECT id FROM permisos WHERE codigo = '{codigo}')
        """)

    # Eliminar permisos
    for codigo, _, _, _, _, _ in NUEVOS_PERMISOS:
        op.execute(f"DELETE FROM permisos WHERE codigo = '{codigo}'")
