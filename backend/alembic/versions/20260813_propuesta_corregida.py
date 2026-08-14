"""Add 'corregida' outcome + valor_corregido to tickets_propuestas_ia
(tickets-triage-feedback PR1)

`confirmar()` gains an optional corrected value for `severidad`/`urgencia`
proposals (see `confirmacion_service._resolver_correccion`). This migration
widens `estado`'s CHECK constraint from 4 to 5 values and adds
`valor_corregido`, so a corrected confirm has somewhere to record BOTH the
outcome and the human's chosen value — the fourth structurally distinct
proposal outcome alongside ratified/discarded/from-scratch.

VARCHAR + CHECK for both `estado` (extending the existing constraint) and
`valor_corregido` (new): same rationale as every other campo/estado
constraint on this table — a value can never be dropped from a Postgres
ENUM type, so an ENUM's `downgrade()` would be a lie.

`valor_corregido`'s CHECK is deliberately campo-agnostic (the union of BOTH
correctable vocabularies, severidad ∪ urgencia): it blocks a corrupted value
at the DB layer while the per-campo correlation (a severidad value on a
severidad proposal) stays in the app, in
`app.tickets.services.vocabularios.VOCABULARIOS` +
`confirmacion_service._resolver_correccion` — the same two-layer shape
`campo` itself already uses (app allowlist + DB CHECK).

DIVERGES from this table's own `20260810_sector_tipo_check_ia.py` precedent
on downgrade shape, and says so rather than hiding it: that migration
REFUSES loudly (raises `RuntimeError`) if any row still uses one of its new
`campo` values, because `campo` has no semantically adjacent target — a
`sector` proposal is not a `severidad` proposal, so any remap would corrupt
it. `estado='corregida'` is different: `descartada` IS semantically
adjacent — both are terminal states meaning "the AI's proposed value is not
what ended up on the ticket." So THIS migration's `downgrade()` remaps
`corregida` rows to `descartada` instead of refusing.

THIS REMAP IS DELIBERATELY LOSSY, ON PURPOSE, AND IRREVERSIBLE — spelled out
again at the call site below: after downgrade, a correction becomes
indistinguishable from a discard, and `valor_corregido` is dropped in the
same downgrade, so re-upgrading cannot recover which value the human chose.
Accepted because the alternative (refusing loudly, like `campo` does) would
leave an un-downgradeable migration forever: an operator CAN reassign or
delete a wrong `campo` value by hand, but cannot un-correct a correction —
there is no "put the AI's original guess back as the ticket's live value"
operation that makes sense to ask an operator to perform manually.

Revision ID: 20260813_propuesta_corregida
Revises: 7f4b76219e4c
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260813_propuesta_corregida"
# Rebased onto the merge revision, not onto `20260812_triage_auto_apply`
# directly. That revision stopped being a head when `7f4b76219e4c` merged it
# with the pxq branch; hanging off it again re-forked the chain and broke the
# seven `TestMigrationGraph` single-head assertions spread across the suite.
down_revision = "7f4b76219e4c"
branch_labels = None
depends_on = None

_ESTADO_CONSTRAINT = "ck_tickets_propuestas_ia_estado"
_OLD_ESTADOS = ("pendiente", "confirmada", "descartada", "reemplazada")
_NEW_ESTADOS = _OLD_ESTADOS + ("corregida",)

_VALOR_CORREGIDO_CONSTRAINT = "ck_tickets_propuestas_ia_valor_corregido"
# Union of `vocabularios.VOCABULARIOS["severidad"]` and `["urgencia"]` —
# campo-agnostic by design, see module docstring. Literal tuple, not an
# import from application code: migrations must stay runnable against an
# old checkout of the app code, same convention as every other migration
# on this table.
_VALORES_CORREGIBLES = ("trivial", "menor", "mayor", "critica", "baja", "normal", "alta", "inmediata")


def upgrade() -> None:
    op.drop_constraint(_ESTADO_CONSTRAINT, "tickets_propuestas_ia", type_="check")
    op.create_check_constraint(
        _ESTADO_CONSTRAINT,
        "tickets_propuestas_ia",
        "estado IN (" + ", ".join(f"'{v}'" for v in _NEW_ESTADOS) + ")",
    )

    op.add_column("tickets_propuestas_ia", sa.Column("valor_corregido", sa.String(20), nullable=True))
    op.create_check_constraint(
        _VALOR_CORREGIDO_CONSTRAINT,
        "tickets_propuestas_ia",
        "valor_corregido IS NULL OR valor_corregido IN (" + ", ".join(f"'{v}'" for v in _VALORES_CORREGIBLES) + ")",
    )


def downgrade() -> None:
    bind = op.get_bind()
    # DESTRUCTIVE AND IRREVERSIBLE, documented at length in the module
    # docstring above: after this, a correction is indistinguishable from
    # a discard. `valor_corregido` is dropped right below, so re-running
    # `upgrade()` afterward cannot recover which value the human chose —
    # only that SOMETHING was once corrected is lost entirely, same as any
    # other discard.
    bind.execute(sa.text("UPDATE tickets_propuestas_ia SET estado = 'descartada' WHERE estado = 'corregida'"))

    op.drop_constraint(_VALOR_CORREGIDO_CONSTRAINT, "tickets_propuestas_ia", type_="check")
    op.drop_column("tickets_propuestas_ia", "valor_corregido")

    op.drop_constraint(_ESTADO_CONSTRAINT, "tickets_propuestas_ia", type_="check")
    op.create_check_constraint(
        _ESTADO_CONSTRAINT,
        "tickets_propuestas_ia",
        "estado IN (" + ", ".join(f"'{v}'" for v in _OLD_ESTADOS) + ")",
    )
