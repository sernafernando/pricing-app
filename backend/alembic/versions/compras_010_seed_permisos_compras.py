"""compras 010 — seed permisos críticos compras (sin asignación default)

Revision ID: compras_010_seed_perm
Revises: compras_009_seed_sd
Create Date: 2026-04-17

Inserta 2 permisos críticos nuevos del módulo de compras:
  - administracion.aprobar_ordenes_compra
  - administracion.ejecutar_pagos

IMPORTANTE: NO se asignan a ningún rol base ni usuario — admins los otorgan
manualmente via panel. Esto cumple R8 del proposal (permisos sin asignación
default para evitar escalada de privilegios).

Schema real de la tabla `permisos` (verificado en app/models/permiso.py):
  id, codigo (unique), nombre (NOT NULL), descripcion, categoria (NOT NULL),
  orden, es_critico, created_at

Para respetar NOT NULL de `nombre` y `categoria`, se completa con valores
sensatos derivados del catálogo existente (categoría 'administracion_sector').
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_010_seed_perm"
down_revision: Union[str, None] = "compras_009_seed_sd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Orden relativo dentro de la categoría administracion_sector (sigue después
# de los permisos ya catalogados hasta orden=159 — sincronizar_caja).
_ORDEN_APROBAR: int = 170
_ORDEN_EJECUTAR_PAGOS: int = 171

_CATEGORIA: str = "administracion_sector"

_PERMISOS_NUEVOS: tuple[dict, ...] = (
    {
        "codigo": "administracion.aprobar_ordenes_compra",
        "nombre": "Aprobar órdenes de compra",
        "descripcion": "Aprobar o rechazar pedidos de compra",
        "categoria": _CATEGORIA,
        "orden": _ORDEN_APROBAR,
        "es_critico": True,
    },
    {
        "codigo": "administracion.ejecutar_pagos",
        "nombre": "Ejecutar pagos",
        "descripcion": ("Marcar una orden de pago como pagada (impacta Caja y CC proveedor)"),
        "categoria": _CATEGORIA,
        "orden": _ORDEN_EJECUTAR_PAGOS,
        "es_critico": True,
    },
)


def upgrade() -> None:
    conn = op.get_bind()

    # Idempotente: solo inserta si el codigo no existe aún. Esto permite
    # re-ejecutar la migración sin romper si alguien creó los permisos a mano.
    insert_sql = sa.text(
        """
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico)
        ON CONFLICT (codigo) DO NOTHING
        """
    )
    for permiso in _PERMISOS_NUEVOS:
        conn.execute(insert_sql, permiso)


def downgrade() -> None:
    conn = op.get_bind()

    # Cascade de roles_permisos_base y usuarios_permisos_override ocurre
    # automáticamente por la FK ON DELETE CASCADE (ver modelo Permiso).
    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = ANY(:codigos)"),
        {"codigos": [p["codigo"] for p in _PERMISOS_NUEVOS]},
    )
