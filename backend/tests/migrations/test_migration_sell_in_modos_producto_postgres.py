"""Migration `20261227_sell_in_modos_producto`, its permissions: the owner asked for a separate permission per
choice ("con un permiso aparte se pueda elegir ponderar", "otro permiso aparte para poder setear cantidad y costo a
mano", "me pidieron que el último precio tenga un permiso diferente a ppp") and one more to backdate ("lo de la fecha
tendría que poder aplicarse para atrás, por lo menos con un permiso adicional"); all four for ADMIN only (owner,
2026-11-02). Upgrade, re-run and downgrade on a real Postgres, after the sell-in chain it builds on. The table itself
is proven by `tests/models/test_sell_in_schema_postgres.py`."""

from __future__ import annotations

from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text

from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from tests.models.test_sell_in_schema_postgres import _MIGRATIONS, _STUBS, _load_migration
from tests.services.sell._schema import throwaway_schema

# This revision by name: later ones are appended to the shared chain (20261105_tacticals, ...).
_PROPIA = next(path for path in _MIGRATIONS if "20261227_sell_in_modos_producto" in str(path))
_ANTERIORES = _MIGRATIONS[: _MIGRATIONS.index(_PROPIA)]
CODIGOS = ["sell_in.costo_manual", "sell_in.costo_ponderado", "sell_in.costo_retroactivo", "sell_in.costo_ultimo"]
_GRANTS = text("""
    SELECT p.codigo, r.codigo FROM roles_permisos_base rp
    JOIN roles r ON r.id = rp.rol_id JOIN permisos p ON p.id = rp.permiso_id
    WHERE p.codigo LIKE 'sell_in.costo_%' ORDER BY p.codigo, r.codigo
""")


def _step(engine: Engine, path, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_load_migration(path), step)()


def _before(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO roles (id, codigo, nombre, es_sistema, orden, activo)
                VALUES (1, 'ADMIN', 'Admin', true, 1, true), (2, 'PRICING', 'Pricing', false, 4, true)
            """)
        )
    for path in _ANTERIORES:
        _step(engine, path, "upgrade")


@pytest.fixture
def engine() -> Iterator[Engine]:
    tables = [Rol.__table__, Permiso.__table__, RolPermisoBase.__table__, UsuarioPermisoOverride.__table__]
    with throwaway_schema("sell_in_modos", tables, _STUBS, after=_before) as engine:
        yield engine


@pytest.mark.postgres
def test_upgrade_seeds_the_four_permissions_for_admin_only(engine: Engine) -> None:
    _step(engine, _PROPIA, "upgrade")

    with engine.connect() as conn:
        grants = conn.execute(_GRANTS).all()
        categorias = conn.execute(text("SELECT DISTINCT categoria FROM permisos")).scalars().all()

    assert [tuple(g) for g in grants] == [(codigo, "ADMIN") for codigo in CODIGOS]
    assert categorias == ["productos"]


@pytest.mark.postgres
def test_upgrade_twice_keeps_one_permission_and_grant_each(engine: Engine) -> None:
    _step(engine, _PROPIA, "upgrade")
    _step(engine, _PROPIA, "upgrade")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM permisos")).scalar_one() == 4
        assert len(conn.execute(_GRANTS).all()) == 4


@pytest.mark.postgres
def test_downgrade_removes_the_permissions_their_grants_and_overrides(engine: Engine) -> None:
    _step(engine, _PROPIA, "upgrade")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) "
                "SELECT 7, id, true FROM permisos WHERE codigo = 'sell_in.costo_manual'"
            )
        )

    _step(engine, _PROPIA, "downgrade")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM permisos")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM roles_permisos_base")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM usuarios_permisos_override")).scalar_one() == 0
