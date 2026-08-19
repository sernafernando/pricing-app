"""
Shared test fixtures for the Pricing App backend.

Provides:
- In-memory SQLite database with all tables created.
- FastAPI TestClient wired to the test DB.
- Helper fixtures to create users and obtain auth tokens.

Usage:
    def test_something(client, auth_headers):
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
"""

import os
import re
from contextlib import contextmanager

# Must be set before `from app.main import app` below, since app.core.rate_limit
# reads RATE_LIMIT_STORAGE_URI at import time (design §9). Tests never hit a
# real Redis; in-memory storage keeps limiter tests deterministic and isolated.
os.environ.setdefault("RATE_LIMIT_STORAGE_URI", "memory://")
from datetime import date
from typing import Optional

import fakeredis
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, BigInteger, Integer, JSON, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from pgvector.sqlalchemy import Vector

from app.core.database import Base, get_async_db, get_db
from app.core.security import get_password_hash, create_access_token, create_refresh_token
from app.core import token_revocation
from app.main import app
from app.models.rma_caso import RmaCaso
from app.models.rma_caso_historial import RmaCasoHistorial
from app.models.rma_caso_item import RmaCasoItem
from app.models.rma_seguimiento_opcion import RmaSeguimientoOpcion
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.models.rol import Rol
from app.models.ml_bot_answer_history import MlBotAnswerHistory  # noqa: F401 — registers table for create_all
from app.models.precio_gremio_override import PrecioGremioOverride  # noqa: F401 — registers table for create_all

# ---------------------------------------------------------------------------
# Token revocation test seam
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fake_revocation_redis():
    """Back the token denylist with an in-memory fakeredis for every test.

    Raw redis-py can't use memory:// (that's a limits-lib scheme used by the
    rate limiter), so we inject a FakeRedis instead. Fresh instance per test
    => no cross-test leakage of revoked jtis. Reset to None afterwards so
    nothing holds a stale client.
    """
    fake = fakeredis.FakeStrictRedis()
    token_revocation._set_client_for_tests(fake)
    yield fake
    token_revocation._set_client_for_tests(None)


