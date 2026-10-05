"""ODD `metricas-ml-tablero` T3: `GET /api/ml-metricas/board` and its nested
publications endpoint -- the Métricas ML board ("tablero bursátil").

The board reads the tables Ventas ML reads (orders, items, frozen costs,
stored metrics, group accreditation day); `_day` seeds one sale the way the
ingestion and the metrics worker would have stored it. "Today" is frozen
at 2026-09-30 (Buenos Aires) so every window is deterministic:

- period (default 30d): 2026-09-01..2026-09-30, previous: 2026-08-02..2026-08-31
- 3d: 09-28..30 · 7d: 09-24..30 · 15d: 09-16..30 · 30d: 09-01..30
- 90d: 2026-07-03..2026-09-30
"""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.permiso import Permiso, RolPermisoBase
from app.models.producto import ProductoERP
from app.routers import ml_metricas
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics.seed import Line, seed_sale

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)  # 15:00 in Buenos Aires
URL = "/api/ml-metricas/board"


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


@pytest.fixture(autouse=True)
def bg_sessions(db, monkeypatch):
    """Stands in for `get_background_db` (a real `SessionLocal` would not see
    the test transaction) and records every short session the export opens.
    Each one is a DISTINCT `Session` on the test's connection, so handing the
    request session to the page work is detectable by identity."""
    events = {"open": 0, "close": 0, "max_open": 0, "sessions": [], "fail_on_open": None, "on_open": None}

    @contextmanager
    def _fake():
        events["open"] += 1
        if events["on_open"] is not None:
            # A hook to change the data BETWEEN pages, as a concurrent sale or
            # metrics recompute would.
            events["on_open"](events["open"])
        if events["fail_on_open"] is not None and events["open"] >= events["fail_on_open"]:
            events["close"] += 1
            raise RuntimeError("pool timeout")
        events["max_open"] = max(events["max_open"], events["open"] - events["close"])
        session = Session(bind=db.get_bind())
        events["sessions"].append(session)
        try:
            yield session
        finally:
            session.close()
            events["close"] += 1

    monkeypatch.setattr(ml_metricas, "get_background_db", _fake, raising=False)
    return events


def _grant(db, rol, *codigos: str) -> None:
    for codigo in codigos:
        permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
        if not permiso:
            permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="ml_metricas", orden=300)
            db.add(permiso)
            db.flush()
        db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


def _producto(db, item_id: int, descripcion: str, marca: str, subcategoria_id: int = 1) -> None:
    db.add(
        ProductoERP(
            item_id=item_id,
            codigo=f"SKU-{item_id}",
            descripcion=descripcion,
            marca=marca,
            categoria="Cat",
            subcategoria_id=subcategoria_id,
        )
    )


def _pub(db, mlp_id, mla, item_id, store, status_id=153, listing="gold_special", catalog=False, full=False):
    db.add(
        MercadoLibreItemPublicado(
            mlp_id=mlp_id,
            mlp_publicationID=mla,
            item_id=item_id,
            mlp_official_store_id=store,
            mlp_lastStatusID=status_id,
            mlp_listing_type_id=listing,
            mlp_catalog_listing=catalog,
            mlp_is4FulFillment=full,
            mlp_itemTitle=f"Título {mla}",
            mlp_start_time=datetime(2026, 6, 1),
            mlp_thumbnail=f"https://http2.mlstatic.com/{mla}.jpg",
        )
    )


_ORDER_IDS = iter(range(2000090000000001, 2000090000100000))


def _day(db, product, mla, day, units, gross, tg, costo):
    """One sale of `units` x `mla` accredited at 15:00 UTC on `day`, with
    its order, items, frozen cost, stored metrics, payment and group row:
    what the ingestion and the metrics worker would have stored."""
    seed_sale(
        db,
        next(_ORDER_IDS),
        datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15),
        [Line(product, mla, units, Decimal(gross) / units)],
        tg=tg,
        costo=costo,
    )


@pytest.fixture()
def board_data(db, rol_admin):
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    _producto(db, 11, "Impresora Epson L3250", "Epson")
    _producto(db, 12, "Notebook Lenovo V15", "Lenovo", subcategoria_id=2)
    _producto(db, 13, "Taladro DeWalt", "DeWalt")
    _producto(db, 14, "Router TP-Link AX55", "TP-Link")
    db.flush()
    _pub(db, 1, "MLA1", 11, 57997, full=True)
    _pub(db, 2, "MLA2", 11, 57997, status_id=154, listing="gold_pro")
    _pub(db, 3, "MLA3", 12, 2645)
    _pub(db, 4, "MLA4", 13, 57997, catalog=True)
    _pub(db, 5, "MLA5", 14, 144)
    # p11: rising markup (prev 20% -> now 25%)
    _day(db, 11, "MLA1", date(2026, 9, 30), 2, "200", "30", "100")
    _day(db, 11, "MLA1", date(2026, 9, 20), 3, "300", "60", "200")
    _day(db, 11, "MLA1", date(2026, 8, 15), 1, "100", "20", "100")
    _day(db, 11, "MLA2", date(2026, 9, 25), 1, "100", "10", "100")
    # p12: last sale 2026-07-10 -> ageing 82 days, nothing in 30d
    _day(db, 12, "MLA3", date(2026, 7, 10), 5, "500", "50", "400")
    # p14: falling markup (prev 20% -> now 10%)
    _day(db, 14, "MLA5", date(2026, 9, 10), 1, "150", "10", "100")
    _day(db, 14, "MLA5", date(2026, 8, 10), 1, "150", "20", "100")
    # p13: never sold
    db.commit()


