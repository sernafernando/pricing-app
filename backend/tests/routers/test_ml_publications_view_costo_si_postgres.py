"""The costo SI column of Publicaciones ML (sell-in-costo-si T3 PR 2, inventory §10, C4/C5): the `costo_si` line next
to `ppp` under each cost (`view/cost_lines.py`), the `costo_si` sort key (`listing.SORT_COLUMNS`) and the "Costo SI"
columns of the Auditoría de stock export. Display only: the `costo` sort and every other figure stay as they were.

The cost lines read the pricing database; here a throwaway Postgres schema holds the tables they read, so the real
`lote.actuales` runs. The sort runs in the store's own Postgres schema (`pg`). Invented data.
"""

# ruff: noqa: F811 -- the fixtures are imported and used by name

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Iterator

import pytest
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.sell_in import SellInModoProducto
from app.services.costo_si import lote
from app.services.ml_publications.view import cost_lines as module
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, get, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401 -- the store plus the Board's tables
from tests.routers.test_ml_publications_view_markup import analyst, pricing, reader  # noqa: F401
from tests.routers.test_ml_publications_view_stock_audit import (  # noqa: F401
    BOM_DDL,
    EXPORT_URL,
    PERMISO,
    fill as audit_fill,
    no_split,
    started,
)
from tests.services.costo_si import _world as w
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

USD_SI, ARS_LISTA, SIN_COSTO = 9101, 9102, 9103
PASOS_DDL = (
    "CREATE TABLE IF NOT EXISTS costo_si_pasos (item_id integer, orden integer, fecha date, promedio_usd numeric,"
    " moneda varchar(3));"
    # the reader's USD rate falls back to the ERP's rate history (one database with the store in production)
    " CREATE TABLE IF NOT EXISTS tb_cur_exch_history (ceh_id bigint, comp_id integer, curr_id_1 integer,"
    " curr_id_2 integer, ceh_cd timestamp, ceh_exchange numeric(18, 6))"
)


def usd_si_payload() -> dict:
    return {
        "costo": 20.5,
        "moneda": "USD",
        "fuente": "costo_si",
        "desde": date(2026, 10, 1),
        "tipo_cambio": 1000.0,
        "costo_ars": 20500.0,
        "markups": {},
    }


def ars_lista_payload() -> dict:
    return {
        "costo": 15000.0,
        "moneda": "ARS",
        "fuente": "lista",
        "desde": None,
        "tipo_cambio": None,
        "costo_ars": 15000.0,
        "markups": {},
    }


# --- the cost lines, on a pricing database that holds what they read ----------------------------------------------


@pytest.fixture()
def pricing_pg() -> Iterator[Session]:
    with throwaway_schema(
        "pubml_costo_si", [*w.TABLES, SellInModoProducto.__table__, MercadoLibreItemPublicado.__table__], w.STUBS
    ) as engine:
        w.producto(engine, USD_SI, costo="10")  # list USD 10, costo SI USD 20.5 from 10-01
        w.producto(engine, ARS_LISTA, moneda="ARS", costo="15000")  # no costo SI: the list cost stands in (Q1)
        w.producto(engine, SIN_COSTO)  # no cost at all
        w.run(
            engine,
            "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base,"
            " stock_despues, promedio_usd, moneda) VALUES (:i, 0, 'inicio', '2026-10-01', 0, 0, 0, 0, 20.5, 'USD')",
            i=USD_SI,
        )
        w.run(engine, "INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (CURRENT_DATE, 'USD', 1000, 1000)")
        session = sessionmaker(bind=engine)()
        try:
            yield session
        finally:
            session.close()


PRODUCTS = {USD_SI: (10.0, "USD", 21.0), ARS_LISTA: (15000.0, "ARS", 21.0), SIN_COSTO: (None, "USD", 21.0)}


class Publication:
    def __init__(self, item_id: str, producto: int) -> None:
        self.item_id, self.producto_item_id = item_id, producto
        self.costo, self.moneda_costo, self.costo_iva = PRODUCTS[producto]


class _NoSellIn:
    """The sell in / sell out batch of a page where nothing applies: not what these tests pin (its own tests do), and
    its campaign tables are out of this schema."""

    def markups(self, product, **kwargs):
        return self

    def payload(self):
        return None


