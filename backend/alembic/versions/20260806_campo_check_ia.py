"""Add campo CHECK constraint to tickets_propuestas_ia (tickets-ai-triage
confirmacion_service hardening)

Defect fix: `PropuestaIA.campo` was a plain VARCHAR(50) with no CHECK
constraint and no application-level validation, making the confirmation
path (`confirmacion_service._aplicar_confirmacion`) structurally an
arbitrary-attribute-write primitive on `Ticket` — a proposal row with
`campo='estado_id'` could write `ticket.estado_id` directly, with zero
workflow-graph validation, walking straight around the
`POST /tickets/{id}/transicion` enforcement engine (PR 1 / PR
#1072/#1074).

This migration adds the DB-level half of the fix: a CHECK constraint
mirroring `confirmacion_service.CAMPOS_CONFIRMABLES`
(severidad|urgencia|titulo|resumen). The app-level allowlist enforced in
`_aplicar_confirmacion()` is the other half — defense in depth, so even a
raw INSERT or a future app bug can't smuggle in an out-of-vocabulary
`campo`.

VARCHAR + CHECK (not a PG ENUM): same rationale as `estado`
(20260805_create_tickets_propuestas_ia.py) — you cannot drop a value from
a Postgres enum type, so a migration `downgrade()` would be a lie.

If a future slice adds a 5th confirmable field, this constraint's
vocabulary AND `confirmacion_service.CAMPOS_CONFIRMABLES` must both be
updated, plus a new migration — they are two independent, intentionally
un-shared literals (same convention as `estado`'s vocabulary above).

Revision ID: 20260806_campo_check_ia
Revises: 20260806_titulo_resumen_cols
Create Date: 2026-08-06
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260806_campo_check_ia"
down_revision = "20260806_titulo_resumen_cols"
branch_labels = None
depends_on = None

_CAMPO_VALUES = ("severidad", "urgencia", "titulo", "resumen")
_CONSTRAINT_NAME = "ck_tickets_propuestas_ia_campo"


def upgrade() -> None:
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "tickets_propuestas_ia",
        "campo IN (" + ", ".join(f"'{v}'" for v in _CAMPO_VALUES) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "tickets_propuestas_ia", type_="check")
