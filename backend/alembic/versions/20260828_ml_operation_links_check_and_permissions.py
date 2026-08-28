"""ml-ventas-fuente-de-verdad slice 4: ml_operation_links CHECK constraints
+ ml_ops.ver / ml_ops.gestionar permission catalog

Revision ID: 20260828_ml_op_links_perms
Revises: 20260828_merge_ops_panel
Create Date: 2026-08-28

1. `ml_operation_links.entity_type`/`link_source`/`link_confidence` shipped
   in slice 1 as plain String columns whose valid values lived only in a
   comment, because nothing wrote to them yet. Slice 4's link resolver is
   the first writer, so per this change's own instructions (and the
   slice-3 lesson, obs #1843/#1852) the contract moves into a real CHECK
   constraint here. UNLIKE `20260827_ml_ops_divergence_check`, this
   revision does NOT normalise existing rows first: `ml_operation_links`
   has had zero writers since it was created in slice 1 (nothing here has
   ever written to it before this same PR's resolver), so there is no
   pre-existing data to worry about, and normalising to an existing REAL
   value (e.g. `entity_type = 'claim'`) would silently turn invalid data
   into WRONG data -- worse than leaving it invalid, and `downgrade()`
   cannot undo it either. If this assumption ever turns out to be false in
   some environment, the CHECK creation below fails loudly and the
   deploy stops, which is the correct outcome for a data-integrity bug.
2. `ml_ops.ver` / `ml_ops.gestionar` permission catalog rows, following the
   `20260713_add_permisos_promociones.py` precedent, using parameterised
   `sa.text()` (not f-strings) so a value containing an apostrophe cannot
   break the statement. `ml_ops.gestionar` is `es_critico=true`
   (state/assignment/note writes on divergence rows). Granted to ADMIN
   (both) and GERENTE (`ml_ops.ver` only). SUPERADMIN is NOT granted a
   catalog row here on purpose: `PermisosService.tiene_permiso`/
   `obtener_permisos_usuario` short-circuit on `usuario.es_superadmin`
   before ever consulting the catalog (see `app/services/permisos_service.py`),
   so SUPERADMIN has every permission regardless of what this table
   contains -- adding a row for it here would be dead data, not a grant.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_ml_op_links_perms"
down_revision: Union[str, None] = "20260828_merge_ops_panel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISOS = [
    (
        "ml_ops.ver",
        "Ver operaciones ML",
        "Ver la vista de venta (orden + envío + reclamo + preguntas/mensajes vinculados) y el listado de divergencias",
        "ml_ops",
        200,
        False,
    ),
    (
        "ml_ops.gestionar",
        "Gestionar divergencias ML",
        "Cambiar estado, asignar, anotar y disparar un re-sync manual sobre una divergencia",
        "ml_ops",
        201,
        True,
    ),
]

# SUPERADMIN intentionally absent -- see module docstring point 2.
ROL_PERMISOS = {
    "ADMIN": ["ml_ops.ver", "ml_ops.gestionar"],
    "GERENTE": ["ml_ops.ver"],
}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico, NOW())
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

_DELETE_ROLES_PERMISOS_BASE = sa.text("""
    DELETE FROM roles_permisos_base
    WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = ANY(:codigos))
""")

_DELETE_USUARIOS_PERMISOS_OVERRIDE = sa.text("""
    DELETE FROM usuarios_permisos_override
    WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = ANY(:codigos))
""")

_DELETE_PERMISOS = sa.text("DELETE FROM permisos WHERE codigo = ANY(:codigos)")


def upgrade() -> None:
    op.create_check_constraint(
        "ck_ml_operation_links_entity_type",
        "ml_operation_links",
        "entity_type IN ('claim', 'question', 'message')",
    )
    op.create_check_constraint(
        "ck_ml_operation_links_link_source",
        "ml_operation_links",
        "link_source IN ('claim_resource_id', 'pack_id', 'item_id', 'manual')",
    )
    op.create_check_constraint(
        "ck_ml_operation_links_link_confidence",
        "ml_operation_links",
        "link_confidence IN ('exact', 'inferred')",
    )

    conn = op.get_bind()
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        conn.execute(
            _INSERT_PERMISO,
            {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": desc,
                "categoria": cat,
                "orden": orden,
                "es_critico": critico,
            },
        )

    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(_INSERT_ROL_PERMISO, {"rol_codigo": rol, "permiso_codigo": codigo})


def downgrade() -> None:
    codigos = [p[0] for p in PERMISOS]
    conn = op.get_bind()

    conn.execute(_DELETE_ROLES_PERMISOS_BASE, {"codigos": codigos})
    conn.execute(_DELETE_USUARIOS_PERMISOS_OVERRIDE, {"codigos": codigos})
    conn.execute(_DELETE_PERMISOS, {"codigos": codigos})

    op.drop_constraint("ck_ml_operation_links_link_confidence", "ml_operation_links", type_="check")
    op.drop_constraint("ck_ml_operation_links_link_source", "ml_operation_links", type_="check")
    op.drop_constraint("ck_ml_operation_links_entity_type", "ml_operation_links", type_="check")
