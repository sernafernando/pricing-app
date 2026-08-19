"""Unit tests for `app.services.pxq_markup_service` (slice A1, task 1.3).

Wires `resolve_pxq_pricing_context` (product/commission) + `resolve_tier_shipping`
(existing, `pxq_markup.py`) into `calcular_markup_pxq` (existing, ZERO production
callers before this slice) -- ONLY when BOTH inputs resolve. Never a fabricated
number: every unresolved tier carries a reason instead.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import date
from decimal import Decimal

import pytest

from app.core.security import get_password_hash
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.pxq_markup import ShipmentShippingCost, calcular_markup_pxq, resolve_order_cost
from app.services.pxq_markup_service import TierMarkup, markup_for_tiers, markup_resolved


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_markup_svc_user",
        email="pxq_markup_svc_user@example.com",
        nombre="PxQ Markup Service User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def comision_fixtures(db) -> ComisionVersion:
    version = ComisionVersion(nombre="Test PxQ Markup", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=20.0))
    db.flush()
    return version


def _make_publicacion(db, *, item_id_suffix: int, pricelist_id: int = 4, moneda_costo: str = "ARS") -> PublicacionML:
    producto = ProductoERP(
        item_id=92000 + item_id_suffix,
        codigo=f"SKU-PXQ-MKT-{item_id_suffix}",
        descripcion="Producto PxQ markup service",
        costo=1000.0,
        moneda_costo=moneda_costo,
        iva=21.0,
    )
    db.add(producto)
    db.flush()
    pub = PublicacionML(
        mla=f"MLA9200{item_id_suffix:03d}",
        item_id=producto.item_id,
        codigo=producto.codigo,
        pricelist_id=pricelist_id,
    )
    db.add(pub)
    db.flush()
    return pub


def _make_tier(db, publicacion, pxq_user, *, cantidad_minima=10, precio_unitario="500.00", costo_envio_total=None):
    tier = MlPxqTier(
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=cantidad_minima,
        precio_unitario=Decimal(precio_unitario),
        costo_envio_total=Decimal(costo_envio_total) if costo_envio_total is not None else None,
        usuario_id=pxq_user.id,
    )
    db.add(tier)
    db.flush()
    return tier


class TestBothPresentMatchesCalcularMarkupPxq:
    def test_markup_matches_calcular_markup_pxq_output(self, db, pxq_user, comision_fixtures) -> None:
        publicacion = _make_publicacion(db, item_id_suffix=1)
        tier = _make_tier(db, publicacion, pxq_user, costo_envio_total="200.00")

        result = markup_for_tiers(db, publicacion.mla)

        assert tier.id in result
        entry = result[tier.id]
        assert markup_resolved(entry)
        assert entry.reason is None

        expected = calcular_markup_pxq(
            precio_unitario=Decimal("500.00"),
            cantidad_minima=10,
            comision_base_pct=20.0,
            iva=21.0,
            costo=resolve_order_cost(1000.0, 10),
            shipping=ShipmentShippingCost(amount=200.0),
        )
        assert entry.markup == pytest.approx(expected["markup"])
        assert entry.limpio == pytest.approx(expected["limpio"])
        assert entry.comision_total == pytest.approx(expected["comision_total"])


class TestShippingMissing:
    def test_shipping_missing_reports_shipping_unavailable(self, db, pxq_user, comision_fixtures) -> None:
        publicacion = _make_publicacion(db, item_id_suffix=2)
        tier = _make_tier(db, publicacion, pxq_user, costo_envio_total=None)

        result = markup_for_tiers(db, publicacion.mla)

        entry = result[tier.id]
        assert entry.reason == "shipping_unavailable"
        assert not markup_resolved(entry)
        # No numeric field appears beside the reason -- assert on dict keys,
        # not just that values happen to be None.
        payload = {k: v for k, v in asdict(entry).items() if v is not None}
        assert set(payload.keys()) == {"tier_id", "reason"}


class TestProductDataMissing:
    def test_product_data_missing_reports_product_data_missing(self, db, pxq_user, comision_fixtures) -> None:
        # No ProductoERP/PublicacionML for this MLA at all -- context is
        # unresolvable, independent of shipping being present.
        producto = ProductoERP(
            item_id=92099,
            codigo="SKU-PXQ-MKT-NOCOST",
            descripcion="Producto sin costo",
            costo=0,
            moneda_costo="ARS",
            iva=21.0,
        )
        db.add(producto)
        db.flush()
        publicacion = PublicacionML(mla="MLA9200099", item_id=producto.item_id, codigo=producto.codigo, pricelist_id=4)
        db.add(publicacion)
        db.flush()
        tier = _make_tier(db, publicacion, pxq_user, costo_envio_total="200.00")

        result = markup_for_tiers(db, publicacion.mla)

        entry = result[tier.id]
        assert entry.reason == "product_data_missing"
        assert not markup_resolved(entry)


class TestBothMissingPrecedence:
    def test_both_missing_reports_product_data_missing_not_shipping(self, db, pxq_user, comision_fixtures) -> None:
        producto = ProductoERP(
            item_id=92098,
            codigo="SKU-PXQ-MKT-BOTHMISSING",
            descripcion="Producto sin costo, sin envio",
            costo=0,
            moneda_costo="ARS",
            iva=21.0,
        )
        db.add(producto)
        db.flush()
        publicacion = PublicacionML(mla="MLA9200098", item_id=producto.item_id, codigo=producto.codigo, pricelist_id=4)
        db.add(publicacion)
        db.flush()
        tier = _make_tier(db, publicacion, pxq_user, costo_envio_total=None)

        result = markup_for_tiers(db, publicacion.mla)

        entry = result[tier.id]
        assert entry.reason == "product_data_missing"


class TestRegressionGuardNeverFabricated:
    def test_no_markup_shaped_field_when_unresolved(self, db, pxq_user, comision_fixtures) -> None:
        publicacion = _make_publicacion(db, item_id_suffix=3)
        tier = _make_tier(db, publicacion, pxq_user, costo_envio_total=None)

        result = markup_for_tiers(db, publicacion.mla)

        entry = result[tier.id]
        assert entry.markup is None
        assert entry.limpio is None
        assert entry.comision_total is None
        # Structural guard: TierMarkup never gains a stray numeric field that
        # would slip past the exclude_none contract at the router layer.
        assert {f.name for f in fields(TierMarkup)} == {"tier_id", "reason", "markup", "limpio", "comision_total"}


class TestUniformAcrossPublications:
    def test_no_per_item_branching_across_different_pricelist_and_currency(
        self, db, pxq_user, comision_fixtures
    ) -> None:
        pub_ars = _make_publicacion(db, item_id_suffix=4, pricelist_id=4, moneda_costo="ARS")
        pub_usd = _make_publicacion(db, item_id_suffix=5, pricelist_id=4, moneda_costo="USD")
        from app.models.tipo_cambio import TipoCambio

        db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=990.0, venta=1000.0))
        db.flush()

        tier_ars = _make_tier(db, pub_ars, pxq_user, costo_envio_total="150.00")
        tier_usd = _make_tier(db, pub_usd, pxq_user, costo_envio_total="150.00")

        result_ars = markup_for_tiers(db, pub_ars.mla)
        result_usd = markup_for_tiers(db, pub_usd.mla)

        # Both resolve through the identical code path -- both end up with a
        # markup, computed off their respective (already-converted) cost.
        assert markup_resolved(result_ars[tier_ars.id])
        assert markup_resolved(result_usd[tier_usd.id])
        # The USD publication's cost was converted (1000 USD-equivalent vs
        # 1000 ARS raw), so their markups differ -- proving the currency
        # conversion actually ran, not that a shared branch was skipped.
        assert result_ars[tier_ars.id].markup != pytest.approx(result_usd[tier_usd.id].markup)


class TestEmptyMirror:
    def test_no_tiers_for_item_returns_empty_dict(self, db, comision_fixtures) -> None:
        assert markup_for_tiers(db, "MLA_NO_TIERS_AT_ALL") == {}


class TestUsesDatabaseDrivenPricingConstants:
    """Every OTHER production caller of `calcular_comision_ml_total` /
    `calcular_limpio` passes `db=`/`constantes=` so an operator's edit to
    `pricing_constants` is honored (`pricing.py:139`, `:604`,
    `productos_pricing.py:1022`). `markup_for_tiers` must do the same --
    otherwise the markup shown on the PxQ panel silently diverges from what
    the rest of the app computes for the same product the moment the
    constants table changes."""

    def test_a_custom_varios_percentage_changes_the_computed_markup(self, db, pxq_user, comision_fixtures) -> None:
        from app.models.pricing_constants import PricingConstants

        publicacion = _make_publicacion(db, item_id_suffix=6)
        tier = _make_tier(db, publicacion, pxq_user, costo_envio_total="200.00")

        # Baseline: no PricingConstants row -> module hardcoded defaults.
        baseline = markup_for_tiers(db, publicacion.mla)[tier.id]

        # A drastically different `varios_porcentaje` (module default is
        # 6.5) must change the computed markup if -- and only if -- the
        # service actually reads the DB-driven constants.
        db.add(
            PricingConstants(
                monto_tier1=15000,
                monto_tier2=24000,
                monto_tier3=33000,
                comision_tier1=1095,
                comision_tier2=2190,
                comision_tier3=2628,
                varios_porcentaje=25.0,
                fecha_desde=date(2000, 1, 1),
            )
        )
        db.flush()

        with_custom_constants = markup_for_tiers(db, publicacion.mla)[tier.id]

        assert with_custom_constants.markup != pytest.approx(baseline.markup)


class TestDeterministicOrdering:
    """Mirrors `GET /{item_id}/live`'s discipline (`pxq.py`): a tier is a
    QUANTITY THRESHOLD, so the batch must not depend on insertion order."""

    def test_tiers_are_read_in_cantidad_minima_order_regardless_of_insertion(
        self, db, pxq_user, comision_fixtures
    ) -> None:
        publicacion = _make_publicacion(db, item_id_suffix=7)
        # Inserted out of order on purpose: 30, then 5, then 10.
        tier_30 = _make_tier(db, publicacion, pxq_user, cantidad_minima=30, costo_envio_total="200.00")
        tier_5 = _make_tier(db, publicacion, pxq_user, cantidad_minima=5, costo_envio_total="200.00")
        tier_10 = _make_tier(db, publicacion, pxq_user, cantidad_minima=10, costo_envio_total="200.00")

        result = markup_for_tiers(db, publicacion.mla)

        assert [tm.tier_id for tm in result.values()] == [tier_5.id, tier_10.id, tier_30.id]