# The board's default hides rows with no sale in the period ("Solo con ventas
# en el período", ODD "Período y stock" PS1). Most tests here are about the
# whole catalog (windows, ageing of what never sold, chips...): they ask for
# it explicitly. `TestSoloConVentas` covers the default.
CATALOG = {"solo_con_ventas": "false"}


def _get(client, headers, **params):
    resp = client.get(URL, params={**CATALOG, **params}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_key(body):
    return {row["key"]: row for row in body["rows"]}


class TestPermissions:
    def test_without_ver_is_403(self, client, admin_auth_headers, db):
        assert client.get(URL, headers=admin_auth_headers).status_code == 403

    def test_without_ver_ganancia_money_of_margin_is_hidden(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_metricas.ver")
        _producto(db, 11, "Impresora", "Epson")
        _pub(db, 1, "MLA1", 11, 57997)
        _day(db, 11, "MLA1", date(2026, 9, 30), 2, "200", "30", "100")
        db.commit()

        body = _get(client, admin_auth_headers)

        row = body["rows"][0]
        assert row["gross"] == 200
        assert row["total_gauss"] is None
        assert row["markup_pct"] is None
        assert row["series_markup_90d"] is None
        assert body["kpis"]["total_gauss"]["value"] is None
        assert body["kpis"]["markup"]["value"] is None
        assert body["can_see_margin"] is False
        assert client.get(URL, params={"sort": "markup"}, headers=admin_auth_headers).status_code == 403
        assert client.get(URL, params={"alerts": "margen_cayendo"}, headers=admin_auth_headers).status_code == 403


class TestProductRows:
    def test_windows_markup_and_ageing(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers)

        assert body["period"] == {
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "prev_from": "2026-08-02",
            "prev_to": "2026-08-31",
        }
        assert body["total"] == 4
        p11 = _by_key(body)["11"]
        assert p11["title"] == "Impresora Epson L3250"
        assert p11["sku"] == "SKU-11"
        assert p11["marca"] == "Epson"
        assert p11["publications_count"] == 2
        assert [p11[f"units_{w}"] for w in ("3d", "7d", "15d", "30d")] == [2, 3, 6, 6]
        assert p11["units"] == 6
        assert p11["gross"] == 600
        assert p11["total_gauss"] == 100
        assert p11["markup_pct"] == 25.0
        assert p11["markup_prev_pct"] == 20.0
        assert p11["markup_delta_pp"] == 5.0
        assert p11["markup_min_90d"] == 10.0
        assert p11["markup_max_90d"] == 30.0
        assert p11["ageing_days"] == 0
        assert p11["last_sale_at"].startswith("2026-09-30")

        p12 = _by_key(body)["12"]
        assert p12["units_30d"] == 0
        assert p12["markup_pct"] is None
        assert p12["ageing_days"] == 82
        # Never sold: ageing counts from the publication's start.
        p13 = _by_key(body)["13"]
        assert p13["last_sale_at"] is None
        assert p13["ageing_days"] == 121

    def test_daily_series_cover_90_days_ending_on_date_to(self, client, admin_auth_headers, board_data):
        p11 = _by_key(_get(client, admin_auth_headers))["11"]

        assert len(p11["series_units_90d"]) == 90
        assert p11["series_units_90d"][-1] == 2
        assert p11["series_units_90d"][-6] == 1  # 09-25
        assert p11["series_markup_90d"][-1] == 30.0
        assert p11["series_markup_90d"][-2] is None  # no sale, no markup -- never 0

    def test_default_sort_is_gross_desc_and_pages(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, limit=1, offset=1)

        assert body["total"] == 4
        assert [row["key"] for row in body["rows"]] == ["14"]
        assert body["with_sales_count"] == 2

    def test_pages_hand_out_each_row_once_even_when_every_row_ties(self, client, admin_auth_headers, board_data):
        """Three of the four rows tie on units_24h (0: only p11 sold in the
        last 24h); pages of one row must still return each exactly once."""
        keys = [
            row["key"]
            for offset in range(4)
            for row in _get(client, admin_auth_headers, sort="units_24h", limit=1, offset=offset)["rows"]
        ]

        assert sorted(keys) == ["11", "12", "13", "14"]

    def test_units_24h_come_from_orders(self, db, client, admin_auth_headers, board_data):
        order_id = 2000012345678901
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=NOW,
                date_created=NOW,
                seller_id=999,
                currency_id="ARS",
            )
        )
        db.add(MlOrderItemOps(order_id=order_id, item_id="MLA1", quantity=4, unit_price=100))
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id="MLA1",
                costo_origen=10,
                moneda="ARS",
                costo_unitario_ars=10,
                iva_pct=21,
                precio_unitario=100,
                fuente="t",
                producto_item_id=11,
            )
        )
        db.add(
            MlGroupMetrics(
                group_key=f"o:{order_id}",
                gauss_status="ok",
                member_order_ids=[order_id],
                group_date=NOW - timedelta(hours=2),
                formula_version=1,
                computed_at=NOW,
            )
        )
        db.commit()

        p11 = _by_key(_get(client, admin_auth_headers))["11"]

        # 4 from this order + the 2 that `board_data` sold today at 15:00 UTC
        # (3 hours before NOW): the 24h window and the 3d window read the
        # same sales, so 24h can never exceed 3d.
        assert p11["units_24h"] == 6
        assert p11["units_24h"] <= p11["units_3d"]


