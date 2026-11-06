"""`borrar_sell_in_sin_tactical` against Postgres: the owner's "los dos sell in que quedaron anulados los podemos
borrar" deletes only voided purchases and bonuses without a tactical. Dry run by default; a row still referenced
stops it with nothing deleted."""

from __future__ import annotations

import json
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.core import database
from app.models.producto import ProductoERP
from app.models.sell_in import (
    SellInBonoItem,
    SellInBonoMarca,
    SellInCompra,
    SellInCompraItem,
    SellInConsumo,
    SellInModoProducto,
)
from app.models.tactical import Tactical
from app.scripts import borrar_sell_in_sin_tactical as script
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY)",
]
_TABLES = [
    ProductoERP.__table__,
    Tactical.__table__,
    SellInBonoMarca.__table__,
    SellInBonoItem.__table__,
    SellInCompra.__table__,
    SellInCompraItem.__table__,
    SellInModoProducto.__table__,
    SellInConsumo.__table__,
]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("borrar_si", _TABLES, _STUBS) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        for table in ("sell_in_modos_producto", "sell_in_compras", "sell_in_bonos_marca", "tacticals", "productos_erp"):
            conn.execute(text(f"DELETE FROM {table}"))


def _compra(conn, id_: int, estado: str, *, tactical_id=None, bono_id=None) -> None:
    conn.execute(
        text(
            "INSERT INTO sell_in_compras (id, fecha_compra, moneda, monto_total, estado, usuario_id, tactical_id,"
            " tactical_linea, bono_id, origen) VALUES (:id, '2026-10-01', 'ARS', 100, :estado, 7, :t, :l, :b, :o)"
        ),
        {
            "id": id_,
            "estado": estado,
            "t": tactical_id,
            "l": 1 if tactical_id else None,
            "b": bono_id,
            "o": "bono_marca" if bono_id else "manual",
        },
    )
    conn.execute(
        text(
            "INSERT INTO sell_in_compra_items (compra_id, item_id, cantidad, costo_base_unit, monto_asignado)"
            " VALUES (:id, 1, 1, 10, 100)"
        ),
        {"id": id_},
    )


def _bono(conn, id_: int, estado: str) -> None:
    conn.execute(
        text(
            "INSERT INTO sell_in_bonos_marca (id, marca, monto_unit, moneda, fecha_desde, fecha_hasta, usuario_id, estado)"
            " VALUES (:id, 'M', 5, 'ARS', '2026-10-01', '2026-10-31', 7, :estado)"
        ),
        {"id": id_, "estado": estado},
    )


@pytest.fixture()
def mundo(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO productos_erp (item_id) VALUES (1)"))
        conn.execute(
            text(
                "INSERT INTO tacticals (id, tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id)"
                " VALUES (5, 'sell_in', 'T', 'M', '2026-10-01', '2026-10-31', 'ARS', 7)"
            )
        )
        _compra(conn, 1, "anulada")  # legacy voided: goes
        _compra(conn, 2, "activa")  # legacy active: stays
        _compra(conn, 3, "anulada", tactical_id=5)  # a tactical's: stays
        _bono(conn, 10, "anulada")  # legacy voided: goes
        _bono(conn, 11, "activa")  # stays


def _ids(engine: Engine, table: str) -> list[int]:
    with engine.connect() as conn:
        return [i for (i,) in conn.execute(text(f"SELECT id FROM {table} ORDER BY id"))]


@pytest.fixture()
def correr(engine, monkeypatch, capsys):
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))

    def _run(*argv: str):
        code = script.main(list(argv))
        out = capsys.readouterr()
        return code, (json.loads(out.out) if out.out.strip() else None), out.err

    return _run


def test_dry_run_lists_the_voided_rows_without_a_tactical_and_deletes_nothing(engine, mundo, correr):
    code, summary, _ = correr()

    assert code == 0
    assert summary == {"dry_run": True, "compras": [1], "bonos": [10]}
    assert _ids(engine, "sell_in_compras") == [1, 2, 3]
    assert _ids(engine, "sell_in_bonos_marca") == [10, 11]


def test_apply_deletes_only_the_voided_rows_without_a_tactical_and_their_lines(engine, mundo, correr):
    code, summary, _ = correr("--apply")

    assert code == 0
    assert summary == {"dry_run": False, "compras": [1], "bonos": [10]}
    assert _ids(engine, "sell_in_compras") == [2, 3]
    assert _ids(engine, "sell_in_bonos_marca") == [11]
    with engine.connect() as conn:
        lineas = [c for (c,) in conn.execute(text("SELECT compra_id FROM sell_in_compra_items ORDER BY compra_id"))]
    assert lineas == [2, 3]


def test_apply_deletes_a_voided_bonus_together_with_its_voided_purchase(engine, correr):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO productos_erp (item_id) VALUES (1)"))
        _bono(conn, 20, "anulada")
        _compra(conn, 21, "anulada", bono_id=20)

    code, summary, _ = correr("--apply")

    assert (code, summary["compras"], summary["bonos"]) == (0, [21], [20])
    assert _ids(engine, "sell_in_compras") == []
    assert _ids(engine, "sell_in_bonos_marca") == []


def test_a_purchase_a_cost_mode_points_to_stops_the_run_and_deletes_nothing(engine, mundo, correr):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_in_modos_producto (item_id, modo, desde, origen, compra_id, usuario_id)"
                " VALUES (1, 'fifo', '2026-10-01', 'carga', 1, 7)"
            )
        )

    code, summary, err = correr("--apply")

    assert (code, summary) == (1, None)
    assert err.strip() == script.REFERENCIADA
    assert _ids(engine, "sell_in_compras") == [1, 2, 3]
    assert _ids(engine, "sell_in_bonos_marca") == [10, 11]
