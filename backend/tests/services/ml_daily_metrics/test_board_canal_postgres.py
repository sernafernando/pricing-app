"""vpf-metricas-canal (T2): the Métricas ML board with `canal=fuera|todo`, on real Postgres, through the HTTP API.

Por fuera reads ONLY the PDF operations of #2291 (`ventas_fuera_operaciones` + `ventas_fuera_operacion_lineas`):
Total Gauss = precio - costo, costo = Costo D (precio_costo x 1.065, default) or precio_costo, markup = monto/costo - 1,
no commission nor shipping. Venta carries VAT like the ML Venta does: precio x (1 + the line's VAT), the product's
`productos_erp.iva`, or for a line without product the rate its document's header Importe leaves for it. Every
document, product and amount here is INVENTED. "Today" is 2026-09-30: the default period is 2026-09-01..30."""

from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator, Optional, Sequence

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea, VentaFueraPdfCarga
from app.routers import ml_metricas
from app.services.ml_daily_metrics import board
from app.services.sell_out.resumen import Remanente
from tests.services.ml_daily_metrics.seed import Line, seed_order
from tests.services.ml_daily_metrics.test_board_sell_in_out_postgres import CONSUMPTION_DDL

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
URL = "/api/ml-metricas/board"
PERMISOS = {"ml_metricas.ver", "ml_metricas.ver_ganancia", "ventas_fuera.ver_metricas_pdf"}
EMPRESA, VENDEDOR = "EMPRESA EJEMPLO SA", "Vendedor Uno"
MONITOR, LIBRO = 501, 502  # productos_erp: VAT 21% and 10.5%
CABLE = "7790000099999"  # a code productos_erp does not have


@dataclass(frozen=True)
class Ln:
    precio: str
    costo: str
    codigo: Optional[str] = None
    articulo: str = "Articulo"
    cantidad: str = "1"
    moneda: str = "ARS"


@pytest.fixture(scope="module")
def fuera_engine(board_pg_engine):
    """The board's tables plus #2291's operations tables and `productos_erp.iva` (the minimal copy lacks it)."""
    tables = [VentaFueraPdfCarga.__table__, VentaFueraOperacion.__table__, VentaFueraOperacionLinea.__table__]
    created = [t for t in tables if not sa_inspect(board_pg_engine).has_table(t.name)]
    for table in created:
        table.create(board_pg_engine)
    added_iva = "iva" not in {c["name"] for c in sa_inspect(board_pg_engine).get_columns("productos_erp")}
    if added_iva:
        with board_pg_engine.begin() as conn:
            conn.execute(text("ALTER TABLE productos_erp ADD COLUMN iva DOUBLE PRECISION"))
    yield board_pg_engine
    for table in reversed(created):
        table.drop(board_pg_engine, checkfirst=True)
    if added_iva:
        with board_pg_engine.begin() as conn:
            conn.execute(text("ALTER TABLE productos_erp DROP COLUMN IF EXISTS iva"))


@pytest.fixture()
def conn(fuera_engine):
    connection = fuera_engine.connect()
    transaction = connection.begin()
    # The sell in / sell out the profit view reads (stand-ins, dropped with the transaction): no fuera line has any.
    connection.execute(text(CONSUMPTION_DDL))
    yield connection
    transaction.rollback()
    connection.close()


@pytest.fixture()
def db(conn) -> Iterator[Session]:
    session = Session(bind=conn, autoflush=False)
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", False)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)
    # Full view: the PM scope tables are not part of this schema.
    monkeypatch.setattr(ml_metricas, "_scope_pairs", lambda db, user: None)
    # The monto total campaigns' remainder reads the sell out schema, not part of this one: none ends in the period.
    monkeypatch.setattr(board, "remanentes", lambda *args, **kwargs: Remanente(Decimal("0"), 0, 0))