class TestPublications:
    def test_group_by_publication(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, group_by="publication")

        rows = _by_key(body)
        assert set(rows) == {"MLA1", "MLA2", "MLA3", "MLA4", "MLA5"}
        assert rows["MLA1"]["units"] == 5
        assert rows["MLA1"]["product_item_id"] == 11
        assert rows["MLA1"]["status"] == "active"
        assert rows["MLA1"]["listing_type"] == "clasica"
        assert rows["MLA1"]["is_full"] is True
        assert rows["MLA1"]["store_id"] == 57997
        assert rows["MLA2"]["status"] == "paused"
        assert rows["MLA4"]["is_catalog"] is True
        assert rows["MLA1"]["thumbnail"] == "https://http2.mlstatic.com/MLA1.jpg"

    def test_a_product_row_shows_the_thumbnail_of_its_best_selling_publication(
        self, client, admin_auth_headers, board_data
    ):
        assert _by_key(_get(client, admin_auth_headers))["11"]["thumbnail"] == "https://http2.mlstatic.com/MLA1.jpg"

    def test_nested_publications_of_a_product_mark_the_best(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/products/11/publications", headers=admin_auth_headers)

        assert resp.status_code == 200
        pubs = {p["key"]: p for p in resp.json()["rows"]}
        assert set(pubs) == {"MLA1", "MLA2"}
        assert pubs["MLA1"]["is_best"] is True
        assert pubs["MLA2"]["is_best"] is False
        assert pubs["MLA2"]["markup_pct"] == 10.0


class TestFilters:
    def test_store(self, client, admin_auth_headers, board_data):
        assert set(_by_key(_get(client, admin_auth_headers, stores="2645"))) == {"12"}

    def test_publication_status_narrows_the_product_row_too(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, pub_status="paused")

        assert set(_by_key(body)) == {"11"}
        assert _by_key(body)["11"]["units"] == 1

    def test_publication_type(self, client, admin_auth_headers, board_data):
        assert set(_by_key(_get(client, admin_auth_headers, pub_type="premium"))) == {"11"}
        assert set(_by_key(_get(client, admin_auth_headers, pub_type="catalogo"))) == {"13"}
        assert set(_by_key(_get(client, admin_auth_headers, pub_type="full"))) == {"11"}

    def test_excluding_paused_hides_only_the_paused_publication(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, pub_status_exclude="paused")

        assert set(_by_key(body)) == {"11", "12", "13", "14"}
        # p11 keeps MLA1 (active) but loses MLA2's paused unit and gross.
        assert _by_key(body)["11"]["units"] == 5
        assert _by_key(body)["11"]["publications_count"] == 1

    def test_excluding_active_leaves_only_the_paused_pair(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, pub_status_exclude="active")

        assert set(_by_key(body)) == {"11"}
        assert _by_key(body)["11"]["units"] == 1

    def test_excluding_a_type(self, client, admin_auth_headers, board_data):
        assert set(_by_key(_get(client, admin_auth_headers, pub_type_exclude="catalogo"))) == {"11", "12", "14"}
        # MLA1 is also Full: excluding Full drops it, MLA2 keeps p11 alive.
        body = _get(client, admin_auth_headers, pub_type_exclude="full")
        assert _by_key(body)["11"]["units"] == 1
        # Exclusion matches ANY excluded type: premium or catalogo.
        body = _get(client, admin_auth_headers, pub_type_exclude="premium,catalogo")
        assert set(_by_key(body)) == {"11", "12", "14"}
        assert _by_key(body)["11"]["units"] == 5

    def test_exclusion_combines_with_include_stores_and_brands(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, stores="57997", pub_status_exclude="paused")
        assert set(_by_key(body)) == {"11", "13"}
        assert _by_key(body)["11"]["units"] == 5
        body = _get(client, admin_auth_headers, marcas="epson", pub_type_exclude="full", pub_status="paused")
        assert set(_by_key(body)) == {"11"}
        assert _by_key(body)["11"]["units"] == 1
        assert _get(client, admin_auth_headers, marcas="lenovo", pub_status_exclude="active")["rows"] == []

    def test_facet_counts_ignore_their_own_excluded_axis(self, client, admin_auth_headers, board_data):
        facets = _get(client, admin_auth_headers, pub_status_exclude="paused", pub_type_exclude="catalogo")["facets"]

        # Each group counts what it hides (own axis ignored) but sees the other's exclusion: no premium.
        assert facets["pub_status"] == {"active": 3, "paused": 1}
        assert facets["pub_type"] == {"clasica": 4, "catalogo": 1, "full": 1}

    def test_other_axes_see_the_exclusions(self, client, admin_auth_headers, board_data):
        facets = _get(client, admin_auth_headers, pub_status_exclude="paused", pub_type_exclude="catalogo")["facets"]

        assert facets["stores"] == {"57997": 1, "2645": 1, "144": 1}
        assert facets["stores_total"] == 3

    def test_nested_publications_honour_the_exclusion(self, client, admin_auth_headers, board_data):
        resp = client.get(
            f"{URL}/products/11/publications", params={"pub_status_exclude": "paused"}, headers=admin_auth_headers
        )

        assert resp.status_code == 200
        assert {p["key"] for p in resp.json()["rows"]} == {"MLA1"}

    def test_export_honours_the_exclusion(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/export", params={"pub_status_exclude": "active"}, headers=admin_auth_headers)

        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert len(rows) == 1

    @pytest.mark.parametrize("params", [{"pub_status_exclude": "borrada"}, {"pub_type_exclude": "nope"}])
    def test_unknown_exclusions_are_422(self, client, admin_auth_headers, board_data, params):
        assert client.get(URL, params=params, headers=admin_auth_headers).status_code == 422

    @pytest.mark.parametrize(
        "params",
        [
            {"pub_status": "paused", "pub_status_exclude": "paused,closed"},
            {"pub_type": "full,premium", "pub_type_exclude": "full"},
        ],
    )
    def test_a_value_in_include_and_exclude_is_422_with_a_clear_message(
        self, client, admin_auth_headers, board_data, params
    ):
        resp = client.get(URL, params=params, headers=admin_auth_headers)

        assert resp.status_code == 422
        assert "incluir y excluir" in resp.json()["error"]["message"]

    def test_product_facets_and_search(self, client, admin_auth_headers, board_data):
        assert set(_by_key(_get(client, admin_auth_headers, marcas="epson"))) == {"11"}
        assert set(_by_key(_get(client, admin_auth_headers, subcategorias="2"))) == {"12"}
        assert set(_by_key(_get(client, admin_auth_headers, q="lenovo"))) == {"12"}
        assert set(_by_key(_get(client, admin_auth_headers, q="MLA5"))) == {"14"}
        assert set(_by_key(_get(client, admin_auth_headers, q="SKU-13"))) == {"13"}

    def test_alerts(self, client, admin_auth_headers, board_data):
        assert set(_by_key(_get(client, admin_auth_headers, alerts="sin_ventas_30d"))) == {"12", "13"}
        assert set(_by_key(_get(client, admin_auth_headers, alerts="ageing_60d"))) == {"12", "13"}
        assert set(_by_key(_get(client, admin_auth_headers, alerts="margen_cayendo"))) == {"14"}

    def test_facet_counts_ignore_their_own_axis(self, client, admin_auth_headers, board_data):
        facets = _get(client, admin_auth_headers, stores="2645")["facets"]

        assert facets["stores"] == {"57997": 2, "2645": 1, "144": 1}
        assert facets["stores_total"] == 4
        assert facets["pub_status"] == {"active": 1}
        assert facets["alerts"] == {"sin_ventas_30d": 1, "ageing_60d": 1, "margen_cayendo": 0}

    def test_dates_and_compare_with_last_year(self, client, admin_auth_headers, board_data):
        body = _get(
            client, admin_auth_headers, date_from="2026-09-15", date_to="2026-09-30", comparar_con="anio_anterior"
        )

        assert body["period"]["prev_from"] == "2025-09-15"
        assert body["period"]["prev_to"] == "2025-09-30"
        assert _by_key(body)["11"]["units"] == 6
        assert _by_key(body)["11"]["markup_prev_pct"] is None

    @pytest.mark.parametrize(
        "params",
        [
            {"group_by": "marca"},
            {"comparar_con": "ayer"},
            {"date_from": "2026-09-30", "date_to": "2026-09-01"},
            {"sort": "nope"},
            {"stores": "abc"},
            {"alerts": "nope"},
            {"pub_status": "borrada"},
        ],
    )
    def test_bad_params_are_422(self, client, admin_auth_headers, board_data, params):
        assert client.get(URL, params=params, headers=admin_auth_headers).status_code == 422


class TestKpis:
    def test_period_totals_deltas_and_series(self, client, admin_auth_headers, board_data):
        kpis = _get(client, admin_auth_headers)["kpis"]

        # Period: p11 (6 u, 600, tg 100 / c 400) + p14 (1 u, 150, tg 10 / c 100)
        # Previous: p11 (1 u, 100, 20/100) + p14 (1 u, 150, 20/100)
        assert kpis["units"]["value"] == 7
        assert kpis["units"]["delta_pct"] == 250.0
        assert kpis["gross"]["value"] == 750
        assert kpis["gross"]["delta_pct"] == 200.0
        assert kpis["total_gauss"]["value"] == 110
        assert kpis["markup"]["value"] == 22.0
        assert kpis["markup"]["delta_pp"] == 2.0
        assert len(kpis["units"]["series"]) == 30
        # "rows": products, or publications when grouped by publication.
        assert kpis["rows_with_sales"] == {"value": 2, "of_total": 4}
        assert "products_with_sales" not in kpis
        assert kpis["ageing"]["over_60"] == 2
        # The ageing bar's three segments: <= 30 / 31-60 / > 60 days.
        assert (kpis["ageing"]["up_to_30"], kpis["ageing"]["from_31_to_60"]) == (2, 0)

    def test_the_ageing_buckets_are_all_required(self):
        """No defaults that could quietly report 0 for a bucket nobody filled."""
        from app.routers.ml_metricas import KpiAgeing

        for name in ("up_to_30", "from_31_to_60", "over_60"):
            assert KpiAgeing.model_fields[name].is_required(), name


class TestExport:
    def test_export_never_builds_sparkline_series(self, client, admin_auth_headers, board_data, query_counter):
        """The CSV has no sparklines: the 90-day daily series (one GROUP BY
        day per page of rows) is the board's most expensive per-page read and
        the export must not pay for it."""
        with query_counter() as counter:
            resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        assert resp.status_code == 200
        series = [s for s in counter.statements if "group by fp.rk, board_lines.day" in s]
        assert series == []

    def test_export_reads_rows_in_bounded_pages(
        self, client, admin_auth_headers, board_data, query_counter, monkeypatch
    ):
        from app.routers import ml_metricas

        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 2)
        with query_counter() as counter:
            resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert len(rows) == 4
        # ONE ordered-keys read, then each page fetched by its keys (2 + 2).
        key_lists = [s for s in counter.statements if "limit" in s and "board_rows" in s]
        pages = [s for s in counter.statements if "board_rows.rk in" in s]
        assert len(key_lists) == 1
        assert len(pages) == 2

    def test_csv_holds_every_filtered_row(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/export", params={**CATALOG, "stores": "57997"}, headers=admin_auth_headers)

        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert {row["Producto"] for row in rows} == {"Impresora Epson L3250", "Taladro DeWalt"}


class TestDateRangeBounds:
    """The KPI daily series has one entry per day of the period: an unbounded
    range (0001-01-02..9999-12-31) is millions of entries in memory. The
    period is capped and both ends must be sane dates."""

    @pytest.mark.parametrize(
        "params",
        [
            {"date_from": "0001-01-02", "date_to": "9999-12-31"},
            {"date_from": "2025-01-01", "date_to": "2026-01-02"},  # 367 days
            {"date_from": "1999-12-31", "date_to": "2000-01-31"},  # before the floor
            {"date_from": "2101-01-01", "date_to": "2101-01-31"},  # after the ceiling
            {"date_to": "0001-01-01"},
        ],
    )
    def test_out_of_bounds_is_422(self, client, admin_auth_headers, board_data, params):
        for url in (URL, f"{URL}/export", f"{URL}/products/11/publications"):
            assert client.get(url, params=params, headers=admin_auth_headers).status_code == 422, url

    def test_a_full_year_is_accepted(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, date_from="2025-10-01", date_to="2026-09-30")

        assert len(body["kpis"]["units"]["series"]) == 365


class TestExportIsSafeForSpreadsheets:
    """Titles come from Mercado Libre and the ERP: a cell starting with
    `= + - @`, a tab or a CR is run as a formula by Excel/Sheets. Every
    free-text cell of the CSV is defused with a leading quote."""

    PREFIXES = ["=", "+", "-", "@", "\t", "\r"]

    def test_free_text_cells_starting_like_a_formula_are_defused(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_metricas.ver")
        for i, prefix in enumerate(self.PREFIXES):
            item_id = 7100 + i
            db.add(
                ProductoERP(
                    item_id=item_id,
                    codigo=f"{prefix}SKU{i}",
                    descripcion=f'{prefix}HYPERLINK("http://x")',
                    marca=f"{prefix}Marca",
                    categoria="Cat",
                    subcategoria_id=1,
                )
            )
            db.flush()
            _pub(db, 7100 + i, f"MLA71{i}", item_id, 57997)
        db.commit()

        resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert len(rows) == len(self.PREFIXES)
        for row in rows:
            for column in ("Producto", "SKU", "Marca"):
                assert row[column].startswith("'"), (column, row[column])


class TestExportStreamsWithShortSessions:
    """The CSV outlives the request handler: holding the request session (and
    its pooled connection) while the client downloads is the QueuePool
    incident of PR #811. Each page runs on its own short session; the request
    session is closed before the first byte; a page failing mid-stream ends
    the file with an explicit line instead of a silently truncated file."""

    def test_each_page_runs_in_its_own_short_session(
        self, client, admin_auth_headers, board_data, bg_sessions, monkeypatch
    ):
        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 2)

        resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        assert resp.status_code == 200
        assert len(list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))) == 4
        assert bg_sessions["open"] == bg_sessions["close"] == 2  # keys + page 1, then page 2
        assert bg_sessions["max_open"] == 1

    def test_the_page_work_never_runs_on_the_request_session(
        self, db, client, admin_auth_headers, board_data, bg_sessions, monkeypatch
    ):
        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 2)
        used = []
        real_init = board.Board.__init__

        def spy(self, session, *args, **kwargs):
            used.append(session)
            real_init(self, session, *args, **kwargs)

        monkeypatch.setattr(board.Board, "__init__", spy)

        assert client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers).status_code == 200
        assert used and all(s is not db and any(s is o for o in bg_sessions["sessions"]) for s in used)

    def test_the_request_session_is_closed_before_the_stream(
        self, db, client, admin_auth_headers, board_data, bg_sessions, monkeypatch
    ):
        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 2)
        timeline = []
        real_close = db.close
        monkeypatch.setattr(
            db, "close", lambda: (timeline.append(("request_close", bg_sessions["open"])), real_close())[1]
        )

        assert client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers).status_code == 200
        # Closed right after page 1 was read, before page 2's session opened.
        assert timeline and timeline[0] == ("request_close", 1)

    def test_a_page_failing_mid_stream_ends_the_file_with_an_error_line(
        self, client, admin_auth_headers, board_data, bg_sessions, monkeypatch
    ):
        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 2)
        bg_sessions["fail_on_open"] = 2

        resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        assert resp.status_code == 200
        lines = resp.content.decode("utf-8-sig").splitlines()
        assert lines[-1] == "# ERROR: exportación incompleta — 2 de 4 filas exportadas. Volvé a intentar."
        assert len(lines[1:-1]) == 2

    def test_a_complete_export_has_no_error_line(self, client, admin_auth_headers, board_data):
        text = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers).content.decode("utf-8-sig")
        assert "# ERROR" not in text


