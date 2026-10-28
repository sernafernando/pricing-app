"""Sorting the Publicaciones list by Métricas ML's figures (`orden` facturado_30d, unidades_7d, unidades_30d,
markup_30d, total_gauss_30d): the WHOLE filtered set is ranked by the Board's own publication figures over the last
30 business days, then paged -- never the page alone.

Real Postgres: the store and the Board's tables in one throwaway schema, as in production. What matters: the order
is total and stable across pages (`item_id` closes every tie), publications without sales in the 30 days (and,
for the markup, without cost) go last in BOTH directions, the filter still decides the set and the total, and
the persisted lines give the same order as the live derivation.
"""

# ruff: noqa: F811 -- `mlpub_pg` is the store's fixture, imported and used by name

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, text, update
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import FilterError, parse_filter
from tests.services.ml_daily_metrics.test_board_sale_lines_postgres import populate_sale_lines
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_units_sold_postgres import order

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
RECENT = datetime(2026, 9, 28, 15, tzinfo=timezone.utc)  # inside the 7 days
EARLIER = datetime(2026, 9, 15, 15, tzinfo=timezone.utc)  # inside the 30 days, outside the 7
OLD = datetime(2026, 8, 1, 15, tzinfo=timezone.utc)  # before the 30 days


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", False)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def priced(session, order_id, mla, qty, accredited, *, tg, costo) -> None:
    order(session, order_id, [(mla, None, qty)], accredited=accredited)
    session.execute(
        update(MlOrderMetrics)
        .where(MlOrderMetrics.order_id == order_id)
        .values(
            total_gauss=None if tg is None else Decimal(tg), costo_mercaderia=None if costo is None else Decimal(costo)
        )
    )
    session.flush()


@pytest.fixture()
def store(mlpub_pg):  # noqa: F811
    """Unit price 10 everywhere, so gross = 10 x units.

    MLA1  5 u (all recent)     gross 50  markup 20 %   Total Gauss 10
    MLA2  3 u (1 recent)       gross 30  markup 50 %   Total Gauss 30
    MLA3  3 u (earlier)        gross 30  no cost       Total Gauss 6
    MLA4  never sold
    MLA5  sold only before the 30 days
    MLA6  1 u (recent)         gross 10  markup -10 %  Total Gauss -1
    MLA7  paused: out of the `estado=active` set
    """
    from app.models.producto import ProductoERP

    ProductoERP.__table__.create(bind=mlpub_pg)
    seed.create_board_tables(mlpub_pg)
    with mlpub_pg.begin() as conn:
        for mla in ("MLA1", "MLA2", "MLA3", "MLA4", "MLA5", "MLA6"):
            seed.add_item(conn, mla, status="active")
        seed.add_item(conn, "MLA7", status="paused")
    session = sessionmaker(bind=mlpub_pg)()
    priced(session, 1, "MLA1", 5, RECENT, tg="10", costo="50")
    priced(session, 2, "MLA2", 1, RECENT, tg="10", costo="20")
    priced(session, 3, "MLA2", 2, EARLIER, tg="20", costo="40")
    priced(session, 4, "MLA3", 3, EARLIER, tg="6", costo=None)
    priced(session, 5, "MLA5", 9, OLD, tg="9", costo="9")
    priced(session, 6, "MLA6", 1, RECENT, tg="-1", costo="10")
    priced(session, 7, "MLA7", 99, RECENT, tg="99", costo="99")
    session.commit()
    session.close()
    reader = sessionmaker(bind=mlpub_pg)()
    yield reader
    reader.rollback()
    reader.close()


def ids(db, orden: str, direction: str = "desc", limit: int = 100, offset: int = 0, **filters: str) -> list[str]:
    page = listing.list_items(
        db,
        parse_filter(**filters),
        listing.parse_sort(orden, direction),
        limit,
        offset,
        events=False,
        can_see_margin=True,
    )
    return [item["item_id"] for item in page.items]


def every_page(db, orden: str, direction: str, size: int = 2, **filters: str) -> list[str]:
    out: list[str] = []
    for offset in range(0, 10, size):
        out += ids(db, orden, direction, limit=size, offset=offset, **filters)
    return out


