"""Migration `20261120_tactical_sell_in_usd` on a real Postgres (tactical sell in USD S1-S3, S6, S8).

Owner: "vos elegís un tipo de moneda para el sell in y un tipo de cambio qué importa en qué se cargó la factura?". A
tactical's cost bonus may be USD; its rows keep `monto_usd` + `tc_venta`; the collection keeps the rate the brand
paid at. The schema the models create (the bonus test world) is what this migration's upgrade leaves."""

from __future__ import annotations

import importlib.util
import os
from typing import Dict, Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, InternalError

from tests.services.sell_in import _bono_world as b

_VERSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic", "versions"
)
_REVISION = "20261120_tactical_sell_in_usd"
_CONSTRAINTS = (
    "ck_sell_in_bonos_marca_costo_venta",
    "ck_sell_in_bono_consumos_usd",
    "ck_sell_in_bono_consumos_tc_positivo",
    "ck_tactical_cobranzas_tc_positivo",
)


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
    with b.world("tactical_sell_in_usd_mig") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    _step(engine, "upgrade")  # every test starts from the upgraded (model) schema
    b.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tactical_cobranzas"))
        conn.execute(text("DELETE FROM tacticals"))


def _definiciones(engine: Engine) -> Dict[str, str]:
    with engine.connect() as conn:
        return {
            nombre: definicion
            for nombre, definicion in conn.execute(
                text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = ANY(:n)"),
                {"n": list(_CONSTRAINTS)},
            )
        }


def _columnas(engine: Engine) -> set:
    with engine.connect() as conn:
        return {
            (t, c)
            for t, c in conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = "
                    "current_schema() AND (table_name, column_name) IN (('sell_in_bono_consumos', 'monto_usd'), "
                    "('sell_in_bono_consumos', 'tc_venta'), ('tactical_cobranzas', 'tipo_cambio'))"
                )
            )
        }


def _tactical(engine: Engine) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, tc_modo, usuario_id) "
                "VALUES ('sell_in', 'Synthetic', 'TP-LINK', '2026-10-01', '2026-10-31', 'USD', 'al_cobro', 7) "
                "RETURNING id"
            )
        ).scalar()


def _bono(engine: Engine, moneda: str, tactical_id, tipo: str = "por_unidad") -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (base, alcance, marca, tipo, monto_unit, monto_total, "
                "reparto_criterio, moneda, fecha_desde, fecha_hasta, usuario_id, tactical_id, tactical_linea) "
                "VALUES ('costo_venta', 'marca', 'TP-LINK', :tipo, :mu, :mt, :rc, :m, '2026-10-01', '2026-10-31', 7, "
                ":t, :l) RETURNING id"
            ),
            {
                "tipo": tipo,
                "mu": "10.00" if tipo == "por_unidad" else None,
                "mt": "100.00" if tipo == "monto_total" else None,
                "rc": "unidades" if tipo == "monto_total" else None,
                "m": moneda,
                "t": tactical_id,
                "l": 1 if tactical_id is not None else None,
            },
        ).scalar()


def test_revises_the_current_sell_in_head() -> None:
    module = _module()
    assert (module.revision, module.down_revision) == (_REVISION, "20261119_ventas_fuera_pdf_cargas_detalle")


@pytest.mark.postgres
def test_upgrade_leaves_exactly_the_models_schema_and_is_idempotent(engine: Engine) -> None:
    del_modelo = _definiciones(engine)
    assert set(del_modelo) == set(_CONSTRAINTS)

    _step(engine, "downgrade")
    assert _columnas(engine) == set()
    assert set(_definiciones(engine)) == {"ck_sell_in_bonos_marca_costo_venta"}
    _step(engine, "upgrade")
    _step(engine, "upgrade")

    assert _definiciones(engine) == del_modelo
    assert len(_columnas(engine)) == 3


@pytest.mark.postgres
class TestReglas:
    def test_a_tacticals_usd_cost_bonus_is_accepted_and_an_ars_one_still_is(self, engine: Engine) -> None:
        _bono(engine, "USD", _tactical(engine))
        _bono(engine, "ARS", None)

    def test_a_usd_cost_bonus_without_a_tactical_is_refused(self, engine: Engine) -> None:
        with pytest.raises(IntegrityError, match="ck_sell_in_bonos_marca_costo_venta"):
            _bono(engine, "USD", None)

    def test_a_usd_cost_total_is_refused(self, engine: Engine) -> None:
        with pytest.raises(IntegrityError, match="ck_sell_in_bonos_marca_costo_venta"):
            _bono(engine, "USD", _tactical(engine), tipo="monto_total")

    def test_a_row_with_a_usd_amount_and_no_rate_is_refused(self, engine: Engine) -> None:
        bono = _bono(engine, "USD", _tactical(engine))
        with pytest.raises(IntegrityError, match="ck_sell_in_bono_consumos_usd"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, "
                        "unidades, descuento_ars, monto_usd) VALUES (:b, 'fuera', 1, 2964, '2026-10-05', 1, 10, 1)"
                    ),
                    {"b": bono},
                )

    def test_a_collection_rate_must_be_positive(self, engine: Engine) -> None:
        tactical = _tactical(engine)
        with pytest.raises(IntegrityError, match="ck_tactical_cobranzas_tc_positivo"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO tactical_cobranzas (tactical_id, fecha_cobro, tipo_cambio, usuario_id) "
                        "VALUES (:t, '2026-11-05', 0, 7)"
                    ),
                    {"t": tactical},
                )


@pytest.mark.postgres
class TestDowngrade:
    def test_refuses_while_a_usd_cost_bonus_exists_and_changes_nothing(self, engine: Engine) -> None:
        _bono(engine, "USD", _tactical(engine))

        with pytest.raises(InternalError, match="USD cost bonuses exist"):
            _step(engine, "downgrade")

        assert len(_columnas(engine)) == 3

    def test_refuses_while_a_collection_rate_exists(self, engine: Engine) -> None:
        tactical = _tactical(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tactical_cobranzas (tactical_id, fecha_cobro, tipo_cambio, usuario_id) "
                    "VALUES (:t, '2026-11-05', 1350, 7)"
                ),
                {"t": tactical},
            )

        with pytest.raises(InternalError, match="collection rates exist"):
            _step(engine, "downgrade")