@pytest.fixture(autouse=True)
def _no_pxq_shipping_proxy(monkeypatch):
    """Pin the PxQ shipping auto-fetch to the proxy-absent contract for every
    test.

    Slice B wired `refresh_tier_shipping` into the markup read path, and any
    `MlPxqTier` built straight through the ORM has `costo_envio_fetched_at`
    NULL -- which triggers one REAL outbound call to the ml-webhook proxy per
    tier. Today that host answers 404 and the client collapses it to `None`,
    so everything "passes" while silently depending on the network. Pin the
    singleton's method to `None` (identical to today's production reality)
    instead; tests that exercise the fetch itself re-patch it locally.
    """
    from unittest.mock import AsyncMock

    from app.services import pxq_markup_service

    monkeypatch.setattr(
        pxq_markup_service.ml_webhook_client,
        "get_pxq_seller_shipping_cost",
        AsyncMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite://"  # in-memory

# Map PostgreSQL-specific types to SQLite-compatible equivalents
_PG_TYPE_MAP = {
    JSONB: lambda: JSON(),
    PG_UUID: lambda: String(36),
    # pgvector's `Vector(dim)` compiles to a Postgres-only `VECTOR(n)` column
    # type with no SQLite equivalent; remap to JSON so the test DB can build
    # the table and round-trip a plain list[float] (ml-bot-dynamic-fewshot).
    # `none_as_null=True` is required so a Python `None` binds as real SQL
    # NULL (and trips a NOT NULL constraint) instead of JSON's default
    # behavior of storing the JSON "null" literal, which would silently
    # satisfy a NOT NULL column.
    Vector: lambda: JSON(none_as_null=True),
}

# Snapshot of the real PostgreSQL column types, captured at import time —
# i.e. before any fixture (including the SQLite `engine` fixture below) has
# a chance to mutate `Base.metadata` in place via `_patch_pg_types_for_sqlite`.
# `Column` objects override `__eq__` to build SQL expressions, not booleans,
# but dict/set membership still works correctly here: CPython's dict lookup
# short-circuits on `is` (identity) before ever calling `__eq__`, and every
# key here is the exact same Column object being looked up later.
#
# Postgres-only session fixtures (`pg_tickets_engine`, ...) call
# `_restore_pristine_pg_types()` on their own tables right before building
# DDL, so the DDL they create always matches production — regardless of
# whether the SQLite fixture already patched the same shared Column objects
# earlier in this test session. Without this, a full-suite run and an
# isolated single-file run of the same `@pytest.mark.postgres` test can see
# two different column types (e.g. JSONB vs plain JSON) depending on
# fixture execution order — a real bug caught in tickets-ai-triage PR 2b's
# `valor_propuesto` JSONB round-trip test.
_PRISTINE_PG_COLUMN_TYPES = {
    column: column.type
    for table in Base.metadata.tables.values()
    for column in table.columns
    if isinstance(column.type, tuple(_PG_TYPE_MAP.keys()))
}


def _restore_pristine_pg_types(tables) -> None:
    """Force real PostgreSQL types back onto `tables`' columns before a
    Postgres-only fixture builds DDL from them, undoing
    `_patch_pg_types_for_sqlite()` for just those columns."""
    for table in tables:
        for column in table.columns:
            if column in _PRISTINE_PG_COLUMN_TYPES:
                column.type = _PRISTINE_PG_COLUMN_TYPES[column]


def _patch_pg_types_for_sqlite() -> None:
    """Replace PostgreSQL-only column types with SQLite equivalents in metadata.

    Also downgrades `BigInteger` PK columns to `Integer` so that SQLite's
    AUTOINCREMENT behaviour kicks in — SQLite only autoincrements INTEGER PKs,
    so tables whose IDs are declared as BigInteger (e.g. imputaciones,
    cc_proveedor_movimientos) fail with `NOT NULL constraint failed: <tbl>.id`
    at INSERT time. This mirrors the existing JSONB/UUID remapping pattern.
    """
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for pg_type, factory in _PG_TYPE_MAP.items():
                if isinstance(column.type, pg_type):
                    column.type = factory()
                    break
            # BigInteger PKs → Integer under SQLite so autoincrement works.
            if column.primary_key and isinstance(column.type, BigInteger):
                column.type = Integer()


@pytest.fixture(scope="session")
def engine():
    """Create a single in-memory engine for the whole test session."""
    eng = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable FK support for SQLite
    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _patch_pg_types_for_sqlite()
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture()
def db(engine):
    """Provide a transactional database session that rolls back after each test.

    Wraps every test in a SAVEPOINT (the standard SQLAlchemy "join a Session
    into an external transaction" recipe) and auto-restarts a fresh SAVEPOINT
    after each `session.commit()`/`session.rollback()`. Without this, a plain
    `db.rollback()` called by application code under test (e.g. an
    IntegrityError handler) cascades past any SAVEPOINT to the true root of
    the connection's transaction, silently wiping out ALL prior test fixture
    data — not just the failed operation's own pending changes. This makes
    application-level rollback paths correctly test-isolated: a rollback
    inside the code under test only undoes that operation, exactly as it
    would against a real per-request session in production.
    """
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    # Standard SQLAlchemy "join a Session into an external transaction"
    # recipe: SAVEPOINT at the CONNECTION level, restarted after each one
    # ends. Tracked in an outer-scope list (not a plain closure variable)
    # so the `after_transaction_end` listener can rebind it.
    nested = [connection.begin_nested()]

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        if not nested[0].is_active:
            nested[0] = connection.begin_nested()

    _ensure_global_equipo(session)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def _ensure_global_equipo(session) -> None:
    """Seeds the singleton global ("U") `Equipo` row for every test.

    Production DBs get this row from the productos-color-teams migration
    backfill (PR1). Read-side helpers (`resolver_layer_activo`,
    `get_global_equipo_id`) hard-require it to exist, so tests that never
    touch the color-teams feature explicitly still need it present —
    otherwise any read that resolves the default color layer 500s.
    """
    from app.models.equipo import Equipo

    if session.query(Equipo).filter(Equipo.es_global.is_(True)).first() is None:
        session.add(Equipo(nombre="Global", es_global=True))
        session.flush()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the login rate limiter's in-memory counters before/after each test.

    `memory://` storage (see RATE_LIMIT_STORAGE_URI above) persists across
    tests within the same process, so without this reset, login attempts made
    by one test file (e.g. test_login_rate_limit.py) leak quota into any other
    test that also calls POST /api/auth/login (test_auth_flows.py,
    test_error_contract.py), causing flaky 429s unrelated to what's being
    tested. Function-scoped + autouse so no test file needs to opt in.
    """
    app.state.limiter.reset()
    yield
    app.state.limiter.reset()


@pytest.fixture()
def client(db):
    """FastAPI TestClient using the test database session."""

    def _override_get_db():
        yield db

    async def _override_get_async_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_async_db] = _override_get_async_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Query counting fixture (shared across suites)
# ---------------------------------------------------------------------------


class _QueryCounter:
    """Records SQL statements executed on a connection during a `with` block."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def total(self) -> int:
        return len(self.statements)

    def matching(self, needle: str) -> int:
        """Count executed statements that SELECT/JOIN the table named `needle`.

        Uses a precise `\\b(from|join)\\s+<table>\\b` regex instead of a bare
        substring match. A plain substring match over-counts: e.g. matching
        "offsets_ganancia" against raw SQL text would also match unrelated
        occurrences (column names, other tables sharing a prefix, etc.), which
        silently pads the observed count and can mask the difference between
        "genuinely bounded" and "grows with N" queries. Requiring the table
        name to appear right after `FROM`/`JOIN` (word-bounded) ties the count
        to actual query targets against that table.
        """
        pattern = re.compile(rf"\b(from|join)\s+{re.escape(needle.lower())}\b")
        return sum(1 for s in self.statements if pattern.search(s))


# ---------------------------------------------------------------------------
# PostgreSQL fixtures (productos-costo-ppp perf round — LATERAL resolver)
# ---------------------------------------------------------------------------
#
# The PPP resolver (`app.services.costo_ppp_service.resolver_ppp_batch`) uses
# a PostgreSQL-only LATERAL join for its fast path (see that module's
# docstring for the production EXPLAIN ANALYZE numbers). Tests that must
# prove that exact path — not the portable SQLite ROW_NUMBER() fallback —
# are marked `@pytest.mark.postgres` and use the fixtures below instead of
# the SQLite-backed `db`/`engine` fixtures used by the rest of the suite.
#
# CI runs a `postgres` service for the backend test job (see
# .github/workflows/ci.yml) and points POSTGRES_TEST_URL at it. Locally, a
# developer with no PostgreSQL running simply gets these tests skipped with
# a clear message — the rest of the suite (~3700 tests) is unaffected and
# keeps running on the in-memory SQLite `db` fixture above.

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL", "postgresql+psycopg2://postgres@localhost:5432/pricing_test")


def _postgres_reachable() -> bool:
    try:
        probe_engine = create_engine(POSTGRES_TEST_URL)
        with probe_engine.connect():
            pass
        probe_engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped PostgreSQL engine with only `tb_item_transactions` created.

    Only the one table the PPP resolver needs is created (not the full
    `Base.metadata`, which includes pgvector/JSONB tables requiring
    extensions this test DB doesn't need to have installed).
    """
    if not _postgres_reachable():
        pytest.skip(
            f"PostgreSQL not reachable at {POSTGRES_TEST_URL} — set POSTGRES_TEST_URL "
            "or start a local PostgreSQL to run @pytest.mark.postgres tests. "
            "CI provides this via the `postgres` service in .github/workflows/ci.yml."
        )

    eng = create_engine(POSTGRES_TEST_URL)
    from app.models.item_transaction import ItemTransaction

    ItemTransaction.__table__.create(bind=eng, checkfirst=True)
    yield eng
    ItemTransaction.__table__.drop(bind=eng, checkfirst=True)
    eng.dispose()


@pytest.fixture()
def pg_db(pg_engine):
    """Transactional PostgreSQL session, rolled back after each test."""
    connection = pg_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="session")
def pg_tickets_engine():
    """Session-scoped PostgreSQL engine with only the tables the tickets
    severidad/urgencia CHECK constraints (tickets-ai-triage PR 2a) and the
    `tickets_propuestas_ia` side table (PR 2b) need: roles, usuarios,
    tickets_sectores, tickets_workflows, tickets_estados, tickets_tipos,
    tickets, tickets_propuestas_ia.

    Deliberately ONE session-scoped engine for every tickets-related
    Postgres-only table, not one engine per PR slice: `tickets_propuestas_ia`
    has an FK to `tickets`, and two independent session-scoped engines each
    creating/dropping their own copy of `tickets` against the same physical
    `POSTGRES_TEST_URL` database race on teardown order — whichever engine
    drops `tickets` first fails with `DependentObjectsStillExist` if the
    other engine's FK-dependent table is still there.

    Not the full `Base.metadata` — same rationale as `pg_engine` above: that
    would also create pgvector-backed tables whose extension isn't installed
    on the CI postgres service.
    """
    if not _postgres_reachable():
        pytest.skip(
            f"PostgreSQL not reachable at {POSTGRES_TEST_URL} — set POSTGRES_TEST_URL "
            "or start a local PostgreSQL to run @pytest.mark.postgres tests. "
            "CI provides this via the `postgres` service in .github/workflows/ci.yml."
        )

    from app.models.rol import Rol as _Rol
    from app.tickets.models.propuesta_ia import PropuestaIA as _PropuestaIA
    from app.tickets.models.sector import Sector as _Sector
    from app.tickets.models.tipo_ticket import TipoTicket as _TipoTicket
    from app.tickets.models.ticket import Ticket as _Ticket
    from app.tickets.models.workflow import EstadoTicket as _EstadoTicket, Workflow as _Workflow

    tables = [
        _Rol.__table__,
        Usuario.__table__,
        _Sector.__table__,
        _Workflow.__table__,
        _EstadoTicket.__table__,
        _TipoTicket.__table__,
        _Ticket.__table__,
        _PropuestaIA.__table__,
    ]

    # `Ticket.campos_metadata` (JSONB) and `PropuestaIA.valor_propuesto`
    # (JSONB) / `.run_id` (UUID) are shared Column objects with the ORM
    # models used by the SQLite-backed `db` fixture. If that fixture's
    # `engine()` already ran in this test session, `_patch_pg_types_for_sqlite`
    # already rewrote those types to plain JSON/String for SQLite — restore
    # the real Postgres types just for building this engine's DDL, so this
    # fixture reproduces production's actual schema regardless of test
    # execution order.
    _restore_pristine_pg_types(tables)
    eng = create_engine(POSTGRES_TEST_URL)
    Base.metadata.create_all(bind=eng, tables=tables)
    # Leave the shared Column objects patched for SQLite again, in case the
    # `db` fixture is used by a later test in this same session.
    _patch_pg_types_for_sqlite()
    yield eng
    Base.metadata.drop_all(bind=eng, tables=tables)
    eng.dispose()


@pytest.fixture()
def pg_tickets_db(pg_tickets_engine):
    """Transactional PostgreSQL session (tickets + propuestas_ia tables), rolled back after each test."""
    connection = pg_tickets_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def query_counter(db):
    """
    Count SQL statements on the test connection.

    Usage:
        with query_counter() as counter:
            client.get("/api/offset-grupos-resumen", headers=auth_headers)
        assert counter.matching("offset_grupo_resumen") <= 1

    The listener is attached to `db.connection()`, the same connection the
    `client` fixture's `get_db` override yields, so it observes every query
    the endpoint runs during the request.
    """
    conn = db.connection()

    @contextmanager
    def _run():
        counter = _QueryCounter()

        def _listen(conn_inner, cursor, statement, parameters, context, executemany):
            counter.statements.append(statement.lower())

        sa.event.listen(conn, "before_cursor_execute", _listen)
        try:
            yield counter
        finally:
            sa.event.remove(conn, "before_cursor_execute", _listen)

    return _run


# ---------------------------------------------------------------------------
# User + Auth fixtures
# ---------------------------------------------------------------------------

TEST_PASSWORD = "TestPass123!"


@pytest.fixture()
def rol_admin(db) -> Rol:
    """Create the ADMIN role in test DB."""
    rol = Rol(codigo="ADMIN", nombre="Administrador", es_sistema=True, orden=1, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def rol_ventas(db) -> Rol:
    """Create the VENTAS role in test DB."""
    rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def active_user(db, rol_ventas) -> Usuario:
    """Create an active user with VENTAS role."""
    user = Usuario(
        username="testuser",
        email="test@example.com",
        nombre="Test User",
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def inactive_user(db, rol_ventas) -> Usuario:
    """Create an inactive (disabled) user."""
    user = Usuario(
        username="inactiveuser",
        email="inactive@example.com",
        nombre="Inactive User",
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=False,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def admin_user(db, rol_admin) -> Usuario:
    """Create an active admin user."""
    user = Usuario(
        username="adminuser",
        email="admin@example.com",
        nombre="Admin User",
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.ADMIN,
        rol_id=rol_admin.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def make_access_token(user: Usuario) -> str:
    """Helper: create a valid access token for a user."""
    return create_access_token(data={"sub": user.username})


def make_refresh_token(user: Usuario) -> str:
    """Helper: create a valid refresh token for a user."""
    return create_refresh_token(data={"sub": user.username})


@pytest.fixture()
def auth_headers(active_user) -> dict:
    """Authorization headers with a valid access token for the active_user."""
    token = make_access_token(active_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_auth_headers(admin_user) -> dict:
    """Authorization headers with a valid access token for the admin_user."""
    token = make_access_token(admin_user)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# RMA Stats fixtures (T-1)
# ---------------------------------------------------------------------------


@pytest.fixture()
def rma_superadmin_user(db) -> Usuario:
    """User with SUPERADMIN rol — bypasses all permission checks via es_superadmin shortcut."""
    user = Usuario(
        username="rma_superadmin",
        email="rma_super@test.com",
        nombre="RMA Superadmin",
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.SUPERADMIN,
        rol_id=None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def rma_no_ver_user(db, rol_ventas) -> Usuario:
    """User with VENTAS role and NO rma.ver permission (no permission rows seeded)."""
    user = Usuario(
        username="rma_nover",
        email="rma_nover@test.com",
        nombre="RMA No Ver",
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def rma_opcion_factory(db):
    """
    Factory to create RmaSeguimientoOpcion records.

    Usage:
        opc = rma_opcion_factory("estado_recepcion", "Recibido OK", orden=1, color="green")
    """
    _counter = [0]

    def factory(
        categoria: str,
        valor: str,
        orden: int = 0,
        color: Optional[str] = None,
    ) -> RmaSeguimientoOpcion:
        _counter[0] += 1
        opcion = RmaSeguimientoOpcion(
            categoria=categoria,
            valor=valor,
            orden=orden,
            color=color,
            activo=True,
        )
        db.add(opcion)
        db.flush()
        return opcion

    return factory


@pytest.fixture()
def rma_caso_factory(db):
    """
    Factory to create RmaCaso records.

    Usage:
        caso = rma_caso_factory(fecha_caso=date(2026, 1, 15), estado_caso_id=opc.id)
    """
    _counter = [0]

    def factory(
        activo: bool = True,
        fecha_caso: Optional[date] = None,
        estado_caso_id: Optional[int] = None,
    ) -> RmaCaso:
        _counter[0] += 1
        caso = RmaCaso(
            numero_caso=f"TEST-STATS-{_counter[0]:05d}",
            activo=activo,
            fecha_caso=fecha_caso,
            estado_caso_id=estado_caso_id,
            estado="abierto",
        )
        db.add(caso)
        db.flush()
        return caso

    return factory


@pytest.fixture()
def rma_item_factory(db):
    """
    Factory to create RmaCasoItem records.

    Usage:
        item = rma_item_factory(caso_id=caso.id, estado_recepcion_id=opc.id)
    """

    def factory(
        caso_id: int,
        recepcion_fecha=None,
        estado_recepcion_id: Optional[int] = None,
        causa_devolucion_id: Optional[int] = None,
        apto_venta_id: Optional[int] = None,
        estado_proceso_id: Optional[int] = None,
        estado_proveedor_id: Optional[int] = None,
        supp_id: Optional[int] = None,
        proveedor_nombre: Optional[str] = None,
        serial_number: Optional[str] = None,
        ean: Optional[str] = None,
        producto_desc: Optional[str] = None,
    ) -> RmaCasoItem:
        item = RmaCasoItem(
            caso_id=caso_id,
            recepcion_fecha=recepcion_fecha,
            estado_recepcion_id=estado_recepcion_id,
            causa_devolucion_id=causa_devolucion_id,
            apto_venta_id=apto_venta_id,
            estado_proceso_id=estado_proceso_id,
            estado_proveedor_id=estado_proveedor_id,
            supp_id=supp_id,
            proveedor_nombre=proveedor_nombre,
            serial_number=serial_number,
            ean=ean,
            producto_desc=producto_desc,
        )
        db.add(item)
        db.flush()
        return item

    return factory


@pytest.fixture()
def rma_historial_factory(db):
    """
    Factory to create RmaCasoHistorial records (status transition audit rows).

    Usage:
        rma_historial_factory(caso_id=1, caso_item_id=5, campo="estado_recepcion_id",
                               valor_nuevo="12", usuario_id=user.id)
    """

    def factory(
        caso_id: int,
        usuario_id: int,
        campo: str,
        valor_anterior: Optional[str] = None,
        valor_nuevo: Optional[str] = None,
        caso_item_id: Optional[int] = None,
    ) -> RmaCasoHistorial:
        historial = RmaCasoHistorial(
            caso_id=caso_id,
            caso_item_id=caso_item_id,
            campo=campo,
            valor_anterior=valor_anterior,
            valor_nuevo=valor_nuevo,
            usuario_id=usuario_id,
        )
        db.add(historial)
        db.flush()
        return historial

    return factory


# ---------------------------------------------------------------------------
# Offset factories (dashboard-batch-prefetch — shared by unit + integration tests)
# ---------------------------------------------------------------------------


@pytest.fixture()
def offset_grupo_factory(db):
    """Factory to create OffsetGrupo records."""
    from app.models.offset_grupo import OffsetGrupo

    _seq = [0]

    def factory(nombre: Optional[str] = None):
        _seq[0] += 1
        g = OffsetGrupo(nombre=nombre or f"Grupo {_seq[0]}")
        db.add(g)
        db.flush()
        return g

    return factory


@pytest.fixture()
def offset_ganancia_factory(db):
    """Factory to create OffsetGanancia records."""
    from app.models.offset_ganancia import OffsetGanancia

    def factory(
        *,
        grupo_id: Optional[int] = None,
        item_id: Optional[int] = None,
        max_unidades: Optional[int] = None,
        max_monto_usd: Optional[float] = None,
        tipo_offset: str = "monto_fijo",
        monto: float = 100.0,
        moneda: str = "ARS",
        fecha_desde: date = date(2026, 1, 1),
        **extra,
    ):
        o = OffsetGanancia(
            grupo_id=grupo_id,
            item_id=item_id,
            max_unidades=max_unidades,
            max_monto_usd=max_monto_usd,
            tipo_offset=tipo_offset,
            monto=monto,
            moneda=moneda,
            fecha_desde=fecha_desde,
            **extra,
        )
        db.add(o)
        db.flush()
        return o

    return factory


@pytest.fixture()
def offset_grupo_resumen_factory(db):
    """Factory to create OffsetGrupoResumen records."""
    from app.models.offset_grupo_consumo import OffsetGrupoResumen

    def factory(
        *,
        grupo_id: int,
        total_unidades: int = 0,
        total_monto_ars: float = 0,
        total_monto_usd: float = 0,
        cantidad_ventas: int = 0,
        limite_alcanzado: Optional[str] = None,
    ):
        r = OffsetGrupoResumen(
            grupo_id=grupo_id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=cantidad_ventas,
            limite_alcanzado=limite_alcanzado,
        )
        db.add(r)
        db.flush()
        return r

    return factory


@pytest.fixture()
def offset_individual_resumen_factory(db):
    """Factory to create OffsetIndividualResumen records."""
    from app.models.offset_individual_consumo import OffsetIndividualResumen

    def factory(
        *,
        offset_id: int,
        total_unidades: int = 0,
        total_monto_ars: float = 0,
        total_monto_usd: float = 0,
        cantidad_ventas: int = 0,
        limite_alcanzado: Optional[str] = None,
    ):
        r = OffsetIndividualResumen(
            offset_id=offset_id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=cantidad_ventas,
            limite_alcanzado=limite_alcanzado,
        )
        db.add(r)
        db.flush()
        return r

    return factory