class TestExportKeysAreFixedUpFront:
    def test_a_change_between_pages_never_repeats_or_drops_a_row(
        self, db, client, admin_auth_headers, board_data, bg_sessions, monkeypatch
    ):
        """The export fixes its ORDERED list of row keys in its first short
        transaction and then fetches each page BY KEY. With OFFSET over a
        fresh board per page, a sale landing between pages reordered the set:
        here product 13 jumps to the top after page 1, which under OFFSET
        repeated product 14 and dropped product 13. A row is written with its
        values as of its own page."""
        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 2)

        def big_sale_for_13(opened: int) -> None:
            if opened == 2:
                _day(db, 13, "MLA4", date(2026, 9, 29), 50, "100000", "1000", "5000")
                db.flush()

        bg_sessions["on_open"] = big_sale_for_13

        resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        products = [r["Producto"] for r in csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";")]
        assert products == [
            "Impresora Epson L3250",
            "Router TP-Link AX55",
            "Notebook Lenovo V15",
            "Taladro DeWalt",
        ]

    def test_more_rows_than_the_cap_is_422_before_any_byte(self, client, admin_auth_headers, board_data, monkeypatch):
        monkeypatch.setattr(ml_metricas, "EXPORT_MAX_ROWS", 3)

        resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        assert resp.status_code == 422


