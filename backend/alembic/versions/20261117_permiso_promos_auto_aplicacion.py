"""Seed `promos.auto_aplicacion` with no role grants (manual override only).

Permission:
- promos.auto_aplicacion: show and change the Auto-aplicación checkbox in Criterios
  de aplicación (per MLA and bulk). Not assigned to any role — grant via
  usuario_permisos_override. SUPERADMIN still sees it (all catalog permisos).

Revision ID: 20261117_permiso_promos_auto_aplicacion
Revises: 20261117_ml_hay_mejores_audit
Create Date: 2026-11-17

"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261117_permiso_promos_auto_aplicacion"
down_revision: Union[str, None] = "20261117_ml_hay_mejores_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO = "promos.auto_aplicacion"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            '{CODIGO}',
            'Auto-aplicación hay mejores',
            'Activar o desactivar Auto-aplicación en Criterios de aplicación (por MLA y en masa)',
            'promos',
            46,
            true,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = '{CODIGO}');
        """
    )
    op.execute(
        f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = '{CODIGO}');
        """
    )
    op.execute(f"DELETE FROM permisos WHERE codigo = '{CODIGO}';")
