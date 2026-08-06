"""Add ticket resumen/titulo_origen/resumen_origen columns (tickets-ai-triage PR 06)

Adds three nullable columns to `tickets` so the AI-curated `titulo` and
`resumen` can be persisted as proposals and confirmed, closing the gap left
by PR 4b (see obs #1371/#1308): a dedicated `resumen` column so the board
card summary never overwrites `descripcion` (which already carries the raw
intake text since PR 3a) with less information than the detail view; and
`titulo_origen`/`resumen_origen` so `confirmacion_service`'s generic
`setattr(ticket, f"{campo}_origen", ...)` pattern extends to these two
fields with zero special-casing.

Same conventions as PR 2a's `severidad`/`urgencia` columns:
  - `resumen`: VARCHAR(180), matching `TriagePropuesta.resumen`'s
    `max_length=180` LLM-contract cap (enforced again here as a DB-level
    backstop, not because Pydantic can be bypassed by the app itself).
  - `titulo_origen`/`resumen_origen`: VARCHAR + CHECK against the same
    closed vocabulary as `severidad_origen`/`urgencia_origen`
    (humano | ia_confirmada | ia_auto) — NOT a Postgres ENUM. You cannot
    drop a value from a PG enum, so `downgrade()` would be a lie.

No index on `resumen`: the board (a later slice) sorts/groups by
`estado`/`urgencia`, never by summary text, so a text column here would
only ever be read by primary key — an index would cost writes for a query
pattern that doesn't exist.

`titulo` itself is unchanged (already NOT NULL, `String(255)`, added in the
original tickets migration) — this migration only adds provenance for it.

Revision ID: 20260806_titulo_resumen_cols
Revises: 20260806_triage_confirmar
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260806_titulo_resumen_cols"
down_revision = "20260806_triage_confirmar"
branch_labels = None
depends_on = None

_ORIGEN_VALUES = ("humano", "ia_confirmada", "ia_auto")


def _in_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.add_column("tickets", sa.Column("resumen", sa.String(180), nullable=True))
    op.add_column("tickets", sa.Column("titulo_origen", sa.String(14), nullable=True))
    op.add_column("tickets", sa.Column("resumen_origen", sa.String(14), nullable=True))

    op.create_check_constraint(
        "ck_tickets_titulo_origen",
        "tickets",
        _in_check("titulo_origen", _ORIGEN_VALUES),
    )
    op.create_check_constraint(
        "ck_tickets_resumen_origen",
        "tickets",
        _in_check("resumen_origen", _ORIGEN_VALUES),
    )


def downgrade() -> None:
    op.drop_constraint("ck_tickets_resumen_origen", "tickets", type_="check")
    op.drop_constraint("ck_tickets_titulo_origen", "tickets", type_="check")

    op.drop_column("tickets", "resumen_origen")
    op.drop_column("tickets", "titulo_origen")
    op.drop_column("tickets", "resumen")
