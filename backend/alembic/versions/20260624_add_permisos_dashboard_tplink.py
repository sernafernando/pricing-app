"""Seed permissions for TP-Link brand dashboard view

Permissions:
- dashboard_tplink.ver: Access to the TP-Link brand-facing dashboard (non-sensitive data, store 2645)
- dashboard_tplink.ver_ganancia: View margin/markup/cost/commission figures in the TP-Link dashboard

Role assignments:
- ADMIN: both permissions
- GERENTE: both permissions

Brand account provisioning is NOT in this migration — the TP-Link user receives
dashboard_tplink.ver (and optionally .ver_ganancia) via the existing override flow
(usuarios_permisos_override). This is a deliberate manual step.

Revision ID: 20260624_permisos_dashboard_tplink
Revises: 20260624_recepcion_estado_controlado
Create Date: 2026-06-24

"""

from alembic import op

revision = "20260624_permisos_dashboard_tplink"
down_revision = "20260624_recepcion_estado_controlado"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "dashboard_tplink.ver",
        "Ver dashboard TP-Link",
        "Acceso a la vista de marca TP-Link (datos no sensibles, tienda 2645)",
        "ventas_ml",
        60,
        False,
    ),
    (
        "dashboard_tplink.ver_ganancia",
        "Ver ganancia TP-Link",
        "Ver montos de ganancia/markup/costos/comisiones en la vista TP-Link",
        "ventas_ml",
        61,
        False,
    ),
]

ROL_PERMISOS = {
    "ADMIN": ["dashboard_tplink.ver", "dashboard_tplink.ver_ganancia"],
    "GERENTE": ["dashboard_tplink.ver", "dashboard_tplink.ver_ganancia"],
}


def upgrade() -> None:
    # 1. Insert permissions into catalog (idempotent)
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    # 2. Assign to roles (idempotent)
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
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
    codigos = [p[0] for p in PERMISOS]
    codigos_str = ", ".join(f"'{c}'" for c in codigos)

    # Remove role assignments first
    op.execute(f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """)

    # Remove user overrides
    op.execute(f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """)

    # Remove from catalog
    op.execute(f"""
        DELETE FROM permisos WHERE codigo IN ({codigos_str});
    """)