def _client(conn, monkeypatch, permisos=PERMISOS) -> TestClient:
    app = FastAPI()
    app.include_router(ml_metricas.router, prefix="/api")

    def request_db() -> Iterator[Session]:
        session = Session(bind=conn, autoflush=False)
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def background_db() -> Iterator[Session]:
        session = Session(bind=conn, autoflush=False)
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(ml_metricas, "get_background_db", background_db)
    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=7, es_superadmin=False, activo=True, _permisos_cache=set(permisos)
    )
    return TestClient(app)


@pytest.fixture()
def client(conn, monkeypatch) -> TestClient:
    return _client(conn, monkeypatch)


def _products(db) -> None:
    for item_id, codigo, descripcion, marca, iva in (
        (MONITOR, "7790000000017", "Monitor Ejemplo 24", "MarcaUno", 21.0),
        (LIBRO, "7790000000024", "Libro Ejemplo", "MarcaDos", 10.5),
    ):
        db.execute(
            text(
                "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock, iva)"
                " VALUES (:i, :c, :d, :m, 'Cat', 1, 5, :iva)"
            ),
            {"i": item_id, "c": codigo, "d": descripcion, "m": marca, "iva": iva},
        )


_NUMEROS = iter(range(70001, 79999))
_ORDERS = iter(range(2000097000000001, 2000097000100000))


def _doc(
    db,
    fecha: date,
    importe: str,
    lines: Sequence[Ln],
    *,
    tipo: str = "Fc",
    condicion: Optional[str] = "01-Contado",
    recargo: str = "0",
    empresa: str = EMPRESA,
    vendedor: str = VENDEDOR,
) -> None:
    carga = VentaFueraPdfCarga(
        empresa=empresa, vendedor=None, desde=fecha, hasta=fecha, documentos=1, reemplazados=0, avisos=[]
    )
    db.add(carga)
    db.flush()
    op = VentaFueraOperacion(
        carga_id=carga.id,
        empresa=empresa,
        vendedor=vendedor,
        cliente="CLIENTE EJEMPLO",
        tipo=tipo,
        letra="A",
        punto_venta=9,
        numero=next(_NUMEROS),
        fecha=fecha,
        condicion_venta=condicion,
        importe=Decimal(importe),
        saldo=Decimal("0"),
        total_lineas=sum((Decimal(line.precio) for line in lines), Decimal("0")),
        recargo_financiero=Decimal(recargo),
    )
    db.add(op)
    db.flush()
    for renglon, line in enumerate(lines, start=1):
        db.add(
            VentaFueraOperacionLinea(
                operacion_id=op.id,
                renglon=renglon,
                codigo=line.codigo,
                articulo=line.articulo,
                cantidad=Decimal(line.cantidad),
                moneda=line.moneda,
                precio=Decimal(line.precio),
                precio_costo=Decimal(line.costo),
                precio_costo_pp=Decimal(line.costo),
            )
        )
    db.flush()


def _monitor(precio: str = "1000", costo: str = "800", cantidad: str = "1") -> Ln:
    return Ln(precio, costo, codigo="7790000000017", articulo="MONITOR EJEMPLO 24", cantidad=cantidad)


def _libro(precio: str = "2000", costo: str = "1500") -> Ln:
    return Ln(precio, costo, codigo="7790000000024", articulo="LIBRO EJEMPLO")


def _ml_sale(db, product: int, mla: str, day: date, gross: str = "200", tg: str = "30", costo: str = "100") -> None:
    """One ML order of 1 unit, accredited at 15:00 UTC on `day`, with its group row."""
    order_id = next(_ORDERS)
    accredited = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
    seed_order(db, order_id, accredited, [Line(product, mla, 1, Decimal(gross))], tg=tg, costo=costo)
    db.execute(
        text(
            "INSERT INTO ml_group_metrics (group_key, gauss_status, member_order_ids, group_date, formula_version, "
            "computed_at) VALUES (:gk, 'ok', CAST(:members AS BIGINT[]), :gd, 2, now())"
        ),
        {"gk": f"o:{order_id}", "members": "{" + str(order_id) + "}", "gd": accredited},
    )


