"""ml-ventas-fuente-de-verdad slice 4: ml_operation_links CHECK constraints
+ ml_ops.ver / ml_ops.gestionar permission catalog

Revision ID: 20260828_ml_op_links_perms
Revises: 20260827_ml_ops_divergence_check, 20260827_ml_bot_messages_sent_at
Create Date: 2026-08-28

Merge point: two independent slices (this chain's slice 3 and the unrelated
ml-bot-panel-operador PR6) both branched off `20260826_ml_orders_ops_models`,
leaving two heads on `main`. This migration merges them and, in the same
revision, does slice 4's own schema work:

1. `ml_operation_links.entity_type`/`link_source`/`link_confidence` shipped
   in slice 1 as plain String columns whose valid values lived only in a
   comment, because nothing wrote to them yet. Slice 4's link resolver is
   the first writer, so per this change's own instructions (and the
   slice-3 lesson, obs #1843/#1852) the contract moves into a real CHECK
   constraint here, exactly like `20260827_ml_ops_divergence_check`
   normalised `ml_ops_divergence`/`ml_ops_sync_cursor` for the same reason.
   Existing rows are normalised (never deleted -- `downgrade()` cannot
   restore deleted rows) to a sentinel before the constraint is added, in
   case "nothing writes here yet" turns out not to hold in some
   environment.
2. `ml_ops.ver` / `ml_ops.gestionar` permission catalog rows, following the
   `20260713_add_permisos_promociones.py` precedent. `ml_ops.gestionar` is
   `es_critico=true` (state/assignment/note writes on divergence rows).
   Granted to SUPERADMIN/ADMIN; `ml_ops.ver` also to GERENTE.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260828_ml_op_links_perms"
down_revision: Union[str, tuple[str, ...], None] = (
    "20260827_ml_ops_divergence_check",
    "20260827_ml_bot_messages_sent_at",
)
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

ROL_PERMISOS = {
    "ADMIN": ["ml_ops.ver", "ml_ops.gestionar"],
    "GERENTE": ["ml_ops.ver"],
}


def upgrade() -> None:
    # Normalise before constraining, same reasoning/precedent as
    # 20260827_ml_ops_divergence_check_constraints: nothing writes to this
    # table yet, but a CHECK that fails on unexpected data takes the whole
    # deploy down, and normalising (not deleting) keeps downgrade() honest.
    op.execute(
        "UPDATE ml_operation_links SET entity_type = 'claim' WHERE entity_type NOT IN ('claim', 'question', 'message')"
    )
    op.execute(
        "UPDATE ml_operation_links SET link_source = 'manual' "
        "WHERE link_source NOT IN ('claim_resource_id', 'pack_id', 'item_id', 'manual')"
    )
    op.execute(
        "UPDATE ml_operation_links SET link_confidence = 'inferred' WHERE link_confidence NOT IN ('exact', 'inferred')"
    )

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

    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            op.execute(f"""
                INSERT INTO roles_permisos_base (rol_id, permiso_id)
                SELECT r.id, p.id
                FROM roles r
                CROSS JOIN permisos p
                WHERE r.codigo = '{rol}'
                  AND p.codigo = '{codigo}'
                ON CONFLICT DO NOTHING;
            """)


def downgrade() -> None:
    codigos = [p[0] for p in PERMISOS]
    codigos_str = ", ".join(f"'{c}'" for c in codigos)

    op.execute(f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """)
    op.execute(f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """)
    op.execute(f"""
        DELETE FROM permisos WHERE codigo IN ({codigos_str});
    """)

    op.drop_constraint("ck_ml_operation_links_link_confidence", "ml_operation_links", type_="check")
    op.drop_constraint("ck_ml_operation_links_link_source", "ml_operation_links", type_="check")
    op.drop_constraint("ck_ml_operation_links_entity_type", "ml_operation_links", type_="check")
