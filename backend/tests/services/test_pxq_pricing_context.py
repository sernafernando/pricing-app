"""Unit tests for `app.services.pxq_pricing_context` (slice A1, task 1.1; S11b).

Mirrors `ml_promotions_pricing._resolve_pricing_context`'s discipline: every
irresolvable input collapses to a single `PxqPricingUnavailable` with the
header's reason, never a partial context and never a raised exception.
Covers the join chain `MlPxqTier.item_id` (MLA) -> `ml_items` and its
item-level `ml_item_product_links` -> `ProductoERP` (S11b: the header's
inputs, not `publicaciones_ml`).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_publications import MlItem
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.tipo_cambio import TipoCambio
from app.services.pxq_pricing_context import PxqPricingContext, PxqPricingUnavailable, resolve_pxq_pricing_context
from tests.services.pxq_store import store_rows


def _publish(db, mla: str, producto: ProductoERP, codigo: str) -> PublicacionML:
    pub = PublicacionML(mla=mla, item_id=producto.item_id, codigo=codigo, pricelist_id=4)
    db.add(pub)
    db.add_all(store_rows(mla, producto.item_id))
    db.flush()
    return pub


def _reason(context) -> str:
    assert isinstance(context, PxqPricingUnavailable), context
    return context.reason


@pytest.fixture()
def producto(db) -> ProductoERP:
    producto = ProductoERP(
        item_id=91001,
        codigo="SKU-PXQ-CTX",
        descripcion="Producto PxQ context",
        costo=1000.0,
        moneda_costo="ARS",
        iva=21.0,
    )
    db.add(producto)
    db.flush()
    return producto


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    return _publish(db, "MLA9100001", producto, "SKU-PXQ-CTX")


@pytest.fixture()
def comision_fixtures(db) -> ComisionVersion:
    """Grupo 1 matches `GRUPO_DEFAULT` -- `producto` has no `subcategoria_id`,
    so `obtener_grupo_subcategoria` falls back to grupo 1."""
    version = ComisionVersion(nombre="Test PxQ", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=15.5))
    db.flush()
    return version


class TestResolvableTier:
    def test_resolvable_tier_returns_full_context(self, db, publicacion, comision_fixtures) -> None:
        context = resolve_pxq_pricing_context(db, publicacion.mla)

        assert isinstance(context, PxqPricingContext)
        assert context.costo_ars == pytest.approx(1000.0)
        assert context.comision_base_pct == pytest.approx(15.5)
        assert context.iva == pytest.approx(21.0)
        assert context.grupo_id == 1


class TestProductFromTheLink:
    def test_the_product_is_the_one_the_item_level_link_points_to(self, db, producto, comision_fixtures) -> None:
        """S11b: `publicaciones_ml.item_id` names one product, the store link another: the link wins, as in the
        header, so cost/IVA/subcategory are the header's."""
        linked = ProductoERP(
            item_id=91010, codigo="SKU-PXQ-CTX-LINK", descripcion="Linked", costo=2500.0, moneda_costo="ARS", iva=10.5
        )
        db.add(linked)
        db.flush()
        db.add(PublicacionML(mla="MLA9100010", item_id=producto.item_id, codigo="SKU-PXQ-CTX", pricelist_id=4))
        db.add_all(store_rows("MLA9100010", linked.item_id))
        db.flush()

        context = resolve_pxq_pricing_context(db, "MLA9100010")

        assert isinstance(context, PxqPricingContext)
        assert context.costo_ars == pytest.approx(2500.0)
        assert context.iva == pytest.approx(10.5)

    def test_no_item_level_link_reports_sin_vinculo(self, db, producto, comision_fixtures) -> None:
        """Only the stored publication names a product: never priced on it."""
        db.add(PublicacionML(mla="MLA9100011", item_id=producto.item_id, codigo="SKU-PXQ-CTX", pricelist_id=4))
        db.add(MlItem(item_id="MLA9100011", listing_type_id="gold_special"))
        db.flush()

        assert _reason(resolve_pxq_pricing_context(db, "MLA9100011")) == "sin_vinculo"

    def test_a_link_to_a_vanished_product_reports_sin_costo(self, db, comision_fixtures) -> None:
        """The link has no foreign key (the ERP sync rewrites the table): a vanished product has no cost, as in
        the header."""
        db.add_all(store_rows("MLA9100012", 91999))
        db.flush()

        assert _reason(resolve_pxq_pricing_context(db, "MLA9100012")) == "sin_costo"


class TestNotInTheStore:
    def test_an_mla_not_in_the_store_reports_sin_item_ml(self, db, comision_fixtures) -> None:
        """A tier whose `item_id` has no `ml_items` row -- never a partial or guessed value."""
        assert _reason(resolve_pxq_pricing_context(db, "MLA_DOES_NOT_EXIST")) == "sin_item_ml"


class TestMissingCost:
    def test_zero_costo_reports_sin_costo(self, db, comision_fixtures) -> None:
        producto = ProductoERP(
            item_id=91002,
            codigo="SKU-PXQ-CTX-ZERO",
            descripcion="Producto sin costo",
            costo=0,
            moneda_costo="ARS",
            iva=21.0,
        )
        db.add(producto)
        db.flush()
        pub = _publish(db, "MLA9100002", producto, "SKU-PXQ-CTX-ZERO")

        assert _reason(resolve_pxq_pricing_context(db, pub.mla)) == "sin_costo"