def _pub(db, mlp_id: int, mla: str, item_id: int, store: int) -> None:
    db.add(
        MercadoLibreItemPublicado(
            mlp_id=mlp_id,
            mlp_publicationID=mla,
            item_id=item_id,
            mlp_official_store_id=store,
            mlp_lastStatusID=153,
            mlp_listing_type_id="gold_special",
            mlp_itemTitle=f"Titulo {mla}",
            mlp_start_time=datetime(2026, 6, 1),
        )
    )
    db.flush()


def _get(client: TestClient, endpoint: str = URL, **params) -> dict:
    resp = client.get(endpoint, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows(body: dict) -> dict:
    return {row["title"]: row for row in body["rows"]}


def _money(row: dict) -> tuple:
    return row["units"], row["gross"], row["total_gauss"], row["markup_pct"]


class TestFuera:
    def test_fuera_reads_only_the_pdf_operations_with_costo_d_by_default(self, client, db):
        """S1/S2: default costo_d = Precio Costo x 1.065; Total Gauss = precio - costo; markup = monto/costo - 1. The
        ML sale of the same product is not read."""
        _products(db)
        _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5))
        _doc(db, date(2026, 9, 10), "2420", [_monitor("2000", "1600", cantidad="2")])

        body = _get(client, canal="fuera")

        # costo D = 1600 x 1.065 = 1704; Total Gauss = 2000 - 1704 = 296; markup = 296 / 1704 = 17.37%
        assert [(r["product_item_id"], *_money(r)) for r in body["rows"]] == [(MONITOR, 2, 2420.0, 296.0, 17.4)]
        assert body["kpis"]["gross"]["value"] == 2420.0
        assert body["kpis"]["total_gauss"]["value"] == 296.0
        assert body["kpis"]["markup"]["value"] == 17.4

    def test_costo_takes_the_precio_costo(self, client, db):
        """S1: costo=costo is precio_costo as it is (markup = 2000 / 1600 - 1 = 25%)."""
        _products(db)
        _doc(db, date(2026, 9, 10), "2420", [_monitor("2000", "1600", cantidad="2")])

        body = _get(client, canal="fuera", costo="costo")

        assert [_money(r) for r in body["rows"]] == [(2, 2420.0, 400.0, 25.0)]

    def test_todo_sums_each_sale_with_its_own_rule(self, client, db):
        """S3: "in todo each sale uses its own rule and they are summed"; canal=ml stays the ML sale alone."""
        _products(db)
        _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5), gross="200", tg="30", costo="100")
        _doc(db, date(2026, 9, 10), "1210", [_monitor("1000", "800")])

        todo = _get(client, canal="todo")
        ml = _get(client, canal="ml")

        # ML: gross 200, Total Gauss 30, cost 100. Fuera: gross 1210 (with VAT), Total Gauss 1000 - 852 = 148.
        assert [_money(r) for r in todo["rows"]] == [(2, 1410.0, 178.0, round(178 / 952 * 100, 1))]
        assert todo["rows"][0]["publications_count"] == 1
        assert [_money(r) for r in ml["rows"]] == [(1, 200.0, 30.0, 30.0)]

    def test_empresa_and_vendedor_filter_fuera_only(self, client, db):
        """S4: "fuera filters empresa and vendedor", the stored text as-is; ignored for ML lines in todo."""
        _products(db)
        _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5), gross="200")
        _doc(db, date(2026, 9, 10), "1210", [_monitor("1000", "800")])
        _doc(
            db, date(2026, 9, 11), "484", [_monitor("400", "300")], empresa="OTRA EMPRESA SRL", vendedor="Vendedor Dos"
        )

        assert _get(client, canal="fuera", empresas="OTRA EMPRESA SRL")["kpis"]["gross"]["value"] == 484.0
        assert _get(client, canal="fuera", vendedores="Vendedor Uno")["kpis"]["gross"]["value"] == 1210.0
        assert _get(client, canal="fuera", empresas="OTRA EMPRESA SRL", vendedores="Vendedor Uno")["rows"] == []
        assert _get(client, canal="todo", empresas="OTRA EMPRESA SRL")["kpis"]["gross"]["value"] == 684.0

    def test_sin_producto_rows_appear(self, client, db):
        """S5: one row per code not in productos_erp and one per article text of a line without code; never under a
        marca filter; found by the search on their article or code."""
        _products(db)
        _doc(
            db,
            date(2026, 9, 10),
            "2041",
            [
                _monitor("1000", "800"),
                Ln("300", "150", codigo=CABLE, articulo="Cable Ejemplo", cantidad="2"),
                Ln("400", "0", articulo="Servicio Tecnico (Manual)"),
            ],
        )
        _doc(
            db,
            date(2026, 9, 12),
            "242",
            [Ln("100", "50", codigo=CABLE, articulo="Cable Ejemplo"), Ln("100", "0", articulo="Flete Ejemplo")],
        )

        rows = _rows(_get(client, canal="fuera"))

        assert {title: row["units"] for title, row in rows.items()} == {
            "Monitor Ejemplo 24": 1,
            "Cable Ejemplo": 3,
            "Servicio Tecnico (Manual)": 1,
            "Flete Ejemplo": 1,
        }
        assert rows["Cable Ejemplo"]["sku"] == CABLE
        assert len({row["key"] for row in rows.values()}) == 4
        assert all(
            rows[t]["product_item_id"] < 0 for t in ("Cable Ejemplo", "Servicio Tecnico (Manual)", "Flete Ejemplo")
        )
        assert list(_rows(_get(client, canal="fuera", marcas="MarcaUno"))) == ["Monitor Ejemplo 24"]
        assert list(_rows(_get(client, canal="fuera", q="cable"))) == ["Cable Ejemplo"]
        assert list(_rows(_get(client, canal="fuera", q=CABLE))) == ["Cable Ejemplo"]
        assert list(_rows(_get(client, canal="fuera", q="servicio"))) == ["Servicio Tecnico (Manual)"]

    def test_a_line_without_cost_counts_in_venta_but_not_in_total_gauss_nor_markup(self, client, db):
        """S8: cost 0 counts in Venta and units, left out of Total Gauss and markup."""
        _products(db)
        _doc(db, date(2026, 9, 10), "1815", [_monitor("1000", "800"), Ln("500", "0", articulo="Servicio Tecnico")])

        body = _get(client, canal="fuera", costo="costo")

        assert _money(_rows(body)["Servicio Tecnico"]) == (1, 605.0, 0.0, None)
        assert body["kpis"]["gross"]["value"] == 1815.0
        assert body["kpis"]["total_gauss"]["value"] == 200.0
        assert body["kpis"]["markup"]["value"] == 25.0

    def test_a_non_ars_line_counts_units_but_no_money(self, client, db):
        """S9: a non-ARS line counts units but 0 in Venta / Total Gauss (as ML)."""
        _products(db)
        _doc(db, date(2026, 9, 10), "60.50", [Ln("50", "40", codigo="7790000000017", moneda="USD")])

        body = _get(client, canal="fuera")

        assert [_money(r) for r in body["rows"]] == [(1, 0.0, 0.0, None)]

    def test_the_date_is_the_document_fecha_and_operations_count_documents(self, client, db):
        """S12: a fuera line's day is its document's `fecha`; the operations KPI counts fuera documents."""
        _products(db)
        _doc(db, date(2026, 9, 10), "2420", [_monitor("1000", "800"), _monitor("1000", "800")])
        _doc(db, date(2026, 9, 30), "1210", [_monitor("1000", "800")])
        _doc(db, date(2026, 8, 31), "1210", [_monitor("1000", "800")])

        body = _get(client, canal="fuera")
        august = _get(client, canal="fuera", date_from="2026-08-31", date_to="2026-08-31")

        assert body["kpis"]["operations"]["value"] == 2
        assert body["kpis"]["units"]["value"] == 3
        assert body["rows"][0]["last_sale_at"].startswith("2026-09-30")
        assert august["kpis"]["units"]["value"] == 1


