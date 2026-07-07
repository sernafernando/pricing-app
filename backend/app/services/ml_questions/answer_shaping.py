"""
Answer-shaping for the ML questions bot (follow-up slice,
`sdd/ml-questions-ai/answer-shaping`).

Adds three panel-editable, live-DB-read knobs on top of the raw LLM answer
(design §6 stage 7 hand-off, same fail-safe `ml_bot_config` convention as
`policy.py`):

1. `answer_max_chars` — dynamically injected into the system prompt AND
   enforced fail-closed at parse time (`llm_provider.parse_llm_output`).
   Absent/malformed -> `_DEFAULT_ANSWER_MAX_CHARS` (300).
2. `answer_closing_text` — appended to REAL (bot) answers only, never to the
   warm fallback message. Absent/empty = off.
3. Company signature, discriminated by the publication's official store
   (`item.official_store_id` from the ML item payload — see
   `context_builder.extract_official_store_id`):
   - `answer_company_signature` — DEFAULT signature, used ONLY for items
     WITHOUT an official store.
   - `answer_signatures_by_store` — JSON `{official_store_id: "text"}` map
     for items WITH an official store. `""` value = explicitly no signature
     for that store. An official-store item with NO entry in the map gets
     NO signature (fail-safe: better silent than wrong-store-signed).
     Malformed JSON -> no per-store signatures at all (+ warning logged);
     the default signature is unaffected (it only applies to non-official
     items in the first place).

Assembly order (design): `LLM answer + "\\n\\n" + closing (if any) + "\\n" +
signature (if any)`. The assembled text is a hard ceiling of
`_ML_HARD_CHAR_LIMIT` (2000, ML's own limit) REGARDLESS of how the config
knobs above are set — a generous `answer_max_chars` plus a long closing/
signature must never produce a string ML itself would reject.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.services.ml_questions import policy

logger = logging.getLogger(__name__)

_DEFAULT_ANSWER_MAX_CHARS = 300
_ML_HARD_CHAR_LIMIT = 2000


def get_answer_max_chars(db: Session) -> int:
    """R-max-chars: panel-editable answer length budget. Absent, empty, or a
    non-positive/non-numeric value fails safe to `_DEFAULT_ANSWER_MAX_CHARS`
    (mirrors `policy.resolve_wait_minutes`'s malformed-int handling)."""
    raw = policy.get_config(db, "answer_max_chars", cast=str, default=str(_DEFAULT_ANSWER_MAX_CHARS))
    try:
        value = int(raw)
    except (ValueError, TypeError):
        logger.warning(
            "ml_bot_config: malformed answer_max_chars=%r; falling back to default=%d",
            raw,
            _DEFAULT_ANSWER_MAX_CHARS,
        )
        return _DEFAULT_ANSWER_MAX_CHARS
    if value <= 0:
        logger.warning(
            "ml_bot_config: non-positive answer_max_chars=%r; falling back to default=%d",
            raw,
            _DEFAULT_ANSWER_MAX_CHARS,
        )
        return _DEFAULT_ANSWER_MAX_CHARS
    return value


def resolve_closing_text(db: Session) -> str:
    """Global closing greeting, appended to real bot answers only. Absent or
    blank config = off (empty string)."""
    return policy.get_config(db, "answer_closing_text", cast=str, default="") or ""


def resolve_signature(db: Session, official_store_id: Optional[int]) -> str:
    """Company signature, discriminated by official store.

    - No official store (`official_store_id is None`) -> the DEFAULT
      signature (`answer_company_signature`), which may itself be unset (no
      signature).
    - Official store -> ONLY the per-store map (`answer_signatures_by_store`)
      applies; the default signature is intentionally never used here, so a
      store we haven't explicitly mapped never gets the wrong signature.
    """
    if official_store_id is None:
        return policy.get_config(db, "answer_company_signature", cast=str, default="") or ""

    raw = policy.get_config(db, "answer_signatures_by_store", cast=str, default="")
    if not raw:
        return ""

    try:
        mapping = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "ml_bot_config: malformed answer_signatures_by_store=%r; treating as no per-store signatures",
            raw,
        )
        return ""

    if not isinstance(mapping, dict):
        logger.warning(
            "ml_bot_config: answer_signatures_by_store=%r is not a JSON object; treating as no per-store signatures",
            raw,
        )
        return ""

    key = str(official_store_id)
    if key not in mapping:
        # Fail-safe (documented decision, sdd/ml-questions-ai/answer-shaping):
        # an official-store item with no explicit map entry gets NO
        # signature — better unsigned than signed with the wrong store's text.
        return ""

    value = mapping[key]
    if not isinstance(value, str):
        logger.warning(
            "ml_bot_config: answer_signatures_by_store[%r]=%r is not a string; treating as no signature",
            key,
            value,
        )
        return ""
    return value


def assemble_final_answer(answer: str, closing: str, signature: str) -> str:
    """Deterministic post-LLM append, applied ONLY to real bot answers
    (never the warm fallback). Order: answer, then closing (if any), then
    signature (if any). Hard-capped at `_ML_HARD_CHAR_LIMIT` regardless of
    config, since ML itself rejects longer answers."""
    text = answer
    if closing:
        text = f"{text}\n\n{closing}"
    if signature:
        text = f"{text}\n{signature}"
    if len(text) > _ML_HARD_CHAR_LIMIT:
        text = text[:_ML_HARD_CHAR_LIMIT]
    return text
