"""compras_036: dedup + unique constraint en (proveedor_id, numero_nc_proveedor)

Revision ID: compras_036_ncs_sync_dedup
Revises: 20260527_permiso_ver_prearmadas_stats
Create Date: 2026-05-28

Bugs corregidos:
  - NCs duplicadas en sync ERP: se elimina la fila duplicada (menor id),
    preservando la que tiene imputaciones o, en su defecto, la más reciente.
  - Se agrega UNIQUE parcial sobre (proveedor_id, numero_nc_proveedor)
    WHERE numero_nc_proveedor IS NOT NULL para prevenir futuros duplicados.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "compras_036_ncs_sync_dedup"
down_revision = "20260527_permiso_ver_prearmadas_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 0. Pre-flight: detectar duplicados donde MÚLTIPLES filas tienen
    #    imputaciones activas (es_reversal=FALSE). En ese caso NO podemos
    #    resolver automáticamente cuál conservar sin riesgo de dinero real.
    #    Fallar ruidosamente para que un operador resuelva manualmente.
    conflictos = conn.execute(
        sa.text(
            """
            SELECT ncl.proveedor_id, ncl.numero_nc_proveedor,
                   array_agg(ncl.id ORDER BY ncl.id) AS ids_afectados
            FROM notas_credito_local ncl
            WHERE ncl.numero_nc_proveedor IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM imputaciones i
                  WHERE i.origen_tipo = 'nota_credito_local'
                    AND i.origen_id = ncl.id
                    AND i.es_reversal = FALSE
              )
            GROUP BY ncl.proveedor_id, ncl.numero_nc_proveedor
            HAVING COUNT(*) > 1
            """
        )
    ).all()

    if conflictos:
        detalles = "; ".join(
            f"proveedor_id={row[0]}, numero_nc_proveedor={row[1]!r}, ids={list(row[2])}" for row in conflictos
        )
        raise Exception(
            f"compras_036: ABORTADO — se encontraron {len(conflictos)} grupo(s) de NCs "
            f"duplicadas donde MÚLTIPLES filas tienen imputaciones activas. "
            f"Es necesaria reconciliación manual antes de correr esta migración. "
            f"Grupos afectados: {detalles}"
        )

    # ── 1. Dedup: por cada (proveedor_id, numero_nc_proveedor) con >1 fila,
    #    conservar la que tiene imputaciones (es_reversal=FALSE) o, si ninguna
    #    tiene, la de mayor id (más reciente). Borrar el resto.
    #
    #    Se usa una CTE de ranking:
    #      - rank=1: fila a conservar.
    #      - rank>1: filas a eliminar.
    #    Ranking: primero las filas CON imputaciones activas, después por id DESC.
    conn.execute(
        sa.text(
            """
            DELETE FROM notas_credito_local
            WHERE id IN (
                SELECT id FROM (
                    SELECT
                        ncl.id,
                        ROW_NUMBER() OVER (
                            PARTITION BY ncl.proveedor_id, ncl.numero_nc_proveedor
                            ORDER BY
                                CASE WHEN imp.nc_id IS NOT NULL THEN 0 ELSE 1 END,
                                ncl.id DESC
                        ) AS rn
                    FROM notas_credito_local ncl
                    LEFT JOIN LATERAL (
                        SELECT 1 AS nc_id
                        FROM imputaciones i
                        WHERE i.origen_tipo = 'nota_credito_local'
                          AND i.origen_id = ncl.id
                          AND i.es_reversal = FALSE
                        LIMIT 1
                    ) imp ON TRUE
                    WHERE ncl.numero_nc_proveedor IS NOT NULL
                ) ranked
                WHERE rn > 1
            )
            """
        )
    )

    # ── 2. Reemplazar el índice no-único previo por el nuevo índice UNIQUE.
    #    El índice anterior (ix_ncs_local_numero_nc_prov) era idéntico en columnas
    #    y predicado pero sin unique=True. Se lo elimina para evitar dos índices
    #    redundantes sobre las mismas columnas.
    op.drop_index(
        "ix_ncs_local_numero_nc_prov",
        table_name="notas_credito_local",
        if_exists=True,
    )
    op.create_index(
        "uq_ncs_local_proveedor_numero_nc_prov",
        "notas_credito_local",
        ["proveedor_id", "numero_nc_proveedor"],
        unique=True,
        postgresql_where=sa.text("numero_nc_proveedor IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ncs_local_proveedor_numero_nc_prov",
        table_name="notas_credito_local",
    )
    # Restaurar el índice no-único original.
    op.create_index(
        "ix_ncs_local_numero_nc_prov",
        "notas_credito_local",
        ["proveedor_id", "numero_nc_proveedor"],
        postgresql_where=sa.text("numero_nc_proveedor IS NOT NULL"),
    )