class TestVentaWithVat:
    """S11: Venta of a fuera line carries VAT like the ML Venta: the product's `productos_erp.iva`, or the rate its
    document's header Importe leaves for the lines without product. Total Gauss and markup stay without VAT."""

    def test_a_matched_product_takes_its_own_vat(self, client, db):
        _products(db)
        _doc(db, date(2026, 9, 10), "2210", [_libro("2000", "1500")])

        row = _get(client, canal="fuera", costo="costo")["rows"][0]

        assert _money(row) == (1, 2210.0, 500.0, round(500 / 1500 * 100, 1))

    def test_a_manual_line_of_a_single_vat_document_takes_the_document_rate(self, client, db):
        _doc(db, date(2026, 9, 10), "605", [Ln("500", "400", articulo="Servicio Tecnico (Manual)")])

        row = _get(client, canal="fuera", costo="costo")["rows"][0]

        assert _money(row) == (1, 605.0, 100.0, 25.0)

    def test_an_unmatched_line_of_a_mixed_vat_document_takes_what_the_header_leaves(self, client, db):
        """Monitor at 21% (1000 -> 1210) and an unmatched cable at 10.5%: Importe 1541.50 leaves 331.50 for 300."""
        _products(db)
        _doc(
            db,
            date(2026, 9, 10),
            "1541.50",
            [_monitor("1000", "800"), Ln("300", "150", codigo=CABLE, articulo="Cable")],
        )

        rows = _rows(_get(client, canal="fuera"))

        assert rows["Monitor Ejemplo 24"]["gross"] == 1210.0
        assert rows["Cable"]["gross"] == 331.5

    def test_a_cheque_document_leaves_out_its_surcharge(self, client, db):
        """CHEQUE 30 D: Importe = lines x VAT x 1.04. Book (10.5%) 2000 -> 2210 and a manual freight at 21% 100 -> 121:
        Importe (2210 + 121) x 1.04 = 2424.24; the 4% surcharge never enters Venta (parent S12)."""
        _products(db)
        _doc(
            db,
            date(2026, 9, 10),
            "2424.24",
            [_libro("2000", "1500"), Ln("100", "0", articulo="Flete Ejemplo")],
            condicion="CHEQUE 30 D",
            recargo="84",
        )

        body = _get(client, canal="fuera")

        assert {title: row["gross"] for title, row in _rows(body).items()} == {
            "Libro Ejemplo": 2210.0,
            "Flete Ejemplo": 121.0,
        }
        assert body["kpis"]["gross"]["value"] == 2331.0


