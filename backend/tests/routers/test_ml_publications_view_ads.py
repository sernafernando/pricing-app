"""P6.T4 + T5: the Ads block and "restar publicidad" in `GET /api/ml-publications/view/items`.

T4: until `ml-billing-balance` exists the provider is `UnavailableAdsProvider`: the response says Ads is not
available, a provider that raises degrades to the same (200, never a 500), and `restar_publicidad` is ignored and
reported. T5: with a FAKE provider the Ads cost is applied: the row markup, the sort and the filters use the
Ads-adjusted value, a publication with Ads cost but no sales shows the amount, and the formula is the configured one.
Units come from the real sales base (`ml_daily_metrics/sales.py`), seeded in the application database.
"""

# ruff: noqa: F811 -- the fixtures are imported from the markup test module and used by name

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.main import app
from app.services.ml_publications import settings_store
from app.services.ml_publications.view import ads as ads_module
from app.services.ml_ads.read import ViewAdsProvider
from app.services.ml_publications.view.ads import AdsAvailability, get_ads_provider
from app.services.ml_publications.view.markup import unit_markup
from tests.routers.test_ml_publications_view_markup import (  # noqa: F401
    COST,
    analyst,
    fill,
    ids,
    pg,
    pricing,
    reader,
    view_pg,
    worst_of,
)
from tests.routers.test_ml_publications_view import get, seed_rows
from tests.services.ml_daily_metrics import seed as sales_seed
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs

pytestmark = pytest.mark.postgres

SOLD = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)
PERIOD = {"ads_desde": "2026-09-01", "ads_hasta": "2026-09-30"}


class FakeAds:
    """An Ads cost provider with fixed amounts (ARS, already net of IVA) that records how it was asked."""

    def __init__(self, amounts, available: bool = True) -> None:
        self._amounts = amounts
        self._available = available
        self.calls: list[tuple] = []

    def availability(self) -> AdsAvailability:
        return AdsAvailability.AVAILABLE if self._available else AdsAvailability.UNAVAILABLE

    def amounts(self, mla_ids, date_from, date_to):
        self.calls.append((None if mla_ids is None else list(mla_ids), date_from, date_to))
        return self._amounts


class Exploding:
    def __init__(self, where: str) -> None:
        self.where = where

    def availability(self) -> AdsAvailability:
        if self.where == "availability":
            raise RuntimeError("billing is down")
        return AdsAvailability.AVAILABLE

    def amounts(self, mla_ids, date_from, date_to):
        raise RuntimeError("billing is down")


@pytest.fixture()
def provide():
    def _set(provider) -> None:
        app.dependency_overrides[get_ads_provider] = lambda: provider

    yield _set
    app.dependency_overrides.pop(get_ads_provider, None)


def sell(db, mla: str, qty: int, order_id: int) -> None:
    sales_seed.seed_sale(db, order_id, SOLD, [sales_seed.Line(77, mla, qty, Decimal("100"))])


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", sales_seed.SELLER)


def row_of(response, item_id: str) -> dict:
    return next(r for r in response.json()["items"] if r["item_id"] == item_id)


