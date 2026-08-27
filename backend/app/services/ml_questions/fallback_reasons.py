"""Fallback-reason vocabulary for the ML questions bot drafting pipeline.

Leaf module (design ml-bot-fallback-reason-tracking): no DB imports, no
app imports besides this file itself. `resolve_fallback_reason` is a pure
function so it can be exhaustively truth-tabled in
`tests/unit/test_ml_bot_fallback_reasons.py` without any DB/app fixture.

Precedence (highest first) mirrors the checks already made in
`drafting_service._draft_one` at the "resolved" call site (~line 586):
`fallback_denylist > deflection > low_confidence > drafted_no_answer`.
The two call sites that bypass this resolver entirely
(`injection_flagged` at ~529, `provider_error` at ~572) pass their literal
reason directly — see `INJECTION_FLAG_REASONS` below for why the denylist
value must also participate in the `injection_flag` derivation.
"""

from __future__ import annotations

# Reason literal: the manipulation-signal detector (R-503) matched BEFORE
# any LLM call was attempted.
REASON_INJECTION_FLAGGED = "injection_flagged"
# Reason literal: the LLM provider call or parse failed outright.
REASON_PROVIDER_ERROR = "provider_error"
# Reason literal: the LLM's answer matched the denylist validator (R-502).
REASON_FALLBACK_DENYLIST = "fallback_denylist"
# Reason literal: the LLM's answer was a recognized deflection response.
REASON_DEFLECTION = "deflection"
# Reason literal: the LLM's confidence was below the configured minimum.
REASON_LOW_CONFIDENCE = "low_confidence"
# Reason literal: the LLM explicitly reported it could not answer.
REASON_DRAFTED_NO_ANSWER = "drafted_no_answer"

FALLBACK_REASONS: frozenset[str] = frozenset(
    {
        REASON_INJECTION_FLAGGED,
        REASON_PROVIDER_ERROR,
        REASON_FALLBACK_DENYLIST,
        REASON_DEFLECTION,
        REASON_LOW_CONFIDENCE,
        REASON_DRAFTED_NO_ANSWER,
    }
)

# Reasons that must set `MlBotQuestion.injection_flag = True` (non-regression
# surface: this is the ONLY place that decides which reasons imply the flag,
# preserving the pre-existing `injection_flag=True/denylist_hit` behavior at
# both drafting_service.py call sites).
INJECTION_FLAG_REASONS: frozenset[str] = frozenset({REASON_INJECTION_FLAGGED, REASON_FALLBACK_DENYLIST})


def resolve_fallback_reason(
    *,
    can_answer: bool,
    below_confidence: bool,
    denylist_hit: bool,
    deflection: bool,
) -> str:
    """Pure precedence resolution for the "resolved" fallback call site
    (drafting_service.py ~line 586), where `can_answer`/confidence/denylist/
    deflection are all already known.

    Precedence (highest first): `fallback_denylist` > `deflection` >
    `low_confidence` > `drafted_no_answer`. `below_confidence` and
    `deflection` are independent booleans (either or both may be true
    alongside a `can_answer=False` LLM response); denylist takes priority
    over both because the denylist enforces a hard safety boundary.

    Raises `ValueError` when no cause is present at all (`can_answer` true
    and every rejection check false). The caller only reaches this resolver
    once at least one of the four is a cause, so that input is a programming
    error — and answering `drafted_no_answer` to it would record that the
    model declined when it reported the opposite, poisoning the very
    distribution this column exists to measure."""
    if denylist_hit:
        return REASON_FALLBACK_DENYLIST
    if deflection:
        return REASON_DEFLECTION
    if below_confidence:
        return REASON_LOW_CONFIDENCE
    if not can_answer:
        return REASON_DRAFTED_NO_ANSWER
    raise ValueError(
        "resolve_fallback_reason called with no fallback cause: "
        "can_answer=True with below_confidence, denylist_hit and deflection all False"
    )
