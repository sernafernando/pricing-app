"""`promo_price.recompute` (promo-ml-precio-inmediato T1): the ML worker drains
`promo_price_recompute_queue` and runs the SAME `recompute_item` as the panel apply and the
`sync_promo_prices` cron, with the promo activation time taken from the mirror (`updated_at`),
so last-write-wins vs a manual price, MIN across promos and frozen-on-end stay identical.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.models.producto import ProductoERP, ProductoPricing, TipoMoneda
from app.models.producto_precio_origen import ProductoPrecioOrigen
from app.models.promo_price_recompute_queue import PromoPriceRecomputeQueue
from app.models.publicacion_ml import PublicacionML
from app.services import promo_price_recompute
from app.workers import registry
from app.workers.context import WorkerContext
from app.workers.handlers.promo_price_recompute import recompute as handler
from tests.costo_si_lista import costo_si_lista  # noqa: F401  (fixture)

pytestmark = [*globals().get("pytestmark", []), pytest.mark.usefixtures("costo_si_lista")]

ACTIVATION = datetime(2026, 1, 2, tzinfo=UTC)


def _ctx(seconds: int = 30) -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=seconds), worker_name="worker-ml")


def _make_item(db, item_id: int, *mlas: str) -> None:
    db.add(
        ProductoERP(
            item_id=item_id,
            codigo=f"COD{item_id}",
            descripcion="Producto de prueba",
            subcategoria_id=1,
            costo=1000.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
    )
    db.add(ProductoPricing(item_id=item_id, precio_lista_ml=1234.0))
    for mla in mlas:
        db.add(PublicacionML(mla=mla, item_id=item_id, pricelist_id=4))
    db.commit()


def _queue(db, item_id: int, attempts: int = 0) -> None:
    db.add(PromoPriceRecomputeQueue(item_id=item_id, attempts=attempts))
    db.commit()


def _row(db, item_id: int):
    db.expire_all()
    return db.query(PromoPriceRecomputeQueue).filter_by(item_id=item_id).one_or_none()


def _price(db, item_id: int) -> float:
    db.expire_all()
    return float(db.query(ProductoPricing).filter_by(item_id=item_id).one().precio_lista_ml)


class _FakeCtx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, *a):
        if exc_type is None:
            self.db.commit()
        else:
            self.db.rollback()
        return False


@pytest.fixture(autouse=True)
def _promo_writes_on():
    original = settings.PROMOS_WRITE_ENABLED
    settings.PROMOS_WRITE_ENABLED = True
    yield
    settings.PROMOS_WRITE_ENABLED = original


@pytest.fixture
def wired(db):
    """Background sessions are the test session; the two cross-DB reads (mirror activation times
    and the item's promos) are stubbed, everything else is the real code."""
    mirror: Dict[str, datetime] = {}
    promos: Dict[str, List[dict]] = {}
    with (
        patch.object(promo_price_recompute, "get_background_db", side_effect=lambda: _FakeCtx(db)),
        patch.object(
            promo_price_recompute,
            "fetch_activation_times",
            side_effect=lambda mlas: {m: mirror[m] for m in mlas if m in mirror},
        ) as activation_spy,
        patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            side_effect=lambda mla, active_only=True: promos.get(mla, []),
        ) as promos_spy,
    ):
        yield MagicMock(mirror=mirror, promos=promos, activation_spy=activation_spy, promos_spy=promos_spy)


class TestRegistration:
    def test_runs_in_its_own_thread_of_the_ml_worker_every_five_seconds(self):
        assert handler in registry.ML_PUBLICATIONS_REGISTRY
        assert handler.name == "promo_price.recompute"
        assert handler.own_thread is True
        assert handler.interval == timedelta(seconds=5)
        assert handler.channels == ()


