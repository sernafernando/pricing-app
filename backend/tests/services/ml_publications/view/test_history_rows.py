"""Readable Historial rows and the Eventos promotion state, over real production rows.

Every change list and event below is a row captured read-only from production on 2026-10-16
(`history_events_MLA1402898289_20261016.json`), so the paths and nested shapes are the ones the store
really writes, not shapes made up for the test.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.ml_publications.view import events_view, history, history_rows
from tests.services.ml_publications.conftest import load_fixture

CAPTURE = "history_events_MLA1402898289_20261016.json"


def log_row(row_id: int) -> dict[str, Any]:
    return next(row for row in load_fixture(CAPTURE)["change_log"] if row["id"] == row_id)


def rows_of(row_id: int) -> list[history_rows.Row]:
    row = log_row(row_id)
    return history_rows.readable(row["resource_type"], row["changes"])


def by_label(rows: list[history_rows.Row], label: str) -> list[history_rows.Row]:
    return [row for row in rows if row.label == label]


def one(rows: list[history_rows.Row], label: str) -> history_rows.Row:
    (found,) = by_label(rows, label)
    return found


ALL_ROW_IDS = [row["id"] for row in load_fixture(CAPTURE)["change_log"]]


class TestScalarsOnly:
    @pytest.mark.parametrize("row_id", ALL_ROW_IDS)
    def test_no_value_is_a_dict_or_a_list_and_every_row_has_a_spanish_label(self, row_id: int) -> None:
        rows = rows_of(row_id)
        assert rows
        for row in rows:
            assert not isinstance(row.before, (dict, list)) and not isinstance(row.after, (dict, list)), row
            assert row.label and row.label == row.label.strip()


class TestItem:
    def test_reactivation_row_reads_as_business_with_formatted_values(self) -> None:
        """6989: paused -> active with price, stock and the out-of-stock substatus gone."""
        rows = rows_of(6989)
        price = one(rows, "Precio")
        assert (price.before, price.after, price.is_technical) == ("$ 80.049", "$ 91.193", False)
        stock = one(rows, "Stock disponible")
        assert (stock.before, stock.after, stock.is_technical) == ("0", "5", False)
        status = one(rows, "Estado")
        assert (status.before, status.after) == ("Pausada", "Activa")
        sub = one(rows, "Subestado")
        assert (sub.before, sub.after, sub.is_technical) == ("Sin stock", None, False)

    def test_timestamps_ids_and_attributes_are_technical(self) -> None:
        rows = rows_of(6989)
        technical = {row.path for row in rows if row.is_technical}
        assert {"last_updated", "expiration_time", "initial_quantity", "attributes[SELLER_SKU]"} <= technical
        sku = next(row for row in rows if row.path == "attributes[SELLER_SKU]")
        assert sku.after == "314" and sku.before is None

    def test_sold_quantity_is_units_sold(self) -> None:
        """7666."""
        sold = one(rows_of(7666), "Unidades vendidas")
        assert (sold.before, sold.after, sold.is_technical) == ("460", "461", False)

    def test_a_tag_added_reads_its_value(self) -> None:
        """70046: moderation penalty tag added while paused."""
        tag = one(rows_of(70046), "Etiqueta")
        assert tag.before is None and tag.after == "moderation_penalty" and not tag.is_technical


class TestPromotions:
    def test_an_applied_promotion_flattens_into_name_type_state_and_price(self) -> None:
        """7672: C-MLA1717163 added as started."""
        rows = [row for row in rows_of(7672) if row.path == "[C-MLA1717163]"]
        assert {row.subject for row in rows} == {"A PVP TODO"}
        assert one(rows, "Promoción").after == "A PVP TODO"
        assert one(rows, "Tipo de promoción").after == "Campaña del vendedor"
        state = one(rows, "Estado de la promoción")
        assert (state.before, state.after, state.status_label) == (None, "Aplicada", "Aplicada")
        assert one(rows, "Precio de la promoción").after == "$ 77.000"
        assert not any(row.is_technical for row in rows)

    def test_the_suggested_price_churn_is_technical(self) -> None:
        churn = [row for row in rows_of(7672) if row.path.endswith(".suggested_discounted_price")]
        assert churn and all(row.is_technical for row in churn)
        assert churn[0].label == "Precio sugerido" and churn[0].after == "$ 77.000"

    def test_a_candidate_that_vanished_is_no_longer_offered_and_a_new_one_is_available(self) -> None:
        """9282: two candidate coupons removed, two new candidate coupons added."""
        rows = rows_of(9282)
        gone = next(r for r in rows if r.path == "[C-MLA1713876]" and r.label == "Estado de la promoción")
        assert (gone.before, gone.after, gone.status_label) == (
            "Disponible para activar",
            "Ya no se ofrece",
            "Ya no se ofrece",
        )
        new = next(r for r in rows if r.path == "[C-MLA1717457]" and r.label == "Estado de la promoción")
        assert (new.before, new.after, new.status_label) == (None, "Disponible para activar", "Disponible para activar")
        assert next(r for r in rows if r.path == "[C-MLA1717457]" and r.label == "Tipo de promoción").after == (
            "Cupón del vendedor"
        )

    def test_a_candidate_without_a_price_has_no_price_row(self) -> None:
        rows = [row for row in rows_of(9282) if row.path == "[C-MLA1717457]"]
        assert by_label(rows, "Precio de la promoción") == []

    @pytest.mark.parametrize(
        ("status", "reason", "expected"),
        [
            ("candidate", None, "Disponible para activar"),
            ("started", None, "Aplicada"),
            ("pending", None, "Pendiente"),
            ("finished", "absent", "Ya no se ofrece"),
            (None, "absent", "Ya no se ofrece"),
            ("something_new", None, None),
        ],
    )
    def test_status_labels(self, status, reason, expected) -> None:
        assert history_rows.promotion_status_label(status, reason) == expected


class TestPricesAndSalePrice:
    def test_a_promotion_price_added_reads_as_its_amount(self) -> None:
        """7671: prices[1058] (type promotion) added."""
        rows = rows_of(7671)
        amount = one(rows, "Precio de promoción")
        assert (amount.before, amount.after, amount.is_technical) == (None, "$ 77.000", False)
        assert all(row.is_technical for row in rows if row is not amount)

    def test_sale_price_amount_is_business_and_its_ids_technical(self) -> None:
        """7673."""
        rows = rows_of(7673)
        sale = one(rows, "Precio de venta")
        assert (sale.before, sale.after, sale.is_technical) == ("$ 91.193", "$ 77.000", False)
        technical = {row.path for row in rows if row.is_technical}
        assert {"metadata.campaign_id", "metadata.promotion_id", "price_id"} <= technical


class TestVisitsStockReplenishmentCompetition:
    def test_visits_total_is_business_and_the_window_technical(self) -> None:
        """34965."""
        rows = rows_of(34965)
        total = one(rows, "Visitas de los últimos 30 días")
        assert (total.before, total.after, total.is_technical) == ("17", "18", False)
        assert all(row.is_technical for row in rows if row is not total)
        day = next(row for row in rows if row.path == "results[2026-10-10T00:00:00Z].total")
        assert day.subject == "10/10/2026" and day.after == "7"

    def test_a_visits_day_rolling_in_is_flattened_and_technical(self) -> None:
        """148600: the window moved, one day out and one in."""
        rows = rows_of(148600)
        assert rows and all(row.is_technical for row in rows)
        rolled_in = next(row for row in rows if row.path == "results[2026-10-14T00:00:00Z]")
        assert rolled_in.after == "2" and rolled_in.subject == "14/10/2026"

    def test_stock_by_location(self) -> None:
        """175494."""
        rows = rows_of(175494)
        stock = one(rows, "Stock disponible")
        assert (stock.subject, stock.before, stock.after, stock.is_technical) == (
            "Depósito de Mercado Libre",
            "48",
            "49",
            False,
        )
        assert next(row for row in rows if row.path == "last_updated").is_technical

    def test_weekly_sales_totals_are_business_and_the_rolling_weeks_technical(self) -> None:
        """172543: the weekly window rolls (weeks removed and added) and the totals change."""
        rows = rows_of(172543)
        units = one(rows, "Unidades vendidas")
        assert (units.before, units.after, units.is_technical) == ("1", "2", False)
        weeks = [row for row in rows if row.path.startswith("sales.sales_history[")]
        assert weeks and all(row.is_technical and row.label == "Unidades vendidas en la semana" for row in weeks)
        first = next(row for row in weeks if row.path == "sales.sales_history[2026-09-03]")
        assert (first.before, first.after, first.subject) == ("3", None, "03/09/2026 al 09/09/2026")

    def test_price_to_win_is_business_and_the_winner_technical(self) -> None:
        """140177."""
        rows = rows_of(140177)
        assert one(rows, "Precio para ganar").after == "$ 77.429"
        winner = [row for row in rows if row.path.startswith("winner.")]
        assert winner and all(row.is_technical for row in winner)
        assert next(row for row in winner if row.path == "winner.price").after == "$ 81.191,59"


class TestOddShapes:
    def test_an_impossible_date_with_a_date_shape_is_shown_as_written(self) -> None:
        assert history_rows.day("2026-13-00") == "2026-13-00"

    def test_an_odd_stored_shape_falls_back_to_a_technical_text_row_instead_of_failing(self) -> None:
        """7671's real prices[1058] entry with `conditions` stored as a list and `type` as a dict."""
        (entry,) = [c for c in log_row(7671)["changes"] if c["p"] == "prices[1058]"]
        odd = {**entry["new"], "conditions": ["channel_marketplace"], "type": {"id": "promotion"}}
        (row,) = history_rows.readable("prices", [{**entry, "new": odd}])
        assert row.is_technical and row.path == "prices[1058]"
        assert not isinstance(row.after, (dict, list)) and row.after

    def test_the_rows_after_an_odd_one_are_still_read(self) -> None:
        changes = log_row(7671)["changes"]
        odd = {"p": "prices[1]", "op": "add", "new": {"conditions": "x", "type": ["promotion"]}}
        rows = history_rows.readable("prices", [odd, *changes])
        assert rows[0].is_technical and one(rows, "Precio de promoción").after == "$ 77.000"


