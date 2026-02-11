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

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, JSON, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from app.core.database import Base, get_db
from app.core.security import get_password_hash, create_access_token, create_refresh_token
from app.main import app
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
    """Replace PostgreSQL-only column types with SQLite equivalents in metadata."""
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for pg_type, factory in _PG_TYPE_MAP.items():
                if isinstance(column.type, pg_type):
                    column.type = factory()
                    break


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


@pytest.fixture()
def client(db):
    """FastAPI TestClient using the test database session."""

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
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