class TestExportEdges:
    def test_an_empty_scope_is_a_header_only_file(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/export", params={"q": "no-existe-nada"}, headers=admin_auth_headers)

        assert resp.status_code == 200
        lines = resp.content.decode("utf-8-sig").splitlines()
        assert len(lines) == 1 and lines[0].startswith("Producto;SKU;Marca;MLA;")

    @staticmethod
    def _export_rows(client, headers) -> list:
        resp = client.get(f"{URL}/export", params=CATALOG, headers=headers)
        assert resp.status_code == 200
        return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))

    def test_exactly_the_cap_exports_every_row(self, client, admin_auth_headers, board_data, monkeypatch):
        """The cap and the page size come from the fixture's own row count, so
        the test does not silently depend on how many rows board_data seeds;
        the exact ordered rows prove the page boundary neither repeats nor
        drops one."""
        full = self._export_rows(client, admin_auth_headers)
        assert len(full) >= 2, "the fixture must span more than one page"
        monkeypatch.setattr(ml_metricas, "EXPORT_MAX_ROWS", len(full))
        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", len(full) - 1)

        rows = self._export_rows(client, admin_auth_headers)

        assert [(r["Producto"], r["MLA"]) for r in rows] == [(r["Producto"], r["MLA"]) for r in full]

    def test_one_over_the_cap_is_422_with_the_reason(self, client, admin_auth_headers, board_data, monkeypatch):
        baseline = self._export_rows(client, admin_auth_headers)
        assert len(baseline) >= 2, "the fixture must seed enough rows for a positive cap"
        cap = len(baseline) - 1
        monkeypatch.setattr(ml_metricas, "EXPORT_MAX_ROWS", cap)

        resp = client.get(f"{URL}/export", params=CATALOG, headers=admin_auth_headers)

        assert resp.status_code == 422
        assert resp.json()["error"]["message"] == (
            f"Son más de {cap} filas, demasiadas para exportar de una vez. Acotá los filtros (tienda, marca, búsqueda...)."
        )


