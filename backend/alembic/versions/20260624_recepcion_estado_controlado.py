"""Agregar estado 'controlado' a pedidos_compra (two-step reception)

Revision ID: 20260624_recepcion_estado_controlado
Revises: 20260623_permiso_reescribir_lh
Create Date: 2026-06-24

NOTE (data migration): upgrade renames existing 'recibido' rows to 'controlado'
because in the two-step model 'recibido' now means "arrived but not yet counted".
Downgrade reverts the constraint only — it does NOT restore the old 'recibido'
semantics. Data is one-way; manual backfill would be required after downgrade.
"""

from alembic import op

revision = "20260624_recepcion_estado_controlado"
down_revision = "20260623_permiso_reescribir_lh"
branch_labels = None
depends_on = None

_ESTADOS_NUEVOS = (
    "borrador",
    "pendiente_aprobacion",
    "aprobado",
    "rechazado",
    "cancelado",
    "pagado_parcial",
    "pagado",
    "recibido",
    "con_faltantes",
    "controlado",
)

_ESTADOS_ANTERIORES = (
    "borrador",
    "pendiente_aprobacion",
    "aprobado",
    "rechazado",
    "cancelado",
    "pagado_parcial",
    "pagado",
    "recibido",
    "con_faltantes",
)


def _estados_check(estados: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{e}'" for e in estados)
    return f"estado IN ({quoted})"


def upgrade() -> None:
  develop
    # Step 1: Drop the current 9-state constraint FIRST.
    # The data migration below writes 'controlado', a value the OLD constraint
    # does NOT allow. The constraint must be gone before the UPDATE runs, or
    # Postgres rejects the write with a CheckViolation. (Reading 'recibido' is
    # fine under the old constraint — the problem is writing 'controlado'.)
    op.drop_constraint("ck_pedidos_compra_estado", "pedidos_compra", type_="check")

    # Step 2: Rename existing terminal 'recibido' rows to 'controlado'.
    # In the two-step model 'recibido' now means "arrived, not yet controlled",
    # so the previous terminal 'recibido' rows become the new terminal 'controlado'.
    op.execute("UPDATE pedidos_compra SET estado = 'controlado' WHERE estado = 'recibido'")

    # Step 3: Add the new 10-state constraint (includes 'controlado').

    # Step 1: Rename existing terminal 'recibido' rows to 'controlado'
    # MUST happen BEFORE dropping the constraint so the value is still valid.
    op.execute("UPDATE pedidos_compra SET estado = 'controlado' WHERE estado = 'recibido'")

    # Step 2: Drop current 9-state constraint
    op.drop_constraint("ck_pedidos_compra_estado", "pedidos_compra", type_="check")

    # Step 3: Add new 10-state constraint (includes 'controlado')
 main
    op.create_check_constraint(
        "ck_pedidos_compra_estado",
        "pedidos_compra",
        _estados_check(_ESTADOS_NUEVOS),
    )


def downgrade() -> None:
    # Revert to the prior 9-state constraint.
    # WARNING: any rows currently in 'controlado' will violate the restored constraint.
    # This migration is considered one-way — see module docstring.
    op.drop_constraint("ck_pedidos_compra_estado", "pedidos_compra", type_="check")
    op.create_check_constraint(
        "ck_pedidos_compra_estado",
        "pedidos_compra",
        _estados_check(_ESTADOS_ANTERIORES),
    )
