"""Unit tests for `app.services.pxq_pricing_context` (slice A1, task 1.1).

Mirrors `ml_promotions_pricing._resolve_pricing_context`'s discipline: every
irresolvable input collapses to a single `None`, never a partial context and
never a raised exception. Covers the join chain `MlPxqTier.item_id` (MLA) ->
`PublicacionML.mla` -> `PublicacionML.item_id` (ERP) -> `ProductoERP`.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.tipo_cambio import TipoCambio
from app.services.pxq_pricing_context import PxqPricingContext, resolve_pxq_pricing_context


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
    pub = PublicacionML(mla="MLA9100001", item_id=producto.item_id, codigo="SKU-PXQ-CTX", pricelist_id=4)
    db.add(pub)
    db.flush()
    return pub


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

        assert context is not None
        assert isinstance(context, PxqPricingContext)
        assert context.costo_ars == pytest.approx(1000.0)
        assert context.comision_base_pct == pytest.approx(15.5)
        assert context.iva == pytest.approx(21.0)
        assert context.grupo_id == 1


class TestUnlinkedMla:
    def test_unlinked_mla_resolves_to_none(self, db, comision_fixtures) -> None:
        """A tier whose `item_id` has no matching `PublicacionML.mla` --
        never a partial or guessed value."""
        context = resolve_pxq_pricing_context(db, "MLA_DOES_NOT_EXIST")

        assert context is None


class TestMissingCost:
    def test_zero_costo_resolves_to_none(self, db, comision_fixtures) -> None:
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
        pub = PublicacionML(mla="MLA9100002", item_id=producto.item_id, codigo="SKU-PXQ-CTX-ZERO", pricelist_id=4)
        db.add(pub)
        db.flush()

        context = resolve_pxq_pricing_context(db, pub.mla)

        assert context is None


class TestNoComisionBase:
    def test_no_comision_base_resolves_to_none(self, db, publicacion) -> None:
        """No `ComisionVersion`/`ComisionBase` row anywhere -- product and
        publication both resolve, but the commission does not."""
        context = resolve_pxq_pricing_context(db, publicacion.mla)

        assert context is None


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
        pub = PublicacionML(mla="MLA9100003", item_id=producto.item_id, codigo="SKU-PXQ-CTX-USD", pricelist_id=4)
        db.add(pub)
        db.flush()
        db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=990.0, venta=1000.0))
        db.flush()

        context = resolve_pxq_pricing_context(db, pub.mla)

        assert context is not None
        assert context.costo_ars == pytest.approx(100.0 * 1000.0)
        assert context.comision_base_pct == pytest.approx(15.5)
        assert context.iva == pytest.approx(21.0)
        assert context.grupo_id == 1
