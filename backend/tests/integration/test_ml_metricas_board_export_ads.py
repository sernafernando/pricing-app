"""The Métricas ML CSV follows the board's "Publicidad" position (owner decision 2026-10-16).

With the position off the file is the pre-ads file, byte for byte. With `mla` or `todo` it gains a
"Publicidad (inversión)" column right after "Total Gauss" (the board's column order and label), and its
Total Gauss / markup are the adjusted values the board shows for that position -- same rows, same figures.
DERIVED fixtures: figures chosen to be checkable by hand.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import csv
import io
from datetime import date

import pytest

from app.models.ml_ads import MlAdsCampaignContribution, MlAdsItemDay

from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _day,
    _frozen_clock,
    _grant,
    _producto,
    _pub,
    bg_sessions,
)
from tests.services.ml_daily_metrics.test_board_ads_subtract import _ad

AD_DAY = date(2026, 9, 4)
ADS_HEADER = "Publicidad (inversión)"


@pytest.fixture()
def one_product(db, rol_admin):
    """Product 11 (MLA1) sold once in the period: TG 300 on a cost of 400; 60 of ads on MLA1."""
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    _producto(db, 11, "Impresora", "Epson")
    db.flush()
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 20), 1, "1000", "300", "400")
    _ad(db, "MLA1", AD_DAY, "60")
    db.commit()


def _export(client, headers, **params) -> str:
    resp = client.get(f"{URL}/export", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.content.decode("utf-8-sig")


def _rows(text: str) -> list:
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def _board(client, headers, **params) -> dict:
    resp = client.get(URL, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return {row["key"]: row for row in resp.json()["rows"]}


def _money(value) -> str:
    return f"{value:.2f}".replace(".", ",")


PRE_ADS_HEADER = (
    "Producto;SKU;Marca;MLA;Unidades;24h;3d;7d;15d;30d;Facturado;"
    "Total Gauss;Markup %;Markup anterior %;Variación pp;Última venta;Ageing (días);Stock"
)


class TestOffIsThePreAdsFile:
    def test_off_and_no_position_write_the_same_bytes_without_the_ads_column(
        self, client, admin_auth_headers, one_product
    ):
        absent = _export(client, admin_auth_headers)
        off = _export(client, admin_auth_headers, publicidad="off")

        assert off == absent
        assert off.splitlines()[0] == PRE_ADS_HEADER
        assert off.splitlines()[1].startswith("Impresora;SKU-11;Epson;;1;0;0;0;1;1;1000,00;300,00;75,00;")


class TestThePositionAddsTheColumn:
    @pytest.mark.parametrize("position", ["mla", "todo"])
    def test_the_column_follows_total_gauss_with_the_board_figures(
        self, client, admin_auth_headers, one_product, position
    ):
        text = _export(client, admin_auth_headers, publicidad=position)
        board_row = _board(client, admin_auth_headers, publicidad=position)["11"]

        header = text.splitlines()[0].split(";")
        assert header[header.index("Total Gauss") + 1] == ADS_HEADER
        (row,) = _rows(text)
        assert row[ADS_HEADER] == _money(board_row["ads"]["cost"]) == "60,00"
        # The adjusted Total Gauss and markup the board shows -- the ads subtracted once, never twice.
        assert row["Total Gauss"] == _money(board_row["total_gauss"]) == "240,00"
        assert row["Markup %"] == _money(board_row["markup_pct"]) == "60,00"

    def test_a_brand_contribution_comes_off_the_column_like_off_the_board(
        self, client, admin_auth_headers, db, one_product
    ):
        """ml-ads-brand-contribution S9: MLA1's 60 belong to campaign 7, which a brand covers at 50%."""
        db.query(MlAdsItemDay).update({MlAdsItemDay.campaign_id: 7})
        db.add(
            MlAdsCampaignContribution(
                advertiser_id=1,
                campaign_id=7,
                kind="percentage",
                value=50,
                date_from=date(2026, 9, 1),
                date_to=date(2026, 9, 30),
                created_by_id=1,
                updated_by_id=1,
            )
        )
        db.commit()
        (row,) = _rows(_export(client, admin_auth_headers, publicidad="mla"))
        board_row = _board(client, admin_auth_headers, publicidad="mla")["11"]
        assert row[ADS_HEADER] == _money(board_row["ads"]["cost"]) == "30,00"
        assert row["Total Gauss"] == _money(board_row["total_gauss"]) == "270,00"

    def test_restar_publicidad_true_is_the_mla_position(self, client, admin_auth_headers, one_product):
        legacy = _export(client, admin_auth_headers, restar_publicidad="true")
        assert legacy == _export(client, admin_auth_headers, publicidad="mla")

    def test_an_ads_only_row_and_the_sin_producto_row_are_exported_like_the_board(
        self, db, client, admin_auth_headers, one_product
    ):
        _producto(db, 12, "Notebook", "Lenovo")
        db.flush()
        _pub(db, 2, "MLA2", 12, 57997)
        _ad(db, "MLA2", AD_DAY, "500")  # product 12: ads, no sale
        _ad(db, "MLAX", AD_DAY, "30")  # owned by no product: "Sin producto"
        db.commit()
        params = {"publicidad": "mla", "solo_con_ventas": "true"}

        board = _board(client, admin_auth_headers, **params)
        rows = {row["Producto"]: row for row in _rows(_export(client, admin_auth_headers, **params))}

        assert {r["title"] for r in board.values()} == set(rows)
        assert (rows["Notebook"][ADS_HEADER], rows["Notebook"]["Total Gauss"]) == ("500,00", "-500,00")
        assert (rows["Sin producto"][ADS_HEADER], rows["Sin producto"]["Total Gauss"]) == ("30,00", "-30,00")

    def test_the_grouped_export_carries_it_on_every_leaf(self, client, admin_auth_headers, one_product):
        text = _export(client, admin_auth_headers, publicidad="mla", group_by="group", dimension="marca")

        header = text.splitlines()[0].split(";")
        assert header[header.index("Total Gauss") + 1] == ADS_HEADER
        (row,) = _rows(text)
        assert (row["Marca"], row[ADS_HEADER], row["Total Gauss"]) == ("Epson", "60,00", "240,00")

    def test_without_the_margin_permission_the_position_is_403(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_metricas.ver")
        db.commit()

        resp = client.get(f"{URL}/export", params={"publicidad": "mla"}, headers=admin_auth_headers)

        assert resp.status_code == 403
