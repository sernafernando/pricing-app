"""Unit tests for `refresh_tier_shipping` (pxq_markup_service.py, slice B,
task 4.7/4.8) -- the TTL-gated auto-fetch trigger wired into the markup
read path BEFORE `resolve_tier_shipping`.

All tests run against a FAKE `MLWebhookClient` -- the proxy route
`GET /api/shipping/seller-cost` does not exist in production yet, so a
None-returning fake IS today's real-world response, not a stand-in for a
hypothetical. See `test_pxq_shipping_refresh_degrade_regression.py`-style
coverage folded into `TestDegradeNeverFabricate` below for the guard that
matters most: absence degrades to a STATE, never a fabricated 0 or markup.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.security import get_password_hash
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import pxq_markup_service
from app.services.pxq_markup_service import markup_for_tiers, refresh_tier_shipping


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_refresh_user",
        email="pxq_refresh_user@example.com",
        nombre="PxQ Refresh User",
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
    version = ComisionVersion(nombre="Test PxQ Refresh", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=20.0))
    db.flush()
    return version


def _make_publicacion(db, *, item_id_suffix: int) -> PublicacionML:
    producto = ProductoERP(
        item_id=93000 + item_id_suffix,
        codigo=f"SKU-PXQ-REFRESH-{item_id_suffix}",
        descripcion="Producto PxQ refresh",
        costo=1000.0,
        moneda_costo="ARS",
        iva=21.0,
    )
    db.add(producto)
    db.flush()
    pub = PublicacionML(
        mla=f"MLA9300{item_id_suffix:03d}",
        item_id=producto.item_id,
        codigo=producto.codigo,
        pricelist_id=4,
    )
    db.add(pub)
    db.flush()
    return pub


def _make_tier(db, publicacion, pxq_user, *, fetched_at=None, costo_envio_total=None):
    tier = MlPxqTier(
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=10,
        precio_unitario=Decimal("500.00"),
        costo_envio_total=Decimal(costo_envio_total) if costo_envio_total is not None else None,
        costo_envio_fetched_at=fetched_at,
        usuario_id=pxq_user.id,
    )
    db.add(tier)
    db.flush()
    return tier


class _FakeClient:
    """Records every call; `amount` controls the canned response -- None
    reproduces today's real production behaviour (proxy route absent)."""

    def __init__(self, amount=None):
        self.amount = amount
        self.calls = []

    async def get_pxq_seller_shipping_cost(self, item_id, quantity, tier_price):
        self.calls.append((item_id, quantity, tier_price))
        return self.amount


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    monkeypatch.setattr(pxq_markup_service, "MLWebhookClient", lambda: fake)


class TestTtlGating:
    def test_fresh_stamp_2h_old_makes_zero_proxy_calls(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=1)
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=2)
        tier = _make_tier(db, pub, pxq_user, fetched_at=fetched_at, costo_envio_total="200.00")
        fake = _FakeClient(amount=999.0)
        _install_fake_client(monkeypatch, fake)

        refresh_tier_shipping(db, tier)

        assert fake.calls == []
        assert tier.costo_envio_total == Decimal("200.00")

    def test_stale_stamp_25h_old_calls_the_proxy(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=2)
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=25)
        tier = _make_tier(db, pub, pxq_user, fetched_at=fetched_at, costo_envio_total="200.00")
        fake = _FakeClient(amount=333.0)
        _install_fake_client(monkeypatch, fake)

        refresh_tier_shipping(db, tier)

        assert len(fake.calls) == 1
        assert tier.costo_envio_total == Decimal("333.0")
        assert tier.costo_envio_fetched_at is not None

    def test_null_stamp_never_fetched_calls_the_proxy(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=3)
        tier = _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=42.0)
        _install_fake_client(monkeypatch, fake)

        refresh_tier_shipping(db, tier)

        assert len(fake.calls) == 1
        assert tier.costo_envio_total == Decimal("42.0")

    def test_three_reopens_within_1h_of_a_10min_old_fetch_make_zero_additional_calls(
        self, db, pxq_user, comision_fixtures, monkeypatch
    ) -> None:
        pub = _make_publicacion(db, item_id_suffix=4)
        fetched_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        tier = _make_tier(db, pub, pxq_user, fetched_at=fetched_at, costo_envio_total="150.00")
        fake = _FakeClient(amount=777.0)
        _install_fake_client(monkeypatch, fake)

        for _ in range(3):
            refresh_tier_shipping(db, tier)

        assert fake.calls == []
        assert tier.costo_envio_total == Decimal("150.00")


class TestFailedFetchTouchesNothing:
    def test_none_response_leaves_both_columns_untouched(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=5)
        tier = _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=None)
        _install_fake_client(monkeypatch, fake)

        refresh_tier_shipping(db, tier)

        assert len(fake.calls) == 1
        assert tier.costo_envio_total is None
        assert tier.costo_envio_fetched_at is None


class TestWiredIntoMarkupReadPath:
    def test_markup_for_tiers_calls_refresh_before_resolving_shipping(
        self, db, pxq_user, comision_fixtures, monkeypatch
    ) -> None:
        pub = _make_publicacion(db, item_id_suffix=6)
        tier = _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=250.0)
        _install_fake_client(monkeypatch, fake)

        result = markup_for_tiers(db, pub.mla)

        assert len(fake.calls) == 1
        entry = result[tier.id]
        assert entry.reason is None
        assert entry.markup is not None


class TestDegradeNeverFabricate:
    """Regression guard (task 4.9): the FAKE returning None reproduces the
    CURRENT production state (proxy route absent). Every tier must degrade
    to `shipping_unavailable`, `costo_envio_total` must stay exactly what
    it was, and NOTHING may ever read as 0 or produce a fabricated
    markup."""

    def test_proxy_absent_every_tier_reads_shipping_unavailable(
        self, db, pxq_user, comision_fixtures, monkeypatch
    ) -> None:
        pub = _make_publicacion(db, item_id_suffix=7)
        tier = _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=None)
        _install_fake_client(monkeypatch, fake)

        result = markup_for_tiers(db, pub.mla)

        entry = result[tier.id]
        assert entry.reason == "shipping_unavailable"
        assert entry.markup is None
        assert entry.limpio is None
        assert entry.comision_total is None
        assert tier.costo_envio_total is None

    def test_proxy_absent_never_zero_never_fabricated_even_with_a_prior_value(
        self, db, pxq_user, comision_fixtures, monkeypatch
    ) -> None:
        pub = _make_publicacion(db, item_id_suffix=8)
        # A stale, previously-fetched value present -- the failed re-fetch
        # must not touch it, and it must not silently expire to 0 either.
        stale_fetched_at = datetime.now(timezone.utc) - timedelta(hours=48)
        tier = _make_tier(db, pub, pxq_user, fetched_at=stale_fetched_at, costo_envio_total="180.00")
        fake = _FakeClient(amount=None)
        _install_fake_client(monkeypatch, fake)

        result = markup_for_tiers(db, pub.mla)

        entry = result[tier.id]
        # The STALE value is still there -- resolve_tier_shipping reads
        # whatever costo_envio_total currently holds, which the failed
        # fetch did not touch. It is NOT `shipping_unavailable` here
        # because a stale-but-present value is still a usable number; the
        # guard is that it was never replaced by 0 or invented.
        assert entry.reason is None
        assert tier.costo_envio_total == Decimal("180.00")
        assert tier.costo_envio_total != Decimal("0")
