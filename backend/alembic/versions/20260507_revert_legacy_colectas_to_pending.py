"""Revertir colectas legacy de HOY de despachadas a pendientes

La migración previa (20260507_colectas) marcó todas las colectas creadas por
backfill como 'despachada'. Las viejas (días anteriores) realmente ya se fueron,
pero las del día en curso pueden estar en proceso. Este UPDATE las pasa de
vuelta a pendiente para que el operador decida cuándo marcarlas despachadas.

Filtro: observaciones='Colecta legacy creada en migración' AND fecha = CURRENT_DATE.

Idempotente: si las del día ya están pendientes, no hace cambios.

Revision ID: 20260507_legacy_pending
Revises: 20260507_colectas
Create Date: 2026-05-07

"""

from alembic import op


revision = "20260507_legacy_pending"
down_revision = "20260507_colectas"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE colectas
        SET estado = 'pendiente',
            despachada_at = NULL
        WHERE observaciones = 'Colecta legacy creada en migración'
          AND fecha = CURRENT_DATE
          AND estado = 'despachada'
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE colectas
        SET estado = 'despachada',
            despachada_at = COALESCE(despachada_at, NOW())
        WHERE observaciones = 'Colecta legacy creada en migración'
          AND fecha = CURRENT_DATE
          AND estado = 'pendiente'
        """
    )
