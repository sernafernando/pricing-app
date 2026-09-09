"""Seed ml-webhook-bridge service user, ML_BRIDGE role, ml_ops.ingest
permission (ml-activity-receiver slice 1)

Materializes the narrow inbound-authentication boundary for ml-webhook's
activity ping (design domain `ml-ops-service-auth`): a service user row
that resolves like any other `Usuario` through `require_permission()`
(`app/routers/ml_ventas_ops.py:80`), scoped to EXACTLY `ml_ops.ingest` --
deliberately NOT `ml_ops.ver` and NOT `ml_ops.gestionar`, which already
exist for human operators (`20260828_ml_operation_links_check_and_permissions.py`).

This slice is inert on its own: no endpoint requires `ml_ops.ingest` yet
(it is added in slice 3's ping handler), so seeding this permission/role/
user here changes zero runtime behavior.

Seeds, in order (same shape as `20260807_seed_agente_ia_service_user.py`):
1. `ml_ops.ingest` -- a NEW, narrow permission, category `ml_ops` alongside
   its siblings.
2. Role `ML_BRIDGE`, `es_sistema=True`, holding ONLY `ml_ops.ingest`.
3. `usuarios(username='ml-webhook-bridge', activo=True, password_hash=NULL)`.
   NULL is an allowed state for this column (`app/models/usuario.py:33`)
   and the login endpoint's NULL-hash guard already refuses it cleanly
   with 401 (`auth.py:94`) -- confirmed still in place, not re-added here.
   `activo=True` because this row authenticates via a real 90-day JWT
   (`scripts/mint_ml_bridge_token.py`); `usuario.activo=False` is this
   row's own kill switch (`deps.py:44-45`).

`downgrade()` removes ONLY what `upgrade()` certainly created: the user
and its role. It deliberately leaves `ml_ops.ingest` in place, because
`upgrade()` inserts that permission with `ON CONFLICT (codigo) DO NOTHING`
and therefore cannot know whether it created the row or found it already
there. Deleting it on the way down would cascade away grants and overrides
belonging to roles and users this migration never touched -- that is a
destructive teardown, not a rollback. A leftover permission that nothing
references is inert; a deleted one that something referenced is not.

Revision ID: 20260909_seed_ml_bridge
Revises: 20260908_tplink_ganancia_prod
Create Date: 2026-09-09
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260909_seed_ml_bridge"
down_revision = "20260908_tplink_ganancia_prod"
branch_labels = None
depends_on = None

USERNAME = "ml-webhook-bridge"
ROL_CODIGO = "ML_BRIDGE"
PERMISO_CODIGO = "ml_ops.ingest"


def upgrade() -> None:
    bind = op.get_bind()

    # Idempotency guard, same shape as 20260807_seed_agente_ia: a retried
    # run must not crash on a unique violation.
    existing_user_id = bind.execute(
        sa.text("SELECT id FROM usuarios WHERE username = :u"), {"u": USERNAME}
    ).scalar_one_or_none()
    if existing_user_id is not None:
        return  # Already seeded.

    op.execute(
        sa.text(
            """
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES (:codigo, :nombre, :descripcion, 'ml_ops', 202, false, NOW())
            ON CONFLICT (codigo) DO NOTHING
            """
        ).bindparams(
            codigo=PERMISO_CODIGO,
            nombre="Ingerir actividad ML (bridge)",
            descripcion=(
                "Permite al servicio ml-webhook-bridge notificar actividad de "
                "órdenes (POST /activity/ping), sin acceso de lectura "
                "(ml_ops.ver) ni de gestión (ml_ops.gestionar)."
            ),
        )
    )

    rol_id = bind.execute(
        sa.text(
            """
            INSERT INTO roles (codigo, nombre, descripcion, es_sistema, orden, activo, created_at)
            VALUES (:codigo, :nombre, :descripcion, true, 901, true, NOW())
            RETURNING id
            """
        ).bindparams(
            codigo=ROL_CODIGO,
            nombre="ML Webhook Bridge",
            descripcion=("Rol de servicio para el bridge ml-webhook. No debe asignarse a usuarios humanos."),
        )
    ).scalar_one()

    bind.execute(
        sa.text(
            """
            INSERT INTO roles_permisos_base (rol_id, permiso_id)
            SELECT :rol_id, p.id FROM permisos p WHERE p.codigo = :codigo
            ON CONFLICT DO NOTHING
            """
        ).bindparams(rol_id=rol_id, codigo=PERMISO_CODIGO)
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO usuarios (username, nombre, password_hash, activo, auth_provider, rol_id, created_at)
            VALUES (:username, :nombre, NULL, true, 'LOCAL', :rol_id, :created_at)
            """
        ).bindparams(
            username=USERNAME,
            nombre="ML Webhook Bridge",
            rol_id=rol_id,
            created_at=datetime.now(UTC),
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    user_id = bind.execute(sa.text("SELECT id FROM usuarios WHERE username = :u"), {"u": USERNAME}).scalar_one_or_none()
    if user_id is None:
        return  # Nothing to undo.

    bind.execute(sa.text("DELETE FROM usuarios WHERE id = :uid"), {"uid": user_id})

    rol_id = bind.execute(sa.text("SELECT id FROM roles WHERE codigo = :c"), {"c": ROL_CODIGO}).scalar_one_or_none()
    if rol_id is not None:
        # roles_permisos_base rows for this role cascade on delete (rol_id
        # FK is ondelete="CASCADE") -- no separate DELETE needed.
        bind.execute(sa.text("DELETE FROM roles WHERE id = :rid"), {"rid": rol_id})

    # `ml_ops.ingest` is intentionally NOT deleted here -- see the module
    # docstring. `upgrade()` created it with ON CONFLICT DO NOTHING, so it
    # cannot know whether the row is ours to remove, and both
    # `usuarios_permisos_override.permiso_id` and
    # `roles_permisos_base.permiso_id` cascade on delete: dropping the
    # permission would silently revoke it from every other role and user
    # that holds it. This migration's own user is already gone above, and
    # its overrides cascaded with it (`usuario_id` is ON DELETE CASCADE).
