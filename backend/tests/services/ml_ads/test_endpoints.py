"""ml-billing-balance PR 1b -- ADS-1 / D5: request builders for the one-day ingestion recipe."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.ml_ads import endpoints
from tests.services.ml_ads.captures import load

DAY = date(2026, 10, 5)


def _captured(path_suffix: str, **params):
    for call in load("requests_2026_10_05.json"):
        if call["path"].endswith(path_suffix) and all(call["params"].get(k) == v for k, v in params.items()):
            return call
    raise AssertionError(f"no captured call for {path_suffix} {params}")


def _without_metrics(params: dict) -> dict:
    return {k: v for k, v in params.items() if k != "metrics"}


class TestOneDayWindows:
    def test_groups_page_matches_the_captured_request(self) -> None:
        request = endpoints.ad_groups_request(25713, DAY, offset=5400)
        captured = _captured("/25713/product_ads/ad_groups/search", offset=5400)
        assert request.path == captured["path"]
        assert _without_metrics(dict(request.params)) == _without_metrics(captured["params"])
        assert request.params["limit"] == 200

    def test_ads_page_matches_the_captured_request(self) -> None:
        request = endpoints.group_ads_request(953639148, DAY, offset=50)
        captured = _captured("/953639148/ads", offset=50)
        assert request.path == captured["path"]
        assert _without_metrics(dict(request.params)) == _without_metrics(captured["params"])
        assert request.params["limit"] == 50

    def test_summary_matches_the_captured_request(self) -> None:
        request = endpoints.campaigns_summary_request(25713, DAY)
        captured = _captured("/25713/product_ads/campaigns/search")
        assert request.path == captured["path"]
        # The capture also sent `limit=50` (16 campaigns fit); the summary is global, so we do not page it.
        assert _without_metrics(dict(request.params)) == {
            k: v for k, v in _without_metrics(captured["params"]).items() if k != "limit"
        }

    @pytest.mark.parametrize(
        "request_",
        [
            endpoints.ad_groups_request(25713, DAY, offset=0),
            endpoints.group_ads_request(953712626, DAY, offset=0),
            endpoints.campaigns_summary_request(714700, DAY),
        ],
    )
    def test_never_asks_for_daily_aggregation(self, request_) -> None:
        assert "aggregation_type" not in request_.params
        assert request_.params["date_from"] == request_.params["date_to"] == "2026-10-05"

    def test_metrics_list_asks_for_everything_the_mapper_reads(self) -> None:
        wanted = {
            "cost", "clicks", "prints", "direct_amount", "indirect_amount", "direct_units_quantity",
            "indirect_units_quantity", "units_quantity", "organic_units_quantity", "organic_units_amount",
        }  # fmt: skip
        sent = set(endpoints.ad_groups_request(1, DAY, offset=0).params["metrics"].split(","))
        assert wanted <= sent


class TestApiVersionHeaders:
    def test_the_captured_product_ads_calls_all_ran_on_version_2(self) -> None:
        calls = load("requests_2026_10_05.json")
        assert len(calls) == 114  # 2 summaries + 30 group pages + 82 `/ads` pages
        assert {call["api_version"] for call in calls} == {"2"}
        assert {call["status"] for call in calls} == {200}

    def test_product_ads_calls_use_version_2(self) -> None:
        for request in (
            endpoints.ad_groups_request(25713, DAY, offset=0),
            endpoints.group_ads_request(953712626, DAY, offset=0),
            endpoints.campaigns_summary_request(25713, DAY),
        ):
            assert request.headers == {"Api-Version": "2"}

    def test_advertisers_call_uses_version_1(self) -> None:
        request = endpoints.advertisers_request("PADS")
        assert request.path == "/advertising/advertisers"
        assert request.params == {"product_id": "PADS"}
        assert request.headers == {"Api-Version": "1"}

    def test_the_version_check_answered_200_with_no_header_v1_and_v2(self) -> None:
        checks = load("api_version_check_2026_10_05.json")
        assert [(c["api_version"], c["status"]) for c in checks] == [(None, 200), ("1", 200), ("2", 200)]


class TestIdsAreCoerced:
    def test_numeric_string_ids_are_interpolated_as_ints(self) -> None:
        assert endpoints.group_ads_request("0953712626", DAY, offset=0).path.endswith("/ad_groups/953712626/ads")
        assert "/advertisers/25713/" in endpoints.ad_groups_request("25713", DAY, offset=0).path

    @pytest.mark.parametrize("bad", ["25713/../x", "1; DROP", "", None, 1.5])
    def test_non_integer_ids_are_rejected_before_building_a_path(self, bad) -> None:
        with pytest.raises((ValueError, TypeError)):
            endpoints.ad_groups_request(bad, DAY, offset=0)
        with pytest.raises((ValueError, TypeError)):
            endpoints.group_ads_request(bad, DAY, offset=0)

    def test_negative_offset_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            endpoints.ad_groups_request(25713, DAY, offset=-1)