class TestMlOnlyParts:
    """S10: envios and publications are ML; store, status and type filters only touch ML lines."""

    def test_envios_is_empty_for_fuera_and_ml_only_in_todo(self, client, db):
        _products(db)
        _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5), gross="200")
        _doc(db, date(2026, 9, 10), "1210", [_monitor()])

        assert _get(client, f"{URL}/envios", canal="fuera") == {"rows": []}
        assert [r["gross"] for r in _get(client, f"{URL}/envios", canal="todo")["rows"]] == [200.0]

    def test_publications_are_empty_for_fuera_and_only_ml_in_todo(self, client, db):
        _products(db)
        _pub(db, 9001, "MLA9001", MONITOR, 57997)
        _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5), gross="200")
        _doc(db, date(2026, 9, 10), "1210", [_monitor()])
        path = f"{URL}/products/{MONITOR}/publications"

        assert _get(client, path, canal="fuera") == {"rows": []}
        assert [(r["mla"], r["gross"]) for r in _get(client, path, canal="todo")["rows"]] == [("MLA9001", 200.0)]

    def test_a_store_filter_in_todo_keeps_the_fuera_lines(self, client, db):
        _products(db)
        _pub(db, 9001, "MLA9001", MONITOR, 57997)
        _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5), gross="200")
        _doc(db, date(2026, 9, 10), "2210", [_libro()])

        rows = _rows(_get(client, canal="todo", stores="2645"))

        assert {title: row["gross"] for title, row in rows.items()} == {"Libro Ejemplo": 2210.0}


