"""compras 022 — seed permiso administracion.aprobar_ncs_locales

Revision ID: compras_022_aprobar_nc
Revises: compras_021_nc_local
Create Date: 2026-04-22

Inserta el permiso crítico `administracion.aprobar_ncs_locales`, requerido
para aprobar/rechazar notas de crédito locales (v2 NCs).

Razón de separación de funciones (no reusar `aprobar_ordenes_compra`):
quien aprueba pedidos no necesariamente aprueba NCs. Caso típico:
  - PM aprueba pedidos (compras planificadas).
  - Tesorería/contable aprueba NCs (afectan el haber del proveedor y se
    pueden imputar a deudas existentes — equivalente a un "pago en
    especie").

IMPORTANTE: NO se asigna a ningún rol base ni usuario por default. Es un
permiso destructivo (modifica la posición de CC del proveedor cuando se
imputan las NCs aprobadas) que el admin decide manualmente a quién dárselo.

Orden relativo (continuación del módulo compras):
  170 = aprobar_ordenes_compra
  171 = ejecutar_pagos
  172 = eliminar_compras_basura
  173 = ajustar_monto_pedido
  174 = aprobar_ncs_locales      ← éste
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_022_aprobar_nc"
down_revision: Union[str, None] = "compras_021_nc_local"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORDEN_APROBAR_NC: int = 174
_CATEGORIA: str = "administracion_sector"

_PERMISO: dict = {
    "codigo": "administracion.aprobar_ncs_locales",
    "nombre": "Aprobar notas de crédito locales",
    "descripcion": (
        "Permite aprobar o rechazar notas de crédito locales cargadas en "
        "pricing-app. La NC aprobada queda DISPONIBLE para imputarse a "
        "pedidos/facturas (no impacta CC al aprobar — solo al imputar). "
        "Separa la función de aprobador de pedidos: tesorería/contable "
        "decide qué NCs son válidas para reducir deuda del proveedor."
    ),
    "categoria": _CATEGORIA,
    "orden": _ORDEN_APROBAR_NC,
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
    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = :codigo"),
        {"codigo": _PERMISO["codigo"]},
    )