@pytest.fixture(autouse=True)
def no_sell_in(monkeypatch) -> None:
    monkeypatch.setattr(module, "resolver_sell_in_out_batch", lambda db, ids, hoy: _NoSellIn())
    monkeypatch.setattr(
        module, "resolver_sell_in_out_por_contexto", lambda db, ids, hoy, contextos: {k: _NoSellIn() for k in contextos}
    )


class TestCostLines:
    def test_each_product_carries_its_costo_si_next_to_the_ppp(self, pricing_pg) -> None:
        lines = module.cost_lines(pricing_pg, PRODUCTS)

        assert lines[USD_SI]["costo_si"] == usd_si_payload()
        assert lines[ARS_LISTA]["costo_si"] == ars_lista_payload()  # no costo SI: the list cost, fuente 'lista'
        assert lines[SIN_COSTO]["costo_si"] is None
        assert set(lines[USD_SI]) == {"ppp", "sell_in_out", "costo_si"}

    def test_each_publication_carries_its_products_costo_si(self, pricing_pg) -> None:
        rows = [Publication("MLA1", USD_SI), Publication("MLA2", ARS_LISTA), Publication("MLA3", SIN_COSTO)]

        lines = module.cost_lines_by_publication(pricing_pg, rows)

        assert lines["MLA1"]["costo_si"] == usd_si_payload()
        assert lines["MLA2"]["costo_si"] == ars_lista_payload()
        assert lines["MLA3"]["costo_si"] is None

    def test_a_failing_costo_si_read_leaves_every_line_out_as_the_other_reads(self, pricing_pg, monkeypatch) -> None:
        from sqlalchemy.exc import OperationalError

        def roto(*args, **kwargs):
            raise OperationalError("SELECT", {}, Exception("costo SI down"))

        monkeypatch.setattr(module.lote, "actuales", roto)

        assert module.cost_lines(pricing_pg, PRODUCTS) is None
        assert module.cost_lines_by_publication(pricing_pg, [Publication("MLA1", USD_SI)]) is None

    def test_no_product_still_answers_with_no_lines(self, pricing_pg) -> None:
        assert module.cost_lines(pricing_pg, {}) == {}

    def test_a_product_without_lines_reads_costo_si_as_null(self) -> None:
        assert module.NO_COST_LINES["costo_si"] is None


# --- the `costo_si` sort, in the store's own schema -----------------------------------------------------------------


def fill_sort(conn) -> None:
    """MLA1: USD list 10 (10000 pesos), costo SI USD 30 (30000). MLA2: ARS list 15000, no costo SI (15000). MLA3: USD
    list 20 (20000), no costo SI (20000). MLA4: a product with no cost. MLA5: no product. USD rate 1000."""
    for ddl in BOM_DDL:
        conn.execute(text(ddl))
    conn.execute(text(PASOS_DDL))
    seed.add_usd_rate(conn, 1000.0, date.today().isoformat())
    for item_id, costo, moneda in ((80, 10, "USD"), (81, 15000, "ARS"), (82, 20, "USD"), (83, None, "USD")):
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}")
        seed.add_cost(conn, item_id, costo, moneda_costo=moneda)
    conn.execute(text("INSERT INTO costo_si_pasos VALUES (80, 0, '2026-10-01', 30, 'USD')"))
    for number in range(1, 6):
        seed.add_item(conn, f"MLA{number}", title=f"Item {number}")
    for mla, product in (("MLA1", 80), ("MLA2", 81), ("MLA3", 82), ("MLA4", 83)):
        seed.add_link(conn, mla, product)


def order_of(client, headers, **params) -> list[str]:
    response = get(client, headers, **params)
    assert response.status_code == 200, response.text
    return [row["item_id"] for row in response.json()["items"]]


