"""Insert permisos for Administración module and assign to SUPERADMIN, ADMIN, GERENTE.

Revision ID: f7d3e5a6b041
Revises: e6c2d4f5a930
Create Date: 2026-03-26
"""

from alembic import op

revision = "f7d3e5a6b041"
down_revision = "e6c2d4f5a930"
branch_labels = None
depends_on = None

# Permisos del módulo Administración (sector empresa)
PERMISOS = [
    # (codigo, nombre, descripcion, categoria, orden, es_critico)
    ("administracion.ver_proveedores", "Ver proveedores", "Acceso a la lista de proveedores y sus datos fiscales", "administracion_sector", 150, False),
    ("administracion.gestionar_proveedores", "Gestionar proveedores", "Crear, editar proveedores y sincronizar desde ERP", "administracion_sector", 151, False),
    ("administracion.consultar_afip", "Consultar AFIP", "Consultar situación tributaria de proveedores en AFIP (Padrón A4/A5)", "administracion_sector", 152, True),
    ("administracion.ver_cuentas_corrientes", "Ver cuentas corrientes", "Acceso a cuentas corrientes de proveedores y clientes", "administracion_sector", 153, False),
    ("administracion.gestionar_cuentas_corrientes", "Gestionar cuentas corrientes", "Registrar movimientos en cuentas corrientes", "administracion_sector", 154, False),
    ("administracion.ver_ordenes_compra", "Ver órdenes de compra", "Acceso a las órdenes de compra a proveedores", "administracion_sector", 155, False),
    ("administracion.gestionar_ordenes_compra", "Gestionar órdenes de compra", "Crear, editar y aprobar órdenes de compra", "administracion_sector", 156, True),
]

# Roles que reciben TODOS los permisos de administración
ROLES_FULL = ["SUPERADMIN", "ADMIN"]

# Roles que reciben solo lectura
ROLES_READ = ["GERENTE"]

PERMISOS_READ = [
    "administracion.ver_proveedores",
    "administracion.ver_cuentas_corrientes",
    "administracion.ver_ordenes_compra",
]


def upgrade() -> None:
    # 1. Insertar permisos
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    # 2. Asignar todos los permisos a SUPERADMIN y ADMIN
    for rol in ROLES_FULL:
        for codigo, *_ in PERMISOS:
            op.execute(f"""
                INSERT INTO roles_permisos_base (rol_id, permiso_id)
                SELECT r.id, p.id
                FROM roles r
                CROSS JOIN permisos p
                WHERE r.codigo = '{rol}'
                  AND p.codigo = '{codigo}'
                ON CONFLICT DO NOTHING;
            """)

    # 3. Asignar permisos de lectura a GERENTE
    for rol in ROLES_READ:
        for codigo in PERMISOS_READ:
            op.execute(f"""
                INSERT INTO roles_permisos_base (rol_id, permiso_id)
                SELECT r.id, p.id
                FROM roles r
                CROSS JOIN permisos p
                WHERE r.codigo = '{rol}'
                  AND p.codigo = '{codigo}'
                ON CONFLICT DO NOTHING;
            """)


def downgrade() -> None:
    codigos = [f"'{c}'" for c, *_ in PERMISOS]
    codigos_str = ", ".join(codigos)

    # Quitar asignaciones de roles
    op.execute(f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN ({codigos_str}))
    """)

    # Quitar permisos
    op.execute(f"""
        DELETE FROM permisos WHERE codigo IN ({codigos_str})
    """)