class TestAdsBlockWhileUnavailable:
    def test_the_default_provider_is_the_billing_one(self, pg) -> None:
        assert isinstance(get_ads_provider(pg), ViewAdsProvider)

    def test_the_response_says_ads_is_not_available(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        assert get(client, analyst).json()["ads"] == {
            "available": False,
            "reason": "provider_missing",
            "requested": False,
            "applied": False,
        }

    def test_without_ver_ganancia_there_is_no_ads_block(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, fill)
        assert "ads" not in get(client, reader).json()

    def test_restar_publicidad_is_ignored_and_reported_while_unavailable(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        plain = get(client, analyst, orden="markup")
        asked = get(client, analyst, orden="markup", restar_publicidad="true", **PERIOD)
        assert asked.status_code == 200
        assert asked.json()["ads"] == {
            "available": False,
            "reason": "provider_missing",
            "requested": True,
            "applied": False,
            "date_from": "2026-09-01",  # the period the client sent is echoed even when nothing was applied
            "date_to": "2026-09-30",
        }
        assert asked.json()["items"] == plain.json()["items"]

    def test_ignoring_it_does_not_require_a_period(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        assert get(client, analyst, restar_publicidad="true").status_code == 200

    @pytest.mark.parametrize("where", ["availability", "amounts"])
    def test_a_provider_that_raises_degrades_to_available_false_never_a_500(
        self, client, pg, analyst, pricing, provide, where
    ) -> None:
        seed_rows(pg, fill)
        provide(Exploding(where))
        response = get(client, analyst, orden="markup", restar_publicidad="true", **PERIOD)
        assert response.status_code == 200
        assert response.json()["ads"]["available"] is False
        assert response.json()["ads"]["reason"] == "provider_error"
        assert response.json()["ads"]["applied"] is False
        assert response.json()["ads"]["date_from"] == "2026-09-01"  # what the client asked for is still echoed
        assert ids(response)[:2] == ["MLA2", "MLA4"]  # the plain markup order: Ads simply is not there

    def test_a_provider_that_raises_on_a_page_request_degrades_too(self, client, pg, analyst, pricing, provide) -> None:
        seed_rows(pg, fill)
        provide(Exploding("amounts"))
        response = get(client, analyst, restar_publicidad="true", **PERIOD)
        assert response.status_code == 200 and response.json()["ads"]["reason"] == "provider_error"
        assert row_of(response, "MLA1")["markup"]["worst"] == round(worst_of(70), 2)


class TestPeriod:
    @pytest.mark.parametrize(
        "params, field",
        [
            ({"ads_desde": "2026-09-01"}, "ads_hasta"),
            ({"ads_hasta": "2026-09-01"}, "ads_desde"),
            ({"ads_desde": "yesterday", "ads_hasta": "2026-09-01"}, "ads_desde"),
            ({"ads_desde": "2026-09-30", "ads_hasta": "2026-09-01"}, "ads_desde"),
        ],
    )
    def test_a_malformed_or_inverted_period_is_422(self, client, pg, analyst, pricing, params, field) -> None:
        response = get(client, analyst, **params)
        assert response.status_code == 422 and response.json()["error"]["field"] == field

    def test_applying_ads_requires_the_period(self, client, pg, analyst, pricing, provide) -> None:
        provide(FakeAds({}))
        response = get(client, analyst, restar_publicidad="true")
        assert response.status_code == 422 and response.json()["error"]["field"] == "ads_desde"


class TestAdsApplied:
    def seed_ads(self, pg, db) -> FakeAds:
        seed_rows(pg, fill)
        sell(db, "MLA1", 4, 1001)  # 8000 of Ads over 4 units: 2000 each
        sell(db, "MLA6", 10, 1002)  # 100000 over 10 units: 10000 each -> negative
        # MLA2 has Ads cost and no sales; MLA5 has no Ads cost at all.
        return FakeAds({"MLA1": 8000.0, "MLA2": 5000.0, "MLA6": 100000.0})

    def test_the_row_markup_uses_the_ads_value_with_the_costo_extra_formula(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        provide(self.seed_ads(pg, db))
        response = get(client, analyst, restar_publicidad="true", **PERIOD)
        limpio = unit_markup(make_ctx(), make_inputs(producto_item_id=70, costo=COST[70]), {}).limpio
        expected = (limpio / (COST[70] + 2000.0) - 1) * 100
        row = row_of(response, "MLA1")
        assert row["markup"]["worst"] == round(expected, 2) < round(worst_of(70), 2)
        assert row["markup"]["ads"] == {"state": "ok", "amount": 8000.0, "units": 4, "per_unit": 2000.0}
        assert response.json()["ads"] == {
            "available": True,
            "reason": "ok",
            "requested": True,
            "applied": True,
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
        }

    def test_a_publication_with_ads_cost_and_no_sales_shows_the_amount_and_no_value(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        provide(self.seed_ads(pg, db))
        row = row_of(get(client, analyst, restar_publicidad="true", **PERIOD), "MLA2")
        assert row["markup"]["worst"] is None and row["markup"]["reason"] == "ads_sin_ventas"
        assert row["markup"]["ads"] == {"state": "ads_sin_ventas", "amount": 5000.0, "units": 0, "per_unit": None}

    def test_a_publication_without_ads_cost_keeps_its_plain_markup(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        provide(self.seed_ads(pg, db))
        row = row_of(get(client, analyst, restar_publicidad="true", **PERIOD), "MLA5")
        assert row["markup"]["worst"] == round(worst_of(72), 2)
        assert row["markup"]["ads"]["state"] == "sin_costo"

    def test_without_the_flag_the_markup_is_plain_and_the_provider_is_not_asked(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        fake = self.seed_ads(pg, db)
        provide(fake)
        body = get(client, analyst, **PERIOD).json()
        assert body["ads"] == {
            "available": True,
            "reason": "ok",
            "requested": False,
            "applied": False,
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
        }
        assert "ads" not in row_of(get(client, analyst), "MLA1")["markup"]
        assert fake.calls == []

    def test_the_sort_uses_the_ads_value_and_unpriced_by_ads_go_last(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        provide(self.seed_ads(pg, db))
        assert ids(get(client, analyst, orden="markup", restar_publicidad="true", **PERIOD)) == [
            "MLA4",  # no Ads: -19% from its worst variation
            "MLA6",  # 7.8% -> -11.8% after 10000 per unit
            "MLA5",
            "MLA1",  # 21% -> 15.5%
            "MLA2",  # Ads cost without sales: no value
            "MLA3",  # no link: no value
        ]

    def test_the_negative_filter_uses_the_ads_value(self, client, pg, analyst, pricing, provide, db) -> None:
        provide(self.seed_ads(pg, db))
        plain = get(client, analyst, markup_neg="true", orden="titulo")
        applied = get(client, analyst, markup_neg="true", orden="titulo", restar_publicidad="true", **PERIOD)
        assert ids(plain) == ["MLA2", "MLA4", "MLA5"]
        assert ids(applied) == ["MLA4", "MLA5", "MLA6"]  # MLA2 has no value after Ads; MLA6 went negative

    def test_min_and_max_apply_to_the_ads_value(self, client, pg, analyst, pricing, provide, db) -> None:
        provide(self.seed_ads(pg, db))
        applied = get(client, analyst, markup_min="0", orden="titulo", restar_publicidad="true", **PERIOD)
        assert ids(applied) == ["MLA1"]  # MLA6 fell below zero

    def test_the_provider_is_asked_for_the_page_mlas_on_the_page_path_and_for_everything_set_wide(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        fake = self.seed_ads(pg, db)
        provide(fake)
        get(client, analyst, limit=2, restar_publicidad="true", **PERIOD)
        get(client, analyst, orden="markup", restar_publicidad="true", **PERIOD)
        assert fake.calls == [
            (["MLA1", "MLA2"], date(2026, 9, 1), date(2026, 9, 30)),
            (None, date(2026, 9, 1), date(2026, 9, 30)),
        ]

    def test_money_figures_are_rounded_to_cents_for_display_but_the_markup_uses_the_exact_per_unit(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        seed_rows(pg, fill)
        sell(db, "MLA1", 3, 1001)
        provide(FakeAds({"MLA1": 100.0}))  # 33.333... per unit
        row = row_of(get(client, analyst, restar_publicidad="true", **PERIOD), "MLA1")
        assert row["markup"]["ads"] == {"state": "ok", "amount": 100.0, "units": 3, "per_unit": 33.33}
        limpio = unit_markup(make_ctx(), make_inputs(producto_item_id=70, costo=COST[70]), {}).limpio
        assert row["markup"]["worst"] == round((limpio / (COST[70] + 100.0 / 3) - 1) * 100, 2)

    def test_the_resta_limpio_formula_is_used_when_configured(self, client, pg, analyst, pricing, provide, db) -> None:
        provide(self.seed_ads(pg, db))
        settings_store.set_setting("view.ads_formula", "resta_limpio", "test")
        limpio = unit_markup(make_ctx(), make_inputs(producto_item_id=70, costo=COST[70]), {}).limpio
        row = row_of(get(client, analyst, restar_publicidad="true", **PERIOD), "MLA1")
        assert row["markup"]["worst"] == round(((limpio - 2000.0) / COST[70] - 1) * 100, 2)

    def test_the_same_per_unit_value_applies_to_every_variation(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        fake = self.seed_ads(pg, db)
        fake._amounts = {"MLA4": 4000.0}
        sell(db, "MLA4", 4, 1003)  # 1000 per unit on both variations
        provide(fake)
        row = row_of(get(client, analyst, restar_publicidad="true", **PERIOD), "MLA4")
        limpio = unit_markup(make_ctx(), make_inputs(producto_item_id=70, costo=COST[70]), {}).limpio
        assert row["markup"]["max"] == round((limpio / (COST[70] + 1000.0) - 1) * 100, 2)
        assert row["markup"]["ads"]["per_unit"] == 1000.0


def test_the_ads_module_exports_the_status_resolver() -> None:
    assert hasattr(ads_module, "resolve_ads")
