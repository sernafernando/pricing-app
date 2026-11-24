"""Markup with sell in / sell out in every view of Publicaciones ML (pubml-markup-siso S1-S4).

* "Markup actual c/ SISO" (`markup_siso` on a publication row, `markup_siso_min/max` on a group node): the plain
  markup's units at today's price, each with the sell out the panel's Resumen gives it (the same resolver,
  store-scoped, ONE batch for the page), summarized with the plain markup's rule (range, worst variation). Where no
  sell out applies a unit keeps its plain value (as Auditoría's Real 30D shows the plain one); a unit whose sell out
  cannot be priced (a missing rate or base) has no value and counts as pending, as Precios says "Pendiente".
* "Markup real 30D c/ SISO" (`metrics.markup_sell_30d`): the Board's sold lines with their sell out, read with
  `sell_in_out=True` only for who may see the margin (`view.real_so`).

D1 (sell-in-costo-si T3 PR 5, owner L12: "el costo siso no existe, es costo SI y SO va en la venta, como ganancia
adicional"): the sell in never comes off the cost, so a sell in alone leaves the plain markup (`applies` false) and
next to a sell out it changes nothing; with sell out the markup is (net + sell out - costo SI) / costo SI. The SQLite
pricing db has no costo SI steps, so costo SI is the list cost here (`tests/costo_si_lista.py`).
"""

# ruff: noqa: F811 -- the fixtures are imported from the detail's and markup's test modules and used by name

from __future__ import annotations

import pytest

from app.routers import ml_publications_view
from app.services.ml_publications.view import cost_lines
from app.services.ml_publications.view.markup import UnitMarkup
from app.schemas.sell_in_out_producto import SellInOutProducto, SellOutProducto
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import get as get_items
from tests.routers.test_ml_publications_view_groups import get as get_groups
from tests.routers.test_ml_publications_view_markup import (  # noqa: F401
    COST,
    analyst,
    pg,
    pricing,
    reader,
    view_pg,
)
from tests.routers.test_ml_publications_view_sell_in_out import markup_with_sell_out, sell_in, sell_out
from tests.routers.test_ml_publications_view_stock_audit import board_row
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view.test_detail_postgres import body_of, rows  # noqa: F401
from tests.costo_si_lista import costo_si_lista  # noqa: F401 -- the SQLite pricing db reads lote.actuales

pytestmark = pytest.mark.usefixtures("costo_si_lista")

METRICAS = "ml_metricas.ver"


def items_of(client, headers, **params) -> dict[str, dict]:
    response = get_items(client, headers, **params)
    assert response.status_code == 200, response.text
    return {item["item_id"]: item for item in response.json()["items"]}


def panel_markup(client, headers, item_id: str) -> float:
    """What the panel's Resumen shows "c/ sell in/out" for `item_id` (its worst unit): the one definition. D1: only
    the markup with sell out exists (`markups_sell_in` is always empty)."""
    found = body_of(client, headers, item_id)["sell_in_out"]
    assert found["markups_sell_in"] == {}
    return found["markups_sell_in_out"].get("publicacion")


