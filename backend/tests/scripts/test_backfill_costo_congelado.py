"""Tests for the frozen-cost-history backfill
(backfill-costo-congelado-historico).

The single invariant this whole script exists to protect: a backfilled
cost is ALWAYS dated at or before the sale, NEVER "whatever is latest" and
NEVER the current ERP cost. Every mutation-verified test here is written
to fail if that discipline is silently loosened back to
`obtener_costo_item`'s fallback #2/#3 behaviour.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.item_cost_list_history import ItemCostListHistory
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.producto import ProductoERP, TipoMoneda
from app.models.publicacion_ml import PublicacionML
from app.models.tipo_cambio import TipoCambio
from app.scripts import backfill_costo_congelado as script
from app.services.ml_orders_ingestion.costeo_service import (
    FUENTE_BACKFILL_PUBLICACION,
    FUENTE_BACKFILL_SKU,
)


@pytest.fixture(autouse=True)
def _session_local(db, monkeypatch):
    """The script opens its OWN `SessionLocal()` (CLI entry point, same as
    every other script in `app/scripts/`) -- point it at the test's
    in-memory sqlite session instead, and make its `.close()` a no-op so
    the fixture-owned session survives the call."""

    class _NoCloseSession:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    wrapped = _NoCloseSession(db)
    monkeypatch.setattr(script, "SessionLocal", lambda: wrapped)


def _order(order_id: int, order_date: datetime, seller_id: int = 1) -> MlOrdersOps:
    return MlOrdersOps(order_id=order_id, seller_id=seller_id, date_created=order_date, ml_last_updated=order_date)


def _item(
    order_id: int,
    item_id: str = "MLA1",
    seller_sku: str = "SKU-1",
    unit_price: float = 1000.0,
    variation_id=None,
):
    return MlOrderItemOps(
        order_id=order_id,
        item_id=item_id,
        variation_id=variation_id,
        seller_sku=seller_sku,
        title="Producto de prueba",
        quantity=1,
        unit_price=unit_price,
    )


def _producto(db, item_id: int = 500, iva: float = 21.0) -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo="SKU-1",
        descripcion="Producto de prueba",
        costo=None,  # never read by the backfill -- history is the source
        moneda_costo=TipoMoneda.ARS,
        iva=iva,
    )
    db.add(producto)
    db.flush()
    return producto


def _publicacion(db, mla: str = "MLA1", item_id: int = 500) -> PublicacionML:
    publicacion = PublicacionML(mla=mla, item_id=item_id, activo=True)
    db.add(publicacion)
    db.flush()
    return publicacion


def _history(db, item_id: int, price: float, when: date, iclh_id: int, curr_id: int = 1) -> ItemCostListHistory:
    row = ItemCostListHistory(
        iclh_id=iclh_id,
        coslis_id=1,
        item_id=item_id,
        iclh_price=price,
        curr_id=curr_id,
        iclh_cd=datetime.combine(when, datetime.min.time()),
    )
    db.add(row)
    db.flush()
    return row


class TestOldSaleGetsOldCost:
    def test_sale_before_a_cost_change_gets_the_old_cost(self, db):
        """MUTATION-VERIFIED: swapping `_pick_history_row`'s `max` selection
        over ELIGIBLE (dated <= sale) rows for a plain `max` over ALL rows
        (i.e. reintroducing obtener_costo_item's fallback #2) makes this
        test fail -- it would pick the September row for a July sale."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=100.0, when=date(2026, 7, 1), iclh_id=1)
        _history(db, item_id=500, price=300.0, when=date(2026, 9, 1), iclh_id=2)
        db.add(_order(1001, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1001))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        row = db.query(MlOrderItemCosto).filter_by(order_id=1001, item_id="MLA1").one()
        assert row.costo_origen == Decimal("100.0")
        assert row.costo_fecha == date(2026, 7, 1)
        assert result.resolved == 1
        assert result.written == 1


class TestFutureOnlyHistoryIsSkipped:
    def test_item_with_only_later_history_rows_is_skipped(self, db):
        """MUTATION-VERIFIED: dropping the `iclh_cd <= as_of` filter in
        `_pick_history_row` (falling back to current cost / latest row)
        makes this test fail -- a row would get written instead of none."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=300.0, when=date(2026, 9, 1), iclh_id=1)
        db.add(_order(1002, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1002))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        assert db.query(MlOrderItemCosto).filter_by(order_id=1002).count() == 0
        assert result.skipped[script.SKIP_NO_HISTORY] == 1


class TestAlreadyFrozenRowUntouched:
    def test_existing_frozen_row_is_never_touched(self, db):
        """MUTATION-VERIFIED: removing the hole-only candidate filter (or
        the `ON CONFLICT DO NOTHING` backstop) makes this test fail -- the
        existing row's value would flip to what history says."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=999.0, when=date(2026, 7, 1), iclh_id=1)
        db.add(_order(1003, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1003))
        existing = MlOrderItemCosto(
            order_id=1003,
            item_id="MLA1",
            variation_id=None,
            costo_origen=Decimal("42.0"),
            moneda="ARS",
            costo_unitario_ars=Decimal("42.0"),
            iva_pct=Decimal("21.0"),
            precio_unitario=Decimal("1000.0"),
            fuente="erp_publicacion",
            producto_item_id=500,
        )
        db.add(existing)
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        row = db.query(MlOrderItemCosto).filter_by(order_id=1003).one()
        assert row.costo_origen == Decimal("42.0")
        assert result.examined == 0
        assert result.resolved == 0
        assert result.written == 0


class TestUsdConvertsAtSaleDateRate:
    def test_usd_cost_converts_at_the_sale_date_rate_not_today(self, db):
        """A single-order batch: `_usd_rates_by_date` fetches rates with
        `fecha <= max(batch dates)`, so with ONE order the later rate never
        even enters the candidate set. That means this test pins the
        end-to-end result but NOT `_pick_fx_rate`'s own date guard --
        removing that guard leaves this test GREEN (measured). The test
        below is the one that pins it."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=10.0, when=date(2026, 7, 1), iclh_id=1, curr_id=2)
        db.add(TipoCambio(fecha=date(2026, 7, 1), moneda="USD", compra=900.0, venta=950.0))
        # A LATER, higher rate that must NOT be used for this sale.
        db.add(TipoCambio(fecha=date(2026, 9, 1), moneda="USD", compra=1100.0, venta=1200.0))
        db.add(_order(1004, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1004))
        db.commit()

        script.run_backfill(limit=100, dry_run=False)

        row = db.query(MlOrderItemCosto).filter_by(order_id=1004).one()
        assert row.moneda == "USD"
        assert row.tipo_cambio == Decimal("950.0")
        assert row.costo_unitario_ars == Decimal("9500.0")
        assert row.tipo_cambio_fecha == date(2026, 7, 1)

    def test_an_older_sale_sharing_a_batch_with_a_newer_one_keeps_its_own_rate(self, db):
        """THE test for `_pick_fx_rate`. A batch is fetched with
        `fecha <= max(dates)`, so as soon as ONE newer sale rides along,
        the newer rate IS in the candidate set and only the per-item date
        guard keeps it off the older sale. Production batches are always
        mixed-date; a single-order test cannot see this.

        MUTATION-VERIFIED: dropping `rate.fecha <= as_of` from
        `_pick_fx_rate` turns this red (and leaves the single-order test
        above green).
        """
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=10.0, when=date(2026, 7, 1), iclh_id=1, curr_id=2)
        db.add(TipoCambio(fecha=date(2026, 7, 1), moneda="USD", compra=900.0, venta=950.0))
        db.add(TipoCambio(fecha=date(2026, 9, 1), moneda="USD", compra=1100.0, venta=1200.0))
        # The OLD sale, and a NEWER one that drags the later rate into the
        # same batch fetch.
        db.add(_order(1010, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1010))
        db.add(_order(1011, datetime(2026, 9, 10, tzinfo=timezone.utc)))
        db.add(_item(1011))
        db.commit()

        script.run_backfill(limit=100, dry_run=False)

        vieja = db.query(MlOrderItemCosto).filter_by(order_id=1010).one()
        assert vieja.tipo_cambio == Decimal("950.0")
        assert vieja.tipo_cambio_fecha == date(2026, 7, 1)

        nueva = db.query(MlOrderItemCosto).filter_by(order_id=1011).one()
        assert nueva.tipo_cambio == Decimal("1200.0")
        assert nueva.tipo_cambio_fecha == date(2026, 9, 1)

    def test_usd_cost_with_no_usable_rate_is_skipped(self, db):
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=10.0, when=date(2026, 7, 1), iclh_id=1, curr_id=2)
        db.add(_order(1005, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1005))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        assert db.query(MlOrderItemCosto).filter_by(order_id=1005).count() == 0
        assert result.skipped[script.SKIP_NO_FX] == 1


class TestCostoFechaMatchesHistoryRow:
    def test_costo_fecha_equals_the_history_row_actually_used(self, db):
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=50.0, when=date(2026, 6, 1), iclh_id=1)
        _history(db, item_id=500, price=75.0, when=date(2026, 7, 10), iclh_id=2)
        db.add(_order(1006, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1006))
        db.commit()

        script.run_backfill(limit=100, dry_run=False)

        row = db.query(MlOrderItemCosto).filter_by(order_id=1006).one()
        assert row.costo_origen == Decimal("75.0")
        assert row.costo_fecha == date(2026, 7, 10)


class TestFuenteIsDistinguishable:
    def test_backfilled_row_uses_backfill_fuente_not_live_fuente(self, db):
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=50.0, when=date(2026, 6, 1), iclh_id=1)
        db.add(_order(1007, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1007))
        db.commit()

        script.run_backfill(limit=100, dry_run=False)

        row = db.query(MlOrderItemCosto).filter_by(order_id=1007).one()
        assert row.fuente == FUENTE_BACKFILL_PUBLICACION
        assert row.fuente != "erp_publicacion"

    def test_sku_fallback_uses_its_own_backfill_fuente(self, db):
        _producto(db, item_id=500)
        # No PublicacionML for this MLA -- only the seller_sku matches.
        _history(db, item_id=500, price=50.0, when=date(2026, 6, 1), iclh_id=1)
        db.add(_order(1008, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1008, item_id="MLA-SIN-PUBLICACION", seller_sku="SKU-1"))
        db.commit()

        script.run_backfill(limit=100, dry_run=False)

        row = db.query(MlOrderItemCosto).filter_by(order_id=1008).one()
        assert row.fuente == FUENTE_BACKFILL_SKU


class TestDryRunWritesNothing:
    def test_dry_run_reports_but_writes_nothing(self, db):
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=50.0, when=date(2026, 6, 1), iclh_id=1)
        db.add(_order(1009, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1009))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=True)

        # THE distinction `filled` used to blur: the item resolved to a
        # complete snapshot, and NOTHING was written. One counter could not
        # say both, so it said the reassuring one.
        assert result.resolved == 1
        assert result.written == 0
        assert db.query(MlOrderItemCosto).filter_by(order_id=1009).count() == 0


class TestZeroPricedHistoryRowIsNotACost:
    def test_a_history_row_with_zero_price_is_skipped_not_frozen(self, db):
        """A `iclh_price` of 0 is an ERP hole that happens to have a row.
        Freezing it would render the sale as 100% margin and nothing
        downstream could tell that from a genuinely cheap product -- the
        same lie this whole script exists to avoid, just arriving through
        a different door.

        MUTATION-VERIFIED: removing the `costo_origen <= 0` guard in
        `_resolve_backfill_cost` turns this red.
        """
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=0.0, when=date(2026, 7, 1), iclh_id=1)
        db.add(_order(1012, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1012))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        assert db.query(MlOrderItemCosto).filter_by(order_id=1012).count() == 0
        # The zero is ALL this product has, so there is no earlier real
        # cost to fall back to -- and the reason says which problem it is.
        assert result.skipped[script.SKIP_NO_PRICE_IN_HISTORY] == 1

    def test_a_history_row_with_a_null_price_reports_its_own_reason(self, db):
        """`no_dated_history_row` and `history_row_has_no_price` are
        DIFFERENT problems -- the first means the ERP has no cost for that
        date, the second that the row exists but came empty. They get
        fixed in different places, and the skip breakdown is the only
        observable output this script has: collapsing them into one
        counter makes it mute the first time it is not zero.
        """
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=None, when=date(2026, 7, 1), iclh_id=1)
        db.add(_order(1013, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(1013))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        assert db.query(MlOrderItemCosto).filter_by(order_id=1013).count() == 0
        assert result.skipped[script.SKIP_NO_PRICE_IN_HISTORY] == 1
        assert result.skipped[script.SKIP_NO_HISTORY] == 0


class TestWrittenCountsWhatTheDatabaseAccepted:
    def test_written_counts_only_the_row_the_insert_accepted(self, db, monkeypatch):
        """The race the `written` counter exists for, made reproducible --
        and made to discriminate.

        Normally the candidate query already excludes items that have a
        frozen row, so `ON CONFLICT DO NOTHING` never drops anything. It
        drops a row only when another writer freezes the same item between
        our candidate read and our INSERT. That window is forced here by
        pointing the candidate query at an item that IS already frozen.

        THE BATCH IS DELIBERATELY MIXED: one row conflicts, one row is new,
        so the only correct answer is `written == 1`. An all-or-nothing
        batch proves nothing -- `written` could be a constant 0, or count
        the rows DROPPED, and still pass. This is what the first version of
        this test got wrong.

        A NON-NULL `variation_id` is load-bearing: SQLite does not honour
        `postgresql_nulls_not_distinct`, so with NULL variations its unique
        index treats the two rows as distinct and the INSERT never
        conflicts at all -- the same dialect gap `costeo_service.congelar`
        documents. The conflict path is only reachable with a real
        variation id.
        """
        _producto(db, item_id=500)
        _publicacion(db)
        _publicacion(db, mla="MLA2", item_id=500)
        _history(db, item_id=500, price=100.0, when=date(2026, 6, 1), iclh_id=1)

        db.add(_order(2001, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(2001, item_id="MLA1", variation_id=9001))
        db.commit()

        # First run freezes ONLY 2001 -- it is the row "the concurrent
        # writer got in first".
        primera = script.run_backfill(limit=100, dry_run=False)
        assert primera.written == 1
        assert db.query(MlOrderItemCosto).count() == 1

        # 2002 arrives afterwards and has NO frozen row.
        db.add(_order(2002, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(2002, item_id="MLA2", variation_id=9002))
        db.commit()

        # Candidate query without the hole filter: BOTH come back, so the
        # batch carries one conflicting row and one new row.
        real = script._candidate_query

        def sin_filtro_de_hueco(session):
            return (
                session.query(script.MlOrderItemOps, script.MlOrdersOps.date_created)
                .join(script.MlOrdersOps, script.MlOrdersOps.order_id == script.MlOrderItemOps.order_id)
                .order_by(script.MlOrderItemOps.order_id, script.MlOrderItemOps.id)
            )

        monkeypatch.setattr(script, "_candidate_query", sin_filtro_de_hueco)
        result = script.run_backfill(limit=100, dry_run=False)
        monkeypatch.setattr(script, "_candidate_query", real)

        # Two resolved, ONE accepted: 2001 conflicted, 2002 went in.
        assert result.resolved == 2
        assert result.written == 1
        assert db.query(MlOrderItemCosto).count() == 2
        assert db.query(MlOrderItemCosto).filter_by(order_id=2002).count() == 1


class TestAZeroDoesNotPoisonTheCostsBeforeIt:
    """Measured in production: 4.360 zero-priced rows spread over 4.353
    products blocked 3.462 sales, because taking "the most recent dated
    row" and giving up on a zero discards every sale between that junk row
    and the next real cost. A zero is a MISSING cost, not a cost change."""

    def test_a_sale_after_a_zero_row_uses_the_last_real_cost_before_it(self, db):
        """MUTATION-VERIFIED: dropping the price filter from
        `_pick_history_row` turns this red -- it picks the zero row and the
        sale is skipped instead of costed at 100."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=100.0, when=date(2026, 5, 1), iclh_id=1)
        _history(db, item_id=500, price=0.0, when=date(2026, 6, 1), iclh_id=2)
        db.add(_order(3001, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(3001))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        row = db.query(MlOrderItemCosto).filter_by(order_id=3001).one()
        assert row.costo_origen == Decimal("100.0")
        # The date of the REAL row used, not of the zero that came after.
        assert row.costo_fecha == date(2026, 5, 1)
        assert result.written == 1

    def test_it_still_never_reaches_past_the_sale_for_a_real_cost(self, db):
        """The loosening stops exactly here: skipping a zero must not become
        an excuse to take a priced row dated AFTER the sale. This product's
        only real cost arrives in September; a July sale stays uncosted."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=0.0, when=date(2026, 6, 1), iclh_id=1)
        _history(db, item_id=500, price=100.0, when=date(2026, 9, 1), iclh_id=2)
        db.add(_order(3002, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(3002))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        assert db.query(MlOrderItemCosto).filter_by(order_id=3002).count() == 0
        assert result.skipped[script.SKIP_NO_PRICE_IN_HISTORY] == 1

    def test_no_dated_row_at_all_is_a_different_reason_than_an_empty_one(self, db):
        """`no_dated_history_row` must not absorb the zero case now that the
        picker rejects zeros: one is "the ERP has nothing for that date",
        the other "it has rows and they came empty"."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=100.0, when=date(2026, 9, 1), iclh_id=1)
        db.add(_order(3003, datetime(2026, 7, 15, tzinfo=timezone.utc)))
        db.add(_item(3003))
        db.commit()

        result = script.run_backfill(limit=100, dry_run=False)

        assert result.skipped[script.SKIP_NO_HISTORY] == 1
        assert result.skipped[script.SKIP_NO_PRICE_IN_HISTORY] == 0


class TestLimitIsOptional:
    def test_without_a_limit_every_candidate_is_examined(self, db):
        """A backfill with no arguments must do the whole job. The old
        default of 5000 re-examined the same unresolvable items every run
        and starved the tail -- in production `examined` stayed pinned at
        the cap while `resolved` fell from 4.557 to 767."""
        _producto(db, item_id=500)
        _publicacion(db)
        _history(db, item_id=500, price=100.0, when=date(2026, 5, 1), iclh_id=1)
        for order_id in (3101, 3102, 3103):
            db.add(_order(order_id, datetime(2026, 7, 15, tzinfo=timezone.utc)))
            db.add(_item(order_id))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        assert result.examined == 3
        assert result.written == 3
