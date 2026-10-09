"""ml-billing-balance 6-iii -- the ads read service (design D9, AR-1/3/4): per MLA, per product, account level
and coverage. Product Ads come from the captured, drilled 2026-10-05 group 953712626; Display from the captured
2026-10-05 campaigns; Brand Ads from the captured all-zero body with the day's cost edited in the test
(DERIVED, said where it happens). Owners are DERIVED publication rows (`M`) laid over the captured MLAs."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado as M
from app.models.ml_ads import MlAdsDayLedger
from app.services.ml_ads import iva, mapper, read, store
from tests.services.ml_ads.test_brand import ADVERTISERS, _body, _with_spend
from tests.services.ml_ads.test_display import ADVERTISER as DISPLAY_ADVERTISER
from tests.services.ml_ads.test_display import _facts as display_facts
from tests.services.ml_ads.test_read_provider import DAY, GAUSS, T0, TPLINK, _close, _seed

BIG, SMALL, NO_COST = "MLA1150587086", "MLA3505349772", "MLA1417727981"  # the captured MLAs; NO_COST has organic only


def _publish(db, mlp_id: int, mla: str, product) -> None:
    """DERIVED: a publication row giving `mla` its owner product."""
    db.add(M(mlp_id=mlp_id, mlp_publicationID=mla, item_id=product))
    db.flush()


class TestAdsByMla:
    def test_one_row_per_mla_with_cost_both_bases_and_the_informational_figures(self, db) -> None:
        _seed(db)
        _publish(db, 1, BIG, 10)
        rows = {r.mla: r for r in read.ads_by_mla(db, DAY, DAY)}
        assert set(rows) == {BIG, SMALL}  # the zero-cost MLAs are not ad spend
        big = rows[BIG]
        assert (big.owner_product_id, big.cost_api, big.cost_net) == (10, Decimal("63996.44"), Decimal("63996.44"))
        assert (big.clicks, big.prints, big.direct_units, big.organic_units) == (141, 5296, 32, 28)
        assert (big.direct_amount, big.indirect_amount) == (Decimal("1053364.00"), Decimal("44285.00"))

    def test_an_mla_without_a_publication_or_a_sale_is_sin_producto(self, db) -> None:
        _seed(db)
        assert {r.mla: r.owner_product_id for r in read.ads_by_mla(db, DAY, DAY)} == {BIG: 0, SMALL: 0}

    def test_mlas_narrows_and_the_range_bounds_the_days(self, db) -> None:
        _seed(db)
        _seed(db, DAY + timedelta(days=30))
        rows = read.ads_by_mla(db, DAY, DAY + timedelta(days=1), mlas=[SMALL])
        assert [(r.mla, r.cost_api) for r in rows] == [(SMALL, Decimal("695.74"))]

    def test_the_net_cost_goes_through_the_single_iva_function(self, db, monkeypatch) -> None:
        _seed(db)
        monkeypatch.setitem(iva.API_COST_INCLUDES_IVA, "product_ads", True)
        big = next(r for r in read.ads_by_mla(db, DAY, DAY) if r.mla == BIG)
        assert (big.cost_api, big.cost_net) == (Decimal("63996.44"), Decimal("63996.44") / iva.IVA_ML_DIVISOR)

    def test_no_data_is_an_empty_list(self, db) -> None:
        assert read.ads_by_mla(db, DAY, DAY) == []


class TestAdsByProduct:
    def test_it_sums_the_mlas_of_each_owner_and_counts_them(self, db) -> None:
        _seed(db)
        _publish(db, 1, BIG, 10)
        _publish(db, 2, SMALL, 10)
        [row] = read.ads_by_product(db, DAY, DAY)
        assert (row.product_id, row.mlas_count) == (10, 2)
        assert (row.cost_api, row.clicks, row.prints) == (Decimal("64692.18"), 142, 5302)

    def test_sin_producto_is_the_zero_row(self, db) -> None:
        _seed(db)
        _publish(db, 1, BIG, 10)
        by_product = {r.product_id: r for r in read.ads_by_product(db, DAY, DAY)}
        assert by_product[0].cost_api == Decimal("695.74") and by_product[0].mlas_count == 1

    def test_product_ids_narrows_including_zero(self, db) -> None:
        _seed(db)
        _publish(db, 1, BIG, 10)
        assert [r.product_id for r in read.ads_by_product(db, DAY, DAY, product_ids=[0])] == [0]
        assert [r.product_id for r in read.ads_by_product(db, DAY, DAY, product_ids=[10])] == [10]


class TestAdsAccountLevel:
    def _display(self, db) -> None:
        store.upsert_display_days(db, display_facts(), now=T0)

    def test_display_is_summed_per_campaign_with_its_net_cost(self, db) -> None:
        self._display(db)
        got = read.ads_account_level(db, DAY, DAY).display
        assert got.cost_api == got.cost_net == Decimal("121938.82")  # the four captured campaigns with spend
        assert {c.campaign_id for c in got.by_campaign} == {335306, 301232, 294806, 259859}
        assert next(c for c in got.by_campaign if c.campaign_id == 335306).cost_api == Decimal("27226.79")

    def test_display_net_goes_through_the_single_iva_function(self, db, monkeypatch) -> None:
        self._display(db)
        monkeypatch.setitem(iva.API_COST_INCLUDES_IVA, "display", True)
        got = read.ads_account_level(db, DAY, DAY).display
        assert got.cost_net == Decimal("121938.82") / iva.IVA_ML_DIVISOR

    def test_brand_is_informational_and_has_no_net_cost(self, db) -> None:
        # DERIVED: the captured all-zero Brand body with the day's cost edited (as test_brand does).
        fact = mapper.map_brand_day(ADVERTISERS[1], DAY, _with_spend(_body(ADVERTISERS[1]), 1500.0))
        store.upsert_brand_days(db, [fact], now=T0)
        got = read.ads_account_level(db, DAY, DAY)
        assert (got.brand.cost_informational, got.display.cost_api) == (Decimal("1500.00"), Decimal(0))
        assert not hasattr(got.brand, "cost_net")

    def test_outside_the_range_there_is_nothing(self, db) -> None:
        self._display(db)
        got = read.ads_account_level(db, DAY + timedelta(days=1), DAY + timedelta(days=2))
        assert (got.display.cost_api, got.display.by_campaign) == (Decimal(0), [])
        assert DISPLAY_ADVERTISER == 25713  # the captured advertiser the facts belong to


class TestAdsCoverage:
    TODAY = DAY + timedelta(days=5)

    def test_data_through_is_the_providers(self, db) -> None:
        for advertiser in (GAUSS, TPLINK):
            _close(db, advertiser, DAY)
        got = read.ads_coverage(db, DAY, DAY, today=self.TODAY)
        assert (got.data_through, got.missing_days, got.mismatch_days) == (DAY, [], [])

    def test_a_ledgered_advertiser_without_a_closed_day_is_missing_with_its_status(self, db) -> None:
        _close(db, GAUSS, DAY)
        _close(db, TPLINK, DAY, "error")
        got = read.ads_coverage(db, DAY, DAY, today=self.TODAY)
        assert [(d.source, d.advertiser_id, d.day, d.status) for d in got.missing_days] == [
            ("product_ads", TPLINK, DAY, "error")
        ]

    def test_a_day_without_any_row_is_missing_with_no_status(self, db) -> None:
        _close(db, GAUSS, DAY)
        _close(db, GAUSS, DAY + timedelta(days=2))
        got = read.ads_coverage(db, DAY, DAY + timedelta(days=2), today=self.TODAY)
        assert [(d.day, d.status) for d in got.missing_days] == [(DAY + timedelta(days=1), None)]

    def test_today_and_the_future_are_not_missing(self, db) -> None:
        _close(db, GAUSS, DAY)
        got = read.ads_coverage(db, DAY, DAY + timedelta(days=9), today=DAY + timedelta(days=1))
        assert got.missing_days == []

    def test_mismatch_days_are_listed_and_are_not_missing(self, db) -> None:
        _close(db, GAUSS, DAY, "mismatch")
        got = read.ads_coverage(db, DAY, DAY, today=self.TODAY)
        assert [(d.source, d.day, d.status) for d in got.mismatch_days] == [("product_ads", DAY, "mismatch")]
        assert got.missing_days == []

    def test_every_source_is_checked(self, db) -> None:
        db.add(MlAdsDayLedger(source="display", advertiser_id=GAUSS, day=DAY, status="refetch"))
        db.flush()
        got = read.ads_coverage(db, DAY, DAY, today=self.TODAY)
        assert [(d.source, d.status) for d in got.missing_days] == [("display", "refetch")]
