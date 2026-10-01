"""ODD `metricas-ml-tablero` T2: `backfill_ml_daily_metrics` fills and heals
`ml_product_daily_metrics` from source. Same reporting discipline as the
other backfills: `examined`/`written`/`remaining`, `remaining` from a FULL
re-scan, and a dry run that writes nothing."""

from __future__ import annotations

import logging

import pytest

from app.models.ml_daily_metrics import MlProductDailyMetrics
from app.scripts import backfill_ml_daily_metrics as script
from app.services.order_metrics.store import store_order_metrics
from tests.services.ml_daily_metrics.test_rollup import DAY, _item, _metrics, _order, _seller  # noqa: F401


@pytest.fixture()
def seeded(db, monkeypatch):
    class _NoClose:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    monkeypatch.setattr(script, "SessionLocal", lambda: _NoClose(db))
    for order_id, mla in ((301, "MLA1"), (302, "MLA2"), (303, "MLA3")):
        _order(db, order_id)
        _item(db, order_id, mla, qty=1, price="100.00", producto=11)
    store_order_metrics(db, {301: _metrics(301), 302: _metrics(302), 303: _metrics(303)})
    # History before the rollup existed: wipe it, and leave one stale row
    # for a bucket that has no sale at all.
    db.query(MlProductDailyMetrics).delete()
    db.add(MlProductDailyMetrics(product_item_id=11, mla="MLA_GHOST", day=DAY, units=5, orders=1))
    db.commit()
    return db


def _units(db):
    return {r.mla: r.units for r in db.query(MlProductDailyMetrics).all()}


def test_dry_run_reports_and_writes_nothing(seeded):
    result = script.run_backfill(dry_run=True)

    assert result["examined"] == 4
    assert result["remaining"] == 4
    assert result["written"] == 0
    assert _units(seeded) == {"MLA_GHOST": 5}


def test_run_fills_missing_buckets_and_drops_ghosts(seeded):
    result = script.run_backfill(dry_run=False)

    assert _units(seeded) == {"MLA1": 1, "MLA2": 1, "MLA3": 1}
    assert result["examined"] == 4
    assert result["written"] == 4
    assert result["remaining"] == 0


def test_a_second_run_writes_nothing(seeded):
    script.run_backfill(dry_run=False)
    again = script.run_backfill(dry_run=False)

    assert again["written"] == 0
    assert again["remaining"] == 0


def test_a_limited_run_says_not_done(seeded, caplog):
    with caplog.at_level(logging.WARNING):
        script.main(["--limit", "1"])

    assert "NOT DONE" in caplog.text