UNSOLD = ["MLA4", "MLA5"]  # no sales in the 30 days: last in both directions, by item_id


class TestOrder:
    def test_gross_ranks_the_whole_set_ties_by_item_id_unsold_last(self, store) -> None:
        assert ids(store, "facturado_30d", "desc", estado="active") == ["MLA1", "MLA2", "MLA3", "MLA6", *UNSOLD]
        assert ids(store, "facturado_30d", "asc", estado="active") == ["MLA6", "MLA2", "MLA3", "MLA1", *UNSOLD]

    def test_a_next_key_breaks_the_figure_ties_and_the_export_keeps_the_order(self, store) -> None:
        for mla, title in (("MLA2", "Zeta"), ("MLA3", "Alfa"), ("MLA4", "Zulu"), ("MLA5", "Beta")):
            store.execute(text("UPDATE ml_items SET title = :t WHERE item_id = :i"), {"t": title, "i": mla})
        # MLA2 and MLA3 both sold 30; the unsold tie too: the title decides, not the item id
        expected = ["MLA1", "MLA3", "MLA2", "MLA6", "MLA5", "MLA4"]
        assert ids(store, "facturado_30d,titulo", "desc", estado="active") == expected
        assert every_page(store, "facturado_30d,titulo", "desc", estado="active") == expected
        keys = listing.ordered_keys(
            store, parse_filter(estado="active"), listing.parse_sort("facturado_30d,titulo", "desc"), None, events=False
        )
        assert keys == expected

    def test_pages_cut_the_ranked_set_never_rank_the_page(self, store) -> None:
        whole = ids(store, "facturado_30d", "desc", estado="active")
        assert every_page(store, "facturado_30d", "desc", estado="active") == whole
        assert ids(store, "facturado_30d", "desc", limit=2, offset=2, estado="active") == ["MLA3", "MLA6"]

    def test_units_of_7_and_30_days(self, store) -> None:
        # 7 days: MLA1 5, MLA2 1, MLA6 1, MLA3 0 (sold in the 30 days: ranked, at 0)
        assert ids(store, "unidades_7d", "desc", estado="active") == ["MLA1", "MLA2", "MLA6", "MLA3", *UNSOLD]
        assert ids(store, "unidades_30d", "asc", estado="active") == ["MLA6", "MLA2", "MLA3", "MLA1", *UNSOLD]

    def test_markup_without_cost_goes_last_with_the_unsold(self, store) -> None:
        assert ids(store, "markup_30d", "desc", estado="active") == ["MLA2", "MLA1", "MLA6", "MLA3", *UNSOLD]
        assert ids(store, "markup_30d", "asc", estado="active") == ["MLA6", "MLA1", "MLA2", "MLA3", *UNSOLD]

    def test_total_gauss(self, store) -> None:
        assert ids(store, "total_gauss_30d", "desc", estado="active") == ["MLA2", "MLA1", "MLA3", "MLA6", *UNSOLD]
        assert ids(store, "total_gauss_30d", "asc", estado="active") == ["MLA6", "MLA3", "MLA1", "MLA2", *UNSOLD]

    def test_the_filter_decides_the_set_and_the_total(self, store) -> None:
        page = listing.list_items(
            store, parse_filter(estado="active"), listing.parse_sort("facturado_30d", "desc"), 2, 0, events=False
        )
        assert page.total == 6 and "MLA7" not in ids(store, "facturado_30d", estado="active")
        assert ids(store, "facturado_30d")[0] == "MLA7"  # unfiltered, the paused 990 leads
        assert ids(store, "facturado_30d", q="no-such-publication") == []

    def test_a_page_past_the_end_is_empty_with_the_total(self, store) -> None:
        page = listing.list_items(
            store, parse_filter(estado="active"), listing.parse_sort("facturado_30d", "desc"), 2, 50, events=False
        )
        assert (page.items, page.total) == ([], 6)

    def test_the_persisted_lines_give_the_same_order(self, store, monkeypatch) -> None:
        from app.models.ml_sale_line import MlSaleLine

        live = {orden: ids(store, orden, estado="active") for orden in listing.METRIC_SORTS}
        MlSaleLine.__table__.create(bind=store.connection())
        assert populate_sale_lines(store) == 7
        monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
        reads: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            if "ml_sale_lines" in statement:
                reads.append(statement)

        engine = store.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            persisted = {orden: ids(store, orden, estado="active") for orden in listing.METRIC_SORTS}
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert reads, "the flag is on, yet no statement read ml_sale_lines: the order came from the live derivation"
        assert persisted == live

    def test_the_default_direction_is_highest_first(self) -> None:
        for orden in ("facturado_30d", "unidades_7d", "unidades_30d", "markup_30d", "total_gauss_30d"):
            assert listing.parse_sort(orden, None).descending is True

    def test_the_board_is_gone_when_the_page_is_done(self, store) -> None:
        from sqlalchemy import text

        ids(store, "facturado_30d", estado="active")
        assert store.execute(text(f"SELECT to_regclass('pg_temp.{board.MLA_SET_TABLE}') IS NULL")).scalar() is True