@pytest.mark.postgres
class TestActualOnTheList:
    def test_a_publication_with_sell_out_shows_the_panels_markup_with_sell_out(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 70)

        siso = items_of(client, analyst)["MLA11"]["markup_siso"]

        expected = markup_with_sell_out(70, 500.0)  # (net + 500 - cost) / cost
        assert siso["worst"] == expected == panel_markup(client, analyst, "MLA11")
        assert (siso["min"], siso["max"], siso["applies"], siso["pending"]) == (expected, expected, True, 0)

    def test_a_sell_in_next_to_the_sell_out_changes_nothing(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 70)
        sell_in(db, admin_user, 70)

        siso = items_of(client, analyst)["MLA11"]["markup_siso"]

        assert siso["worst"] == markup_with_sell_out(70, 500.0) == panel_markup(client, analyst, "MLA11")

    def test_a_sell_in_alone_shows_the_plain_markup(self, client, rows, analyst, pricing, db, admin_user) -> None:
        sell_in(db, admin_user, 70)

        item = items_of(client, analyst)["MLA11"]

        siso, plain = item["markup_siso"], item["markup"]
        assert (siso["min"], siso["max"], siso["worst"]) == (plain["min"], plain["max"], plain["worst"])
        assert (siso["applies"], siso["pending"]) == (False, 0)

    def test_without_sell_in_or_sell_out_it_is_the_plain_markup(self, client, rows, analyst, pricing) -> None:
        item = items_of(client, analyst)["MLA11"]

        siso, plain = item["markup_siso"], item["markup"]
        assert (siso["min"], siso["max"], siso["worst"]) == (plain["min"], plain["max"], plain["worst"])
        assert (siso["applies"], siso["pending"]) == (False, 0)

    def test_with_variations_the_worst_unit_is_the_panels_one(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 71)  # variation 12, the worst one: the unit the panel explains

        item = items_of(client, analyst)["MLA10"]

        assert item["markup_siso"]["worst"] == panel_markup(client, analyst, "MLA10") is not None
        assert item["markup_siso"]["max"] == item["markup"]["max"]  # the other units keep their plain markup

    def test_a_publication_without_a_linked_product_has_no_value(self, client, rows, analyst, pricing) -> None:
        siso = items_of(client, analyst)["MLA12"]["markup_siso"]
        assert (siso["min"], siso["max"], siso["worst"], siso["applies"]) == (None, None, None, False)

    def test_without_ver_ganancia_it_is_absent(self, client, rows, reader, pricing, db, admin_user) -> None:
        sell_in(db, admin_user, 70)
        assert all("markup_siso" not in item for item in items_of(client, reader).values())

    def test_sorting_by_it_puts_the_worst_first_and_the_ones_without_value_last(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 70, monto="30000.00")  # 30000 per unit: MLA11 is the best one now

        response = get_items(client, analyst, orden="markup_siso", dir="asc")
        assert response.status_code == 200, response.text
        order = [item["item_id"] for item in response.json()["items"]]
        worst = {item["item_id"]: item["markup_siso"]["worst"] for item in response.json()["items"]}
        valued = [mla for mla in order if worst[mla] is not None]
        assert valued == sorted(valued, key=lambda mla: worst[mla])
        assert order[len(valued) :] == [mla for mla in order if worst[mla] is None]
        assert order[len(valued) - 1] == "MLA11"

    def test_sorting_by_it_needs_ver_ganancia(self, client, rows, reader, pricing) -> None:
        assert get_items(client, reader, orden="markup_siso").status_code == 403


class TestPendingUnit:
    """The per-unit rule, the panel's: with sell out > pending > the plain value. `siso_unit_value` still falls back
    to a `markups_sell_in` value, which the resolver never fills since D1 (the payloads below are hand-built)."""

    UNIT = UnitMarkup(10.0, "ok", 1100.0, 1000.0, 2000.0, "item_price", 4)

    def test_the_markup_with_sell_out_wins(self) -> None:
        payload = SellInOutProducto(
            sell_out=SellOutProducto(monto_unit=50.0, campana_ids=[1]),
            markups_sell_in={"u": 22.22},
            markups_sell_in_out={"u": 27.78},
        )
        assert cost_lines.siso_unit_value(self.UNIT, payload, "u") == (27.78, True, False)

    def test_a_markups_sell_in_value_when_the_sell_out_is_pending(self) -> None:
        payload = SellInOutProducto(
            sell_out=SellOutProducto(monto_unit=None, campana_ids=[1]),
            markups_sell_in={"u": 22.22},
        )
        assert cost_lines.siso_unit_value(self.UNIT, payload, "u") == (22.22, True, False)

    def test_pending_when_nothing_can_be_priced(self) -> None:
        payload = SellInOutProducto(sell_out=SellOutProducto(monto_unit=None, campana_ids=[1]))
        assert cost_lines.siso_unit_value(self.UNIT, payload, "u") == (None, True, True)

    def test_the_plain_value_when_neither_applies(self) -> None:
        assert cost_lines.siso_unit_value(self.UNIT, None, "u") == (10.0, False, False)


@pytest.fixture()
def board_calls(monkeypatch) -> list[bool]:
    """The page's Board read, faked: MLA11 sold with a sell out of 30 over a cost of 1000 (Total Gauss 200); the
    Board has no sell in (Costo SI T5 PR B)."""
    seen: list[bool] = []
    figures = {
        "MLA11": board_row(
            "MLA11",
            d7=1,
            d30=2,
            gross=2000.0,
            tg=200.0,
            costo=1000.0,
            sell_out=30.0,
            m_sell_out=30.0,
            sell_out_lineas=1,
        ),
        "MLA10": board_row(
            "MLA10",
            d7=0,
            d30=1,
            gross=500.0,
            tg=50.0,
            costo=400.0,
            sell_out=0.0,
            m_sell_out=0.0,
            sell_out_lineas=0,
        ),
    }

    def fake(db, mlas, sell_in_out=False):
        seen.append(sell_in_out)
        rows = {mla: figures[mla] for mla in mlas if mla in figures}
        if not sell_in_out:  # the Board leaves the sell fields empty when not asked
            rows = {mla: board_row(mla, d7=1, d30=2, gross=2000.0, tg=200.0, costo=1000.0) for mla in rows}
        return rows

    monkeypatch.setattr(ml_publications_view.row_metrics, "metrics_by_mla", fake)
    return seen


