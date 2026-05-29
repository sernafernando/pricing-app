"""Agregar índices CONCURRENTLY sobre tb_item_transactions para ranking de consultas

Revision ID: 20260529_02_consultas_tit_indexes
Revises: 20260529_01_consultas_ageing_table_permiso
Create Date: 2026-05-29

Crea tres índices compuestos sobre ``tb_item_transactions`` usando
``CREATE INDEX CONCURRENTLY`` para no bloquear escrituras en producción.

Motivación
----------
El endpoint GET /api/consultas/ranking ejecuta dos LATERALs sobre
``tb_item_transactions``:

  LATERAL #1 — last_sale:
    Filtra por sd_id IN (1,4,21,56) + df_id IN (...) para determinar la
    última venta y calcular días sin venta. El índice ix_tit_item_cttx
    (item_id, ct_transaction) cubre este subconjunto.

  LATERAL #2 — last_purchase:
    Filtra por puco_id = 10 y ordena por it_cd DESC LIMIT 1.
    puco_id actualmente NO tiene índice — riesgo de performance primario.
    El índice ix_tit_item_puco_cd (item_id, puco_id, it_cd DESC) lo cubre.

  Auxiliar — filtro de canal:
    ix_tct_sd_df_date sobre tb_commercial_transactions(sd_id, df_id, ct_date)
    asiste los JOINs de canal.

Patrón: ``op.get_context().autocommit_block()`` con IF NOT EXISTS.
Precedente: 20260527_add_prearmados_armado_idx.py.

IMPORTANTE: esta migración NO puede correr dentro de una transacción.
Alembic la ejecuta en autocommit_block() — no agregar DDL transaccional aquí.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260529_02_consultas_tit_indexes"
down_revision: Union[str, None] = "20260529_01_consultas_ageing_table_permiso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Índice para LATERAL last_purchase (puco_id = 10, ORDER BY it_cd DESC)
        # puco_id es la columna sin índice — riesgo de performance primario.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tit_item_puco_cd "
            "ON tb_item_transactions(item_id, puco_id, it_cd DESC)"
        )

        # Índice para LATERAL last_sale (filter by ct_transaction + item_id)
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tit_item_cttx ON tb_item_transactions(item_id, ct_transaction)"
        )

        # Índice auxiliar para tb_commercial_transactions (filtro de canal)
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tct_sd_df_date "
            "ON tb_commercial_transactions(sd_id, df_id, ct_date)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_tit_item_puco_cd")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_tit_item_cttx")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_tct_sd_df_date")
