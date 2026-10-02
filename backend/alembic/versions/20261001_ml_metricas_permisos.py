"""ml_metricas.ver / ml_metricas.ver_ganancia for the Métricas ML board

Revision ID: 20261001_ml_metricas_permisos
Revises: 20261001_ml_product_daily_metrics
Create Date: 2026-10-01

ODD `metricas-ml-tablero` T3: the new board gets its own pair of permissions,
same split as `dashboard_tplink.ver` / `.ver_ganancia`: `ver` opens the
screen (units, gross, ageing), `ver_ganancia` adds Total Gauss and markup.
Granted to ADMIN and GERENTE (SUPERADMIN short-circuits the catalog); anyone
else through the per-user overrides screen.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_ml_metricas_permisos"
down_revision: Union[str, None] = "20261001_ml_product_daily_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISOS = [
    (
        "ml_metricas.ver",
        "Ver Métricas ML",
        "Tablero de Métricas ML por producto y publicación: unidades, facturado, última venta y ageing",
        "ventas_ml",
        70,
    ),
    (
        "ml_metricas.ver_ganancia",
        "Ver ganancia en Métricas ML",
        "Ver Total Gauss y markup (actual, anterior, mínimo/máximo y tendencia) en el tablero de Métricas ML",
        "ventas_ml",
        71,
    ),
]
ROL_PERMISOS = {
    "ADMIN": ["ml_metricas.ver", "ml_metricas.ver_ganancia"],
    "GERENTE": ["ml_metricas.ver", "ml_metricas.ver_ganancia"],
}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, false, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id
    FROM roles r
    CROSS JOIN permisos p
    WHERE r.codigo = :rol_codigo
      AND p.codigo = :permiso_codigo
    ON CONFLICT DO NOTHING
""")


def upgrade() -> None:
    conn = op.get_bind()
    for codigo, nombre, descripcion, categoria, orden in PERMISOS:
        conn.execute(
            _INSERT_PERMISO,
            {"codigo": codigo, "nombre": nombre, "descripcion": descripcion, "categoria": categoria, "orden": orden},
        )
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(_INSERT_ROL_PERMISO, {"rol_codigo": rol, "permiso_codigo": codigo})


def downgrade() -> None:
    conn = op.get_bind()
    for codigo, *_rest in PERMISOS:
        params = {"codigo": codigo}
        conn.execute(
            sa.text(
                "DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)"
            ),
            params,
        )
        conn.execute(
            sa.text(
                "DELETE FROM usuarios_permisos_override "
                "WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)"
            ),
            params,
        )
        conn.execute(sa.text("DELETE FROM permisos WHERE codigo = :codigo"), params)
