"""Tactical companions of a Publicaciones ML row follow the publication's official store (as the allocators credit its
sales: the latest `mlp_official_store_id`), against real tables: a tactical scoped to one store paints only that
store's rows, an all-stores tactical paints every row, also one without an official store, and a page with several
stores is resolved from one read. Postgres only."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.item_cost_list_history import ItemCostListHistory
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.tactical import TacticalTienda
from app.services import ml_promotions_pricing
from app.services.ml_publications.view import detail, listing
from app.services.ml_publications.view.detail import LINK_ITEM_LEVEL
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as si
from tests.services.sell_out import _world as so
from tests.services.test_productos_sell_in_out_postgres import STUBS, TABLES, _install as _install_base

pytestmark = pytest.mark.postgres

ROUTER = 2964  # cost 50000 ARS, VAT 21
GAUSS, TPLINK = 57997, 2645
DESDE, HASTA = date(2020, 1, 1), date(2099, 12, 31)  # current whatever day the test runs
PUBLICADOS = (
    "CREATE TABLE tb_mercadolibre_items_publicados ("
    "mlp_id SERIAL PRIMARY KEY, mlp_publicationid VARCHAR(50), mlp_official_store_id INTEGER)"
)


def _install(engine: Engine) -> None:
    _install_base(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) "
                "VALUES (57997, 'GaussOnline', 'gauss', 1, true), (2645, 'TP-Link', 'tplink', 2, true)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO tb_mercadolibre_items_publicados (mlp_publicationid, mlp_official_store_id) "
                "VALUES ('MLA1', 57997), ('MLA2', 2645), ('MLA3', NULL)"
            )
        )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema(
        "cost_lines_tienda",
        [*TABLES, MlTiendaOficial.__table__, TacticalTienda.__table__, ItemCostListHistory.__table__],
        [*STUBS, PUBLICADOS],
        after=_install,
    ) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)
    so.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tacticals"))


def _campana(engine: Engine, *, todas: bool, oficiales=()) -> int:
    with engine.begin() as conn:
        tid = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_out', 'T', 'TP-LINK', :d, :h, 'ARS', 7, :todas, true) "
                "RETURNING id"
            ),
            {"d": DESDE, "h": HASTA, "todas": todas},
        ).scalar_one()
        for store_id in oficiales:
            conn.execute(
                text("INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'oficial', :s)"),
                {"t": tid, "s": store_id},
            )
    gid = so.grupo(engine, [{"item_id": ROUTER}])
    return so.campana(engine, [gid], DESDE, HASTA, tactical_id=tid, tactical_linea=1)


def _row(mla: str, product: Optional[int] = ROUTER) -> SimpleNamespace:
    return SimpleNamespace(item_id=mla, producto_item_id=product, costo=50000, moneda_costo="ARS", costo_iva=21.0)


def _companions(engine: Engine, mlas) -> dict:
    items = [{} for _ in mlas]
    with sessionmaker(bind=engine, autoflush=False)() as db:
        listing.attach_cost(items, [_row(m) for m in mlas], db)
    return {m: (item["sell_in_out"] or {}).get("sell_out", {}) for m, item in zip(mlas, items)}


def _campanas(sell_out) -> list:
    return (sell_out or {}).get("campana_ids", [])


def _statements(engine: Engine, mlas) -> int:
    _companions(engine, mlas)  # the lines are built (a failed read raises KeyError): it must not count nothing
    statements = []
    with sessionmaker(bind=engine, autoflush=False)() as db:
        event.listen(db.connection(), "before_cursor_execute", lambda *a: statements.append(a[2]))
        listing.attach_cost([{} for _ in mlas], [_row(m) for m in mlas], db)
    return len(statements)


class TestListRows:
    def test_each_row_gets_the_tacticals_of_its_own_store_and_a_row_without_store_keeps_all_stores_ones(
        self, engine: Engine
    ) -> None:
        solo_gauss = _campana(engine, todas=False, oficiales=(GAUSS,))
        todas = _campana(engine, todas=True)

        lines = _companions(engine, ["MLA1", "MLA2", "MLA3"])

        assert {m: _campanas(s) for m, s in lines.items()} == {
            "MLA1": [solo_gauss, todas],
            "MLA2": [todas],
            "MLA3": [todas],  # no official store: every all-stores tactical still reaches it
        }

    def test_a_campaign_outside_any_tactical_reaches_every_row(self, engine: Engine) -> None:
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        suelta = so.campana(engine, [gid], DESDE, HASTA)

        assert {m: _campanas(s) for m, s in _companions(engine, ["MLA1", "MLA3"]).items()} == {
            "MLA1": [suelta],
            "MLA3": [suelta],
        }

    def test_a_page_of_several_stores_reads_as_much_as_a_page_of_one(self, engine: Engine) -> None:
        _campana(engine, todas=False, oficiales=(GAUSS,))

        assert _statements(engine, ["MLA1", "MLA2", "MLA3"]) == _statements(engine, ["MLA1"])


class TestDetail:
    def test_a_publication_without_store_keeps_its_all_stores_companion(self, engine: Engine) -> None:
        _campana(engine, todas=False, oficiales=(GAUSS,))
        todas = _campana(engine, todas=True)
        links = [SimpleNamespace(variation_id=LINK_ITEM_LEVEL, product_id=ROUTER, iva=21.0, match_status="linked")]
        found = SimpleNamespace(variation_id=None, breakdown=SimpleNamespace(costo_ars=50000.0, price=None, limpio=0.0))

        with sessionmaker(bind=engine, autoflush=False)() as db:
            payload = detail._sell_in_out(db, links, found, mla="MLA3")

        assert payload["sell_out"]["campana_ids"] == [todas]


class TestRankingContext:
    @pytest.mark.parametrize(
        ("mlas", "expected"),
        [
            (["MLA1"], [("ml", GAUSS)]),
            (["MLA3"], [("ml", None)]),  # no official store: all-stores tacticals still apply
            (["MLA9"], [("ml", None)]),  # no publicado row at all: same
            (["MLA1", "MLA2"], None),  # mixed stores: the global read
        ],
    )
    def test_one_store_context_when_every_publication_shares_it(self, engine: Engine, mlas, expected) -> None:
        with sessionmaker(bind=engine, autoflush=False)() as db:
            assert ml_promotions_pricing._contextos_mlas(db, mlas) == expected
