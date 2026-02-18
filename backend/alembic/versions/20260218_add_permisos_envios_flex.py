"""Agregar permisos para el sistema de Envíos Flex

9 nuevos permisos de categoría envios_flex para controlar acceso granular
a la pestaña de envíos, pistoleado, exportación, gestión de logísticas y config.

Revision ID: 20260218_permisos_flex
Revises: 20260218_pistoleado_op
Create Date: 2026-02-18

"""

from alembic import op

revision = "20260218_permisos_flex"
down_revision = "20260218_pistoleado_op"
branch_labels = None
depends_on = None

# Todos los códigos nuevos (para downgrade limpio)
CODIGOS = [
    "envios_flex.ver",
    "envios_flex.subir_etiquetas",
    "envios_flex.asignar_logistica",
    "envios_flex.cambiar_fecha",
    "envios_flex.eliminar",
    "envios_flex.exportar",
    "envios_flex.gestionar_logisticas",
    "envios_flex.pistoleado",
    "envios_flex.config",
]


def upgrade():
    # 0. Agregar valor 'envios_flex' al ENUM categoriapermiso de PostgreSQL.
    #    La columna en el modelo Python es String(50), pero en la BD sigue siendo ENUM nativo.
    #    ALTER TYPE ... ADD VALUE no puede ejecutarse dentro de un bloque transaccional,
    #    por eso cerramos la transacción actual, agregamos el valor, y abrimos una nueva.
    op.execute("COMMIT")
    op.execute("ALTER TYPE categoriapermiso ADD VALUE IF NOT EXISTS 'envios_flex'")
    op.execute("BEGIN")

    # 1. Insertar los 9 permisos nuevos
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('envios_flex.ver', 'Ver Envíos Flex', 'Acceso a la pestaña Envíos Flex en Preparación', 'envios_flex', 100, false, NOW()),
            ('envios_flex.subir_etiquetas', 'Subir etiquetas', 'Subir archivos ZIP/TXT con etiquetas ZPL de envío', 'envios_flex', 101, false, NOW()),
            ('envios_flex.asignar_logistica', 'Asignar logística', 'Asignar o cambiar logística a etiquetas (individual y masivo)', 'envios_flex', 102, false, NOW()),
            ('envios_flex.cambiar_fecha', 'Cambiar fecha de envío', 'Reprogramar fecha de envío de etiquetas', 'envios_flex', 103, false, NOW()),
            ('envios_flex.eliminar', 'Eliminar etiquetas', 'Borrar etiquetas de envío (con auditoría)', 'envios_flex', 104, true, NOW()),
            ('envios_flex.exportar', 'Exportar a Excel', 'Exportar etiquetas de envío a archivo XLSX', 'envios_flex', 105, false, NOW()),
            ('envios_flex.gestionar_logisticas', 'Gestionar logísticas', 'Crear y desactivar logísticas desde el modal de configuración', 'envios_flex', 106, false, NOW()),
            ('envios_flex.pistoleado', 'Pistoleado de paquetes', 'Acceso a la pestaña de pistoleado de paquetes en depósito', 'envios_flex', 107, false, NOW()),
            ('envios_flex.config', 'Configurar operaciones envío', 'Acceso al panel de config-operaciones (operadores, tabs, costos)', 'envios_flex', 108, true, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. ADMIN: todos los permisos envios_flex.*
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo LIKE 'envios_flex.%'
        ON CONFLICT DO NOTHING;
    """)

    # 3. GERENTE: ver + exportar
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
          AND p.codigo IN ('envios_flex.ver', 'envios_flex.exportar')
        ON CONFLICT DO NOTHING;
    """)

    # 4. VENTAS: solo ver
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'VENTAS'
          AND p.codigo = 'envios_flex.ver'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Limpiar asignaciones de rol
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo LIKE 'envios_flex.%'
        );
    """)

    # Limpiar overrides de usuario (si hay)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo LIKE 'envios_flex.%'
        );
    """)

    # Eliminar permisos
    op.execute("""
        DELETE FROM permisos WHERE codigo LIKE 'envios_flex.%';
    """)
