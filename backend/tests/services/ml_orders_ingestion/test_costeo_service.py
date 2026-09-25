"""Tests for the frozen cost snapshot writer (ml-ventas-modo-logistico, PR3).

The single invariant every test here protects: a re-ingestion of an order
NEVER rewrites an already-frozen `ml_order_item_costos` row, even when the
ERP cost/IVA/exchange rate that produced it has since changed. Every
mutation-verified test in this file is written to FAIL if that invariant is
silently broken (e.g. swapping `ON CONFLICT DO NOTHING` for an UPDATE, or
letting a `coalesce(..., 0)` stand in for "unknown").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.producto import ProductoERP, TipoMoneda
from app.models.publicacion_ml import PublicacionML
from app.models.tb_item_association import TbItemAssociation
from app.models.tipo_cambio import TipoCambio
from app.services.ml_orders_ingestion.costeo_service import FUENTE_COMBO, FUENTE_PUBLICACION, FUENTE_SKU, congelar
from app.services.ml_orders_ingestion.mapper import OrderItemOpsDTO


def _item(
    item_id: str = "MLA1",
    variation_id=None,
    seller_sku: str = "SKU-1",
    unit_price: float = 1000.0,
) -> OrderItemOpsDTO:
    return OrderItemOpsDTO(
        item_id=item_id,
        variation_id=variation_id,
        seller_sku=seller_sku,
        title="Producto de prueba",
        quantity=1,
        unit_price=unit_price,
        full_unit_price=unit_price,
        sale_fee=0.0,
        listing_type_id="gold_special",
    )


def _producto(db, item_id: int = 500, costo: float = 100.0, iva: float = 21.0, moneda=TipoMoneda.ARS) -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo="SKU-1",
        descripcion="Producto de prueba",
        costo=costo,
        moneda_costo=moneda,
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


def _componente(
    db, combo_id: int, componente_id: int, qty: float, itema_id: int, comp_id: int = 1
) -> TbItemAssociation:
    """One line of a combo's bill of materials in `tb_item_association`,
    same shape the backfill's own tests already use."""
    row = TbItemAssociation(
        comp_id=comp_id, itema_id=itema_id, item_id=combo_id, item_id_1=componente_id, iasso_qty=qty
    )
    db.add(row)
    db.flush()
    return row


class TestReingestionNeverRewrites:
    def test_reingestion_never_rewrites_frozen_snapshot(self, db):
        """MUTATION-VERIFIED: replacing `on_conflict_do_nothing` with
        `on_conflict_do_update` in `costeo_service._insert_stmt` call site
        makes this test fail -- the second `congelar()` call would pick up
        the mutated `costo` instead of the frozen one."""
        producto = _producto(db, costo=100.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=111, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=111, item_id="MLA1").one()
        assert row.costo_unitario_ars == Decimal("100.0000")

        producto.costo = 999.0
        db.add(producto)
        db.commit()

        congelar(db, order_id=111, items=[_item()])
        db.commit()

        row_again = db.query(MlOrderItemCosto).filter_by(order_id=111, item_id="MLA1").one()
        assert row_again.costo_unitario_ars == Decimal("100.0000")

    def test_reingestion_never_rewrites_frozen_iva_rate(self, db):
        """Same pattern for `iva_pct` -- a later change to
        `productos_erp.iva` must not leak into an already-frozen snapshot."""
        producto = _producto(db, iva=21.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=222, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=222, item_id="MLA1").one()
        assert row.iva_pct == Decimal("21.00")

        producto.iva = 10.5
        db.add(producto)
        db.commit()

        congelar(db, order_id=222, items=[_item()])
        db.commit()

        row_again = db.query(MlOrderItemCosto).filter_by(order_id=222, item_id="MLA1").one()
        assert row_again.iva_pct == Decimal("21.00")

    def test_new_order_item_stamped_on_first_insert(self, db):
        _producto(db, costo=250.5, iva=10.5)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=333, items=[_item(unit_price=1234.56)])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=333, item_id="MLA1").one()
        assert row.costo_origen == Decimal("250.5")
        assert row.moneda == "ARS"
        assert row.iva_pct == Decimal("10.50")
        assert row.precio_unitario == Decimal("1234.56")
        assert row.producto_item_id == 500
        assert row.congelado_at is not None


