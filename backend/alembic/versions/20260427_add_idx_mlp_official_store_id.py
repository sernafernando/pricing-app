"""add index on mlp_official_store_id (CONCURRENTLY)

Revision ID: 20260427_add_index_mlp_official_store_id
Revises: compras_027_pedido_corregido
Create Date: 2026-04-27

Agrega un índice B-tree sobre `tb_mercadolibre_items_publicados.mlp_official_store_id`
para soportar el nuevo filtro `tiendas_oficiales` en los endpoints de export
(`POST /productos/exportar-rebate` y `GET /exportar-clasica`).

Cubre los 3 patrones de uso del filtro:
  * `mlp_official_store_id IN (...)` — subset de tiendas oficiales tildadas.
  * `mlp_official_store_id IS NULL` — sentinel `sin_tienda`.
  * combinación vía `OR` de los dos anteriores.

Se usa `CREATE INDEX CONCURRENTLY` para no bloquear escrituras en producción.
Esto requiere correr la migración FUERA de transacción — para eso envolvemos
el `op.execute(...)` dentro de un `op.get_context().autocommit_block()`.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260427_add_index_mlp_official_store_id"
down_revision: Union[str, None] = "compras_027_pedido_corregido"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_ml_item_publicado_official_store_id "
            "ON tb_mercadolibre_items_publicados (mlp_official_store_id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ml_item_publicado_official_store_id")
