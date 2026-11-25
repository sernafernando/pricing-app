"""Migration `20261125_sell_in_bono_usd_anulado` on a real Postgres.

Prod 2026-11-25: PUT /api/tacticals/54 answered 500 (CheckViolation `ck_sell_in_bonos_marca_costo_venta`): editing a
tactical voids and detaches its old USD cost bonus, which the CHECK refused. A voided USD cost bonus may now be
detached; a live one still needs its tactical. The schema the models create is what this upgrade leaves."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator, Optional

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, InternalError

from tests.services.sell_in import _bono_world as b

_VERSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic", "versions"
)
_REVISION = "20261125_sell_in_bono_usd_anulado"
_CHECK = "ck_sell_in_bonos_marca_costo_venta"


def _module():
    spec = importlib.util.spec_from_file_location(f"{_REVISION}_migration", os.path.join(_VERSIONS, f"{_REVISION}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bono_usd_anulado_mig") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tacticals"))
    _step(engine, "upgrade")  # every test starts from the upgraded (model) schema


def _definicion(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = :n AND connamespace = current_schema()::regnamespace"
            ),
            {"n": _CHECK},
        ).scalar_one()  # this world's schema only: other test worlds hold the same constraint name


def _tactical(engine: Engine) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, tc_modo, usuario_id) "
                "VALUES ('sell_in', 'Synthetic', 'TP-LINK', '2026-10-01', '2026-10-31', 'USD', 'al_cobro', 7) "
                "RETURNING id"
            )
        ).scalar()


def _bono(engine: Engine, estado: str, tactical_id: Optional[int], tipo: str = "por_unidad") -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (base, alcance, marca, tipo, monto_unit, monto_total, "
                "reparto_criterio, moneda, estado, fecha_desde, fecha_hasta, usuario_id, tactical_id, "
                "tactical_linea) VALUES ('costo_venta', 'marca', 'TP-LINK', :tipo, :mu, :mt, :rc, 'USD', :e, "
                "'2026-10-01', '2026-10-31', 7, :t, :l) RETURNING id"
            ),
            {
                "tipo": tipo,
                "mu": "10.00" if tipo == "por_unidad" else None,
                "mt": "100.00" if tipo == "monto_total" else None,
                "rc": "unidades" if tipo == "monto_total" else None,
                "e": estado,
                "t": tactical_id,
                "l": 1 if tactical_id is not None else None,
            },
        ).scalar()


def test_revises_the_current_head() -> None:
    module = _module()
    assert (module.revision, module.down_revision) == (_REVISION, "20261122_tacticals_aprobacion")


@pytest.mark.postgres
def test_upgrade_leaves_exactly_the_models_check_and_is_idempotent(engine: Engine) -> None:
    del_modelo = _definicion(engine)

    _step(engine, "downgrade")
    assert _definicion(engine) != del_modelo
    _step(engine, "upgrade")
    _step(engine, "upgrade")

    assert _definicion(engine) == del_modelo


@pytest.mark.postgres
class TestReglas:
    def test_a_voided_usd_cost_bonus_may_be_detached(self, engine: Engine) -> None:
        _bono(engine, "anulada", None)

    def test_a_live_usd_cost_bonus_without_a_tactical_is_still_refused(self, engine: Engine) -> None:
        with pytest.raises(IntegrityError, match=_CHECK):
            _bono(engine, "activa", None)

    def test_a_tacticals_live_usd_cost_bonus_is_still_accepted(self, engine: Engine) -> None:
        _bono(engine, "activa", _tactical(engine))

    def test_a_voided_usd_cost_total_is_still_refused(self, engine: Engine) -> None:
        with pytest.raises(IntegrityError, match=_CHECK):
            _bono(engine, "anulada", None, tipo="monto_total")


@pytest.mark.postgres
class TestDowngrade:
    def test_refuses_while_a_detached_voided_usd_cost_bonus_exists_and_changes_nothing(self, engine: Engine) -> None:
        del_modelo = _definicion(engine)
        _bono(engine, "anulada", None)

        with pytest.raises(InternalError, match="detached voided USD cost bonuses exist"):
            _step(engine, "downgrade")

        assert _definicion(engine) == del_modelo
