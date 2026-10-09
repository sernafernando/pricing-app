"""`ads_cost_net_of_iva` is the ONLY place ads money changes basis (design D6, owner answers Q1 and Q10)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import literal, select

from app.services.ml_ads import iva
from app.services.ml_ads.iva import ADS_IVA_MEASUREMENT, API_COST_INCLUDES_IVA, ads_cost_net_of_iva

APP = Path(__file__).resolve().parents[3] / "app"


class TestTheBasisOfEachSource:
    def test_product_ads_is_net_so_nothing_is_divided(self):
        assert ads_cost_net_of_iva(Decimal("121.00"), "product_ads") == Decimal("121.00")

    def test_display_is_treated_as_net_by_owner_decision(self):
        assert ads_cost_net_of_iva(Decimal("194001.04"), "display") == Decimal("194001.04")

    def test_the_default_source_is_product_ads(self):
        assert ads_cost_net_of_iva(Decimal("50")) == Decimal("50")

    @pytest.mark.parametrize("source", ["brand_ads", "banana", ""])
    def test_a_source_that_was_never_measured_raises(self, source):
        with pytest.raises(ValueError, match="never measured"):
            ads_cost_net_of_iva(Decimal("1"), source)


class TestWhenTheApiCostWouldIncludeIva:
    """No source is gross today; the branch must still divide exactly once, in Python and in SQL."""

    @pytest.fixture()
    def gross(self, monkeypatch):
        monkeypatch.setitem(API_COST_INCLUDES_IVA, "product_ads", True)

    def test_python_path_divides_121_to_100(self, gross):
        assert ads_cost_net_of_iva(Decimal("121.00"), "product_ads") == Decimal("100.00")

    def test_sql_path_equals_the_python_path(self, gross, pg_ads_db):
        expression = ads_cost_net_of_iva(literal(Decimal("121.00")), "product_ads")
        assert pg_ads_db.execute(select(expression)).scalar() == Decimal("100.00")


class TestTheRecordedMeasurement:
    def test_product_ads_measurement_is_the_195_line_capture(self):
        m = ADS_IVA_MEASUREMENT["product_ads"]
        assert m["capture"] == "ads_iva_capture_20261008_111323.json.gz"
        assert m["billing_period"] == "2026-09-01"
        assert m["matched_lines"] == 195
        assert Decimal("1.205") <= m["median_ratio_billing_over_api"] <= Decimal("1.215")

    def test_display_records_the_aggregate_evidence_the_owner_accepted(self):
        m = ADS_IVA_MEASUREMENT["display"]
        assert m["accepted_by"] == "owner (answer Q10, 2026-10-08)"
        assert Decimal("1.19") <= m["aggregate_ratio_billing_over_api"] <= Decimal("1.21")

    def test_the_product_ads_boolean_matches_its_recorded_ratio_band(self):
        ratio = ADS_IVA_MEASUREMENT["product_ads"]["median_ratio_billing_over_api"]
        assert API_COST_INCLUDES_IVA["product_ads"] is iva.includes_iva_for_ratio(ratio)

    def test_display_is_outside_the_band_so_only_the_owner_decision_backs_it(self):
        ratio = ADS_IVA_MEASUREMENT["display"]["aggregate_ratio_billing_over_api"]
        with pytest.raises(ValueError, match="unexplained"):
            iva.includes_iva_for_ratio(ratio)
        assert API_COST_INCLUDES_IVA["display"] is False

    @pytest.mark.parametrize("ratio, gross", [("1.21", False), ("1.205", False), ("1.0", True), ("1.004", True)])
    def test_the_decision_rule_bands(self, ratio, gross):
        assert iva.includes_iva_for_ratio(Decimal(ratio)) is gross

    @pytest.mark.parametrize("ratio", ["1.10", "1.30", "0.9"])
    def test_an_unexplained_ratio_is_refused(self, ratio):
        with pytest.raises(ValueError, match="unexplained"):
            iva.includes_iva_for_ratio(Decimal(ratio))

    def test_brand_ads_is_absent_on_purpose(self):
        assert "brand_ads" not in API_COST_INCLUDES_IVA


def test_the_rate_lives_only_in_iva_py():
    """Guard: no other ads or board module may carry its own IVA rate."""
    offenders = []
    for package in ("services/ml_ads", "services/ml_daily_metrics"):
        for path in (APP / package).rglob("*.py"):
            if path.name == "iva.py" and path.parent.name == "ml_ads":
                continue
            text = path.read_text(encoding="utf-8")
            if "1.21" in text or "IVA_ML_DIVISOR" in text:
                offenders.append(str(path.relative_to(APP)))
    assert offenders == []
