"""Unit tests for `refresh_stale_tier_shipping` (pxq_markup_service.py,
slice B pool-safety fix) -- the TTL-gated auto-fetch orchestrator that owns
its own short sessions end-to-end and NEVER holds any session (its own or a
caller's) across the outbound ml-webhook proxy call.

Supersedes the earlier `refresh_tier_shipping(db, tier)` design: that shape
let a real DB connection sit checked out from the pool for up to N
sequential 10s-timeout HTTP calls (the exact QueuePool-exhaustion pattern
this repo already had one production incident over, PR #811), and never
committed its write -- `obtener_markup_pxq`'s `Depends(get_db)` session is
closed WITHOUT a commit (`app/core/database.py`'s `get_db`), so the fetched
value/stamp were discarded on every plain GET, making the 24h TTL a no-op
in production.

All tests run against a FAKE `MLWebhookClient` method -- the proxy route
`GET /api/shipping/seller-cost` does not exist in production yet, so a
None-returning fake IS today's real-world response, not a stand-in for a
hypothetical. `tests/conftest.py`'s autouse guard already pins the
singleton's method to `None` for every test in the suite; the tests below
that need a SUCCESSFUL fetch re-patch it locally, same as every other file
already doing this (`test_pxq_sync_logging.py`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import pxq_markup_service
from app.services.pxq_markup_service import markup_for_tiers, refresh_stale_tier_shipping


# ── Fixtures shared with test_pxq_markup_service.py's conventions ─────────


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


def _make_tier(db, publicacion, pxq_user, *, fetched_at=None, costo_envio_total=None, commit=False):
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
    if commit:
        db.commit()
    else:
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
    monkeypatch.setattr(pxq_markup_service, "ml_webhook_client", fake)


# ── get_background_db doubles, same convention as test_pxq_router_live_endpoint.py ──


class _RealDbCM:
    """Wraps the REAL test `db` fixture session -- used only for tests that
    don't care about cross-session commit durability (TTL gating, D6
    isolation), matching `test_pxq_router_live_endpoint.py`'s own
    `_RealDbCM`. `refresh_stale_tier_shipping` opens TWO of these per call
    (phase a, phase c); this double answers BOTH with the same session,
    which is fine for these tests since none of them assert on genuine
    cross-session persistence -- that is `TestRealPersistenceAcrossASession`
    below, which uses a completely separate, engine-bound sessionmaker
    instead."""

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        # The real `get_background_db` commits on a clean exit; this double
        # reuses the fixture's own session across BOTH of
        # `refresh_stale_tier_shipping`'s phases, so a flush (not a full
        # commit -- that would desync the fixture's SAVEPOINT bookkeeping,
        # see `tests/conftest.py`'s `db` fixture) is what makes phase (c)'s
        # write visible to a subsequent `db.refresh(tier)` in the SAME test.
        self._db.flush()
        return False


def _install_real_db_double(monkeypatch: pytest.MonkeyPatch, db) -> None:
    monkeypatch.setattr(pxq_markup_service, "get_background_db", _RealDbCM(db))


class TestTtlGating:
    def test_fresh_stamp_2h_old_makes_zero_proxy_calls(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=1)
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=2)
        tier = _make_tier(db, pub, pxq_user, fetched_at=fetched_at, costo_envio_total="200.00")
        fake = _FakeClient(amount=999.0)
        _install_fake_client(monkeypatch, fake)
        _install_real_db_double(monkeypatch, db)

        refresh_stale_tier_shipping(pub.mla)

        assert fake.calls == []
        assert tier.costo_envio_total == Decimal("200.00")

    def test_stale_stamp_25h_old_calls_the_proxy(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=2)
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=25)
        tier = _make_tier(db, pub, pxq_user, fetched_at=fetched_at, costo_envio_total="200.00")
        fake = _FakeClient(amount=333.0)
        _install_fake_client(monkeypatch, fake)
        _install_real_db_double(monkeypatch, db)

        refresh_stale_tier_shipping(pub.mla)

        assert len(fake.calls) == 1
        db.refresh(tier)
        assert tier.costo_envio_total == Decimal("333.0")
        assert tier.costo_envio_fetched_at is not None

    def test_null_stamp_never_fetched_calls_the_proxy(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=3)
        tier = _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=42.0)
        _install_fake_client(monkeypatch, fake)
        _install_real_db_double(monkeypatch, db)

        refresh_stale_tier_shipping(pub.mla)

        assert len(fake.calls) == 1
        db.refresh(tier)
        assert tier.costo_envio_total == Decimal("42.0")

    def test_three_reopens_within_1h_of_a_10min_old_fetch_make_zero_additional_calls(
        self, db, pxq_user, comision_fixtures, monkeypatch
    ) -> None:
        pub = _make_publicacion(db, item_id_suffix=4)
        fetched_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        tier = _make_tier(db, pub, pxq_user, fetched_at=fetched_at, costo_envio_total="150.00")
        fake = _FakeClient(amount=777.0)
        _install_fake_client(monkeypatch, fake)
        _install_real_db_double(monkeypatch, db)

        for _ in range(3):
            refresh_stale_tier_shipping(pub.mla)

        assert fake.calls == []
        assert tier.costo_envio_total == Decimal("150.00")


class TestFailedFetchTouchesNothing:
    def test_none_response_leaves_both_columns_untouched(self, db, pxq_user, comision_fixtures, monkeypatch) -> None:
        pub = _make_publicacion(db, item_id_suffix=5)
        tier = _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=None)
        _install_fake_client(monkeypatch, fake)
        _install_real_db_double(monkeypatch, db)

        refresh_stale_tier_shipping(pub.mla)

        assert len(fake.calls) == 1
        assert tier.costo_envio_total is None
        assert tier.costo_envio_fetched_at is None


class TestWiredIntoMarkupReadPath:
    def test_calling_refresh_then_markup_for_tiers_reflects_the_fetch(
        self, db, pxq_user, comision_fixtures, monkeypatch
    ) -> None:
        pub = _make_publicacion(db, item_id_suffix=6)
        tier = _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=250.0)
        _install_fake_client(monkeypatch, fake)
        _install_real_db_double(monkeypatch, db)

        refresh_stale_tier_shipping(pub.mla)
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
        _install_real_db_double(monkeypatch, db)

        refresh_stale_tier_shipping(pub.mla)
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
        _install_real_db_double(monkeypatch, db)

        refresh_stale_tier_shipping(pub.mla)
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


class TestPoolSafety:
    """Direct proof of the fix: the session used to identify stale tiers is
    CLOSED before the proxy fetch starts -- same technique
    `test_pxq_router_live_endpoint.py::test_session_closes_before_the_proxy_call`
    uses for `GET /{item_id}/live`."""

    def test_read_session_closes_before_any_proxy_call_starts(self, monkeypatch) -> None:
        call_order: list[str] = []

        class _StaleRow:
            id = 1
            item_id = "MLA1"
            cantidad_minima = 10
            precio_unitario = Decimal("500.00")
            costo_envio_fetched_at = None

        class _SpyDb:
            def query(self, *a, **k):
                return self

            def filter(self, *a, **k):
                return self

            def all(self):
                return [_StaleRow()]

        class _ReadCM:
            def __enter__(self):
                return _SpyDb()

            def __exit__(self, *exc):
                call_order.append("read_session_closed")
                return False

        class _WriteCM:
            def __enter__(self):
                call_order.append("write_session_opened")
                return _SpyDb()

            def __exit__(self, *exc):
                return False

        cm_sequence = iter([_ReadCM(), _WriteCM()])
        monkeypatch.setattr(pxq_markup_service, "get_background_db", lambda: next(cm_sequence))

        class _ProxyFake:
            async def get_pxq_seller_shipping_cost(self, item_id, quantity, tier_price):
                call_order.append("proxy_call")
                return 111.0

        monkeypatch.setattr(pxq_markup_service, "ml_webhook_client", _ProxyFake())
        # No tier_id=1 to find in the write phase's fake db.get -- patch it out.
        monkeypatch.setattr(_SpyDb, "get", lambda self, model, pk: None, raising=False)

        refresh_stale_tier_shipping("MLA1")

        assert call_order == ["read_session_closed", "proxy_call", "write_session_opened"]


class TestD6CommitOrderInvariant:
    """The caller's OWN session must see NO commits caused by
    `refresh_stale_tier_shipping` -- it must use entirely separate session
    objects. Proven directly: install a commit spy on the caller `db`
    fixture (same technique as
    `test_ml_pxq_write_service.py::TestAuditOrderAndFailureIsolation
    ::test_business_commit_happens_before_any_audit_write`), call the
    refresh with a REAL fetch that would persist a value, and assert the
    spy was never triggered."""

    def test_caller_session_commit_is_never_called_by_the_refresh(
        self, db, pxq_user, comision_fixtures, monkeypatch
    ) -> None:
        pub = _make_publicacion(db, item_id_suffix=9)
        _make_tier(db, pub, pxq_user, fetched_at=None, costo_envio_total=None)
        fake = _FakeClient(amount=55.0)
        _install_fake_client(monkeypatch, fake)
        # Deliberately NOT installing `_install_real_db_double` here --
        # `refresh_stale_tier_shipping` must reach for the REAL
        # `get_background_db` (its own sessions, bound to the same engine
        # for this test's sqlite setup) rather than the fixture's `db`.
        from unittest.mock import MagicMock

        commit_spy = MagicMock(wraps=db.commit)
        monkeypatch.setattr(db, "commit", commit_spy)

        refresh_stale_tier_shipping(pub.mla)

        assert commit_spy.call_count == 0


class TestRealPersistenceAcrossASession:
    """Proves the fetched value/stamp are DURABLY committed -- visible from
    a GENUINELY NEW `Session`, not just a flushed attribute on the object
    the test happens to still be holding. This is what `db.flush()`
    (slice B's first, buggy design) could never prove: `get_db`
    (`app/core/database.py`) closes WITHOUT a commit, so a flush-only write
    is invisible outside the request that made it, exactly like a value
    that never touched `costo_envio_fetched_at` at all.

    Uses a completely separate `sessionmaker` bound to the SAME `engine`
    fixture as the ordinary `db` fixture (StaticPool -> same physical
    SQLite connection), and never touches the `db` fixture in this test at
    all, so there is no SAVEPOINT-nesting interaction to reason about.
    """

    def test_value_and_stamp_survive_in_a_brand_new_session(self, engine, monkeypatch) -> None:
        # Deliberately NOT using the `db`/`rol_ventas` fixtures: those pull
        # in `tests/conftest.py`'s SAVEPOINT-wrapped `db` fixture, bound to
        # the SAME physical connection (StaticPool) this test's raw
        # `sessionmaker(bind=engine)` sessions also use. A real `.commit()`
        # on one of THIS test's sessions would end the underlying DBAPI
        # transaction the `db` fixture's SAVEPOINT stack is nested inside
        # and corrupt its teardown. This test builds its own `Rol` row
        # instead, entirely outside that machinery.
        from app.models.rol import Rol

        Session = sessionmaker(bind=engine)

        setup = Session()
        try:
            rol = Rol(codigo="VENTAS_PERSIST", nombre="Ventas Persist", es_sistema=False, orden=99, activo=True)
            setup.add(rol)
            setup.flush()
            user = Usuario(
                username="pxq_persist_user",
                email="pxq_persist_user@example.com",
                nombre="PxQ Persist User",
                password_hash=get_password_hash("TestPass123!"),
                rol=RolUsuario.VENTAS,
                rol_id=rol.id,
                auth_provider=AuthProvider.LOCAL,
                activo=True,
            )
            setup.add(user)
            setup.flush()
            producto = ProductoERP(
                item_id=93999,
                codigo="SKU-PXQ-PERSIST",
                descripcion="Producto PxQ persist",
                costo=1000.0,
                moneda_costo="ARS",
                iva=21.0,
            )
            setup.add(producto)
            setup.flush()
            pub = PublicacionML(mla="MLA9399901", item_id=producto.item_id, codigo=producto.codigo, pricelist_id=4)
            setup.add(pub)
            setup.flush()
            tier = MlPxqTier(
                publicacion_ml_id=pub.id,
                item_id=pub.mla,
                cantidad_minima=10,
                precio_unitario=Decimal("500.00"),
                costo_envio_total=None,
                costo_envio_fetched_at=None,
                usuario_id=user.id,
            )
            setup.add(tier)
            setup.commit()
            tier_id = tier.id
        finally:
            setup.close()
        # First session is FULLY closed -- nothing left checked out.

        fake = _FakeClient(amount=321.5)
        _install_fake_client(monkeypatch, fake)
        # `get_background_db` is left as the REAL production function --
        # it uses `app.core.database.SessionLocal`, which is bound to the
        # test-run's `DATABASE_URL` env var, NOT this test's `engine`
        # fixture. Point it at THIS test's engine instead, so the refresh's
        # own short sessions land in the same physical DB `setup`/`verify`
        # use.
        from contextlib import contextmanager

        @contextmanager
        def _engine_bound_background_db():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr(pxq_markup_service, "get_background_db", _engine_bound_background_db)

        refresh_stale_tier_shipping("MLA9399901")

        assert len(fake.calls) == 1

        # A THIRD, brand-new session -- proves durability, not object state.
        verify = Session()
        try:
            reread = verify.get(MlPxqTier, tier_id)
            assert reread is not None
            assert reread.costo_envio_total == Decimal("321.5")
            assert reread.costo_envio_fetched_at is not None
        finally:
            verify.close()