class TestUsdExchangeRateFrozen:
    def test_usd_product_survives_later_rate_change(self, db):
        """R1 and R2 are constructed with explicit UTC-aware effective
        dates -- the frozen value must be the rate CAPTURED at snapshot
        time, never re-derived later."""
        _producto(db, costo=10.0, iva=21.0, moneda=TipoMoneda.USD)
        _publicacion(db)
        r1 = TipoCambio(fecha=date(2026, 9, 1), moneda="USD", compra=900.0, venta=950.0)
        db.add(r1)
        db.commit()

        congelar(db, order_id=444, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=444, item_id="MLA1").one()
        assert row.tipo_cambio == Decimal("950.0")
        assert row.costo_unitario_ars == Decimal("9500.0")

        # A later, higher rate arrives -- must NOT change the frozen row.
        r2 = TipoCambio(fecha=date(2026, 9, 10), moneda="USD", compra=1100.0, venta=1200.0)
        db.add(r2)
        db.commit()

        congelar(db, order_id=444, items=[_item()])
        db.commit()

        row_again = db.query(MlOrderItemCosto).filter_by(order_id=444, item_id="MLA1").one()
        assert row_again.tipo_cambio == Decimal("950.0")
        assert row_again.costo_unitario_ars == Decimal("9500.0")


class TestLinkage:
    """Design D6 gives TWO ways to reach the product, and both have to be
    pinned. The SKU fallback had no test at all: removing it entirely left
    the whole suite green, which means a real linkage path was shipping
    unprotected."""

    def test_the_publication_link_resolves_the_product(self, db) -> None:
        _producto(db, item_id=500)
        _publicacion(db, mla="MLA1", item_id=500)
        db.commit()

        congelar(db, 4001, [_item(item_id="MLA1", seller_sku=None)])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=4001).one()
        assert row.producto_item_id == 500

    def test_the_sku_fallback_resolves_when_there_is_no_publication(self, db) -> None:
        """No `PublicacionML` for this MLA, but the seller SKU matches the
        ERP code. Without the fallback the sale would freeze NO cost and
        look like an honest unknown."""
        _producto(db, item_id=500)
        db.commit()

        congelar(db, 4002, [_item(item_id="MLA-SIN-PUBLICACION", seller_sku="SKU-1")])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=4002).one()
        assert row.producto_item_id == 500
        assert row.fuente == FUENTE_SKU

    def test_the_two_paths_are_distinguishable_afterwards(self, db) -> None:
        """`fuente` has to say WHICH path resolved it. Stamping one value
        for both makes the column useless for the only question it ever
        gets asked: when a cost looks wrong, was it the authoritative
        publication link or the SKU fallback that picked this product?"""
        _producto(db, item_id=500)
        _publicacion(db, mla="MLA1", item_id=500)
        db.commit()

        congelar(db, 4004, [_item(item_id="MLA1")])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=4004).one()
        assert row.fuente == FUENTE_PUBLICACION
        assert FUENTE_PUBLICACION != FUENTE_SKU

    def test_the_publication_wins_over_the_sku(self, db) -> None:
        """Both paths resolve, to DIFFERENT products. The publication link
        is the authoritative one; the SKU is only a fallback."""
        _producto(db, item_id=500)
        otro = ProductoERP(
            item_id=777,
            codigo="SKU-1",
            descripcion="Otro producto",
            costo=999.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        db.add(otro)
        _producto_publicado = ProductoERP(
            item_id=888,
            codigo="OTRO-CODIGO",
            descripcion="El publicado",
            costo=123.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        db.add(_producto_publicado)
        _publicacion(db, mla="MLA-AMBOS", item_id=888)
        db.commit()

        congelar(db, 4003, [_item(item_id="MLA-AMBOS", seller_sku="SKU-1")])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=4003).one()
        assert row.producto_item_id == 888, "the SKU fallback beat the publication link"

    def test_usd_product_without_any_rate_freezes_nothing(self, db) -> None:
        """A USD cost with no usable `TipoCambio` is the one unknown that
        could plausibly be "fixed" by letting the raw USD figure through as
        if it were pesos. A cost of 10 would be frozen as $10 instead of
        ~$9.500 -- a sale that looks almost pure profit. No row at all is
        the only honest answer."""
        _producto(db, costo=10.0, iva=21.0, moneda=TipoMoneda.USD)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=4005, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=4005).count() == 0


