"""compras 011 — seed caja_tipo_documentos para Órdenes de Pago

Revision ID: compras_011_seed_caja_tp
Revises: compras_010_seed_perm
Create Date: 2026-04-17

Inserta 2 tipos de documento en `caja_tipo_documentos` para que el módulo
de compras pueda crear `CajaDocumento` vinculados a OPs creadas/anuladas.

Schema real (verificado en app/models/caja.py CajaTipoDocumento):
  id, nombre (unique NOT NULL), descripcion, activo, created_at

IMPORTANTE: la tabla usa `nombre` como identificador único, NO `codigo`.
Esto se confirmó en conversación con el usuario.

REQ-CAJ-003 + D19 (segundo tipo para anulaciones, preserva trazabilidad
bidireccional del pago y su reverso).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_011_seed_caja_tp"
down_revision: Union[str, None] = "compras_010_seed_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TIPOS_NUEVOS: tuple[dict, ...] = (
    {
        "nombre": "Orden de Pago",
        "descripcion": "Documento que respalda pago a proveedor",
        "activo": True,
    },
    {
        "nombre": "Orden de Pago Anulada",
        "descripcion": "Documento que respalda anulación de una OP",
        "activo": True,
    },
)


def upgrade() -> None:
    conn = op.get_bind()

    insert_sql = sa.text(
        """
        INSERT INTO caja_tipo_documentos (nombre, descripcion, activo)
        VALUES (:nombre, :descripcion, :activo)
        ON CONFLICT (nombre) DO NOTHING
        """
    )
    for tipo in _TIPOS_NUEVOS:
        conn.execute(insert_sql, tipo)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM caja_tipo_documentos WHERE nombre = ANY(:nombres)"),
        {"nombres": [t["nombre"] for t in _TIPOS_NUEVOS]},
    )
