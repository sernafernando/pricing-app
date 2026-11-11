"""Auth must not block the event loop when the DB pool is busy (incident 2026-11-11).

``get_current_user`` used to be ``async def`` doing synchronous SQLAlchemy I/O, so it ran
on the event loop. With the pool exhausted, its connection checkout blocked the whole
uvicorn worker for up to ``pool_timeout`` per queued request: ``/health`` (no DB) stopped
answering and requests that already held a connection could not finish, holding it longer.

Real uvicorn (one worker) against real PostgreSQL, with a tiny pool: two slow requests
hold every pooled connection, a burst of authenticated GETs queues on the pool, and
``/health`` must still answer at once.
"""

from __future__ import annotations

import inspect
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import Table, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_current_user
from app.core.database import Base, get_async_db, get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.notificacion import Notificacion
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.models.usuario_rol_adicional import UsuarioRolAdicional
from tests.conftest import (
    POSTGRES_TEST_URL,
    _patch_pg_types_for_sqlite,
    _postgres_reachable,
    _restore_pristine_pg_types,
)

pytestmark = pytest.mark.postgres

POOL_SIZE = 2
POOL_TIMEOUT_S = 3
SLOW_HOLD_S = 6
BURST = 4
HEALTH_LIMIT_S = 1.0


def _fk_closure(*roots: Table) -> list[Table]:
    seen: dict[str, Table] = {}

    def walk(table: Table) -> None:
        if table.name in seen:
            return
        seen[table.name] = table
        for fk in table.foreign_keys:
            walk(fk.column.table)

    for root in roots:
        walk(root)
    return list(seen.values())


@pytest.fixture(scope="module")
def pg_schema() -> Iterator:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    tables = _fk_closure(
        Notificacion.__table__,
        Usuario.__table__,
        Rol.__table__,
        Permiso.__table__,
        RolPermisoBase.__table__,
        UsuarioPermisoOverride.__table__,
        UsuarioRolAdicional.__table__,
    )
    _restore_pristine_pg_types(tables)
    admin = create_engine(POSTGRES_TEST_URL)
    Base.metadata.drop_all(bind=admin, tables=tables)
    Base.metadata.create_all(bind=admin, tables=tables)
    _patch_pg_types_for_sqlite()
    yield admin
    Base.metadata.drop_all(bind=admin, tables=tables)
    admin.dispose()


@pytest.fixture()
def usernames(pg_schema) -> Iterator[list[str]]:
    with Session(pg_schema) as s:
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=True, orden=10, activo=True)
        s.add(rol)
        s.flush()
        names = [f"loop_u{i}" for i in range(POOL_SIZE + BURST)]
        s.add_all(
            Usuario(
                username=name,
                email=f"{name}@example.com",
                nombre=name,
                password_hash=get_password_hash("TestPass123!"),
                rol=RolUsuario.VENTAS,
                rol_id=rol.id,
                auth_provider=AuthProvider.LOCAL,
                activo=True,
            )
            for name in names
        )
        s.commit()
    yield names
    with Session(pg_schema) as s:
        s.query(Usuario).delete()
        s.query(Rol).delete()
        s.commit()


def _slow_router() -> APIRouter:
    router = APIRouter()

    @router.get("/__auth_loop_test/slow")
    def _slow(db: Session = Depends(get_db), _user: Usuario = Depends(get_current_user)) -> dict[str, bool]:
        db.execute(text("SELECT 1"))  # the endpoint session now holds a pooled connection
        time.sleep(SLOW_HOLD_S)  # stands for a slow sync call (e.g. HTTP) made while holding it
        return {"ok": True}

    return router


@pytest.fixture()
def live_server(pg_schema) -> Iterator[str]:
    """One real uvicorn worker on a small pool, wired like production (get_db + get_async_db)."""
    engine = create_engine(POSTGRES_TEST_URL, pool_size=POOL_SIZE, max_overflow=0, pool_timeout=POOL_TIMEOUT_S)
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _get_db() -> Iterator[Session]:
        db = local()
        try:
            yield db
        finally:
            db.close()

    async def _get_async_db() -> Iterator[Session]:
        db = local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_async_db] = _get_async_db
    n_routes = len(app.router.routes)
    app.include_router(_slow_router())

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)
        del app.router.routes[n_routes:]
        app.dependency_overrides.clear()
        engine.dispose()


def test_busy_pool_does_not_freeze_event_loop(live_server: str, usernames: list[str]) -> None:
    results: dict[str, list[tuple[int | str, float]]] = {"slow": [], "burst": [], "warmup": []}

    def call(kind: str, path: str, username: str) -> None:
        headers = {"Authorization": f"Bearer {create_access_token(data={'sub': username})}"}
        start = time.monotonic()
        try:
            code: int | str = httpx.get(live_server + path, headers=headers, timeout=60).status_code
        except httpx.HTTPError as exc:
            code = type(exc).__name__
        results[kind].append((code, round(time.monotonic() - start, 2)))

    # Warm-up with a free pool: FastAPI builds each route's state lazily on its first
    # match (CPU on the event loop); a running prod worker has paid that already.
    httpx.get(live_server + "/__auth_loop_test/missing", timeout=60)  # unmatched: walks every route
    call("warmup", "/api/notificaciones/stats", usernames[0])
    assert results.pop("warmup")[0][0] == 200

    holders = [
        threading.Thread(target=call, args=("slow", "/__auth_loop_test/slow", usernames[i])) for i in range(POOL_SIZE)
    ]
    for t in holders:
        t.start()
    time.sleep(1.0)  # both pooled connections are now held by the slow endpoints
    burst = [
        threading.Thread(target=call, args=("burst", "/api/notificaciones/stats", usernames[POOL_SIZE + i]))
        for i in range(BURST)
    ]
    for t in burst:
        t.start()
    time.sleep(0.3)  # the burst is now waiting on the pool

    start = time.monotonic()
    try:
        health_code: int | str = httpx.get(live_server + "/health", timeout=30).status_code
    except httpx.HTTPError as exc:
        health_code = type(exc).__name__
    health_s = time.monotonic() - start
    for t in holders + burst:
        t.join(timeout=90)

    print(f"health={health_code} in {health_s:.2f}s slow={results['slow']} burst={results['burst']}")
    assert health_code == 200
    assert health_s < HEALTH_LIMIT_S
    # The slow requests already had their connection: a free loop lets them finish on time.
    assert [code for code, _ in results["slow"]] == [200] * POOL_SIZE
    assert all(elapsed < SLOW_HOLD_S + 2 for _, elapsed in results["slow"])