class TestVisible:
    def test_technical_rows_are_hidden_and_counted_unless_asked(self) -> None:
        rows = rows_of(34965)
        shown, hidden = history_rows.visible(rows, include_technical=False)
        assert [row.label for row in shown] == ["Visitas de los últimos 30 días"] and hidden == len(rows) - 1
        shown, hidden = history_rows.visible(rows, include_technical=True)
        assert shown == rows and hidden == 0

    def test_entry_out_keeps_the_old_lines_and_adds_rows(self) -> None:
        row = log_row(34965)
        entry = history._entry_out(row, include_technical=False)
        assert {"business", "technical", "rows", "hidden_technical_count"} <= set(entry)
        assert [r["label"] for r in entry["rows"]] == ["Visitas de los últimos 30 días"]
        assert entry["hidden_technical_count"] == 4
        assert set(entry["rows"][0]) == {"path", "label", "subject", "before", "after", "is_technical", "status_label"}


class TestEvents:
    def events(self) -> dict[int, dict[str, Any]]:
        return {event["id"]: event for event in load_fixture(CAPTURE)["events"]}

    def test_payload_and_promotion_id_are_exposed_next_to_the_old_fields(self) -> None:
        stored = self.events()[3689]  # promotion_activated C-MLA1717163
        out = events_view._event_out(stored)
        assert out["promotion_id"] == "C-MLA1717163" and out["payload"] == {"original_price": "91193"}
        assert out["old_value"] is None and out["new_value"] == "77000" and out["label"] == "Promoción activada"

    @pytest.mark.parametrize(
        ("event_id", "expected"),
        [
            (6378, "Disponible para activar"),  # promotion_offered, candidate
            (3689, "Aplicada"),  # promotion_activated
            (6376, "Ya no se ofrece"),  # promotion_finished, reason absent (was a candidate)
            (43804, "Finalizada"),  # promotion_finished, reason absent, but it had been applied (was started)
            (3688, None),  # price_changed: no promotion state
        ],
    )
    def test_status_label(self, event_id: int, expected) -> None:
        assert events_view._event_out(self.events()[event_id])["status_label"] == expected
