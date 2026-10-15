"""Tests for the TP-Link (cost list 8) cost frozen next to the normal cost.

metricas-ml-tplink-mode / P1. `congelar()` writes, in the SAME insert as the
normal cost snapshot, the CURRENT list-8 price (`tb_item_cost_list`,
`coslis_id=8`, `coslis_price > 0`) converted to ARS at the same latest USD
rate the normal cost uses. A missing or non-positive list-8 price leaves
every `costo_tp_*` column NULL -- that NULL is the "Total TP incomplete"
flag. Never 0, never the normal cost.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.models.item_cost_list import ItemCostList
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.producto import ProductoERP, TipoMoneda
from app.models.publicacion_ml import PublicacionML
from app.models.tb_item_association import TbItemAssociation
from app.models.tipo_cambio import TipoCambio
from app.services.ml_orders_ingestion.costeo_service import (
    FUENTE_PUBLICACION,
    FUENTE_TP_COMBO,
    FUENTE_TP_INGESTA,
    congelar,
)
from app.services.ml_orders_ingestion.mapper import OrderItemOpsDTO

CURR_ARS = 1
CURR_USD = 2


def _item(item_id: str = "MLA1", seller_sku: str = "SKU-1", unit_price: float = 1000.0) -> OrderItemOpsDTO:
    return OrderItemOpsDTO(
        item_id=item_id,
        variation_id=None,
        seller_sku=seller_sku,
        title="Producto de prueba",
        quantity=1,
        unit_price=unit_price,
        full_unit_price=unit_price,
        sale_fee=0.0,
        listing_type_id="gold_special",
    )


def _producto(db, item_id: int = 500, costo=100.0, moneda=TipoMoneda.ARS, codigo: str = "SKU-1") -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo=codigo,
        descripcion="Producto de prueba",
        costo=costo,
        moneda_costo=moneda,
        iva=21.0,
    )
    db.add(producto)
    db.flush()
    return producto


def _publicacion(db, mla: str = "MLA1", item_id: int = 500) -> None:
    db.add(PublicacionML(mla=mla, item_id=item_id, activo=True))
    db.flush()


def _lista8(db, item_id: int, price, curr_id: int = CURR_ARS, coslis_id: int = 8, comp_id: int = 1) -> None:
    db.add(ItemCostList(comp_id=comp_id, coslis_id=coslis_id, item_id=item_id, coslis_price=price, curr_id=curr_id))
    db.flush()


def _componente(db, combo_id: int, componente_id: int, qty: float, itema_id: int) -> None:
    db.add(TbItemAssociation(comp_id=1, itema_id=itema_id, item_id=combo_id, item_id_1=componente_id, iasso_qty=qty))
    db.flush()


def _rate(db, venta: float = 950.0) -> None:
    db.add(TipoCambio(fecha=date(2026, 9, 1), moneda="USD", compra=venta - 50, venta=venta))
    db.flush()


def _row(db, order_id: int) -> MlOrderItemCosto:
    return db.query(MlOrderItemCosto).filter_by(order_id=order_id, item_id="MLA1").one()


def _assert_tp_null(row: MlOrderItemCosto) -> None:
    assert row.costo_tp_origen is None
    assert row.costo_tp_moneda is None
    assert row.costo_tp_tipo_cambio is None
    assert row.costo_tp_unitario_ars is None
    assert row.costo_tp_fuente is None
    assert row.costo_tp_at is None


class TestTpCostFromList8:
    def test_ars_list8_price_is_frozen_as_is(self, db):
        _producto(db, costo=100.0)
        _publicacion(db)
        _lista8(db, item_id=500, price=80, curr_id=CURR_ARS)
        db.commit()

        congelar(db, order_id=1, items=[_item()])
        db.commit()

        row = _row(db, 1)
        assert row.costo_tp_origen == Decimal("80")
        assert row.costo_tp_moneda == "ARS"
        assert row.costo_tp_tipo_cambio is None
        assert row.costo_tp_unitario_ars == Decimal("80")
        assert row.costo_tp_fuente == FUENTE_TP_INGESTA
        assert row.costo_tp_at is not None

    def test_usd_list8_price_converts_at_the_latest_usd_rate(self, db):
        _producto(db, costo=100.0)
        _publicacion(db)
        _lista8(db, item_id=500, price=10, curr_id=CURR_USD)
        _rate(db, venta=950.0)
        db.commit()

        congelar(db, order_id=2, items=[_item()])
        db.commit()

        row = _row(db, 2)
        assert row.costo_tp_origen == Decimal("10")
        assert row.costo_tp_moneda == "USD"
        assert row.costo_tp_tipo_cambio == Decimal("950")
        assert row.costo_tp_unitario_ars == Decimal("9500")

    def test_usd_list8_price_without_a_rate_leaves_tp_null_but_freezes_the_normal_cost(self, db):
        _producto(db, costo=100.0, moneda=TipoMoneda.ARS)
        _publicacion(db)
        _lista8(db, item_id=500, price=10, curr_id=CURR_USD)
        db.commit()

        congelar(db, order_id=3, items=[_item()])
        db.commit()

        row = _row(db, 3)
        assert row.costo_unitario_ars == Decimal("100")
        _assert_tp_null(row)

    def test_missing_list8_price_leaves_tp_null(self, db):
        _producto(db, costo=100.0)
        _publicacion(db)
        # A price on ANOTHER cost list must never be read as the TP cost.
        _lista8(db, item_id=500, price=70, coslis_id=1)
        db.commit()

        congelar(db, order_id=4, items=[_item()])
        db.commit()

        row = _row(db, 4)
        assert row.costo_unitario_ars == Decimal("100")
        _assert_tp_null(row)

    def test_zero_list8_price_leaves_tp_null_never_zero(self, db):
        _producto(db, costo=100.0)
        _publicacion(db)
        _lista8(db, item_id=500, price=0)
        db.commit()

        congelar(db, order_id=5, items=[_item()])
        db.commit()

        _assert_tp_null(_row(db, 5))

    def test_unknown_currency_leaves_tp_null(self, db):
        _producto(db, costo=100.0)
        _publicacion(db)
        _lista8(db, item_id=500, price=80, curr_id=99)
        db.commit()

        congelar(db, order_id=6, items=[_item()])
        db.commit()

        _assert_tp_null(_row(db, 6))

    def test_reingestion_never_rewrites_the_tp_cost(self, db):
        _producto(db, costo=100.0)
        _publicacion(db)
        _lista8(db, item_id=500, price=80)
        db.commit()

        congelar(db, order_id=7, items=[_item()])
        db.commit()

        precio = db.query(ItemCostList).filter_by(item_id=500, coslis_id=8).one()
        precio.coslis_price = 999
        db.commit()

        congelar(db, order_id=7, items=[_item()])
        db.commit()

        assert _row(db, 7).costo_tp_unitario_ars == Decimal("80")


class TestNormalCostUnchanged:
    def test_normal_cost_columns_are_untouched_by_the_tp_cost(self, db):
        _producto(db, costo=100.0)
        _publicacion(db)
        _lista8(db, item_id=500, price=80)
        db.commit()

        congelar(db, order_id=10, items=[_item()])
        db.commit()

        row = _row(db, 10)
        assert row.costo_origen == Decimal("100")
        assert row.moneda == "ARS"
        assert row.costo_unitario_ars == Decimal("100")
        assert row.fuente == FUENTE_PUBLICACION

    def test_list8_price_alone_never_freezes_a_row_without_a_normal_cost(self, db):
        """The TP cost rides on the normal snapshot row: no normal cost, no
        row -- the list-8 price never stands in for the normal cost."""
        _producto(db, costo=0.0)
        _publicacion(db)
        _lista8(db, item_id=500, price=80)
        db.commit()

        congelar(db, order_id=11, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=11).count() == 0


class TestTpCostCombos:
    def _combo(self, db, combo_costo=100.0):
        _producto(db, item_id=500, costo=combo_costo)
        _producto(db, item_id=901, costo=40.0, codigo="COMP-A")
        _producto(db, item_id=902, costo=10.0, codigo="COMP-B")
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=2, itema_id=1)
        _componente(db, combo_id=500, componente_id=902, qty=1, itema_id=2)

    def test_combo_without_own_list8_price_sums_its_components(self, db):
        """The combo HAS a normal cost of its own but NO list-8 price: the TP
        cost still comes from its components, mixing ARS and USD."""
        self._combo(db, combo_costo=100.0)
        _lista8(db, item_id=901, price=30, curr_id=CURR_ARS)
        _lista8(db, item_id=902, price=2, curr_id=CURR_USD)
        _rate(db, venta=1000.0)
        db.commit()

        congelar(db, order_id=20, items=[_item()])
        db.commit()

        row = _row(db, 20)
        # 2 * 30 + 1 * (2 * 1000) = 2060
        assert row.costo_tp_unitario_ars == Decimal("2060")
        assert row.costo_tp_origen == Decimal("2060")
        assert row.costo_tp_moneda == "ARS"
        assert row.costo_tp_tipo_cambio == Decimal("1000")
        assert row.costo_tp_fuente == FUENTE_TP_COMBO
        # The normal cost keeps using the combo's own cost.
        assert row.costo_unitario_ars == Decimal("100")

    def test_combo_with_a_component_missing_list8_leaves_tp_null(self, db):
        self._combo(db)
        _lista8(db, item_id=901, price=30)
        db.commit()

        congelar(db, order_id=21, items=[_item()])
        db.commit()

        _assert_tp_null(_row(db, 21))

    def test_combo_with_its_own_list8_price_uses_it(self, db):
        self._combo(db)
        _lista8(db, item_id=500, price=55)
        _lista8(db, item_id=901, price=30)
        _lista8(db, item_id=902, price=5)
        db.commit()

        congelar(db, order_id=22, items=[_item()])
        db.commit()

        row = _row(db, 22)
        assert row.costo_tp_unitario_ars == Decimal("55")
        assert row.costo_tp_fuente == FUENTE_TP_INGESTA

    def test_combo_without_normal_cost_gets_both_costs_from_components(self, db):
        self._combo(db, combo_costo=0.0)
        _lista8(db, item_id=901, price=30)
        _lista8(db, item_id=902, price=5)
        db.commit()

        congelar(db, order_id=23, items=[_item()])
        db.commit()

        row = _row(db, 23)
        assert row.costo_unitario_ars == Decimal("90")
        assert row.costo_tp_unitario_ars == Decimal("65")


class TestBatchedLookups:
    def test_list8_lookups_do_not_grow_with_the_number_of_items(self, db):
        """No N+1: the list-8 prices of every item AND every combo component
        are resolved in at most two queries per `congelar()` call."""
        items = []
        for i in range(4):
            erp_id = 500 + i
            mla = f"MLA{i}"
            _producto(db, item_id=erp_id, costo=100.0, codigo=f"SKU-{i}")
            _publicacion(db, mla=mla, item_id=erp_id)
            items.append(_item(item_id=mla, seller_sku=f"SKU-{i}"))
        _lista8(db, item_id=500, price=10)
        _lista8(db, item_id=501, price=1, curr_id=CURR_USD)
        # 502 and 503 are combos without a list-8 price of their own.
        for combo_id, base in ((502, 900), (503, 910)):
            for j in range(2):
                _producto(db, item_id=base + j, costo=5.0, codigo=f"C-{base + j}")
                _componente(db, combo_id=combo_id, componente_id=base + j, qty=1, itema_id=base + j)
                _lista8(db, item_id=base + j, price=3)
        _rate(db)
        db.commit()

        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", _record)
        try:
            congelar(db, order_id=30, items=items)
        finally:
            event.remove(db.bind, "before_cursor_execute", _record)
        db.commit()

        lista8_queries = [s for s in statements if "tb_item_cost_list" in s]
        assert len(lista8_queries) <= 2
        combo_queries = [s for s in statements if "tb_item_association" in s]
        assert len(combo_queries) == 1

        rows = {r.item_id: r for r in db.query(MlOrderItemCosto).filter_by(order_id=30)}
        assert rows["MLA0"].costo_tp_unitario_ars == Decimal("10")
        assert rows["MLA1"].costo_tp_unitario_ars == Decimal("950")
        assert rows["MLA2"].costo_tp_unitario_ars == Decimal("6")
        assert rows["MLA3"].costo_tp_unitario_ars == Decimal("6")


class TestTpCostConstraints:
    def _insert(self, db, **tp):
        from sqlalchemy.exc import IntegrityError

        db.add(
            MlOrderItemCosto(
                order_id=40,
                item_id="MLA1",
                costo_origen=Decimal("1"),
                moneda="ARS",
                costo_unitario_ars=Decimal("1"),
                iva_pct=Decimal("21"),
                precio_unitario=Decimal("10"),
                fuente=FUENTE_PUBLICACION,
                producto_item_id=500,
                **tp,
            )
        )
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return False
        return True

    def test_negative_tp_cost_is_rejected(self, db):
        from datetime import datetime, timezone

        assert not self._insert(
            db,
            costo_tp_origen=Decimal("-1"),
            costo_tp_moneda="ARS",
            costo_tp_unitario_ars=Decimal("-1"),
            costo_tp_fuente=FUENTE_TP_INGESTA,
            costo_tp_at=datetime.now(timezone.utc),
        )

    def test_half_written_tp_cost_is_rejected(self, db):
        assert not self._insert(db, costo_tp_unitario_ars=Decimal("5"))

    def test_fully_null_tp_cost_is_accepted(self, db):
        assert self._insert(db)
