"""Agregar índice parcial ix_prearmados_armado_combo para stats de prearmados

Revision ID: 20260527_prearmados_armado_idx
Revises: cc1b3c3cccba
Create Date: 2026-05-27

Agrega un índice parcial B-tree sobre ``prearmados(combo_item_id)``
restringido a filas donde ``estado = 'armado'``.

Motivación
----------
Las queries de stats de prearmados (POST /api/prearmados/stats/batch y
GET /api/prearmados/stats/armadas) filtran siempre por ``estado = 'armado'``.
El índice parcial cubre exactamente ese subconjunto, resultando en un índice
más pequeño, más rápido para planificador, y amigable con el cache de PG.

Se usa ``CREATE INDEX CONCURRENTLY`` para no bloquear escrituras en producción.
Requiere autocommit — envuelto en ``op.get_context().autocommit_block()``.
Patrón precedente: ``20260427_add_idx_mlp_official_store_id.py``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260527_prearmados_armado_idx"
down_revision: Union[str, None] = "cc1b3c3cccba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_prearmados_armado_combo "
            "ON prearmados(combo_item_id) WHERE estado = 'armado'"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_prearmados_armado_combo")
