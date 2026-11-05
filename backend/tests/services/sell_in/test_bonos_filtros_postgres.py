"""The brand-bonus list's filters (`bonos_crud.listar_bonos`) on Postgres, the real target.

SQLite's `lower()` only folds ASCII, so the non-ASCII case folding of `q` can
only be proven here; the period overlap runs on real `DATE` columns. Runs in a
throwaway schema with the bonus table built from the ORM and bare stand-ins of
the tables it references, read through an `autoflush=False` session like
production's.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.sell_in import bonos_crud
from tests.services.sell_in._bonos_schema import bonos_schema

pytestmark = pytest.mark.postgres

_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, numero VARCHAR(32) NOT NULL)",
    # What the Marca filter reads for the scopes that are not 'marca' (bonos_alcance.alcanza_marcas): empty here.
    "CREATE TABLE productos_erp (item_id INTEGER PRIMARY KEY, marca VARCHAR(100), categoria VARCHAR(100))",
    "CREATE TABLE pedido_compra_lineas_facturadas (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT, item_id INTEGER)",
    "CREATE TABLE pedido_compra_ingresos (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT, item_id INTEGER)",
    "CREATE TABLE sell_in_bono_items (id BIGSERIAL PRIMARY KEY, bono_id BIGINT, item_id INTEGER)",
    "INSERT INTO usuarios VALUES (7)",
]

# key: (marca, moneda, fecha_desde, fecha_hasta, descripcion)
_BONOS = {
    "nandu": ("TP-LINK", "USD", "2026-09-01", "2026-09-30", "ÑANDÚ DISTRIBUCIÓN"),
    "istanbul": ("İSTANBUL", "ARS", "2026-10-01", "2026-10-31", "Acuerdo anual"),
    "q4": ("MERCUSYS", "USD", "2026-10-15", "2026-12-31", "Rebate Q4"),
}


def _schema():
    return bonos_schema("sell_in_bf", ["tacticals", "sell_in_bonos_marca"], _STUBS)


@pytest.fixture(scope="module")
def pg():
    with _schema() as eng:
        ids = {}
        with eng.begin() as conn:
            for key, (marca, moneda, desde, hasta, descripcion) in _BONOS.items():
                ids[key] = conn.execute(
                    text(
                        "INSERT INTO sell_in_bonos_marca (alcance, marca, tipo, monto_unit, moneda, fecha_desde,"
                        " fecha_hasta, base, incluye_iva, acumulable, descripcion, estado, usuario_id)"
                        " VALUES ('marca', :marca, 'por_unidad', 1, :moneda, CAST(:desde AS DATE), CAST(:hasta AS DATE),"
                        " 'factura', false, true, :descripcion, 'activa', 7) RETURNING id"
                    ),
                    {"marca": marca, "moneda": moneda, "desde": desde, "hasta": hasta, "descripcion": descripcion},
                ).scalar_one()
        yield eng, ids


def _listar(eng, **filtros) -> list[int]:
    with Session(bind=eng, autoflush=False) as db:
        bonos, total = bonos_crud.listar_bonos(db, bonos_crud.FiltrosBonos(**filtros))
    assert total == len(bonos)
    return [b.id for b in bonos]


@pytest.mark.parametrize(
    "q,expected",
    [
        ("ñandú", ["nandu"]),  # non-ASCII uppercase description, lowercase query
        ("Ñandú distribución", ["nandu"]),
        ("İstanbul", ["istanbul"]),  # a brand, folded by the database on both sides
        ("rebate", ["q4"]),
        ("100%", []),  # LIKE wildcards stay literal
    ],
)
def test_q_folds_case_in_the_database(pg, q, expected):
    eng, ids = pg
    assert _listar(eng, q=q) == [ids[k] for k in expected]


def test_marcas_moneda_and_the_period_overlap_on_real_dates(pg):
    eng, ids = pg
    assert _listar(eng, marcas=["TP-LINK", "MERCUSYS"]) == [ids["q4"], ids["nandu"]]
    assert _listar(eng, moneda="ARS") == [ids["istanbul"]]
    assert _listar(eng, fecha_desde=date(2026, 10, 1), fecha_hasta=date(2026, 10, 31)) == [ids["q4"], ids["istanbul"]]
    assert _listar(eng, fecha_desde=date(2026, 9, 30), fecha_hasta=date(2026, 9, 30)) == [ids["nandu"]]
    assert _listar(eng, marca="TP-LINK") == [ids["nandu"]]