class TestCostoSiSort:
    def test_ascending_orders_by_the_costo_si_in_pesos_with_the_missing_last(self, client, pg, analyst, pricing):
        seed_rows(pg, fill_sort)
        assert order_of(client, analyst, orden="costo_si", dir="asc") == ["MLA2", "MLA3", "MLA1", "MLA4", "MLA5"]

    def test_descending_keeps_the_missing_last(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill_sort)
        assert order_of(client, analyst, orden="costo_si", dir="desc") == ["MLA1", "MLA3", "MLA2", "MLA4", "MLA5"]

    def test_its_default_direction_is_ascending(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill_sort)
        assert order_of(client, analyst, orden="costo_si") == ["MLA2", "MLA3", "MLA1", "MLA4", "MLA5"]

    def test_costo_still_sorts_the_list_cost_it_shows(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill_sort)
        assert order_of(client, analyst, orden="costo", dir="asc") == ["MLA1", "MLA2", "MLA3", "MLA4", "MLA5"]

    def test_without_ver_ganancia_it_is_a_403_like_costo(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, fill_sort)
        for orden in ("costo", "costo_si", "titulo,costo_si"):
            response = get(client, reader, orden=orden)
            assert response.status_code == 403, (orden, response.text)
            assert GANANCIA in response.json()["error"]["message"]

    def test_the_service_refuses_it_without_the_margin(self) -> None:
        from app.services.ml_publications.view import listing

        assert "costo_si" in listing.MARGIN_SORTS
        assert listing.parse_sort("costo_si", None).descending is False


# --- the Auditoría de stock export ----------------------------------------------------------------------------------


@pytest.fixture()
def audit_costo_si(client, pg, db, rol_admin, admin_auth_headers, started, monkeypatch):
    """The audit's world plus a costo SI step for 100 (USD 900 from 10-01). The export reads the costo SI from the
    pricing database (the SQLite one in this harness): the reader runs the real rule on the store's schema, which
    holds the same products, combos and rate."""
    seed_rows(pg, audit_fill)
    with pg.begin() as conn:
        conn.execute(text(PASOS_DDL))
        conn.execute(text("INSERT INTO costo_si_pasos VALUES (100, 0, '2026-10-01', 900, 'USD')"))
    grant(db, rol_admin, PERMISO)
    real = lote.actuales
    asked: list[list[int]] = []

    def on_the_store(_db, ids, **kwargs):
        ids = list(ids)
        asked.append(sorted(ids))
        with Session(pg) as session:
            return real(session, ids, **kwargs)

    monkeypatch.setattr(lote, "actuales", on_the_store)
    return admin_auth_headers, asked


def sheet(client, headers) -> tuple[list, list[dict]]:
    response = client.get(EXPORT_URL, headers=headers)
    assert response.status_code == 200, response.text
    rows = list(load_workbook(BytesIO(response.content)).active.iter_rows(values_only=True))
    return list(rows[0]), [dict(zip(rows[0], row)) for row in rows[1:]]


class TestStockAuditExport:
    def test_the_costo_si_columns_follow_moneda_costo(self, client, audit_costo_si) -> None:
        header, _ = sheet(client, audit_costo_si[0])
        at = header.index("Moneda costo")
        assert header[at + 1 : at + 3] == ["Costo SI", "Moneda costo SI"]
        assert header[at + 3] == "Stock ERP"

    def test_products_and_variants_carry_their_costo_si(self, client, audit_costo_si) -> None:
        headers, asked = audit_costo_si
        _, rows = sheet(client, headers)
        by_code = {r["Código"]: r for r in rows}

        assert (by_code["C100"]["Costo SI"], by_code["C100"]["Moneda costo SI"]) == (900.0, "USD")
        assert (by_code["C100"]["Costo"], by_code["C100"]["Moneda costo"]) == (1000.0, "USD")  # unchanged
        # a variant: the notebook combo 101 = 100 (costo SI 900) + 102 (list 50), as the costo SI rule sums it
        assert (by_code["C101"]["Costo SI"], by_code["C101"]["Moneda costo SI"]) == (950.0, "USD")
        assert (by_code["C130"]["Costo SI"], by_code["C130"]["Moneda costo SI"]) == (300000.0, "ARS")  # list (Q1)
        assert (by_code["C110"]["Costo SI"], by_code["C110"]["Moneda costo SI"]) == (20.0, "USD")  # the pack
        assert len(asked) == 1  # one read for the whole file
        assert {100, 101, 110, 111, 130, 140} <= set(asked[0])

    def test_the_valuation_does_not_change(self, client, audit_costo_si) -> None:
        _, rows = sheet(client, audit_costo_si[0])
        notebook = {r["Código"]: r for r in rows}["C100"]
        assert (notebook["Valor ERP USD"], notebook["Valor total ARS"]) == (5000.0, 8_100_000.0)
