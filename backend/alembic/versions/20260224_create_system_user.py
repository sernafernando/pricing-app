"""Crear usuario Sistema (service account) para procesos automáticos

Revision ID: 20260224_system_user
Revises: 20260223_ml_users_data
Create Date: 2026-02-24

Corrige bug donde erp_sync.py hardcodeaba usuario_id=1 (Fernando Serna)
para sincronizaciones automáticas, causando atribución incorrecta en auditoría.
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, UTC

revision = "20260224_system_user"
down_revision = "20260223_ml_users_data"
branch_labels = None
depends_on = None

# Username del usuario sistema — usado como constante en app/core/constants.py
SYSTEM_USERNAME = "sistema"


def upgrade() -> None:
    # Insertar usuario sistema con activo=False para que no pueda hacer login
    # Obtener el rol_id de VENTAS (el más básico) para cumplir NOT NULL
    op.execute(
        sa.text(
            """
            INSERT INTO usuarios (username, nombre, email, password_hash, activo, auth_provider, rol_id, created_at)
            VALUES (
                :username, :nombre, :email, :password_hash, :activo, :auth_provider,
                (SELECT id FROM roles WHERE codigo = 'VENTAS' LIMIT 1),
                :created_at
            )
            ON CONFLICT (username) DO NOTHING
            """
        ).bindparams(
            username=SYSTEM_USERNAME,
            nombre="Sistema (automático)",
            email="sistema@pricing-app.internal",
            password_hash="!NOLOGIN",  # Hash inválido, imposible hacer login
            activo=False,  # Inactivo: no puede autenticarse via API
            auth_provider="LOCAL",
            created_at=datetime.now(UTC),
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM usuarios WHERE username = :username").bindparams(
            username=SYSTEM_USERNAME,
        )
    )