class TestFreshness:
    def test_refreshed_at_is_the_last_complete_sales_sync(self, db, client, admin_auth_headers, board_data):
        """No summary table to stamp: "actualizado hace X" is when the sales
        were last brought up to date, the same source as Ventas ML's
        sync-status (the sweep or the activity drain, never the backfill)."""
        from app.models.ml_orders_ops import MlOpsSyncCursor

        db.add(MlOpsSyncCursor(name="sweep", last_success_at=NOW - timedelta(minutes=7)))
        db.add(MlOpsSyncCursor(name="ml_activity", last_success_at=NOW - timedelta(minutes=3)))
        db.add(MlOpsSyncCursor(name="backfill", last_success_at=NOW))
        db.commit()

        body = _get(client, admin_auth_headers)

        assert datetime.fromisoformat(body["refreshed_at"]) == NOW - timedelta(minutes=3)

    def test_refreshed_at_is_null_before_any_sync(self, client, admin_auth_headers, board_data):
        assert _get(client, admin_auth_headers)["refreshed_at"] is None


class TestMoneyHasTwoDecimals:
    def test_no_money_value_in_the_response_has_more_than_two_decimals(self, db, client, admin_auth_headers, rol_admin):
        """One order, three items of equal frozen cost on a Total Gauss of
        100: each product gets 33.33... Filtered to ONE product, every money
        value the board sends -- rows, KPIs and their daily series -- is
        rounded to the cent."""
        _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        for item_id in (41, 42, 43):
            _producto(db, item_id, f"Producto tercio {item_id}", "Tercio")
        db.flush()
        seed_sale(
            db,
            2000091000000001,
            NOW - timedelta(hours=3),
            [Line(p, f"MLA4{p}", 1, Decimal("33.34"), Decimal("10")) for p in (41, 42, 43)],
            tg="100.00",
            costo="30.00",
        )
        db.commit()

        body = _get(client, admin_auth_headers, q="Producto tercio 41")

        kpis = body["kpis"]
        money = [kpis["gross"]["value"], kpis["total_gauss"]["value"], *kpis["gross"]["series"]]
        money += kpis["total_gauss"]["series"]
        for row in body["rows"]:
            money += [row["gross"], row["total_gauss"]]
        assert kpis["total_gauss"]["value"] == 33.33
        for value in money:
            assert value is None or Decimal(repr(value)) == Decimal(repr(value)).quantize(Decimal("0.01")), value


