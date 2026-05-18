"""restore unique constraint uq_rol_permiso on roles_permisos_base

La constraint original `uq_rol_permiso` fue creada por
`create_permisos_system.py` sobre `(rol, permiso_id)`. La migración
`20251216_02_add_rol_id_to_usuarios.py` reemplazó la columna `rol` (string)
por `rol_id` (FK), pero el `op.drop_column('roles_permisos_base', 'rol')`
arrastró silenciosamente la constraint (Postgres elimina las constraints
que dependen de una columna borrada). El reemplazo nunca se creó: durante
~5 meses la tabla quedó sin protección contra duplicados (rol_id, permiso_id).

Esta migración es defensiva:

1. Detecta duplicados existentes (si una asignación rol→permiso aparece N
   veces, conserva la fila con id más bajo y borra el resto).
2. Crea la unique constraint con el mismo nombre original.

El modelo `RolPermisoBase` ya declara la constraint vía `__table_args__`
desde el commit que acompaña esta migración — antes vivía en un
`class Meta` que es sintaxis Django y SQLAlchemy ignora.

Revision ID: 20260518_uq_rol_permiso
Revises: 20260513_add_item_expser
Create Date: 2026-05-18
"""

from alembic import op


revision = "20260518_uq_rol_permiso"
down_revision = "20260513_add_item_expser"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Dedupe defensivo: si quedaron duplicados de los 5 meses sin constraint,
    #    conservamos la fila con menor id y borramos el resto.
    op.execute(
        """
        DELETE FROM roles_permisos_base a
        USING roles_permisos_base b
        WHERE a.rol_id = b.rol_id
          AND a.permiso_id = b.permiso_id
          AND a.id > b.id;
        """
    )

    # 2. Crear la unique constraint que el modelo ya declara.
    op.create_unique_constraint(
        "uq_rol_permiso",
        "roles_permisos_base",
        ["rol_id", "permiso_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_rol_permiso", "roles_permisos_base", type_="unique")