class TestMarginGuard:
    @pytest.mark.parametrize("orden", ["markup_30d", "total_gauss_30d"])
    def test_margin_sorts_refuse_unless_the_caller_says_it_may_see_margins(self, store, orden) -> None:
        """Fail closed: the flag defaults to no."""
        for kwargs in ({}, {"can_see_margin": False}):
            with pytest.raises(FilterError) as caught:
                listing.list_items(
                    store, parse_filter(), listing.parse_sort(orden, None), 10, 0, events=False, **kwargs
                )
            assert caught.value.field == "orden"

    def test_the_sales_sorts_need_no_margin(self, store) -> None:
        page = listing.list_items(
            store, parse_filter(estado="active"), listing.parse_sort("facturado_30d", None), 1, 0, events=False
        )
        assert [item["item_id"] for item in page.items] == ["MLA1"]


class TestWithTheMarkupFilter:
    def test_the_metric_order_ranks_only_what_the_markup_filter_accepted(self, store, monkeypatch) -> None:
        """`markup_min` prices the whole set first; the Métricas order then ranks only the accepted publications."""
        from types import SimpleNamespace

        from app.services.ml_publications.view.filters import MarkupFilter
        from app.services.ml_publications.view.markup_service import MarkupQuery, MarkupResult, MarkupStats

        worst = {"MLA1": 5.0, "MLA2": -1.0, "MLA3": 1.0, "MLA4": 9.0, "MLA5": None, "MLA6": 2.0}

        def priced(_db, _pricing, *, f=None, item_ids=None, ads=None):
            def one(value):
                markup = SimpleNamespace(
                    value_min=value, value_max=value, worst=value, any_negative=False, reason="ok", partial=0
                )
                return SimpleNamespace(markup=markup, ads=None)

            return MarkupResult({k: one(v) for k, v in worst.items()}, MarkupStats(5, {}, 0.0))

        monkeypatch.setattr(listing, "compute_markups", priced)
        query = MarkupQuery(store, MarkupFilter(minimum=0.0))
        page = listing.list_items(
            store,
            parse_filter(estado="active"),
            listing.parse_sort("facturado_30d", "desc"),
            2,
            0,
            events=False,
            markup=query,
            can_see_margin=True,
        )
        # accepted: MLA1 (50), MLA3 (30), MLA4 (unsold), MLA6 (10) -- MLA2 below the minimum, MLA5 unpriced
        assert page.total == 4
        assert [item["item_id"] for item in page.items] == ["MLA1", "MLA3"]
        assert page.items[0]["markup"]["worst"] == 5.0
        rest = listing.list_items(
            store,
            parse_filter(estado="active"),
            listing.parse_sort("facturado_30d", "desc"),
            2,
            2,
            events=False,
            markup=query,
            can_see_margin=True,
        )
        assert [item["item_id"] for item in rest.items] == ["MLA6", "MLA4"]