class TestNoComisionBase:
    def test_no_comision_base_reports_sin_comision(self, db, publicacion) -> None:
        """No `ComisionVersion`/`ComisionBase` row anywhere -- product and
        publication both resolve, but the commission does not."""
        assert _reason(resolve_pxq_pricing_context(db, publicacion.mla)) == "sin_comision"


class TestUsdCostConversion:
    def test_usd_cost_is_converted_to_ars_never_partial(self, db, comision_fixtures) -> None:
        producto = ProductoERP(
            item_id=91003,
            codigo="SKU-PXQ-CTX-USD",
            descripcion="Producto USD",
            costo=100.0,
            moneda_costo="USD",
            iva=21.0,
        )
        db.add(producto)
        db.flush()
        pub = _publish(db, "MLA9100003", producto, "SKU-PXQ-CTX-USD")
        db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=990.0, venta=1000.0))
        db.flush()

        context = resolve_pxq_pricing_context(db, pub.mla)

        assert isinstance(context, PxqPricingContext)
        assert context.costo_ars == pytest.approx(100.0 * 1000.0)
        assert context.comision_base_pct == pytest.approx(15.5)
        assert context.iva == pytest.approx(21.0)
        assert context.grupo_id == 1


class TestUsdCostWithoutTipoCambio:
    def test_usd_cost_without_any_tipo_cambio_row_reports_product_data_missing(self, db, comision_fixtures) -> None:
        """No `TipoCambio` row exists at all (not just missing today's) --
        `obtener_tipo_cambio_actual` returns `None`. A USD cost must NEVER be
        handed to the caller as if it were ARS: `convertir_a_pesos` falls
        through to `return costo` unconverted when `tipo_cambio` is falsy,
        which would silently produce a ~1000x inflated markup with no
        `reason` attached. This is the un-exercised branch of
        `TestUsdCostConversion`, which always inserts a `TipoCambio` row and
        therefore never proves the missing-quote path."""
        producto = ProductoERP(
            item_id=91004,
            codigo="SKU-PXQ-CTX-USD-NOTC",
            descripcion="Producto USD sin cotizacion",
            costo=100.0,
            moneda_costo="USD",
            iva=21.0,
        )
        db.add(producto)
        db.flush()
        pub = _publish(db, "MLA9100004", producto, "SKU-PXQ-CTX-USD-NOTC")
        # Deliberately no TipoCambio row at all -- not even for another date.

        assert _reason(resolve_pxq_pricing_context(db, pub.mla)) == "product_data_missing"


class TestMissingIva:
    def test_null_iva_reports_product_data_missing_never_raises(self, db, comision_fixtures) -> None:
        """`ProductoERP.iva` has `default=21.0` at the ORM level only -- rows
        written by the ERP sync (outside this app's ORM insert path) can
        land with `iva IS NULL`. That must collapse to an unavailable
        context like every other irresolvable input here, never leak a
        `None` into `PxqPricingContext.iva` that later raises a `TypeError`
        deep inside `calcular_markup_pxq`.

        Constructing `ProductoERP(iva=None)` through the ORM is NOT enough
        to reproduce this: SQLAlchemy's Python-side `default=` fires
        whenever the attribute is `None` at flush time regardless of
        whether it was explicitly set, masking exactly the bug this test
        exists to catch. A raw `UPDATE` after flush is required to land a
        real `iva IS NULL` row, matching how the ERP sync writes it."""
        producto = ProductoERP(
            item_id=91005,
            codigo="SKU-PXQ-CTX-NOIVA",
            descripcion="Producto sin iva",
            costo=1000.0,
            moneda_costo="ARS",
            iva=21.0,
        )
        db.add(producto)
        db.flush()
        pub = _publish(db, "MLA9100005", producto, "SKU-PXQ-CTX-NOIVA")
        db.execute(text("UPDATE productos_erp SET iva = NULL WHERE item_id = :item_id"), {"item_id": producto.item_id})
        db.flush()
        db.expire_all()

        assert _reason(resolve_pxq_pricing_context(db, pub.mla)) == "product_data_missing"


class TestUnresolvableCurrency:
    def test_null_moneda_costo_reports_product_data_missing_never_assumes_ars(self, db, comision_fixtures) -> None:
        """`ProductoERP.moneda_costo` has `default=TipoMoneda.ARS` at the ORM
        level only -- an ERP-synced row with `moneda_costo IS NULL` must NOT
        be silently treated as ARS: `convertir_a_pesos` only special-cases
        the literal string `"ARS"`, so any other value (including `None`)
        falls through to `return costo` unconverted -- the exact same
        fabricated-number shape as the missing-`tipo_cambio` case, just for
        a different unresolvable input.

        Same reasoning as `TestMissingIva`: the ORM-level default also
        fires for an explicit `None` at insert time, so a raw `UPDATE`
        after flush is required to reproduce a real `moneda_costo IS NULL`
        row."""
        producto = ProductoERP(
            item_id=91006,
            codigo="SKU-PXQ-CTX-NOMONEDA",
            descripcion="Producto sin moneda",
            costo=1000.0,
            moneda_costo="ARS",
            iva=21.0,
        )
        db.add(producto)
        db.flush()
        pub = _publish(db, "MLA9100006", producto, "SKU-PXQ-CTX-NOMONEDA")
        db.execute(
            text("UPDATE productos_erp SET moneda_costo = NULL WHERE item_id = :item_id"), {"item_id": producto.item_id}
        )
        db.flush()
        db.expire_all()

        assert _reason(resolve_pxq_pricing_context(db, pub.mla)) == "product_data_missing"
