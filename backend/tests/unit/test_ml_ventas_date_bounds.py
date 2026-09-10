"""Day boundaries for the sales listing filters.

`ml_orders_ops.date_created` is stored as UTC, which is right. But the day
an operator types is a LOCAL day: a sale at 22:00 in Buenos Aires is
already the next day in UTC. Resolving the filter's midnights in UTC moves
every evening sale one day forward -- three hours of business, every single
day, on the wrong side of the boundary.

Tested as pure functions rather than through the API because the
integration suite runs on SQLite, which drops the offset of a tz-aware
bound instead of converting it: the same query answers the opposite day
there than it does on Postgres. A test that had to be wrong in production
to be green is worse than no test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.routers.ml_ventas_ops import _parse_date_range, _parse_sold_month


# Buenos Aires is UTC-3, so local midnight is 03:00 UTC the same day.
def _utc(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


class TestTheRangeIsAnchoredToLocalMidnight:
    def test_from_starts_at_local_midnight_not_utc_midnight(self):
        start, _ = _parse_date_range("2026-09-10", None)

        assert start == _utc(2026, 9, 10, 3)

    def test_to_ends_at_the_next_local_midnight(self):
        """ "Up to 23:59:59.999" without having to pick how many nines: the
        bound is exclusive and sits at the next local midnight."""
        _, end = _parse_date_range(None, "2026-09-10")

        assert end == _utc(2026, 9, 11, 3)

    def test_a_sale_at_ten_at_night_falls_inside_the_day_it_was_sold(self):
        """22:00 local on the 10th is 01:00 UTC on the 11th -- the case
        that was landing on the wrong day."""
        start, end = _parse_date_range("2026-09-10", "2026-09-10")
        venta = _utc(2026, 9, 11, 1)

        assert start <= venta < end

    def test_and_does_not_also_fall_into_the_next_day(self):
        """The mirror half: if it belonged to both, two consecutive days
        would each count the same sale."""
        start, _ = _parse_date_range("2026-09-11", "2026-09-11")
        venta = _utc(2026, 9, 11, 1)

        assert venta < start

    def test_a_sale_just_after_local_midnight_belongs_to_the_new_day(self):
        start, end = _parse_date_range("2026-09-11", "2026-09-11")
        venta = _utc(
            2026,
            9,
            11,
            3,
        )

        assert start <= venta < end


class TestTheMonthUsesTheSameBoundary:
    """A month is a local idea too. Leaving the two filters on different
    boundaries would make them disagree about the same sale."""

    def test_the_month_starts_at_local_midnight(self):
        start, _ = _parse_sold_month("2026-09")

        assert start == _utc(2026, 9, 1, 3)

    def test_a_sale_at_ten_at_night_on_the_31st_belongs_to_that_month(self):
        agosto_start, agosto_end = _parse_sold_month("2026-08")
        venta = _utc(2026, 9, 1, 1)  # 22:00 local on 31 August

        assert agosto_start <= venta < agosto_end

    def test_and_not_to_the_next_one(self):
        septiembre_start, _ = _parse_sold_month("2026-09")
        venta = _utc(2026, 9, 1, 1)

        assert venta < septiembre_start


class TestTheGuardsStillHold:
    def test_no_bounds_means_no_filter(self):
        assert _parse_date_range(None, None) is None

    def test_a_backwards_range_is_rejected(self):
        with pytest.raises(HTTPException) as e:
            _parse_date_range("2026-09-12", "2026-09-10")
        assert e.value.status_code == 422

    @pytest.mark.parametrize("bad", ["ayer", "2026-13-01", "2026-09", "10/09/2026", "2026-09-99"])
    def test_an_unparseable_bound_is_rejected(self, bad: str):
        with pytest.raises(HTTPException) as e:
            _parse_date_range(bad, None)
        assert e.value.status_code == 422
