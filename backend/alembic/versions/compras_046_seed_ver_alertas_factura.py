"""compras 046 — seed permiso administracion.ver_alertas_factura

Revision ID: compras_046_seed_ver_alertas_factura
Revises: compras_044_pipeline_tipo_responsable_facturas
Create Date: 2026-09-23

Inserta el permiso `administracion.ver_alertas_factura`, requerido para
recibir el fan-out in-app de factura cargada (PR2 banners). El catálogo
existe; el admin asigna el código a mano.

IMPORTANTE: NO se asigna a ningún rol base ni usuario por default.

045 (pedido_compra_ocs) lives on PR4 and still hangs on 044. This PR2
branch does not contain 045, so 046 parents the current Alembic head
(044). PR4 must rehang 045 → 046.

Orden relativo: continúa después de:
  173 = ajustar_monto_pedido
  174 = aprobar_ncs_locales
  175 = ajustar_cc_proveedor_manual
  176 = ver_alertas_factura   ← éste
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_046_seed_ver_alertas_factura"
down_revision: Union[str, None] = "compras_044_pipeline_tipo_responsable_facturas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORDEN_VER_ALERTAS_FACTURA: int = 176
_CATEGORIA: str = "administracion_sector"

_PERMISO: dict = {
    "codigo": "administracion.ver_alertas_factura",
    "nombre": "Ver alertas de factura cargada",
    "descripcion": (
        "Recibe el aviso in-app cuando se carga una factura en un pedido "
        "de compra. No otorga acciones de escritura. NO se asigna a ningún "
        "rol por default; el admin decide quién lo recibe."
    ),
    "categoria": _CATEGORIA,
    "orden": _ORDEN_VER_ALERTAS_FACTURA,
    "es_critico": False,
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