class TestSoloConVentas:
    """ODD "Período y stock" PS1: "Solo con ventas en el período" (ON by
    default) keeps only the ROWS with a sale in the selected period; it
    filters which rows, never their numbers -- a product sold today still
    shows its 30-day window, other publications' sales included."""

    TODAY = {"date_from": "2026-09-30", "date_to": "2026-09-30"}

    @staticmethod
    def _board(client, headers, **params):
        resp = client.get(URL, params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_by_default_today_shows_only_what_sold_today_with_its_full_windows(
        self, client, admin_auth_headers, board_data
    ):
        body = self._board(client, admin_auth_headers, **self.TODAY)

        assert set(_by_key(body)) == {"11"}
        p11 = _by_key(body)["11"]
        assert p11["units"] == 2
        # 30d keeps the 09-20 sale (MLA1) and the 09-25 one on ANOTHER
        # publication (MLA2): the toggle filters rows, not pairs or days.
        assert p11["units_30d"] == 6
        assert p11["units_7d"] == 3
        assert p11["publications_count"] == 2
        assert p11["markup_min_90d"] == 10.0

    def test_kpis_and_chips_follow_the_same_rows(self, client, admin_auth_headers, board_data):
        body = self._board(client, admin_auth_headers, **self.TODAY)

        assert body["total"] == 1
        assert body["kpis"]["rows_with_sales"] == {"value": 1, "of_total": 1}
        assert body["facets"]["stores"] == {"57997": 1}
        assert body["facets"]["stores_total"] == 1
        assert body["facets"]["alerts"]["sin_ventas_30d"] == 0

    def test_off_shows_the_whole_catalog(self, client, admin_auth_headers, board_data):
        body = self._board(client, admin_auth_headers, solo_con_ventas="false", **self.TODAY)

        assert set(_by_key(body)) == {"11", "12", "13", "14"}
        assert body["kpis"]["rows_with_sales"] == {"value": 1, "of_total": 4}

    def test_grouped_by_publication_it_keeps_the_publications_that_sold(self, client, admin_auth_headers, board_data):
        body = self._board(client, admin_auth_headers, group_by="publication", **self.TODAY)

        assert set(_by_key(body)) == {"MLA1"}
        assert _by_key(body)["MLA1"]["units_30d"] == 5

    def test_the_export_follows_it(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/export", params=self.TODAY, headers=admin_auth_headers)

        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert [row["Producto"] for row in rows] == ["Impresora Epson L3250"]

    def test_a_shown_product_lists_all_its_publications(self, client, admin_auth_headers, board_data):
        """The row-level filters already let the product through: its
        sub-rows are every publication that passes the pair filters, so they
        add up to the product row (MLA2 sold this month, not today)."""
        resp = client.get(f"{URL}/products/11/publications", params=self.TODAY, headers=admin_auth_headers)

        assert resp.status_code == 200
        assert {p["key"] for p in resp.json()["rows"]} == {"MLA1", "MLA2"}

    def test_an_unknown_value_is_422(self, client, admin_auth_headers, board_data):
        assert client.get(URL, params={"solo_con_ventas": "quizas"}, headers=admin_auth_headers).status_code == 422


@pytest.fixture()
def stock_data(db, board_data):
    """`board_data` with the ERP stock (`productos_erp.stock`, deposit 1):
    p11 5, p12 0, p13 3, p14 unknown (NULL)."""
    for item_id, stock in ((11, 5), (12, 0), (13, 3), (14, None)):
        db.query(ProductoERP).filter(ProductoERP.item_id == item_id).update({"stock": stock})
    db.commit()


class TestStock:
    """ODD "Período y stock" PS2: the row's stock is `productos_erp.stock` of
    its product; the "Con stock" / "Sin stock" / "Sin dato" chips filter in
    SQL, so rows, KPIs, chips and the CSV agree."""

    def test_each_row_shows_its_products_stock(self, client, admin_auth_headers, stock_data):
        rows = _by_key(_get(client, admin_auth_headers))

        assert {key: row["stock"] for key, row in rows.items()} == {"11": 5, "12": 0, "13": 3, "14": None}

    def test_a_publication_row_shows_its_products_stock(self, client, admin_auth_headers, stock_data):
        rows = _by_key(_get(client, admin_auth_headers, group_by="publication"))

        assert rows["MLA1"]["stock"] == 5
        assert rows["MLA2"]["stock"] == 5
        assert rows["MLA3"]["stock"] == 0
        assert rows["MLA5"]["stock"] is None

    def test_the_chips_count_rows_by_stock(self, client, admin_auth_headers, stock_data):
        facets = _get(client, admin_auth_headers)["facets"]

        assert facets["stock"] == {"con_stock": 2, "sin_stock": 1, "sin_dato": 1}

    def test_including_and_excluding(self, client, admin_auth_headers, stock_data):
        assert set(_by_key(_get(client, admin_auth_headers, stock="sin_stock"))) == {"12"}
        assert set(_by_key(_get(client, admin_auth_headers, stock="con_stock"))) == {"11", "13"}
        assert set(_by_key(_get(client, admin_auth_headers, stock="sin_stock,sin_dato"))) == {"12", "14"}
        assert set(_by_key(_get(client, admin_auth_headers, stock_exclude="con_stock"))) == {"12", "14"}
        assert set(_by_key(_get(client, admin_auth_headers, stock_exclude="sin_dato"))) == {"11", "12", "13"}

    def test_a_negative_stock_is_sin_stock(self, db, client, admin_auth_headers, stock_data):
        db.query(ProductoERP).filter(ProductoERP.item_id == 13).update({"stock": -2})
        db.commit()

        assert set(_by_key(_get(client, admin_auth_headers, stock="sin_stock"))) == {"12", "13"}

    def test_a_product_missing_from_the_erp_is_sin_dato(self, db, client, admin_auth_headers, stock_data):
        _day(db, 99, "MLA99", date(2026, 9, 29), 1, "100", "10", "50")
        db.commit()

        body = _get(client, admin_auth_headers, stock="sin_dato")

        assert set(_by_key(body)) == {"14", "99"}
        assert _by_key(body)["99"]["stock"] is None

    def test_kpis_and_other_chips_follow_the_stock_filter(self, client, admin_auth_headers, stock_data):
        body = _get(client, admin_auth_headers, stock="con_stock")

        # p11 (6 u in the period) and p13 (never sold).
        assert body["total"] == 2
        assert body["kpis"]["units"]["value"] == 6
        assert body["kpis"]["rows_with_sales"] == {"value": 1, "of_total": 2}
        assert body["facets"]["stores"] == {"57997": 2}
        assert body["facets"]["alerts"]["sin_ventas_30d"] == 1
        # Its own chips ignore it: they keep showing what each would select.
        assert body["facets"]["stock"] == {"con_stock": 2, "sin_stock": 1, "sin_dato": 1}

    def test_the_stock_chips_see_the_other_filters(self, client, admin_auth_headers, stock_data):
        facets = _get(client, admin_auth_headers, stores="57997")["facets"]

        assert facets["stock"] == {"con_stock": 2, "sin_stock": 0, "sin_dato": 0}

    def test_solo_con_ventas_and_sin_stock_is_what_to_rebuy(self, db, client, admin_auth_headers, stock_data):
        db.query(ProductoERP).filter(ProductoERP.item_id == 11).update({"stock": 0})
        db.commit()

        resp = client.get(URL, params={"stock": "sin_stock"}, headers=admin_auth_headers)

        assert set(_by_key(resp.json())) == {"11"}

    def test_a_shown_products_publications_carry_its_stock(self, client, admin_auth_headers, stock_data):
        resp = client.get(
            f"{URL}/products/11/publications", params={**CATALOG, "stock": "con_stock"}, headers=admin_auth_headers
        )

        assert resp.status_code == 200
        assert {p["key"]: p["stock"] for p in resp.json()["rows"]} == {"MLA1": 5, "MLA2": 5}

    def test_the_csv_has_the_stock_column(self, client, admin_auth_headers, stock_data):
        resp = client.get(f"{URL}/export", params={**CATALOG, "stock_exclude": "sin_stock"}, headers=admin_auth_headers)

        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert {row["Producto"]: row["Stock"] for row in rows} == {
            "Impresora Epson L3250": "5",
            "Taladro DeWalt": "3",
            "Router TP-Link AX55": "",
        }

    @pytest.mark.parametrize(
        "params",
        [
            {"stock": "nope"},
            {"stock_exclude": "agotado"},
            {"stock": "con_stock", "stock_exclude": "con_stock"},
        ],
    )
    def test_bad_values_are_422(self, client, admin_auth_headers, stock_data, params):
        assert client.get(URL, params=params, headers=admin_auth_headers).status_code == 422


class TestAgeing:
    """ODD "Período y stock" PS3: ageing chips with the KPI's buckets (<= 30,
    31-60, > 60 days since the last sale -- or since the publication started
    if it never sold), filtered in SQL. In `board_data`: p11 0 d, p14 20 d,
    p12 82 d, p13 121 d."""

    def test_the_chips_count_rows_by_ageing_bucket(self, client, admin_auth_headers, board_data):
        facets = _get(client, admin_auth_headers)["facets"]

        assert facets["ageing"] == {"up_to_30": 2, "from_31_to_60": 0, "over_60": 2}

    def test_including_and_excluding(self, client, admin_auth_headers, board_data):
        assert set(_by_key(_get(client, admin_auth_headers, ageing="over_60"))) == {"12", "13"}
        assert set(_by_key(_get(client, admin_auth_headers, ageing="up_to_30"))) == {"11", "14"}
        assert set(_by_key(_get(client, admin_auth_headers, ageing_exclude="over_60"))) == {"11", "14"}
        assert set(_by_key(_get(client, admin_auth_headers, ageing="up_to_30,over_60"))) == {"11", "12", "13", "14"}

    def test_the_middle_bucket(self, db, client, admin_auth_headers, board_data):
        _producto(db, 15, "Monitor Samsung", "Samsung")
        db.flush()
        _pub(db, 6, "MLA6", 15, 57997)
        _day(db, 15, "MLA6", date(2026, 8, 20), 1, "100", "10", "50")  # 41 days ago
        db.commit()

        body = _get(client, admin_auth_headers, ageing="from_31_to_60")

        assert set(_by_key(body)) == {"15"}
        assert _by_key(body)["15"]["ageing_days"] == 41
        assert body["facets"]["ageing"]["from_31_to_60"] == 1

    def test_the_over_60_chip_is_the_ageing_alert(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers)

        assert body["facets"]["ageing"]["over_60"] == body["facets"]["alerts"]["ageing_60d"]
        assert body["facets"]["ageing"]["over_60"] == body["kpis"]["ageing"]["over_60"]
        assert set(_by_key(_get(client, admin_auth_headers, ageing="over_60"))) == set(
            _by_key(_get(client, admin_auth_headers, alerts="ageing_60d"))
        )

    def test_kpis_follow_and_its_own_chips_ignore_it(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, ageing="over_60")

        assert body["total"] == 2
        assert body["kpis"]["ageing"] == {"avg_days": 101.5, "up_to_30": 0, "from_31_to_60": 0, "over_60": 2}
        assert body["kpis"]["units"]["value"] == 0
        assert body["facets"]["ageing"] == {"up_to_30": 2, "from_31_to_60": 0, "over_60": 2}
        assert body["facets"]["stores"] == {"57997": 1, "2645": 1}

    def test_ageing_and_stock_chips_see_each_other(self, client, admin_auth_headers, stock_data):
        assert _get(client, admin_auth_headers, ageing="over_60")["facets"]["stock"] == {
            "con_stock": 1,
            "sin_stock": 1,
            "sin_dato": 0,
        }
        assert _get(client, admin_auth_headers, stock="con_stock")["facets"]["ageing"] == {
            "up_to_30": 1,
            "from_31_to_60": 0,
            "over_60": 1,
        }

    def test_with_solo_con_ventas_on_stale_rows_are_hidden(self, client, admin_auth_headers, board_data):
        """The board never flips the toggle by itself: the page warns
        instead ("Ocultando productos sin ventas en el período")."""
        resp = client.get(URL, params={"ageing": "over_60"}, headers=admin_auth_headers)

        assert resp.json()["rows"] == []

    def test_the_export_follows_it(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/export", params={**CATALOG, "ageing": "over_60"}, headers=admin_auth_headers)

        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert {row["Producto"] for row in rows} == {"Notebook Lenovo V15", "Taladro DeWalt"}

    @pytest.mark.parametrize(
        "params",
        [{"ageing": "viejo"}, {"ageing_exclude": "90d"}, {"ageing": "over_60", "ageing_exclude": "over_60"}],
    )
    def test_bad_values_are_422(self, client, admin_auth_headers, board_data, params):
        assert client.get(URL, params=params, headers=admin_auth_headers).status_code == 422