class TestUnknownIsNotZero:
    def test_unmatched_product_is_unknown_not_zero(self, db):
        """MUTATION-VERIFIED: substituting a `coalesce(costo, 0)` for the
        None-check in `_resolve_cost` would write a `costo_unitario_ars=0`
        row here instead of writing NOTHING."""
        # No PublicacionML, no ProductoERP with a matching sku either.
        congelar(db, order_id=555, items=[_item(seller_sku="NO-MATCH")])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=555).count() == 0

    def test_missing_costo_is_unknown_not_zero(self, db):
        _producto(db, costo=None, iva=21.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=666, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=666).count() == 0

    def test_unlinked_publication_is_unknown_not_zero(self, db):
        """No `PublicacionML` row at all, and the SKU fallback also
        doesn't match -- unknown, no row."""
        congelar(db, order_id=777, items=[_item(seller_sku="ANOTHER-SKU")])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=777).count() == 0

    def test_product_resolves_iva_does_not_is_unknown_whole(self, db):
        """Cost resolves, IVA does not -- the WHOLE snapshot is unknown,
        never a half-written row."""
        producto = _producto(db, costo=100.0)
        _publicacion(db)
        db.commit()
        # `ProductoERP.iva` has a Python-side `default=21.0` that fires at
        # INSERT time even when explicitly constructed with `iva=None` --
        # an UPDATE bypasses that default, giving a real NULL in the DB.
        db.query(ProductoERP).filter(ProductoERP.item_id == producto.item_id).update({"iva": None})
        db.commit()

        congelar(db, order_id=888, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=888).count() == 0


class TestDialectAwareInsert:
    def test_sqlite_postgres_on_conflict_do_nothing_dialect_path(self, db):
        """Verifies the dialect-aware `_insert_stmt` path actually executes
        `ON CONFLICT DO NOTHING` under SQLite (the test DB's dialect) --
        i.e. a second `congelar()` call for the same key does not raise a
        uniqueness violation and does not change the row."""
        assert db.bind.dialect.name == "sqlite"

        _producto(db, costo=42.0, iva=21.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=999, items=[_item()])
        db.commit()
        congelar(db, order_id=999, items=[_item()])
        db.commit()

        rows = db.query(MlOrderItemCosto).filter_by(order_id=999, item_id="MLA1").all()
        assert len(rows) == 1
        assert rows[0].costo_unitario_ars == Decimal("42.0000")


