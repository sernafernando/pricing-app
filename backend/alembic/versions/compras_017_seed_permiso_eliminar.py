"""compras 017 — seed permiso administracion.eliminar_compras_basura

Revision ID: compras_017_seed_perm_del
Revises: compras_016_papelera
Create Date: 2026-04-21

Inserta el permiso crítico `administracion.eliminar_compras_basura`, que
habilita el hard-delete de pedidos/OPs "basura" (borrador/cancelados sin
movimiento, anulados sin imputaciones activas) con papelera auditable.

IMPORTANTE: NO se asigna a ningún rol base ni usuario por default (misma
regla R8 que compras_010). El admin decide manualmente quién lo tiene —
es un permiso destructivo que debe estar limitado.

Schema real de la tabla `permisos` (verificado en app/models/permiso.py):
  id, codigo (unique), nombre, descripcion, categoria, orden, es_critico, created_at

Continuación del orden relativo de compras_010 (170=aprobar, 171=ejecutar_pagos).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_017_seed_perm_del"
down_revision: Union[str, None] = "compras_016_papelera"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORDEN_ELIMINAR_BASURA: int = 172
_CATEGORIA: str = "administracion_sector"

_PERMISO: dict = {
    "codigo": "administracion.eliminar_compras_basura",
    "nombre": "Eliminar basura de compras",
    "descripcion": (
        "Hard-delete auditable de pedidos/OPs en estado borrador o "
        "cancelado/anulado sin movimiento de dinero. Envía la entidad "
        "a la papelera con snapshot JSON completo. NO restaurable."
    ),
    "categoria": _CATEGORIA,
    "orden": _ORDEN_ELIMINAR_BASURA,
    "es_critico": True,
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
            VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico)
            ON CONFLICT (codigo) DO NOTHING
            """
        ),
        _PERMISO,
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Cascade de roles_permisos_base + usuarios_permisos_override via FK ON DELETE CASCADE.
    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = :codigo"),
        {"codigo": _PERMISO["codigo"]},
    )