class TestSharedReaders:
    """The grouped view, its nodes and the CSV export read the same fuera lines."""

    def test_group_view_nodes_and_export_in_fuera(self, client, db):
        _products(db)
        _doc(
            db,
            date(2026, 9, 10),
            "1541.50",
            [_monitor("1000", "800"), Ln("300", "150", codigo=CABLE, articulo="Cable")],
        )

        nodes = _get(client, canal="fuera", group_by="group", dimension="marca")
        leaves = _get(client, f"{URL}/group-nodes", canal="fuera", dimension="marca", path=json.dumps(["MARCAUNO"]))
        resp = client.get(f"{URL}/export", params={"canal": "fuera"})

        assert sorted(r["gross"] for r in nodes["rows"]) == [331.5, 1210.0]
        # The brand's node opens into its categories: the monitor's one carries its fuera sale alone.
        assert [(r["title"], r["gross"]) for r in leaves["rows"]] == [("Cat", 1210.0)]
        assert resp.status_code == 200, resp.text
        lines = list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))
        by_title = {line[0]: line for line in lines[1:]}
        assert by_title["Cable"][lines[0].index("Facturado")] == "331,50"


class TestUnknownVenta:
    """S13: a derived rate counts only when it is a legal AR VAT rate (0, 2.5, 5, 10.5, 21, 27, +-0.1 pp); otherwise
    the line's with-VAT Venta is unknown and adds nothing. S14: the response counts those lines (canal != ml)."""

    def test_a_cheque_document_without_its_summary_leaves_the_manual_line_unknown_and_counted(self, client, db):
        """Loaded without the summary, the cheque document has no condicion de venta: its header still carries the
        x1.04, so the freight's derived rate is (2424.24 - 2210) / 100 - 1 = 114.24%, no AR VAT rate."""
        _products(db)
        _doc(
            db,
            date(2026, 9, 10),
            "2424.24",
            [_libro("2000", "1500"), Ln("100", "0", articulo="Flete Ejemplo")],
            condicion=None,
        )

        body = _get(client, canal="fuera")

        assert {title: row["gross"] for title, row in _rows(body).items()} == {
            "Libro Ejemplo": 2210.0,
            "Flete Ejemplo": 0.0,
        }
        assert body["kpis"]["gross"]["value"] == 2210.0
        assert body["kpis"]["venta_desconocida_lineas"] == 1

    def test_lines_without_a_rate_adding_up_to_zero_are_unknown_and_counted(self, client, db):
        """The lines without a known rate add up to precio 0 (+100 and -100): no rate can be derived."""
        _products(db)
        _doc(
            db,
            date(2026, 9, 10),
            "2210",
            [_libro("2000", "1500"), Ln("100", "0", articulo="Bonificable"), Ln("-100", "0", articulo="Bonificacion")],
        )

        body = _get(client, canal="todo")

        assert body["kpis"]["gross"]["value"] == 2210.0
        assert body["kpis"]["venta_desconocida_lineas"] == 2

    def test_the_count_follows_the_period_and_the_filters(self, client, db):
        _products(db)
        _doc(db, date(2026, 9, 10), "2424.24", [_libro(), Ln("100", "0", articulo="Flete Ejemplo")], condicion=None)
        _doc(db, date(2026, 8, 10), "2424.24", [_libro(), Ln("100", "0", articulo="Flete Ejemplo")], condicion=None)

        assert _get(client, canal="fuera")["kpis"]["venta_desconocida_lineas"] == 1
        assert _get(client, canal="fuera", empresas="OTRA EMPRESA SRL")["kpis"]["venta_desconocida_lineas"] == 0
        assert _get(client, canal="fuera", marcas="MarcaDos")["kpis"]["venta_desconocida_lineas"] == 0
        assert (
            _get(client, canal="fuera", date_from="2026-08-01", date_to="2026-08-31")["kpis"][
                "venta_desconocida_lineas"
            ]
            == 1
        )

    def test_a_legal_rate_within_a_tenth_of_a_point_is_taken(self, client, db):
        """Importe 120.95 for a manual 100: 20.95% is 21% within 0.1 pp, so Venta = the document's 120.95."""
        _doc(db, date(2026, 9, 10), "120.95", [Ln("100", "50", articulo="Servicio")])

        body = _get(client, canal="fuera")

        assert body["rows"][0]["gross"] == 120.95
        assert body["kpis"]["venta_desconocida_lineas"] == 0


