"""Truth-table tests for `app.services.ml_questions.fallback_reasons`.

This is the non-optional regression proof (design ml-bot-fallback-reason-
tracking, trap #3): the `injection_flag` derivation is the only real
behavior-change surface in this feature, so every one of the 16
`(can_answer, below_confidence, denylist_hit, deflection)` combinations is
exercised, along with the `INJECTION_FLAG_REASONS` membership assertion."""

from __future__ import annotations

import itertools

import pytest

from app.services.ml_questions.fallback_reasons import (
    FALLBACK_REASONS,
    INJECTION_FLAG_REASONS,
    resolve_fallback_reason,
)

_BOOL_COMBINATIONS = list(itertools.product([False, True], repeat=4))


def _expected_reason(can_answer: bool, below_confidence: bool, denylist_hit: bool, deflection: bool) -> str:
    """Independent re-derivation of the precedence rule, deliberately
    written without reusing `resolve_fallback_reason` internals."""
    if denylist_hit:
        return "fallback_denylist"
    if deflection:
        return "deflection"
    if below_confidence:
        return "low_confidence"
    return "drafted_no_answer"


@pytest.mark.parametrize("can_answer,below_confidence,denylist_hit,deflection", _BOOL_COMBINATIONS)
def test_resolve_fallback_reason_truth_table(
    can_answer: bool, below_confidence: bool, denylist_hit: bool, deflection: bool
) -> None:
    expected = _expected_reason(can_answer, below_confidence, denylist_hit, deflection)
    actual = resolve_fallback_reason(
        can_answer=can_answer,
        below_confidence=below_confidence,
        denylist_hit=denylist_hit,
        deflection=deflection,
    )
    assert actual == expected


@pytest.mark.parametrize("can_answer,below_confidence,denylist_hit,deflection", _BOOL_COMBINATIONS)
def test_injection_flag_membership_matches_denylist_hit(
    can_answer: bool, below_confidence: bool, denylist_hit: bool, deflection: bool
) -> None:
    """Non-optional non-regression proof: whether the resolved reason is a
    member of `INJECTION_FLAG_REASONS` must track `denylist_hit` exactly,
    for all 16 rows — this is what protects the pre-existing
    `injection_flag=denylist_hit` behavior at the drafting_service.py
    "resolved" call site."""
    reason = resolve_fallback_reason(
        can_answer=can_answer,
        below_confidence=below_confidence,
        denylist_hit=denylist_hit,
        deflection=deflection,
    )
    assert (reason in INJECTION_FLAG_REASONS) == denylist_hit


def test_fallback_reasons_contains_exactly_six_values() -> None:
    assert FALLBACK_REASONS == {
        "injection_flagged",
        "provider_error",
        "fallback_denylist",
        "deflection",
        "low_confidence",
        "drafted_no_answer",
    }


def test_injection_flag_reasons_exact_set() -> None:
    assert INJECTION_FLAG_REASONS == {"injection_flagged", "fallback_denylist"}