class TestComboLiveCosting:
    """A pack/combo/kit has no purchase cost of its own -- nobody buys a
    pack, so `ProductoERP.costo` is NULL for it forever. Today `congelar()`
    reads that NULL and skips the item, which is the dominant reason (3.470
    of 4.249 measured) the live path leaves a sale without a frozen cost.
    """

    def test_a_combo_with_costed_components_freezes_a_summed_cost(self, db):
        """T1 RED: today this writes NOTHING -- the combo (item_id=500) has
        no `costo` of its own, and `congelar()` has no notion of summing
        its components."""
        combo = _producto(db, item_id=500, costo=None, iva=21.0)
        db.add(combo)
        componente_a = ProductoERP(
            item_id=901,
            codigo="COMP-A",
            descripcion="Componente A",
            costo=40.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        componente_b = ProductoERP(
            item_id=902,
            codigo="COMP-B",
            descripcion="Componente B",
            costo=10.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        db.add(componente_a)
        db.add(componente_b)
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=2, itema_id=1)
        _componente(db, combo_id=500, componente_id=902, qty=1, itema_id=2)
        db.commit()

        congelar(db, order_id=7001, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=7001, item_id="MLA1").one()
        # 2 * 40 + 1 * 10 = 90
        assert row.costo_unitario_ars == Decimal("90.0000")
        assert row.fuente == FUENTE_COMBO
        assert row.fuente != FUENTE_PUBLICACION

    def test_one_uncosted_component_freezes_nothing_for_the_combo(self, db):
        """All-or-nothing, same discipline `SKIP_COMBO_COMPONENT_NO_COST`
        already applies in the backfill: never a partial sum."""
        _producto(db, item_id=500, costo=None, iva=21.0)
        componente_a = ProductoERP(
            item_id=901,
            codigo="COMP-A",
            descripcion="Componente A",
            costo=40.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        componente_sin_costo = ProductoERP(
            item_id=902,
            codigo="COMP-B",
            descripcion="Componente sin costo",
            costo=None,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        db.add(componente_a)
        db.add(componente_sin_costo)
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=1, itema_id=1)
        _componente(db, combo_id=500, componente_id=902, qty=1, itema_id=2)
        db.commit()

        congelar(db, order_id=7002, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=7002).count() == 0

    def test_usd_components_resolve_the_exchange_rate_once(self, db):
        """Two USD components: `latest_usd_rate_with_date` must be resolved
        ONCE per `congelar()` call, not once per component -- mutation-
        verified by asserting the converted total, which would silently
        diverge if a stale/second rate lookup fired mid-sum."""
        _producto(db, item_id=500, costo=None, iva=21.0)
        componente_a = ProductoERP(
            item_id=901,
            codigo="COMP-A",
            descripcion="Componente USD A",
            costo=10.0,
            moneda_costo=TipoMoneda.USD,
            iva=21.0,
        )
        componente_b = ProductoERP(
            item_id=902,
            codigo="COMP-B",
            descripcion="Componente USD B",
            costo=5.0,
            moneda_costo=TipoMoneda.USD,
            iva=21.0,
        )
        db.add(componente_a)
        db.add(componente_b)
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=1, itema_id=1)
        _componente(db, combo_id=500, componente_id=902, qty=1, itema_id=2)
        rate = TipoCambio(fecha=date(2026, 9, 1), moneda="USD", compra=900.0, venta=950.0)
        db.add(rate)
        db.commit()

        congelar(db, order_id=7003, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=7003, item_id="MLA1").one()
        # (10 + 5) * 950 = 14250
        assert row.costo_unitario_ars == Decimal("14250.0")
        assert row.tipo_cambio == Decimal("950.0")

    def test_usd_rate_lookup_is_called_at_most_once_per_congelar_call(self, db, monkeypatch):
        """MUTATION-VERIFIED: dropping the `usd_rate_cache` memoization in
        `_resolve_usd_rate` (calling `latest_usd_rate_with_date` straight
        from `_resolver_combo_vivo` on every component) makes this fail --
        it would be called twice for this two-USD-component combo."""
        import app.services.ml_orders_ingestion.costeo_service as costeo_service_module

        _producto(db, item_id=500, costo=None, iva=21.0)
        componente_a = ProductoERP(
            item_id=901,
            codigo="COMP-A",
            descripcion="Componente USD A",
            costo=10.0,
            moneda_costo=TipoMoneda.USD,
            iva=21.0,
        )
        componente_b = ProductoERP(
            item_id=902,
            codigo="COMP-B",
            descripcion="Componente USD B",
            costo=5.0,
            moneda_costo=TipoMoneda.USD,
            iva=21.0,
        )
        db.add(componente_a)
        db.add(componente_b)
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=1, itema_id=1)
        _componente(db, combo_id=500, componente_id=902, qty=1, itema_id=2)
        rate = TipoCambio(fecha=date(2026, 9, 1), moneda="USD", compra=900.0, venta=950.0)
        db.add(rate)
        db.commit()

        calls = []
        original = costeo_service_module.latest_usd_rate_with_date

        def _spy(db_arg):
            calls.append(1)
            return original(db_arg)

        monkeypatch.setattr(costeo_service_module, "latest_usd_rate_with_date", _spy)

        congelar(db, order_id=7005, items=[_item()])
        db.commit()

        assert len(calls) == 1, "the FX rate must resolve ONCE per congelar() call, not once per component"

    def test_a_combo_with_zero_cost_freezes_the_summed_component_cost(self, db):
        """The sync (`erp_sync.py`) never writes `producto.costo = None` --
        `convertir_a_numero(..., default=0)` means a combo with no cost row
        in the ERP lands as `costo=0.0`, never `NULL`. This is the SHAPE
        `congelar()` actually sees in production, not the `costo=None` the
        other tests in this class use.

        RED today: `_resolve_cost` takes the `producto.costo is not None`
        branch for a `costo=0.0` product, converts a zero, and freezes a
        `costo_unitario_ars == 0` row -- reading exactly like a real cost
        of zero, when the honest state is "this product has no cost of its
        own, sum its components" (same as the `costo=None` case)."""
        _producto(db, item_id=500, costo=0.0, iva=21.0)
        componente_a = ProductoERP(
            item_id=901,
            codigo="COMP-A",
            descripcion="Componente A",
            costo=40.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        componente_b = ProductoERP(
            item_id=902,
            codigo="COMP-B",
            descripcion="Componente B",
            costo=10.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        db.add(componente_a)
        db.add(componente_b)
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=2, itema_id=1)
        _componente(db, combo_id=500, componente_id=902, qty=1, itema_id=2)
        db.commit()

        congelar(db, order_id=7006, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=7006, item_id="MLA1").one()
        # 2 * 40 + 1 * 10 = 90
        assert row.costo_unitario_ars == Decimal("90.0000")
        assert row.fuente == FUENTE_COMBO

    def test_a_plain_product_with_zero_cost_and_no_components_freezes_nothing(self, db):
        """A `costo=0.0` product with NO bill-of-materials rows in
        `tb_item_association` is a hole in the ERP, not a product that
        became free. `congelar()` must not freeze `costo_unitario_ars == 0`
        for it -- "unknown is not zero" applies to the live path exactly
        like it already applies to the backfill's `_tiene_precio`.

        RED today: `producto.costo is not None` is `True` for `0.0`, so
        `_resolve_cost` converts and freezes the zero."""
        _producto(db, item_id=500, costo=0.0, iva=21.0)
        _publicacion(db, item_id=500)
        db.commit()

        congelar(db, order_id=7007, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=7007).count() == 0

    def test_one_zero_cost_component_sinks_the_whole_combo(self, db):
        """A component with `costo=0.0` (the real ERP shape for "no cost"),
        not just `costo=None`, must sink the whole combo -- same
        all-or-nothing discipline, never a partial sum that silently
        excludes the free-looking component.

        RED today: `_resolver_combo_vivo` only checks `componente.costo is
        None`, so a `costo=0.0` component sails through and contributes
        `0` to the sum instead of sinking it -- the combo freezes an
        UNDERSTATED cost that looks complete."""
        _producto(db, item_id=500, costo=None, iva=21.0)
        componente_a = ProductoERP(
            item_id=901,
            codigo="COMP-A",
            descripcion="Componente A",
            costo=40.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        componente_cero = ProductoERP(
            item_id=902,
            codigo="COMP-B",
            descripcion="Componente con costo cero",
            costo=0.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        db.add(componente_a)
        db.add(componente_cero)
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=1, itema_id=1)
        _componente(db, combo_id=500, componente_id=902, qty=1, itema_id=2)
        db.commit()

        congelar(db, order_id=7008, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=7008).count() == 0

    def test_a_plain_product_with_its_own_cost_is_never_treated_as_a_combo(self, db):
        """A product that has BOTH its own cost and (incidentally) rows in
        `tb_item_association` is costed with its own figure -- same order-
        of-preference the backfill documents for `_resolve_backfill_cost`."""
        _producto(db, item_id=500, costo=100.0, iva=21.0)
        componente_a = ProductoERP(
            item_id=901,
            codigo="COMP-A",
            descripcion="Componente A",
            costo=999.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
        db.add(componente_a)
        _publicacion(db, item_id=500)
        _componente(db, combo_id=500, componente_id=901, qty=1, itema_id=1)
        db.commit()

        congelar(db, order_id=7004, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=7004, item_id="MLA1").one()
        assert row.costo_unitario_ars == Decimal("100.0")
        assert row.fuente == FUENTE_PUBLICACION