# ---------------------------------------------------------------------------
# Behaviour kept: same users, same 401/403 codes, now plain sync callables
# ---------------------------------------------------------------------------


@pytest.fixture()
def people(pg_schema) -> Iterator[tuple[Session, dict[str, Usuario]]]:
    s = Session(pg_schema)
    ventas_rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=True, orden=10, activo=True)
    admin_rol = Rol(codigo="ADMIN", nombre="Admin", es_sistema=True, orden=1, activo=True)
    s.add_all([ventas_rol, admin_rol])
    s.flush()

    def user(name: str, rol: Rol, rol_enum: RolUsuario, *, activo: bool = True) -> Usuario:
        u = Usuario(
            username=name,
            email=f"{name}@example.com",
            nombre=name,
            password_hash=get_password_hash("TestPass123!"),
            rol=rol_enum,
            rol_id=rol.id,
            auth_provider=AuthProvider.LOCAL,
            activo=activo,
        )
        s.add(u)
        return u

    people = {
        "ventas": user("auth_ventas", ventas_rol, RolUsuario.VENTAS),
        "inactivo": user("auth_inactivo", ventas_rol, RolUsuario.VENTAS, activo=False),
        "admin": user("auth_admin", admin_rol, RolUsuario.ADMIN),
    }
    s.commit()
    yield s, people
    s.rollback()
    s.query(Usuario).delete()
    s.query(Rol).delete()
    s.commit()
    s.close()


def _creds(username: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_access_token(data={"sub": username}))


def _request(host: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": (host, 1234)})


def _raises(status: int, code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(HTTPException) as exc:
        fn(*args, **kwargs)
    assert exc.value.status_code == status
    assert exc.value.detail["code"] == code


def test_auth_dependencies_are_plain_sync_callables() -> None:
    from app.api import deps

    for dep in (
        deps.get_current_user,
        deps.get_current_user_transient,
        deps.get_current_admin,
        deps.get_current_pricing_manager,
        deps.get_user_or_localhost,
        deps.get_admin_or_localhost,
        deps.require_role([RolUsuario.ADMIN]),
        deps.require_permiso("x.y"),
        deps.require_algun_permiso(["x.y"]),
    ):
        assert not inspect.iscoroutinefunction(dep), dep


def test_get_current_user_keeps_user_and_401s(people) -> None:
    s, users = people
    got = get_current_user(credentials=_creds("auth_ventas"), db=s)
    assert got.id == users["ventas"].id
    assert got.username == "auth_ventas"
    garbage = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
    _raises(401, "INVALID_TOKEN", get_current_user, credentials=garbage, db=s)
    _raises(401, "INVALID_TOKEN", get_current_user, credentials=_creds("nobody"), db=s)
    _raises(401, "INACTIVE_USER", get_current_user, credentials=_creds("auth_inactivo"), db=s)


def test_role_dependencies_keep_403(people) -> None:
    from app.api.deps import get_current_admin, get_current_pricing_manager, require_role

    _, users = people
    assert get_current_admin(current_user=users["admin"]) is users["admin"]
    _raises(403, "INSUFFICIENT_PERMISSIONS", get_current_admin, current_user=users["ventas"])
    # Pre-existing on main and unused: RolUsuario has no PRICING_MANAGER, so every
    # call raises AttributeError (500). Unchanged here; pinned so a fix is deliberate.
    for who in ("admin", "ventas"):
        with pytest.raises(AttributeError):
            get_current_pricing_manager(current_user=users[who])
    checker = require_role([RolUsuario.ADMIN])
    assert checker(current_user=users["admin"]) is users["admin"]
    _raises(403, "INSUFFICIENT_PERMISSIONS", checker, current_user=users["ventas"])


def test_localhost_dependencies_keep_behaviour(people) -> None:
    from app.api.deps import get_admin_or_localhost, get_user_or_localhost

    s, users = people
    assert get_user_or_localhost(_request("127.0.0.1"), None, s) is None
    assert get_user_or_localhost(_request("127.0.0.1"), _creds("auth_ventas"), s).id == users["ventas"].id
    _raises(401, "MISSING_TOKEN", get_user_or_localhost, _request("10.1.2.3"), None, s)
    _raises(401, "INACTIVE_USER", get_user_or_localhost, _request("10.1.2.3"), _creds("auth_inactivo"), s)
    assert get_user_or_localhost(_request("10.1.2.3"), _creds("auth_ventas"), s).id == users["ventas"].id
    assert get_admin_or_localhost(_request("127.0.0.1"), None, s) is None
    _raises(401, "MISSING_TOKEN", get_admin_or_localhost, _request("10.1.2.3"), None, s)
    _raises(403, "INSUFFICIENT_PERMISSIONS", get_admin_or_localhost, _request("10.1.2.3"), _creds("auth_ventas"), s)
    assert get_admin_or_localhost(_request("10.1.2.3"), _creds("auth_admin"), s).id == users["admin"].id