@pytest.mark.postgres
class TestReal30dOnTheList:
    def test_with_ver_ganancia_the_metrics_carry_the_boards_markup_with_sell_out(
        self, client, rows, db, rol_admin, analyst, pricing, board_calls
    ) -> None:
        grant(db, rol_admin, METRICAS)
        found = items_of(client, analyst)

        assert board_calls == [True]
        # D1: (200 + 30) / 1000 = 23 %, the sell in of 50 ignored; in points with one decimal as `markup_30d`
        assert found["MLA11"]["metrics"]["markup_sell_30d"] == round((200 + 30) / 1000 * 100, 1)
        assert found["MLA11"]["metrics"]["markup_30d"] == 20.0
        assert found["MLA10"]["metrics"]["markup_sell_30d"] is None  # neither applies: never a copy

    def test_without_ver_ganancia_the_board_is_read_without_sell_in_out(
        self, client, rows, db, rol_admin, reader, pricing, board_calls
    ) -> None:
        grant(db, rol_admin, METRICAS)
        found = items_of(client, reader)

        assert board_calls == [False]
        assert "markup_sell_30d" not in found["MLA11"]["metrics"]

    def test_the_panels_row_carries_it_too(self, client, rows, db, rol_admin, analyst, pricing, board_calls) -> None:
        grant(db, rol_admin, METRICAS)
        row = body_of(client, analyst, "MLA11")["row"]

        assert board_calls == [True]
        assert row["metrics"]["markup_sell_30d"] == round((200 + 30) / 1000 * 100, 1)  # the list row's figure

    def test_sorting_by_it_needs_ver_ganancia(self, client, rows, db, rol_admin, reader, pricing) -> None:
        grant(db, rol_admin, METRICAS)
        assert get_items(client, reader, orden="markup_sell_30d").status_code == 403


@pytest.mark.postgres
class TestGroupNodes:
    def test_a_node_carries_the_range_of_its_publications_markup_with_sell_in_out(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 70)
        response = get_groups(client, analyst)
        assert response.status_code == 200, response.text

        for node in response.json()["nodes"]:
            found = items_of(client, analyst, **node["params"]).values()
            lows = [i["markup_siso"]["min"] for i in found if i["markup_siso"]["min"] is not None]
            highs = [i["markup_siso"]["max"] for i in found if i["markup_siso"]["max"] is not None]
            assert node["markup_siso_min"] == (min(lows) if lows else None), node["key"]
            assert node["markup_siso_max"] == (max(highs) if highs else None), node["key"]

    def test_without_ver_ganancia_a_node_has_no_markup_with_sell_in_out(self, client, rows, reader, pricing) -> None:
        response = get_groups(client, reader)
        assert all(not {"markup_siso_min", "markup_siso_max"} & set(n) for n in response.json()["nodes"])


@pytest.mark.postgres
class TestVariationRows:
    """An expanded publication's sub-rows carry each variation's markup c/ SISO, as they carry its plain markup: the
    units the list's range summarizes, matched by variation id."""

    @staticmethod
    def variations_of(client, headers, item_id: str = "MLA10") -> dict[int, dict]:
        response = client.get(f"/api/ml-publications/view/items/{item_id}/variations", headers=headers)
        assert response.status_code == 200, response.text
        return {row["variation_id"]: row for row in response.json()["variations"]}

    def test_the_variation_with_sell_out_shows_the_panels_markup_and_the_others_their_plain_one(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 71)  # variation 12's product

        found = self.variations_of(client, analyst)

        assert found[12]["markup_siso"]["value"] == panel_markup(client, analyst, "MLA10")
        for other in (11, 13):  # 13 inherits the publication's product; neither has sell out: their plain one
            assert found[other]["markup_siso"]["value"] == found[other]["markup"]["value"], other
        listed = items_of(client, analyst)["MLA10"]["markup_siso"]
        values = [v["markup_siso"]["value"] for v in found.values() if v["markup_siso"]["value"] is not None]
        assert (min(values), max(values)) == (listed["min"], listed["max"])  # the list's range is these units'

    def test_without_ver_ganancia_there_is_none(self, client, rows, reader, pricing) -> None:
        assert all("markup_siso" not in row for row in self.variations_of(client, reader).values())
