"""permisos: roles adicionales por usuario (solo permisos)

Revision ID: 20261022_usuarios_roles_adicionales
Revises: 20261021_ml_pub_queue_unpark_items
Create Date: 2026-10-22

New table `usuarios_roles_adicionales` (usuario, rol). `PermisosService` unions the base
permissions of these roles with the primary role (`usuarios.rol_id`) before applying the
user overrides. The primary role keeps every identity rule (SUPERADMIN, full brand view by
role code, role label). Empty table = today's behavior. Downgrade drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_usuarios_roles_adicionales"
down_revision: Union[str, None] = "20261021_ml_pub_queue_unpark_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usuarios_roles_adicionales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rol_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("otorgado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("usuario_id", "rol_id", name="uq_usuario_rol_adicional"),
    )
    op.create_index("ix_usuarios_roles_adicionales_id", "usuarios_roles_adicionales", ["id"])
    op.create_index("ix_usuarios_roles_adicionales_usuario_id", "usuarios_roles_adicionales", ["usuario_id"])
    op.create_index("ix_usuarios_roles_adicionales_rol_id", "usuarios_roles_adicionales", ["rol_id"])


def downgrade() -> None:
    op.drop_index("ix_usuarios_roles_adicionales_rol_id", table_name="usuarios_roles_adicionales")
    op.drop_index("ix_usuarios_roles_adicionales_usuario_id", table_name="usuarios_roles_adicionales")
    op.drop_index("ix_usuarios_roles_adicionales_id", table_name="usuarios_roles_adicionales")
    op.drop_table("usuarios_roles_adicionales")
