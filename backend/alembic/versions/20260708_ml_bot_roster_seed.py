"""ml-bot: seed llm_providers roster with Groq+Cerebras+OpenRouter

Revision ID: 20260708_ml_bot_roster
Revises: 20260708_ml_bot_defs
Create Date: 2026-07-08

Follow-up on operator feedback ("está respondiendo solo groq"): the
`llm_providers` roster key was never seeded, so `RotatingProvider` was
falling back to Groq-only. Adds the roster with all three providers
enabled (matching the curated model list) so fresh deploys get
round-robin rotation from the first tick, and existing prod DBs get
the roster the moment this migration runs.

ON CONFLICT (clave) DO NOTHING preserves any existing customization:
production DBs where the operator inserted the roster manually keep
their version untouched. Requires the three API keys in .env — a
provider whose key is missing is silently skipped with a warning
(unchanged behavior).

Kept as a separate migration from 20260708_ml_bot_defs (which is
already applied in production) — Alembic history is append-only, so
extending an applied migration is not an option.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260708_ml_bot_roster"
down_revision: Union[str, None] = "20260708_ml_bot_defs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LLM_PROVIDERS_SEED = {
    "clave": "llm_providers",
    "valor": (
        '[{"name": "groq", "model": "llama-3.3-70b-versatile", "enabled": true}, '
        '{"name": "cerebras", "model": "llama-3.3-70b", "enabled": true}, '
        '{"name": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "enabled": true}]'
    ),
    "descripcion": (
        "Roster de proveedores LLM (JSON list de {name, model, enabled}). "
        "Round-robin por pregunta + failover en cadena (si el primero agota "
        "reintentos, prueba el siguiente antes del warm fallback). "
        "Ausente/malformado → fail-safe a Groq-only. Requiere que las API "
        "keys (GROQ_API_KEY / CEREBRAS_API_KEY / OPENROUTER_API_KEY) estén "
        "configuradas en el .env — proveedor sin key se saltea con warning."
    ),
    "tipo": "string",
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO ml_bot_config (clave, valor, descripcion, tipo)
            VALUES (:clave, :valor, :descripcion, :tipo)
            ON CONFLICT (clave) DO NOTHING
            """
        ),
        _LLM_PROVIDERS_SEED,
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM ml_bot_config WHERE clave = :clave"),
        {"clave": _LLM_PROVIDERS_SEED["clave"]},
    )
