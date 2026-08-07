"""Seed agente-ia service user, AGENTE_IA role, tickets.agente permission
(tickets-ai-triage PR 6)

Materializes the non-human authentication boundary decided in the design
(PRIMARY DECISION: service user row + scoped long-lived JWT). Both
`WorkflowService.can_transition` and `PermisosService.tiene_permiso` take a
`Usuario`, and `tickets_comentarios.usuario_id` is NOT NULL — an AI agent
must resolve to a real `Usuario` row regardless of credential format.

Seeds, in order:
1. `tickets.agente` — a NEW, narrow permission. Deliberately NOT
   `tickets.gestionar`, which bundles state changes, assignment, workflow
   edits, attachment deletion and internal comments (design table, option a).
2. Role `AGENTE_IA`, holding only `tickets.ver` + `tickets.agente` +
   `tickets.triage.confirmar`. The last one is granted here because
   `20260806_add_permiso_triage_confirmar.py`'s own docstring says so
   verbatim: "The future service role AGENTE_IA (slice 6) doesn't exist yet
   here — slice 6's own migration must grant it this permission too." That
   grant was ONLY a no-op there (no matching role existed at that migration's
   time); this migration is what actually makes it real.
3. `usuarios(username='agente-ia', nombre='Agente IA', activo=True,
   password_hash=NULL)`. NULL is already an allowed state for this column
   (`app/models/usuario.py:33`, "Nullable para OAuth") and the login
   endpoint's NULL-hash guard (merged to `main` via PR 1, `auth.py:94`)
   already refuses it cleanly with 401 instead of the unhandled
   `AttributeError` a bare `bcrypt.checkpw(None, ...)` would raise —
   confirmed still in place on this branch, not re-added here.

Unlike `20260224_create_system_user.py`'s "sistema" service account (which
stays `activo=False` forever — it never authenticates, only attributes
automated writes), `agente-ia` MUST be `activo=True`: it authenticates via a
real 90-day JWT (`scripts/mint_agente_token.py`) and `usuario.activo=False`
is this row's own kill switch (`deps.py:44-45`), not a permanent state.

`downgrade()` refuses rather than orphans: if any ticket-domain row (or a
permission override) still references the seeded user, it raises instead of
silently leaving a dangling FK — same convention as
`20260805_seed_inbox_sector_and_workflow.py`.

Revision ID: 20260807_seed_agente_ia
Revises: 20260806_campo_check_ia
Create Date: 2026-08-07
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260807_seed_agente_ia"
down_revision = "20260806_campo_check_ia"
branch_labels = None
depends_on = None

USERNAME = "agente-ia"
ROL_CODIGO = "AGENTE_IA"
PERMISO_CODIGO = "tickets.agente"
PERMISOS_ROL = ["tickets.ver", PERMISO_CODIGO, "tickets.triage.confirmar"]

# Tables (and their usuario-FK column) that must be empty for this user
# before downgrade() may delete it — refusing beats orphaning.
_REFERENCING_TABLES = [
    ("tickets", "creador_id"),
    ("tickets_comentarios", "usuario_id"),
    ("tickets_historial", "usuario_id"),
    ("tickets_propuestas_ia", "confirmado_por_id"),
    ("tickets_asignaciones", "asignado_a_id"),
    ("tickets_asignaciones", "asignado_por_id"),
    ("tickets_adjuntos", "subido_por_id"),
    ("usuarios_permisos_override", "usuario_id"),
]


def upgrade() -> None:
    bind = op.get_bind()

    # Idempotency guard, same shape as 20260805_seed_inbox: a retried run
    # must not crash on a unique violation.
    existing_user_id = bind.execute(
        sa.text("SELECT id FROM usuarios WHERE username = :u"), {"u": USERNAME}
    ).scalar_one_or_none()
    if existing_user_id is not None:
        return  # Already seeded.

    op.execute(
        sa.text(
            """
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES (:codigo, :nombre, :descripcion, 'tickets', 135, false, NOW())
            ON CONFLICT (codigo) DO NOTHING
            """
        ).bindparams(
            codigo=PERMISO_CODIGO,
            nombre="Transicionar tickets (agente IA)",
            descripcion=(
                "Permite a agentes automatizados realizar transiciones de estado en "
                "tickets (POST /transicion), sin el resto de tickets.gestionar: no "
                "asignar, no editar workflow, no borrar adjuntos, no comentarios internos."
            ),
        )
    )

    rol_id = bind.execute(
        sa.text(
            """
            INSERT INTO roles (codigo, nombre, descripcion, es_sistema, orden, activo, created_at)
            VALUES (:codigo, :nombre, :descripcion, true, 900, true, NOW())
            RETURNING id
            """
        ).bindparams(
            codigo=ROL_CODIGO,
            nombre="Agente IA",
            descripcion=(
                "Rol de servicio para el agente de triage automático de tickets. No debe asignarse a usuarios humanos."
            ),
        )
    ).scalar_one()

    for codigo in PERMISOS_ROL:
        bind.execute(
            sa.text(
                """
                INSERT INTO roles_permisos_base (rol_id, permiso_id)
                SELECT :rol_id, p.id FROM permisos p WHERE p.codigo = :codigo
                ON CONFLICT DO NOTHING
                """
            ).bindparams(rol_id=rol_id, codigo=codigo)
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO usuarios (username, nombre, password_hash, activo, auth_provider, rol_id, created_at)
            VALUES (:username, :nombre, NULL, true, 'LOCAL', :rol_id, :created_at)
            """
        ).bindparams(
            username=USERNAME,
            nombre="Agente IA",
            rol_id=rol_id,
            created_at=datetime.now(UTC),
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    user_id = bind.execute(sa.text("SELECT id FROM usuarios WHERE username = :u"), {"u": USERNAME}).scalar_one_or_none()
    if user_id is None:
        return  # Nothing to undo.

    for table, column in _REFERENCING_TABLES:
        count = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :uid"),  # noqa: S608 (table/column are literals above)
            {"uid": user_id},
        ).scalar_one()
        if count:
            raise RuntimeError(
                f"Cannot downgrade {revision}: {count} row(s) in {table}.{column} still "
                f"reference the seeded '{USERNAME}' user (id={user_id}). Reassign or "
                f"delete them first — silently orphaning that foreign key is worse than "
                f"refusing to downgrade."
            )

    bind.execute(sa.text("DELETE FROM usuarios WHERE id = :uid"), {"uid": user_id})

    rol_id = bind.execute(sa.text("SELECT id FROM roles WHERE codigo = :c"), {"c": ROL_CODIGO}).scalar_one_or_none()
    if rol_id is not None:
        # roles_permisos_base rows for this role cascade on delete (rol_id FK
        # is ondelete="CASCADE") — no separate DELETE needed for the grants.
        bind.execute(sa.text("DELETE FROM roles WHERE id = :rid"), {"rid": rol_id})

    bind.execute(
        sa.text(
            "DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :c)"
        ),
        {"c": PERMISO_CODIGO},
    )
    bind.execute(sa.text("DELETE FROM permisos WHERE codigo = :c"), {"c": PERMISO_CODIGO})
