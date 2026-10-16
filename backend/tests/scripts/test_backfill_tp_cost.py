"""Tests for the historical TP-Link (list 8) cost backfill
(metricas-ml-tplink-mode / P2).

Invariants: a backfilled TP cost is the list-8 price IN EFFECT AT THE SALE
DATE (`tb_item_cost_list_history`, `coslis_id = 8`), never a later one and
never the current list; anything unresolvable stays NULL (the "Total TP
incomplete" flag), never 0 and never the normal cost; a TP cost already set
is never rewritten.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.item_cost_list import ItemCostList
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrdersOps
from app.models.tb_item_association import TbItemAssociation
from app.models.tipo_cambio import TipoCambio
from app.scripts import backfill_tp_cost as script
from app.services.ml_orders_ingestion import tp_cost_resolver as resolver

ARS, USD = 1, 2


@pytest.fixture(autouse=True)
def _session_local(db, monkeypatch):
    """Same wrapper as `test_backfill_costo_congelado`: the script opens its
    own `SessionLocal()` per batch; point it at the test session and make
    `.close()` a no-op."""

    class _NoCloseSession:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    wrapped = _NoCloseSession(db)
    monkeypatch.setattr(script, "SessionLocal", lambda: wrapped)


_ids = iter(range(1, 10_000))


def _venta(db, order_id: int, producto_item_id: int = 500, when: date = date(2026, 7, 15), **tp) -> None:
    moment = datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc)
    db.add(MlOrdersOps(order_id=order_id, seller_id=1, date_created=moment, ml_last_updated=moment))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=f"MLA{order_id}",
            costo_origen=Decimal("100"),
            moneda="ARS",
            costo_unitario_ars=Decimal("100"),
            iva_pct=Decimal("21"),
            precio_unitario=Decimal("1000"),
            fuente="erp_publicacion",
            producto_item_id=producto_item_id,
            **tp,
        )
    )
    db.flush()


def _hist(db, item_id: int, price, when: date, curr_id: int = ARS, comp_id: int = 1, coslis_id: int = 8) -> None:
    db.add(
        ItemCostListHistory(
            iclh_id=next(_ids),
            comp_id=comp_id,
            coslis_id=coslis_id,
            item_id=item_id,
            iclh_price=price,
            curr_id=curr_id,
            iclh_cd=datetime.combine(when, datetime.min.time()),
        )
    )
    db.flush()


def _componente(db, combo_id: int, componente_id: int, qty: float) -> None:
    db.add(TbItemAssociation(comp_id=1, itema_id=next(_ids), item_id=combo_id, item_id_1=componente_id, iasso_qty=qty))
    db.flush()


def _rate(db, when: date, venta: float) -> None:
    db.add(TipoCambio(fecha=when, moneda="USD", compra=venta - 10, venta=venta))
    db.flush()


def _row(db, order_id: int) -> MlOrderItemCosto:
    db.expire_all()
    return db.query(MlOrderItemCosto).filter_by(order_id=order_id).one()


def _assert_tp_null(row: MlOrderItemCosto) -> None:
    assert row.costo_tp_unitario_ars is None
    assert row.costo_tp_origen is None
    assert row.costo_tp_fuente is None
    assert row.costo_tp_at is None


class TestPriceAtTheSaleDate:
    def test_the_price_in_effect_at_the_sale_is_used_not_a_later_one(self, db):
        _venta(db, 1, when=date(2026, 7, 15))
        _hist(db, 500, 80, date(2026, 7, 1))
        _hist(db, 500, 300, date(2026, 9, 1))
        # The CURRENT list never stands in for history.
        db.add(ItemCostList(comp_id=1, coslis_id=8, item_id=500, coslis_price=999, curr_id=ARS))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 1)
        assert row.costo_tp_origen == Decimal("80")
        assert row.costo_tp_moneda == "ARS"
        assert row.costo_tp_tipo_cambio is None
        assert row.costo_tp_unitario_ars == Decimal("80")
        assert row.costo_tp_fuente == resolver.FUENTE_TP_HISTORIA
        assert row.costo_tp_at is not None
        assert (result.examined, result.resolved, result.written) == (1, 1, 1)

    def test_usd_converts_at_the_sale_date_rate(self, db):
        _venta(db, 2, when=date(2026, 7, 15))
        _hist(db, 500, 10, date(2026, 7, 1), curr_id=USD)
        _rate(db, date(2026, 7, 10), 900)
        _rate(db, date(2026, 9, 1), 1500)
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 2)
        assert row.costo_tp_moneda == "USD"
        assert row.costo_tp_tipo_cambio == Decimal("900")
        assert row.costo_tp_unitario_ars == Decimal("9000")

    def test_usd_without_a_rate_at_the_sale_date_stays_null(self, db):
        _venta(db, 3, when=date(2026, 7, 15))
        _hist(db, 500, 10, date(2026, 7, 1), curr_id=USD)
        _rate(db, date(2026, 9, 1), 1500)
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 3))
        assert result.skipped[resolver.SKIP_NO_FX] == 1

    def test_an_item_never_priced_on_list8_is_out_of_the_tp_catalog(self, db):
        _venta(db, 4, when=date(2026, 7, 15))
        _hist(db, 500, 70, date(2026, 7, 1), coslis_id=1)
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 4)
        _assert_tp_null(row)
        assert row.costo_unitario_ars == Decimal("100")
        assert result.skipped[resolver.SKIP_FUERA_CATALOGO] == 1

    def test_a_zero_row_is_a_hole_and_the_last_real_price_before_it_applies(self, db):
        """Same picker as the normal-cost backfill (and the list-8 metrics
        job): a non-positive row is never frozen; the last real price at or
        before the sale is."""
        _venta(db, 5, when=date(2026, 7, 15))
        _hist(db, 500, 80, date(2026, 7, 1))
        _hist(db, 500, 0, date(2026, 7, 5))
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        assert _row(db, 5).costo_tp_unitario_ars == Decimal("80")

    def test_only_zero_rows_stay_null_never_zero(self, db):
        _venta(db, 6, when=date(2026, 7, 15))
        _hist(db, 500, 0, date(2026, 7, 1))
        _hist(db, 500, 0, date(2026, 8, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 6))
        assert result.skipped[resolver.SKIP_FUERA_CATALOGO] == 1

    def test_unknown_currency_stays_null(self, db):
        _venta(db, 7)
        _hist(db, 500, 80, date(2026, 7, 1), curr_id=99)
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 7))
        assert result.skipped[resolver.SKIP_BAD_CURRENCY] == 1


class TestMultiCompany:
    def test_companies_that_disagree_at_the_sale_date_stay_null(self, db):
        _venta(db, 10)
        _hist(db, 500, 80, date(2026, 7, 1), comp_id=1)
        _hist(db, 500, 90, date(2026, 7, 1), comp_id=2)
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 10))
        assert result.skipped[resolver.SKIP_AMBIGUOUS] == 1

    def test_companies_that_agree_collapse_to_one_price(self, db):
        _venta(db, 11)
        _hist(db, 500, 80, date(2026, 7, 1), comp_id=1)
        _hist(db, 500, 80, date(2026, 7, 2), comp_id=2)
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        assert _row(db, 11).costo_tp_unitario_ars == Decimal("80")


class TestCombos:
    def test_a_combo_sums_its_components_at_the_sale_date(self, db):
        _venta(db, 20, producto_item_id=500, when=date(2026, 7, 15))
        _componente(db, 500, 901, 2)
        _componente(db, 500, 902, 1)
        _hist(db, 901, 30, date(2026, 7, 1))
        _hist(db, 901, 999, date(2026, 9, 1))
        _hist(db, 902, 2, date(2026, 7, 1), curr_id=USD)
        _rate(db, date(2026, 7, 1), 1000)
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 20)
        # 2 * 30 + 1 * (2 * 1000) = 2060, summed in ARS: no rate kept.
        assert row.costo_tp_unitario_ars == Decimal("2060")
        assert row.costo_tp_origen == Decimal("2060")
        assert row.costo_tp_moneda == "ARS"
        assert row.costo_tp_tipo_cambio is None
        assert row.costo_tp_fuente == resolver.FUENTE_TP_HISTORIA_COMBO

    def test_one_component_never_priced_sinks_the_combo(self, db):
        _venta(db, 21, producto_item_id=500)
        _componente(db, 500, 901, 1)
        _componente(db, 500, 902, 1)
        _hist(db, 901, 30, date(2026, 7, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 21))
        assert result.skipped[resolver.SKIP_FUERA_CATALOGO] == 1

    def test_one_ambiguous_component_sinks_the_combo(self, db):
        _venta(db, 25, producto_item_id=500)
        _componente(db, 500, 901, 1)
        _hist(db, 901, 30, date(2026, 7, 1), comp_id=1)
        _hist(db, 901, 31, date(2026, 7, 1), comp_id=2)
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 25))
        assert result.skipped[resolver.SKIP_COMBO_COMPONENT] == 1

    def test_a_combo_with_its_own_dated_price_uses_it(self, db):
        _venta(db, 22, producto_item_id=500)
        _componente(db, 500, 901, 1)
        _hist(db, 500, 55, date(2026, 7, 1))
        _hist(db, 901, 30, date(2026, 7, 1))
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 22)
        assert row.costo_tp_unitario_ars == Decimal("55")
        assert row.costo_tp_fuente == resolver.FUENTE_TP_HISTORIA

    def test_a_combo_whose_own_price_is_ambiguous_never_falls_back_to_components(self, db):
        _venta(db, 23, producto_item_id=500)
        _componente(db, 500, 901, 1)
        _hist(db, 500, 55, date(2026, 7, 1), comp_id=1)
        _hist(db, 500, 60, date(2026, 7, 1), comp_id=2)
        _hist(db, 901, 30, date(2026, 7, 1))
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 23))

    def test_a_combo_whose_own_price_has_an_unknown_currency_never_falls_back(self, db):
        _venta(db, 24, producto_item_id=500)
        _componente(db, 500, 901, 1)
        _hist(db, 500, 55, date(2026, 7, 1), curr_id=99)
        _hist(db, 901, 30, date(2026, 7, 1))
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 24))


class TestNeverRewritesAndRuns:
    def test_a_tp_cost_already_set_is_never_rewritten(self, db):
        _venta(
            db,
            30,
            costo_tp_origen=Decimal("11"),
            costo_tp_moneda="ARS",
            costo_tp_unitario_ars=Decimal("11"),
            costo_tp_fuente="lista8_ingesta",
            costo_tp_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        _hist(db, 500, 80, date(2026, 7, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 30)
        assert row.costo_tp_unitario_ars == Decimal("11")
        assert row.costo_tp_fuente == "lista8_ingesta"
        assert result.examined == 0

    def test_dry_run_resolves_but_writes_nothing(self, db):
        _venta(db, 31)
        _hist(db, 500, 80, date(2026, 7, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=True)

        _assert_tp_null(_row(db, 31))
        assert (result.resolved, result.written) == (1, 0)

    def test_small_batches_walk_past_unresolvable_rows_to_the_end(self, db):
        _venta(db, 40, producto_item_id=600)  # no history: stays NULL
        _venta(db, 41, producto_item_id=500)
        _venta(db, 42, producto_item_id=600)
        _venta(db, 43, producto_item_id=500)
        _hist(db, 500, 80, date(2026, 7, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False, batch_size=1)

        assert result.examined == 4
        assert result.written == 2
        assert result.batches == 4
        assert _row(db, 43).costo_tp_unitario_ars == Decimal("80")
        _assert_tp_null(_row(db, 42))

    def test_limit_bounds_the_run_and_after_id_resumes_it(self, db):
        for order_id in (50, 51, 52):
            _venta(db, order_id)
        _hist(db, 500, 80, date(2026, 7, 1))
        db.commit()

        first = script.run_backfill(limit=2, dry_run=False, batch_size=1)
        assert first.examined == 2
        _assert_tp_null(_row(db, 52))

        second = script.run_backfill(limit=None, dry_run=False, after_id=first.last_id)
        assert second.examined == 1
        assert _row(db, 52).costo_tp_unitario_ars == Decimal("80")

    def test_the_main_entry_point_prints_a_summary(self, db, caplog):
        _venta(db, 60)
        db.commit()

        with caplog.at_level("INFO"):
            script.main(["--dry-run", "--limit", "5"])

        assert "examined=1" in caplog.text
        assert "last_id=" in caplog.text
        assert "resolved_by_fuente=" in caplog.text
        assert "written_by_fuente=" in caplog.text


class TestFirstPriceFallback:
    """List 8 started on 2026-06-26: a sale before an item's first list-8
    row is costed with that item's FIRST real list-8 price, flagged as
    approximate by its own `fuente`."""

    def test_a_sale_before_the_first_list8_row_uses_the_first_real_price(self, db):
        _venta(db, 70, when=date(2026, 5, 10))
        _hist(db, 500, 0, date(2026, 6, 26))
        _hist(db, 500, 80, date(2026, 6, 27))
        _hist(db, 500, 95, date(2026, 8, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 70)
        assert row.costo_tp_origen == Decimal("80")
        assert row.costo_tp_unitario_ars == Decimal("80")
        assert row.costo_tp_tipo_cambio is None
        assert row.costo_tp_fuente == resolver.FUENTE_TP_PRIMER_PRECIO
        assert result.resolved_by_fuente[resolver.FUENTE_TP_PRIMER_PRECIO] == 1
        assert result.written_by_fuente[resolver.FUENTE_TP_PRIMER_PRECIO] == 1

    def test_a_usd_first_price_converts_at_the_sale_date_rate(self, db):
        _venta(db, 71, when=date(2026, 5, 10))
        _hist(db, 500, 10, date(2026, 6, 27), curr_id=USD)
        _rate(db, date(2026, 5, 1), 1100)
        _rate(db, date(2026, 6, 27), 1300)
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 71)
        assert row.costo_tp_moneda == "USD"
        assert row.costo_tp_tipo_cambio == Decimal("1100")
        assert row.costo_tp_unitario_ars == Decimal("11000")
        assert row.costo_tp_fuente == resolver.FUENTE_TP_PRIMER_PRECIO

    def test_first_prices_that_disagree_across_companies_stay_null(self, db):
        _venta(db, 72, when=date(2026, 5, 10))
        _hist(db, 500, 80, date(2026, 6, 27), comp_id=1)
        _hist(db, 500, 90, date(2026, 6, 27), comp_id=2)
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 72))
        assert result.skipped[resolver.SKIP_AMBIGUOUS] == 1

    def test_a_first_price_in_an_unknown_currency_stays_null(self, db):
        _venta(db, 73, when=date(2026, 5, 10))
        _hist(db, 500, 80, date(2026, 6, 27), curr_id=99)
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 73))
        assert result.skipped[resolver.SKIP_BAD_CURRENCY] == 1

    def test_a_combo_with_a_component_on_its_first_price_is_flagged_approximate(self, db):
        _venta(db, 74, producto_item_id=500, when=date(2026, 7, 15))
        _componente(db, 500, 901, 2)
        _componente(db, 500, 902, 1)
        _hist(db, 901, 30, date(2026, 7, 1))
        _hist(db, 902, 5, date(2026, 9, 1))
        _hist(db, 902, 7, date(2026, 10, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 74)
        # 2 * 30 (dated) + 1 * 5 (first price)
        assert row.costo_tp_unitario_ars == Decimal("65")
        assert row.costo_tp_tipo_cambio is None
        assert row.costo_tp_fuente == resolver.FUENTE_TP_PRIMER_PRECIO_COMBO
        assert result.resolved_by_fuente[resolver.FUENTE_TP_PRIMER_PRECIO_COMBO] == 1

    def test_a_combo_with_its_own_later_price_uses_its_own_first_price(self, db):
        _venta(db, 75, producto_item_id=500, when=date(2026, 5, 10))
        _componente(db, 500, 901, 1)
        _hist(db, 500, 55, date(2026, 6, 27))
        _hist(db, 901, 30, date(2026, 6, 27))
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 75)
        assert row.costo_tp_unitario_ars == Decimal("55")
        assert row.costo_tp_fuente == resolver.FUENTE_TP_PRIMER_PRECIO

    def test_a_dated_price_still_wins_over_the_first_price(self, db):
        _venta(db, 76, when=date(2026, 7, 15))
        _hist(db, 500, 80, date(2026, 6, 27))
        _hist(db, 500, 90, date(2026, 7, 10))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 76)
        assert row.costo_tp_unitario_ars == Decimal("90")
        assert row.costo_tp_fuente == resolver.FUENTE_TP_HISTORIA
        assert result.resolved_by_fuente[resolver.FUENTE_TP_HISTORIA] == 1


class TestComboPrecedence:
    """Exact beats approximate: own dated price, then the exact component
    sum, then own first price, then the component sum with fallback."""

    def test_own_price_only_later_but_components_dated_gives_the_exact_component_sum(self, db):
        _venta(db, 80, producto_item_id=500, when=date(2026, 7, 15))
        _componente(db, 500, 901, 2)
        _componente(db, 500, 902, 1)
        _hist(db, 500, 55, date(2026, 9, 1))
        _hist(db, 901, 30, date(2026, 7, 1))
        _hist(db, 902, 5, date(2026, 7, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 80)
        assert row.costo_tp_unitario_ars == Decimal("65")
        assert row.costo_tp_fuente == resolver.FUENTE_TP_HISTORIA_COMBO
        assert result.resolved_by_fuente[resolver.FUENTE_TP_HISTORIA_COMBO] == 1

    def test_a_component_rejected_at_the_sale_date_sinks_the_combo_even_with_an_own_later_price(self, db):
        _venta(db, 81, producto_item_id=500, when=date(2026, 7, 15))
        _componente(db, 500, 901, 1)
        _componente(db, 500, 902, 1)
        _hist(db, 500, 55, date(2026, 9, 1))
        _hist(db, 901, 30, date(2026, 7, 1), comp_id=1)
        _hist(db, 901, 31, date(2026, 7, 1), comp_id=2)
        _hist(db, 902, 5, date(2026, 9, 1))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 81))
        assert result.skipped[resolver.SKIP_COMBO_COMPONENT] == 1

    def test_own_first_price_beats_a_component_sum_that_needs_the_fallback(self, db):
        _venta(db, 82, producto_item_id=500, when=date(2026, 7, 15))
        _componente(db, 500, 901, 1)
        _componente(db, 500, 902, 1)
        _hist(db, 500, 55, date(2026, 9, 1))
        _hist(db, 901, 30, date(2026, 7, 1))
        _hist(db, 902, 5, date(2026, 9, 1))
        db.commit()

        script.run_backfill(limit=None, dry_run=False)

        row = _row(db, 82)
        assert row.costo_tp_unitario_ars == Decimal("55")
        assert row.costo_tp_fuente == resolver.FUENTE_TP_PRIMER_PRECIO


class TestUnresolvableRowsAreCounted:
    def test_a_cost_row_without_an_order_is_counted_and_stays_null(self, db):
        _venta(db, 90)
        _hist(db, 500, 80, date(2026, 7, 1))
        db.query(MlOrdersOps).filter_by(order_id=90).delete()
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 90))
        assert result.skipped[resolver.SKIP_NO_ORDER_DATE] == 1

    def test_an_order_without_a_date_is_counted_and_stays_null(self, db):
        _venta(db, 91)
        _hist(db, 500, 80, date(2026, 7, 1))
        db.query(MlOrdersOps).filter_by(order_id=91).update({"date_created": None})
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 91))
        assert result.skipped[resolver.SKIP_NO_ORDER_DATE] == 1

    def test_real_prices_only_on_undated_rows_are_counted_and_stay_null(self, db):
        _venta(db, 92)
        db.add(ItemCostListHistory(iclh_id=next(_ids), comp_id=1, coslis_id=8, item_id=500, iclh_price=80, curr_id=ARS))
        db.commit()

        result = script.run_backfill(limit=None, dry_run=False)

        _assert_tp_null(_row(db, 92))
        assert result.skipped[resolver.SKIP_NO_HISTORY] == 1


class TestOneBadRowNeverAbortsTheBatch:
    """`producto_item_id` is NOT NULL in the schema, so these rows are built
    by hand: the guard is defensive, and a batch must survive them."""

    def _filas(self, db):
        from types import SimpleNamespace

        _venta(db, 100)
        _venta(db, 101)
        _hist(db, 500, 80, date(2026, 7, 1))
        db.commit()
        ids = {r.order_id: r.id for r in db.query(MlOrderItemCosto)}
        fecha = datetime(2026, 7, 15, tzinfo=timezone.utc)
        return [
            SimpleNamespace(id=ids[100], producto_item_id=500, date_created=fecha),
            SimpleNamespace(id=999_999, producto_item_id=None, date_created=fecha),
            SimpleNamespace(id=ids[101], producto_item_id=500, date_created=fecha),
        ]

    def test_a_row_without_an_erp_item_is_counted_and_the_others_are_written(self, db):
        filas = self._filas(db)

        for _ in range(2):  # a re-run hits the same row and still does not crash
            result = resolver.BackfillTpResult()
            resolver.procesar_lote(db, filas, False, result)
            db.commit()

        assert result.skipped[resolver.SKIP_SIN_ITEM_ERP] == 1
        assert _row(db, 100).costo_tp_unitario_ars == Decimal("80")
        assert _row(db, 101).costo_tp_unitario_ars == Decimal("80")

    def test_an_unexpected_error_on_one_row_is_counted_and_the_others_are_written(self, db, monkeypatch):
        filas = [f for f in self._filas(db) if f.producto_item_id is not None]
        original = resolver._resolver

        def _falla_en_la_primera(erp_id, as_of, *args):
            if as_of and filas and _falla_en_la_primera.llamadas == 0:
                _falla_en_la_primera.llamadas += 1
                raise ValueError("boom")
            return original(erp_id, as_of, *args)

        _falla_en_la_primera.llamadas = 0
        monkeypatch.setattr(resolver, "_resolver", _falla_en_la_primera)

        result = resolver.BackfillTpResult()
        resolver.procesar_lote(db, filas, False, result)
        db.commit()

        assert result.skipped[resolver.SKIP_ERROR] == 1
        assert result.written == 1
