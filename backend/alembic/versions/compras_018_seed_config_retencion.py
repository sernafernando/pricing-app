"""compras 018 — seed config compras.dias_retencion_cancelados

Revision ID: compras_018_seed_retencion
Revises: compras_017_seed_perm_del
Create Date: 2026-04-21

Inserta la clave `compras.dias_retencion_cancelados` en la tabla
`configuracion` con valor por defecto `'30'`. Determina cuántos días debe
pasar un pedido/OP en estado cancelado/anulado antes de habilitarse para
hard-delete.

Schema real `configuracion` (verificado en app/models/configuracion.py):
  clave (PK VARCHAR 100), valor (TEXT NOT NULL), descripcion, tipo, fecha_modificacion

Leído por `compras_papelera_service._leer_dias_retencion` con fallback 30
si la clave no existe o no parsea a int.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_018_seed_retencion"
down_revision: Union[str, None] = "compras_017_seed_perm_del"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CLAVE: str = "compras.dias_retencion_cancelados"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO configuracion (clave, valor, tipo, descripcion)
            VALUES (:clave, :valor, :tipo, :descripcion)
            ON CONFLICT (clave) DO NOTHING
            """
        ),
        {
            "clave": _CLAVE,
            "valor": "30",
            "tipo": "integer",
            "descripcion": (
                "Días de espera antes de habilitar hard-delete sobre "
                "pedidos/OPs en estado cancelado/anulado. Los pedidos en "
                "borrador se habilitan para eliminación inmediata sin esperar."
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM configuracion WHERE clave = :clave"),
        {"clave": _CLAVE},
    )
