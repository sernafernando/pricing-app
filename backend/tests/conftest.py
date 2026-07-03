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

# Must be set before `from app.main import app` below, since app.core.rate_limit
# reads RATE_LIMIT_STORAGE_URI at import time (design §9). Tests never hit a
# real Redis; in-memory storage keeps limiter tests deterministic and isolated.
os.environ.setdefault("RATE_LIMIT_STORAGE_URI", "memory://")

from datetime import date
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, BigInteger, Integer, JSON, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from app.core.database import Base, get_async_db, get_db
from app.core.security import get_password_hash, create_access_token, create_refresh_token
from app.main import app
from app.models.rma_caso import RmaCaso
from app.models.rma_caso_historial import RmaCasoHistorial
from app.models.rma_caso_item import RmaCasoItem
from app.models.rma_seguimiento_opcion import RmaSeguimientoOpcion
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.models.rol import Rol

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite://"  # in-memory

# Map PostgreSQL-specific types to SQLite-compatible equivalents
_PG_TYPE_MAP = {
    JSONB: lambda: JSON(),
    PG_UUID: lambda: String(36),
}


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
    """Provide a transactional database session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


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