class TestFueraFacets:
    """S15: /board carries the empresa and vendedor option lists of the fuera lines ONLY when canal != ml."""

    def _seed(self, db) -> None:
        _products(db)
        _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5))
        _doc(db, date(2026, 9, 10), "1210", [_monitor()])
        _doc(db, date(2026, 9, 11), "1210", [_monitor()], empresa="OTRA EMPRESA SRL", vendedor="Vendedor Dos")
        _doc(db, date(2026, 9, 12), "1210", [_monitor()], empresa="OTRA EMPRESA SRL", vendedor="Vendedor Tres")

    @pytest.mark.parametrize("canal", ["fuera", "todo"])
    def test_fuera_and_todo_carry_the_empresa_and_vendedor_options(self, client, db, canal):
        self._seed(db)

        facets = _get(client, canal=canal)["facets"]
        narrowed = _get(client, canal=canal, empresas="OTRA EMPRESA SRL")["facets"]

        assert facets["empresas"] == [EMPRESA, "OTRA EMPRESA SRL"]
        assert facets["vendedores"] == ["Vendedor Dos", "Vendedor Tres", VENDEDOR]
        # Each list keeps its own options and is narrowed by the other one.
        assert narrowed["empresas"] == [EMPRESA, "OTRA EMPRESA SRL"]
        assert narrowed["vendedores"] == ["Vendedor Dos", "Vendedor Tres"]

    def test_ml_carries_neither_the_options_nor_the_count(self, client, db):
        self._seed(db)

        body = _get(client, canal="ml")

        assert "empresas" not in body["facets"] and "vendedores" not in body["facets"]
        assert "venta_desconocida_lineas" not in body["kpis"]


# ── Regression tests from the independent verification: margin and permission gates on every endpoint,
# credit notes, cheque documents with mixed VAT rates and the legal-rate tolerance. ──

NO_MARGIN = PERMISOS - {"ml_metricas.ver_ganancia"}
NO_FUERA = PERMISOS - {"ventas_fuera.ver_metricas_pdf"}


@pytest.mark.parametrize("canal", ["fuera", "todo"])
def test_s7_margin_hidden_without_ver_ganancia(conn, db, monkeypatch, canal):
    _products(db)
    _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5))
    _doc(db, date(2026, 9, 10), "1210", [_monitor("1000", "800")])
    c = _client(conn, monkeypatch, NO_MARGIN)
    body = _get(c, canal=canal)
    row = body["rows"][0]
    assert row["gross"] > 0
    assert row["total_gauss"] is None and row["markup_pct"] is None
    k = body["kpis"]
    for key in ("total_gauss", "markup"):
        assert k.get(key) in (None, {}) or (isinstance(k[key], dict) and k[key].get("value") is None), (key, k[key])
    grouped = _get(c, canal=canal, group_by="group", dimension="marca")
    assert all(r["total_gauss"] is None for r in grouped["rows"])
    nodes = _get(c, f"{URL}/group-nodes", canal=canal, dimension="marca", path=json.dumps(["MARCAUNO"]))
    assert all(r["total_gauss"] is None for r in nodes["rows"])
    resp = c.get(f"{URL}/export", params={"canal": canal})
    assert resp.status_code == 200
    header = next(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))
    assert not any("gauss" in h.lower() or "markup" in h.lower() for h in header)
    assert c.get(URL, params={"canal": canal, "sort": "markup"}).status_code == 403


@pytest.mark.parametrize("canal", ["fuera", "todo"])
@pytest.mark.parametrize("path", ["", "/group-nodes", "/export", "/envios", f"/products/{MONITOR}/publications"])
def test_s7_no_fuera_permission_everywhere_pg(conn, db, monkeypatch, canal, path):
    _products(db)
    _doc(db, date(2026, 9, 10), "1210", [_monitor("1000", "800")])
    c = _client(conn, monkeypatch, NO_FUERA)
    params = {"canal": canal}
    if path == "/group-nodes":
        params.update(dimension="marca", path=json.dumps(["MARCAUNO"]))
    resp = c.get(URL + path, params=params)
    assert resp.status_code == 403, resp.text


