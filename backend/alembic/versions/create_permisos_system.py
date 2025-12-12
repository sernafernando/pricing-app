"""Create permisos system tables

Revision ID: create_permisos_system
Revises: add_monto_consumido_to_offsets, add_override_fields
Create Date: 2025-12-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_permisos_system'
down_revision = ('add_monto_consumido_to_offsets', 'add_override_fields')
branch_labels = None
depends_on = None


def upgrade():
    # Tabla de permisos (catálogo)
    op.create_table(
        'permisos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('codigo', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('nombre', sa.String(255), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('categoria', sa.String(50), nullable=False),
        sa.Column('orden', sa.Integer(), default=0),
        sa.Column('es_critico', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'))
    )

    # Tabla de permisos base por rol
    op.create_table(
        'roles_permisos_base',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rol', sa.String(50), nullable=False, index=True),
        sa.Column('permiso_id', sa.Integer(), sa.ForeignKey('permisos.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('rol', 'permiso_id', name='uq_rol_permiso')
    )

    # Tabla de overrides por usuario
    op.create_table(
        'usuarios_permisos_override',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('usuario_id', sa.Integer(), sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('permiso_id', sa.Integer(), sa.ForeignKey('permisos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('concedido', sa.Boolean(), nullable=False),
        sa.Column('otorgado_por_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=True),
        sa.Column('motivo', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('usuario_id', 'permiso_id', name='uq_usuario_permiso')
    )

    # Insertar permisos del catálogo
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico) VALUES
        -- PRODUCTOS
        ('productos.ver', 'Ver productos', 'Acceso a la lista de productos y sus detalles', 'productos', 1, false),
        ('productos.editar_precios', 'Editar precios', 'Modificar precios clásica, cuotas y web transferencia', 'productos', 2, false),
        ('productos.editar_rebate', 'Gestionar Rebate', 'Activar/desactivar rebate y modificar porcentaje', 'productos', 3, false),
        ('productos.editar_web_transferencia', 'Gestionar Web Transferencia', 'Activar/desactivar web transferencia y modificar porcentaje', 'productos', 4, false),
        ('productos.editar_out_of_cards', 'Marcar Out of Cards', 'Marcar/desmarcar productos como out of cards', 'productos', 5, false),
        ('productos.banear', 'Banear productos', 'Agregar productos a la banlist', 'productos', 6, true),
        ('productos.exportar', 'Exportar productos', 'Exportar listado de productos a Excel', 'productos', 7, false),
        ('productos.ver_costos', 'Ver costos', 'Ver columnas de costo en productos', 'productos', 8, false),
        ('productos.ver_auditoria', 'Ver auditoría de productos', 'Ver historial de cambios por producto', 'productos', 9, false),

        -- VENTAS ML
        ('ventas_ml.ver_dashboard', 'Ver dashboard ML', 'Acceso al dashboard de métricas de MercadoLibre', 'ventas_ml', 10, false),
        ('ventas_ml.ver_operaciones', 'Ver operaciones ML', 'Ver detalle de operaciones de venta ML', 'ventas_ml', 11, false),
        ('ventas_ml.ver_rentabilidad', 'Ver rentabilidad ML', 'Acceso a la pestaña de rentabilidad ML', 'ventas_ml', 12, false),
        ('ventas_ml.ver_todas_marcas', 'Ver todas las marcas ML', 'Ver datos de todas las marcas (no solo las asignadas)', 'ventas_ml', 13, false),

        -- VENTAS FUERA ML
        ('ventas_fuera.ver_dashboard', 'Ver dashboard Fuera ML', 'Acceso al dashboard de ventas por fuera de ML', 'ventas_fuera', 20, false),
        ('ventas_fuera.ver_operaciones', 'Ver operaciones Fuera ML', 'Ver detalle de operaciones fuera de ML', 'ventas_fuera', 21, false),
        ('ventas_fuera.ver_rentabilidad', 'Ver rentabilidad Fuera ML', 'Acceso a la pestaña de rentabilidad fuera de ML', 'ventas_fuera', 22, false),
        ('ventas_fuera.editar_overrides', 'Editar datos de ventas Fuera ML', 'Modificar cliente, marca, categoría y otros campos de operaciones', 'ventas_fuera', 23, false),
        ('ventas_fuera.editar_costos', 'Editar costos Fuera ML', 'Modificar costos de operaciones fuera de ML', 'ventas_fuera', 24, false),
        ('ventas_fuera.ver_admin', 'Acceso admin Fuera ML', 'Acceso a la pestaña de administración fuera de ML', 'ventas_fuera', 25, false),

        -- VENTAS TIENDA NUBE
        ('ventas_tn.ver_dashboard', 'Ver dashboard Tienda Nube', 'Acceso al dashboard de ventas Tienda Nube', 'ventas_tn', 30, false),
        ('ventas_tn.ver_operaciones', 'Ver operaciones Tienda Nube', 'Ver detalle de operaciones Tienda Nube', 'ventas_tn', 31, false),
        ('ventas_tn.ver_rentabilidad', 'Ver rentabilidad Tienda Nube', 'Acceso a la pestaña de rentabilidad Tienda Nube', 'ventas_tn', 32, false),
        ('ventas_tn.editar_overrides', 'Editar datos de ventas TN', 'Modificar cliente, marca, categoría y otros campos de operaciones TN', 'ventas_tn', 33, false),
        ('ventas_tn.ver_admin', 'Acceso admin Tienda Nube', 'Acceso a la pestaña de administración Tienda Nube', 'ventas_tn', 34, false),

        -- REPORTES
        ('reportes.ver_auditoria', 'Ver auditoría general', 'Acceso a /ultimos-cambios con historial de modificaciones', 'reportes', 40, false),
        ('reportes.ver_notificaciones', 'Ver notificaciones', 'Acceso a las notificaciones del sistema', 'reportes', 41, false),
        ('reportes.ver_calculadora', 'Usar calculadora', 'Acceso a la calculadora de pricing', 'reportes', 42, false),
        ('reportes.exportar', 'Exportar reportes', 'Exportar datos de reportes a Excel', 'reportes', 43, false),

        -- ADMINISTRACIÓN
        ('admin.ver_panel', 'Ver panel de administración', 'Acceso al panel de administración', 'administracion', 50, false),
        ('admin.gestionar_usuarios', 'Gestionar usuarios', 'Crear, editar y desactivar usuarios', 'administracion', 51, true),
        ('admin.gestionar_permisos', 'Gestionar permisos', 'Modificar permisos de usuarios', 'administracion', 52, true),
        ('admin.gestionar_pms', 'Gestionar Product Managers', 'Asignar marcas a Product Managers', 'administracion', 53, false),
        ('admin.sincronizar', 'Ejecutar sincronizaciones', 'Ejecutar sincronización de datos externos', 'administracion', 54, false),
        ('admin.limpieza_masiva', 'Limpieza masiva de datos', 'Ejecutar limpieza masiva de rebate/web transferencia', 'administracion', 55, true),
        ('admin.gestionar_banlist', 'Gestionar banlist', 'Agregar y quitar items de la banlist', 'administracion', 56, false),
        ('admin.gestionar_mla_banlist', 'Gestionar MLA banlist', 'Agregar y quitar MLAs de la banlist', 'administracion', 57, false),

        -- CONFIGURACIÓN
        ('config.ver_comisiones', 'Ver comisiones', 'Ver configuración de comisiones ML', 'configuracion', 60, false),
        ('config.editar_comisiones', 'Editar comisiones', 'Crear nuevas versiones de comisiones', 'configuracion', 61, true),
        ('config.ver_constantes', 'Ver constantes de pricing', 'Ver configuración de constantes (tiers, varios, etc.)', 'configuracion', 62, false),
        ('config.editar_constantes', 'Editar constantes de pricing', 'Crear nuevas versiones de constantes', 'configuracion', 63, true),
        ('config.ver_tipo_cambio', 'Ver tipo de cambio', 'Ver cotización actual del dólar', 'configuracion', 64, false)
    """)

    # Insertar permisos base por rol
    # SUPERADMIN - todos los permisos
    op.execute("""
        INSERT INTO roles_permisos_base (rol, permiso_id)
        SELECT 'SUPERADMIN', id FROM permisos
    """)

    # ADMIN - casi todos (excepto los que serán específicos de SUPERADMIN en el futuro)
    op.execute("""
        INSERT INTO roles_permisos_base (rol, permiso_id)
        SELECT 'ADMIN', id FROM permisos
    """)

    # GERENTE
    op.execute("""
        INSERT INTO roles_permisos_base (rol, permiso_id)
        SELECT 'GERENTE', id FROM permisos WHERE codigo IN (
            'productos.ver',
            'productos.ver_costos',
            'productos.ver_auditoria',
            'productos.exportar',
            'ventas_ml.ver_dashboard',
            'ventas_ml.ver_operaciones',
            'ventas_ml.ver_rentabilidad',
            'ventas_ml.ver_todas_marcas',
            'ventas_fuera.ver_dashboard',
            'ventas_fuera.ver_operaciones',
            'ventas_fuera.ver_rentabilidad',
            'ventas_tn.ver_dashboard',
            'ventas_tn.ver_operaciones',
            'ventas_tn.ver_rentabilidad',
            'reportes.ver_auditoria',
            'reportes.ver_notificaciones',
            'reportes.ver_calculadora',
            'reportes.exportar',
            'config.ver_comisiones',
            'config.ver_constantes',
            'config.ver_tipo_cambio'
        )
    """)

    # PRICING
    op.execute("""
        INSERT INTO roles_permisos_base (rol, permiso_id)
        SELECT 'PRICING', id FROM permisos WHERE codigo IN (
            'productos.ver',
            'productos.editar_precios',
            'productos.editar_rebate',
            'productos.editar_web_transferencia',
            'productos.editar_out_of_cards',
            'productos.banear',
            'productos.exportar',
            'productos.ver_costos',
            'productos.ver_auditoria',
            'ventas_ml.ver_dashboard',
            'ventas_ml.ver_operaciones',
            'ventas_ml.ver_rentabilidad',
            'ventas_fuera.ver_dashboard',
            'ventas_fuera.ver_operaciones',
            'ventas_tn.ver_dashboard',
            'ventas_tn.ver_operaciones',
            'reportes.ver_notificaciones',
            'reportes.ver_calculadora',
            'reportes.exportar',
            'config.ver_comisiones',
            'config.ver_constantes',
            'config.ver_tipo_cambio'
        )
    """)

    # VENTAS
    op.execute("""
        INSERT INTO roles_permisos_base (rol, permiso_id)
        SELECT 'VENTAS', id FROM permisos WHERE codigo IN (
            'productos.ver',
            'ventas_ml.ver_dashboard',
            'ventas_ml.ver_operaciones',
            'ventas_fuera.ver_dashboard',
            'ventas_fuera.ver_operaciones',
            'ventas_tn.ver_dashboard',
            'ventas_tn.ver_operaciones',
            'reportes.ver_notificaciones',
            'reportes.ver_calculadora',
            'config.ver_tipo_cambio'
        )
    """)


def downgrade():
    op.drop_table('usuarios_permisos_override')
    op.drop_table('roles_permisos_base')
    op.drop_table('permisos')