class TestDrain:
    def test_writes_the_started_promo_price_and_empties_the_queue(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        wired.mirror["MLA8001"] = ACTIVATION
        wired.promos["MLA8001"] = [{"promotion_id": "P-1", "status": "started", "price": 700.0}]
        _queue(db, 8001)

        result = handler.run(_ctx())

        assert result.success is True
        assert result.detail["recomputed"] == 1
        assert _price(db, 8001) == 700.0
        origen = db.query(ProductoPrecioOrigen).filter_by(item_id=8001, column_key="precio_lista_ml").one()
        assert origen.origen == "promo"
        assert _row(db, 8001) is None

    def test_min_across_started_promos_of_the_same_column(self, db, wired):
        _make_item(db, 8001, "MLA8001", "MLA8011")
        wired.mirror.update({"MLA8001": ACTIVATION, "MLA8011": ACTIVATION})
        wired.promos["MLA8001"] = [{"promotion_id": "P-1", "status": "started", "price": 700.0}]
        wired.promos["MLA8011"] = [{"promotion_id": "P-2", "status": "started", "price": 650.0}]
        _queue(db, 8001)

        handler.run(_ctx())

        assert _price(db, 8001) == 650.0

    def test_a_manual_price_set_after_the_mirror_activation_is_not_overwritten(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        db.add(
            ProductoPrecioOrigen(
                item_id=8001, column_key="precio_lista_ml", origen="manual", fecha=ACTIVATION + timedelta(hours=3)
            )
        )
        db.commit()
        wired.mirror["MLA8001"] = ACTIVATION
        wired.promos["MLA8001"] = [{"promotion_id": "P-1", "status": "started", "price": 700.0}]
        _queue(db, 8001)

        handler.run(_ctx())

        assert _price(db, 8001) == 1234.0
        assert _row(db, 8001) is None

    def test_the_activation_time_is_the_latest_mirror_update_of_the_item(self, db, wired):
        _make_item(db, 8001, "MLA8001", "MLA8011")
        wired.mirror.update({"MLA8001": ACTIVATION, "MLA8011": ACTIVATION + timedelta(days=1)})
        _queue(db, 8001)

        with patch.object(promo_price_recompute, "recompute_item") as recompute_spy:
            handler.run(_ctx())

        recompute_spy.assert_called_once_with(db, 8001, now=ACTIVATION + timedelta(days=1))

    def test_an_ended_promo_leaves_the_column_frozen_at_the_promo_price(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        wired.mirror["MLA8001"] = ACTIVATION
        wired.promos["MLA8001"] = [{"promotion_id": "P-1", "status": "started", "price": 700.0}]
        _queue(db, 8001)
        handler.run(_ctx())
        assert _price(db, 8001) == 700.0

        # The promo ended: the mirror keeps only a candidate row, no started promo.
        wired.mirror["MLA8001"] = ACTIVATION + timedelta(days=1)
        wired.promos["MLA8001"] = [{"promotion_id": "P-1", "status": "candidate", "price": 0}]
        _queue(db, 8001)
        result = handler.run(_ctx())

        assert result.detail["recomputed"] == 1
        assert _price(db, 8001) == 700.0
        origen = db.query(ProductoPrecioOrigen).filter_by(item_id=8001, column_key="precio_lista_ml").one()
        assert origen.origen == "promo"
        assert _row(db, 8001) is None

    def test_an_item_without_active_mirror_rows_leaves_the_queue_without_a_recompute(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        _queue(db, 8001)

        with patch.object(promo_price_recompute, "recompute_item") as recompute_spy:
            result = handler.run(_ctx())

        recompute_spy.assert_not_called()
        assert result.detail["no_active_promo"] == 1
        assert _price(db, 8001) == 1234.0
        assert _row(db, 8001) is None

    def test_the_mirror_is_read_once_per_batch_not_once_per_item(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        _make_item(db, 8002, "MLA8002")
        wired.mirror.update({"MLA8001": ACTIVATION, "MLA8002": ACTIVATION})
        _queue(db, 8001)
        _queue(db, 8002)

        result = handler.run(_ctx())

        assert result.detail["recomputed"] == 2
        wired.activation_spy.assert_called_once_with(["MLA8001", "MLA8002"])

    def test_an_empty_queue_reads_nothing_cross_db(self, db, wired):
        result = handler.run(_ctx())

        assert result.success is True
        assert result.detail["recomputed"] == 0
        wired.activation_spy.assert_not_called()


class TestKillSwitch:
    def test_off_reads_nothing_and_keeps_the_queue(self, db, wired):
        settings.PROMOS_WRITE_ENABLED = False
        _make_item(db, 8001, "MLA8001")
        _queue(db, 8001)

        result = handler.run(_ctx())

        assert result.success is True
        wired.activation_spy.assert_not_called()
        wired.promos_spy.assert_not_called()
        assert _row(db, 8001) is not None
        assert _price(db, 8001) == 1234.0


class TestFailures:
    def test_a_failing_item_is_charged_and_does_not_block_the_others(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        _make_item(db, 8002, "MLA8002")
        wired.mirror.update({"MLA8001": ACTIVATION, "MLA8002": ACTIVATION})
        wired.promos["MLA8002"] = [{"promotion_id": "P-2", "status": "started", "price": 500.0}]
        _queue(db, 8001)
        _queue(db, 8002)

        def _promos(mla, active_only=True):
            if mla == "MLA8001":
                raise RuntimeError("mirror down")
            return wired.promos.get(mla, [])

        wired.promos_spy.side_effect = _promos

        result = handler.run(_ctx())

        assert result.detail["failed"] == 1
        assert result.detail["recomputed"] == 1
        row = _row(db, 8001)
        assert row.attempts == 1
        assert "mirror down" in row.last_error
        assert _price(db, 8001) == 1234.0
        assert _price(db, 8002) == 500.0
        assert _row(db, 8002) is None

    def test_an_unreadable_mirror_stops_the_pass_without_charging_anyone(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        _make_item(db, 8002, "MLA8002")
        _queue(db, 8001)
        _queue(db, 8002)
        wired.activation_spy.side_effect = RuntimeError("mlwebhook down")

        result = handler.run(_ctx())

        assert result.success is False
        assert result.detail["mirror_unavailable"] is True
        assert wired.activation_spy.call_count == 1
        for item_id in (8001, 8002):
            row = _row(db, item_id)
            assert row.attempts == 0
            assert row.last_error is None
        wired.promos_spy.assert_not_called()

    def test_a_parked_item_is_not_claimed(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        _queue(db, 8001, attempts=promo_price_recompute.MAX_ATTEMPTS)

        result = handler.run(_ctx())

        assert result.detail["recomputed"] == 0
        wired.activation_spy.assert_not_called()
        assert _row(db, 8001).attempts == promo_price_recompute.MAX_ATTEMPTS

    def test_a_request_arriving_while_the_item_runs_keeps_it_queued(self, db, wired):
        _make_item(db, 8001, "MLA8001")
        wired.mirror["MLA8001"] = ACTIVATION
        _queue(db, 8001)
        db.query(PromoPriceRecomputeQueue).filter_by(item_id=8001).update(
            {"enqueued_at": datetime(2026, 1, 1, tzinfo=UTC)}
        )
        db.commit()

        def _promos(mla, active_only=True):
            promo_price_recompute.enqueue_mlas(db, ["MLA8001"])
            return []

        wired.promos_spy.side_effect = _promos

        handler.run(_ctx())

        row = _row(db, 8001)
        assert row is not None
        assert row.attempts == 0


class TestActivationQuery:
    def test_one_query_for_the_active_rows_of_the_given_mlas(self):
        fake_conn = MagicMock()
        fake_conn.execute.return_value.fetchall.return_value = [("MLA1", ACTIVATION)]
        fake_engine = MagicMock()
        fake_engine.connect.return_value.__enter__.return_value = fake_conn

        with patch.object(promo_price_recompute, "get_mlwebhook_engine", return_value=fake_engine):
            result = promo_price_recompute.fetch_activation_times(["MLA1", "MLA2"])

        assert result == {"MLA1": ACTIVATION}
        assert fake_conn.execute.call_count == 1
        query, params = fake_conn.execute.call_args[0]
        assert "status IN ('candidate', 'started')" in str(query)
        assert params == {"mlas": ["MLA1", "MLA2"]}
