"""`map_replenishment` over the real captures of 2026-10-08, plus the cases of the reference app's
`mlau.test.ts` (`parseReplenishment`) re-expressed on mutated copies of a real body.

full_1 (MLAU228712304): 30DAYS, 311 units, GMV 13427445.75 ARS, six weekly rows newest first
(38, 122, 19, 66, 89, 10 units; days out of stock 1, 0, 0, ...), stock 184 / IN_TWO_WEEKS / min 35.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

from app.services.ml_publications.parsers.replenishment import map_replenishment
from tests.services.ml_publications.conftest import load_fixture

FIXTURE = "replenishment_20261008.json"


def body_of(name: str) -> dict:
    for call in load_fixture(FIXTURE)["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call["body"])
    raise KeyError(name)


def test_full_1_typed_columns():
    typed = map_replenishment(body_of("full_1"))
    assert typed == {
        "partial": False,
        "content_missing": None,
        "period": "30DAYS",
        "units_30d": 311,
        "gmv_30d": Decimal("13427445.75"),
        "currency_id": "ARS",
        "units_7d": 38,
        "units_14d": 160,
        "units_21d": 179,
        "days_out_of_stock_21d": 1,
        "history_through": date(2026, 10, 7),
        "total_stock": 184,
        "shipping_urgency": "IN_TWO_WEEKS",
        "minimum_distributable_stock": 35,
    }


def test_the_no_caller_twin_maps_identically():
    assert map_replenishment(body_of("full_1_no_caller")) == map_replenishment(body_of("full_1"))


def test_a_user_product_outside_full_maps_to_all_null():
    """Real: `stock`, `sales`, `recommendation` null (MLAU370292923)."""
    typed = map_replenishment(body_of("non_full_1"))
    assert all(value is None for key, value in typed.items() if key != "partial")
    assert typed["partial"] is False


def test_non_full_with_sales_still_maps_the_totals():
    typed = map_replenishment(body_of("non_full_2"))
    assert (typed["units_30d"], typed["currency_id"], typed["total_stock"]) == (63, "ARS", 120)


def test_every_capture_maps_without_error():
    for call in load_fixture(FIXTURE)["calls"]:
        map_replenishment(call["body"])


# --- port of mlau.test.ts (parseReplenishment) --------------------------------------------------


def test_history_is_sorted_newest_first_whatever_the_order_received():
    body = body_of("full_1")
    body["sales"]["sales_history"].reverse()
    typed = map_replenishment(body)
    assert (typed["units_7d"], typed["units_14d"], typed["units_21d"]) == (38, 160, 179)
    assert typed["history_through"] == date(2026, 10, 7)


def test_windows_are_the_newest_one_two_and_three_weeks_and_days_out_of_stock_sums_three():
    body = body_of("full_1")
    for week, (units, out) in zip(body["sales"]["sales_history"], [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12)]):
        week["units_sold"], week["days_out_of_stock"] = units, out
    typed = map_replenishment(body)
    assert (typed["units_7d"], typed["units_14d"], typed["units_21d"]) == (1, 4, 9)
    assert typed["days_out_of_stock_21d"] == 2 + 4 + 6


def test_one_week_of_history_gives_only_the_7_day_window_real_payload_truncated():
    body = body_of("full_1")
    body["sales"]["sales_history"] = body["sales"]["sales_history"][:1]
    typed = map_replenishment(body)
    assert typed["units_7d"] == 38
    assert (typed["units_14d"], typed["units_21d"], typed["days_out_of_stock_21d"]) == (None, None, None)


def test_two_weeks_of_history_with_a_week_missing_units_counts_zero_real_payload_truncated():
    body = body_of("full_1")
    body["sales"]["sales_history"] = body["sales"]["sales_history"][:2]
    del body["sales"]["sales_history"][1]["units_sold"]
    typed = map_replenishment(body)
    assert (typed["units_7d"], typed["units_14d"], typed["units_21d"]) == (38, 38, None)


def test_no_history_means_no_windows_real_payload_list_emptied():
    body = body_of("full_1")
    body["sales"]["sales_history"] = []
    typed = map_replenishment(body)
    assert typed["units_30d"] == 311  # totals are independent of the history
    assert (typed["units_7d"], typed["history_through"]) == (None, None)


def test_sales_null_leaves_every_sales_column_null_but_keeps_the_stock_real_payload_field_nulled():
    body = body_of("full_1")
    body["sales"] = None
    typed = map_replenishment(body)
    assert (typed["period"], typed["units_30d"], typed["gmv_30d"], typed["currency_id"]) == (None, None, None, None)
    assert (typed["units_7d"], typed["days_out_of_stock_21d"]) == (None, None)
    assert typed["total_stock"] == 184


def test_missing_totals_keep_the_history_real_payload_key_removed():
    body = body_of("full_1")
    del body["sales"]["sales_totals"]
    typed = map_replenishment(body)
    assert (typed["period"], typed["units_30d"], typed["gmv_30d"], typed["currency_id"]) == (None, None, None, None)
    assert typed["units_7d"] == 38


def test_gmv_is_exact_decimal_not_a_float_artifact():
    body = body_of("full_1")
    body["sales"]["sales_totals"]["gmv"][0]["full"] = 0.1
    assert map_replenishment(body)["gmv_30d"] == Decimal("0.1")


# --- partial answers (206) ----------------------------------------------------------------------


def test_x_content_missing_marks_the_answer_partial():
    typed = map_replenishment(body_of("full_1"), {"x-content-missing": "sales_history"})
    assert (typed["partial"], typed["content_missing"]) == (True, "sales_history")


def test_a_206_without_the_header_is_still_partial():
    typed = map_replenishment(body_of("full_1"), None, status=206)
    assert (typed["partial"], typed["content_missing"]) == (True, None)


def test_header_lookup_is_case_insensitive():
    typed = map_replenishment(body_of("full_1"), {"X-Content-Missing": "stock"})
    assert typed["content_missing"] == "stock"
