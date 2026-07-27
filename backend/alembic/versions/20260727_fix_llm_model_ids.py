"""ml-bot: fix the cerebras/openrouter model ids in the llm_providers roster

Revision ID: 20260727_fix_llm_ids
Revises: 20260724_add_marca_sub_pm
Create Date: 2026-07-27

Operator report: "solo responde groq". The roster seeded by
20260708_ml_bot_roster was present and all three providers enabled, and the
rotation cursor advances correctly — but TWO of the three model ids do not
exist at their provider:

  * openrouter `meta-llama/llama-3.3-70b-instruct:free` — verified against the
    live catalogue (341 models): the `:free` variant was retired, only the
    paid `meta-llama/llama-3.3-70b-instruct` remains.
  * cerebras `llama-3.3-70b` — the account's catalogue exposes `gpt-oss-120b`,
    `zai-glm-4.7` and `gemma-4-31b`; no llama-3.3.

An unknown model id answers 4xx, which `OpenAICompatProvider.complete`
treats as a permanent client error (no retry) -> `LlmProviderError` ->
`RotatingProvider` fails over to the next provider. Groq is the only id that
resolves, so it absorbed every question and the rotation looked broken while
behaving exactly as designed.

Replacements were verified with a real chat-completions call using the same
payload shape the bot sends (`response_format={"type":"json_object"}`,
temperature 0.2); both returned valid JSON in `choices[0].message.content`.
Both are reasoning models, so completion tokens include reasoning tokens —
relevant for cerebras' 30k tokens/minute cap, which binds before its
5 requests/minute cap at our payload sizes.

The UPDATE is conditional on the stored value still being byte-identical to
the broken seed: if an operator has since hand-edited the roster, their
version is left untouched rather than silently overwritten.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_fix_llm_ids"
down_revision: Union[str, None] = "20260724_add_marca_sub_pm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Byte-identical to the value written by 20260708_ml_bot_roster.
BROKEN_ROSTER = (
    '[{"name": "groq", "model": "llama-3.3-70b-versatile", "enabled": true}, '
    '{"name": "cerebras", "model": "llama-3.3-70b", "enabled": true}, '
    '{"name": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "enabled": true}]'
)

FIXED_ROSTER = (
    '[{"name": "groq", "model": "llama-3.3-70b-versatile", "enabled": true}, '
    '{"name": "cerebras", "model": "gpt-oss-120b", "enabled": true}, '
    '{"name": "openrouter", "model": "openai/gpt-oss-20b:free", "enabled": true}]'
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE ml_bot_config
               SET valor = :fixed
             WHERE clave = 'llm_providers'
               AND valor = :broken
            """
        ),
        {"fixed": FIXED_ROSTER, "broken": BROKEN_ROSTER},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE ml_bot_config
               SET valor = :broken
             WHERE clave = 'llm_providers'
               AND valor = :fixed
            """
        ),
        {"fixed": FIXED_ROSTER, "broken": BROKEN_ROSTER},
    )