def test_s2_nc_negative_document(client, db):
    _products(db)
    _doc(db, date(2026, 9, 10), "1210", [_monitor("1000", "800")])
    _doc(db, date(2026, 9, 11), "-1210", [_monitor("-1000", "-800", cantidad="-1")], tipo="Nc")
    _doc(db, date(2026, 9, 12), "-605", [Ln("-500", "-400", articulo="Servicio Nc", cantidad="-1")], tipo="Nc")
    body = _get(client, canal="fuera", costo="costo")
    rows = _rows(body)
    assert _money(rows["Monitor Ejemplo 24"])[:3] == (0, 0.0, 0.0)
    assert _money(rows["Servicio Nc"])[:3] == (-1, -605.0, -100.0)
    assert body["kpis"]["venta_desconocida_lineas"] == 0


def test_s2_nc_alone_costo_d(client, db):
    _products(db)
    _doc(db, date(2026, 9, 11), "-1210", [_monitor("-1000", "-800", cantidad="-1")], tipo="Nc")
    row = _get(client, canal="fuera")["rows"][0]
    # TG = -1000 - (-800 x 1.065) = -148
    assert _money(row)[:3] == (-1, -1210.0, -148.0)


def test_s11_cheque_all_known_and_mixed_rate(client, db):
    """CHEQUE doc with a 21% product and an unmatched 10.5% line: (1210 + 331.5) x 1.04 = 1603.16."""
    _products(db)
    _doc(
        db,
        date(2026, 9, 10),
        "1603.16",
        [_monitor("1000", "800"), Ln("300", "150", codigo=CABLE, articulo="Cable")],
        condicion="CHEQUE 30 D",
        recargo="52",
    )
    rows = _rows(_get(client, canal="fuera"))
    assert rows["Monitor Ejemplo 24"]["gross"] == 1210.0
    assert rows["Cable"]["gross"] == 331.5


def test_s13_illegal_rate_is_unknown_not_21(client, db):
    """Manual 100 with Importe 115 (15%): not legal -> unknown, never 121."""
    _doc(db, date(2026, 9, 10), "115", [Ln("100", "50", articulo="Raro")])
    body = _get(client, canal="fuera")
    assert body["rows"][0]["gross"] == 0.0
    assert body["kpis"]["venta_desconocida_lineas"] == 1


def test_s13_boundary_just_outside_tolerance(client, db):
    _doc(db, date(2026, 9, 10), "120.89", [Ln("100", "50", articulo="Borde")])  # 20.89% -> 0.11pp off
    body = _get(client, canal="fuera")
    assert body["kpis"]["venta_desconocida_lineas"] == 1


def test_s5_sin_producto_key_stable_across_periods(client, db):
    _doc(db, date(2026, 8, 10), "121", [Ln("100", "50", codigo=CABLE, articulo="Cable Ejemplo")])
    _doc(db, date(2026, 9, 10), "121", [Ln("100", "50", codigo=CABLE, articulo="Cable Ejemplo")])
    sep = _get(client, canal="fuera")["rows"]
    aug = _get(client, canal="fuera", date_from="2026-08-01", date_to="2026-08-31")["rows"]
    filt = _get(client, canal="fuera", vendedores="Vendedor Uno")["rows"]
    assert len(sep) == len(aug) == 1
    assert sep[0]["key"] == aug[0]["key"] == filt[0]["key"]
    assert sep[0]["product_item_id"] < 0


def test_s12_recargo_not_in_venta_todo(client, db):
    _products(db)
    _ml_sale(db, LIBRO, "MLA9002", date(2026, 9, 5), gross="200")
    _doc(db, date(2026, 9, 10), "2298.40", [_libro("2000", "1500")], condicion="CHEQUE 30 D", recargo="80")
    assert _get(client, canal="todo")["kpis"]["gross"]["value"] == 2410.0
