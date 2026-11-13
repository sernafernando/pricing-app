"""pubml-promo-mejor S2: the applicable-now rule of a candidate, on the cases the frontend's `isApplicableNow` also
runs (`tests/fixtures/candidata_aplicable_cases.json`, read by `pickPonerPreciosPromos.test.js`)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.ml_promotions_aplicable import candidata_aplicable_ahora, nombre_mes_es, parse_promo_instant

SHARED = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "candidata_aplicable_cases.json").read_text())
NOW = datetime.fromisoformat(SHARED["now"])


@pytest.mark.parametrize("case", SHARED["cases"], ids=[case["name"] for case in SHARED["cases"]])
def test_shared_case(case: dict) -> None:
    entry = {"status": "candidate", **case["entry"]}
    assert candidata_aplicable_ahora(entry, NOW) is case["applicable"]


def test_naive_dates_are_utc_and_a_date_only_finish_ends_at_the_end_of_the_day() -> None:
    assert parse_promo_instant("2026-11-13T10:00:00") == datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
    assert parse_promo_instant("2026-11-13", end_of_day=True) == datetime(2026, 11, 14, tzinfo=timezone.utc)
    assert parse_promo_instant("2026-11-13") == datetime(2026, 11, 13, tzinfo=timezone.utc)
    assert parse_promo_instant("garbage") is None and parse_promo_instant(None) is None


def test_the_premium_month_is_the_month_in_argentina() -> None:
    # 01:00 UTC on Dec 1st is still Nov 30th in Argentina.
    assert nombre_mes_es(datetime(2026, 12, 1, 1, tzinfo=timezone.utc)) == "noviembre"


def test_the_promotion_type_key_of_the_panel_payload_is_read_too() -> None:
    assert candidata_aplicable_ahora({"promotion_type": "SMART"}, NOW) is True
    assert candidata_aplicable_ahora({"promotion_type": "DOD"}, NOW) is False
