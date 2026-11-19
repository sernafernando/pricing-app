"""vpf-operaciones T1: the PDF operations list, the "sin producto" summary and the manual fixes of a line.

S2: "Operations list for PDF por-fuera sales, like the Ventas ML operations screen: one row per comprobante/line with
date, company, salesperson, document, client, product, qty, price, cost (Costo D / Costo), markup, flags (Sin
producto, Nc, cheque surcharge), filters and totals; drill into a document's lines."
S3: "From the operations list the user can fix a line: assign the real product (and remember the mapping so the next
uploads of that code resolve automatically) and/or set the cost by hand" ... "Fixes must recompute metrics, offsets and
sell in/out for affected lines and survive re-uploads of the same PDF range."
S3d: manual fixes need ventas_fuera.subir_pdf; viewing ventas_fuera.ver_metricas_pdf; Total Gauss / markup
ventas_fuera.ver_ganancia (masked otherwise).
S4-L2 (owner, verbatim): "hay que hacerle que se persista la data si cargan de nuevo un pdf que sobreescriba la venta.
(cosa que no estaba pasando, se perdía la data que cargaban ahí)". Tests: "upload -> edit cost -> re-upload same range
-> cost kept; re-upload with changed line -> flagged; old screen behaviour of losing edits must not exist in the new
system."

Money rules = the board's (`ml_daily_metrics.fuera`): Costo D = precio_costo x 1.065, Total Gauss = precio - costo and
markup = Total Gauss / costo only on ARS lines with a cost. Manual cost (owner L4): precio_costo = costo_unitario x
cantidad, the cost saved (typed x (1 + the optional %)); Costo D x 1.065 applies on top. Real Postgres, T4's sell_dirty trigger on the lines installed; the
uploads read documents built in code. Every name, code and amount is INVENTED.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.core.database import get_async_db, get_db
from app.models.sell_dirty import SellDirty
from app.routers import ventas_fuera_pdf
from app.services.sell import queue
from tests.services.sell._schema import throwaway_schema
from tests.services.ventas_fuera_pdf._mundo import (
    EMPRESA,
    STUBS,
    TABLAS,
    TRUNCATE,
    doc,
    linea,
    lineas,
    producto,
    reporte,
)

pytestmark = pytest.mark.postgres

SUBIR, VER, GANANCIA = "ventas_fuera.subir_pdf", "ventas_fuera.ver_metricas_pdf", "ventas_fuera.ver_ganancia"
TODOS = {SUBIR, VER, GANANCIA}
BASE = "/api/ventas-fuera-pdf"
RANGO = {"desde": "2026-10-01", "hasta": "2026-10-31"}
MONITOR, LIBRO, CABLE = "7790000000017", "7790000000024", "7790000099999"
UNO, DOS = "Vendedor Uno", "Vendedor Dos"


def _trigger(engine: Engine) -> None:
    with engine.begin() as conn:
        for sql in queue.UPGRADE_SQL:
            if "sell_dirty_enqueue_pdf_linea" in sql:
                conn.execute(text(sql))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("vf_pdf_ops", [*TABLAS, SellDirty.__table__], STUBS, after=_trigger) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        producto(conn, 501, MONITOR, "Monitor Ejemplo 24")
        producto(conn, 502, LIBRO, "Libro Ejemplo")
    yield
    with engine.begin() as conn:
        conn.execute(text(TRUNCATE + ", sell_dirty"))


def _client(engine: Engine, permisos: set[str]) -> TestClient:
    app = FastAPI()
    app.include_router(ventas_fuera_pdf.router, prefix="/api")
    factory = sessionmaker(bind=engine, autoflush=False)

    def db() -> Iterator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_async_db] = db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=7, es_superadmin=False, _permisos_cache=permisos
    )
    return TestClient(app)


def _mundo(monitor_cantidad: str = "2", monitor_precio: str = "2000", monitor_costo: str = "1600"):
    return reporte(
        doc(
            101,
            [
                linea(MONITOR, "MONITOR EJEMPLO 24", monitor_cantidad, monitor_precio, monitor_costo),
                linea(None, "Servicio Tecnico (Manual)", "1", "400", "0"),
            ],
            cliente="CLIENTE UNO",
        ),
        doc(
            102,
            [linea(MONITOR, "MONITOR EJEMPLO 24", "-1", "-1000", "-800")],
            tipo="Nc",
            vendedor=DOS,
            cliente="CLIENTE DOS",
            fecha=date(2026, 10, 6),
        ),
        doc(
            103,
            [linea(CABLE, "CABLE EJEMPLO", "1", "300", "150"), linea(None, "Flete Ejemplo", "1", "100", "0")],
            fecha=date(2026, 10, 7),
        ),
        doc(104, [linea(LIBRO, "LIBRO EJEMPLO", "1", "2000", "1500")], vendedor=DOS, fecha=date(2026, 10, 8)),
    )


def _subir(engine: Engine, monkeypatch: pytest.MonkeyPatch, rep=None) -> dict:
    rep = rep if rep is not None else _mundo()
    monkeypatch.setattr(ventas_fuera_pdf, "parse_detallada", lambda _: rep)
    response = _client(engine, {SUBIR}).post(
        f"{BASE}/cargas", files={"detallada": ("detallada.pdf", b"%PDF-invented", "application/pdf")}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _listado(engine: Engine, permisos: set[str] = TODOS, **params) -> dict:
    response = _client(engine, permisos).get(f"{BASE}/operaciones/listado", params={**RANGO, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _op(body: dict, numero: int) -> dict:
    return next(o for o in body["operaciones"] if o["numero"] == numero)


def _linea_id(engine: Engine, numero: int, renglon: int) -> int:
    return lineas(engine)[(numero, renglon)]["id"]


def _put(engine: Engine, linea_id: int, body: dict, permisos: set[str] = TODOS):
    return _client(engine, permisos).put(f"{BASE}/lineas/{linea_id}/override", json=body)


def _q(engine: Engine, sql: str) -> list:
    with engine.connect() as conn:
        return conn.execute(text(sql)).all()


class TestListado:
    def test_operations_with_lines_costo_d_markup_flags_and_totals(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)

        body = _listado(engine)

        assert (body["total"], body["page"], body["page_size"]) == (4, 1, 50)
        assert [o["numero"] for o in body["operaciones"]] == [104, 103, 102, 101]
        op = _op(body, 101)
        assert (op["empresa"], op["vendedor"], op["cliente"], op["tipo"], op["fecha"]) == (
            EMPRESA,
            UNO,
            "CLIENTE UNO",
            "Fc",
            "2026-10-05",
        )
        # Costo D = 1600 x 1.065 = 1704; Total Gauss = 2000 - 1704 = 296; markup = 296 / 1704 = 17.37%. The manual
        # service line has no cost: in the sale, never in the cost nor the margin.
        assert (op["venta"], op["costo"], op["total_gauss"], op["markup"]) == (2400.0, 1704.0, 296.0, 17.37)
        assert (op["sin_producto_lineas"], op["revisar_lineas"], op["cheque"]) == (1, 0, False)
        monitor, servicio = op["lineas"]
        assert (monitor["renglon"], monitor["item_id"], monitor["item_origen"], monitor["producto"]) == (
            1,
            501,
            "codigo",
            "Monitor Ejemplo 24",
        )
        assert (monitor["costo"], monitor["total_gauss"], monitor["markup"], monitor["sin_producto"]) == (
            1704.0,
            296.0,
            17.37,
            False,
        )
        assert (monitor["precio_costo"], monitor["precio_costo_pdf"], monitor["override"]) == (1600.0, 1600.0, None)
        assert (servicio["sin_producto"], servicio["sin_producto_causa"], servicio["total_gauss"]) == (
            True,
            "sin_codigo_manual",
            None,
        )
        nc = _op(body, 102)
        assert (nc["tipo"], nc["venta"], nc["costo"], nc["total_gauss"]) == ("Nc", -1000.0, -852.0, -148.0)
        causas = {ln["articulo"]: ln["sin_producto_causa"] for ln in _op(body, 103)["lineas"]}
        assert causas == {"CABLE EJEMPLO": "codigo_no_encontrado", "Flete Ejemplo": "sin_codigo"}
        assert body["totales"] == {
            "documentos": 4,
            "lineas": 6,
            "unidades": 5.0,
            "venta": 3800.0,
            "costo": 2609.25,
            "total_gauss": 690.75,
            "markup": 26.47,
            "sin_producto_lineas": 3,
            "sin_producto_venta": 800.0,
            "revisar_lineas": 0,
        }
        assert body["facets"] == {"empresas": [EMPRESA], "vendedores": [DOS, UNO]}

    def test_costo_basis_is_precio_costo_without_the_6_5_percent(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)

        op = _op(_listado(engine, costo="costo"), 101)

        assert (op["costo"], op["total_gauss"], op["markup"]) == (1600.0, 400.0, 25.0)

    @pytest.mark.parametrize(
        ("params", "numeros"),
        [
            ({"vendedores": [UNO]}, [103, 101]),
            ({"empresas": ["OTRA EMPRESA SA"]}, []),
            ({"q": "cable"}, [103]),
            ({"q": "cliente dos"}, [102]),
            ({"q": "104"}, [104]),
            ({"q": MONITOR}, [102, 101]),
            ({"tipo": "Nc"}, [102]),
            ({"sin_producto": "true"}, [103, 101]),
            ({"revisar": "true"}, []),
            ({"sort": "fecha_asc"}, [101, 102, 103, 104]),
            ({"sort": "importe_desc"}, [101, 104, 103, 102]),
        ],
    )
    def test_filters_and_sorts(self, engine: Engine, monkeypatch: pytest.MonkeyPatch, params, numeros) -> None:
        _subir(engine, monkeypatch)

        body = _listado(engine, **params)

        assert [o["numero"] for o in body["operaciones"]] == numeros
        assert body["total"] == len(numeros)

    def test_markup_asc_puts_the_lowest_markup_first(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _subir(engine, monkeypatch)

        markups = [o["markup"] for o in _listado(engine, sort="markup_asc")["operaciones"]]

        assert markups == sorted(markups) and markups[-1] == 87.79

    def test_pages(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _subir(engine, monkeypatch)

        body = _listado(engine, page=2, page_size=3)

        assert (body["total"], [o["numero"] for o in body["operaciones"]]) == (4, [101])
        assert body["totales"]["documentos"] == 4
        client = _client(engine, TODOS)
        assert client.get(f"{BASE}/operaciones/listado", params={**RANGO, "page_size": 201}).status_code == 422
        assert client.get(f"{BASE}/operaciones/listado", params={**RANGO, "page": 0}).status_code == 422
        assert client.get(f"{BASE}/operaciones/listado", params={"desde": "2026-10-01"}).status_code == 422

    def test_without_ver_ganancia_total_gauss_and_markup_are_null(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)

        body = _listado(engine, {VER})

        op = _op(body, 101)
        assert (op["total_gauss"], op["markup"], op["costo"]) == (None, None, 1704.0)
        assert all(ln["total_gauss"] is None and ln["markup"] is None for ln in op["lineas"])
        assert (body["totales"]["total_gauss"], body["totales"]["markup"]) == (None, None)

    def test_needs_ver_metricas_pdf(self, engine: Engine) -> None:
        for permisos in (set(), {SUBIR}, {GANANCIA}):
            response = _client(engine, permisos).get(f"{BASE}/operaciones/listado", params=RANGO)
            assert response.status_code == 403


class TestResumenSinProducto:
    def test_counts_by_cause(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _subir(engine, monkeypatch)
        client = _client(engine, {VER})

        response = client.get(f"{BASE}/sin-producto/resumen")
        fuera_de_rango = client.get(f"{BASE}/sin-producto/resumen", params={"desde": "2026-11-01"})

        assert response.status_code == 200, response.text
        assert {r["causa"]: (r["lineas"], r["venta"]) for r in response.json()} == {
            "sin_codigo_manual": (1, 400.0),
            "sin_codigo": (1, 100.0),
            "codigo_no_encontrado": (1, 300.0),
        }
        assert fuera_de_rango.json() == []
        assert _client(engine, {SUBIR}).get(f"{BASE}/sin-producto/resumen").status_code == 403


class TestOverrideCosto:
    def test_manual_cost_sets_precio_costo_from_the_unit_cost_and_keeps_the_pdf_cost(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)
        linea_id = _linea_id(engine, 101, 1)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_dirty"))

        response = _put(engine, linea_id, {"costo_unitario": 900})

        assert response.status_code == 200, response.text
        body = response.json()
        # L4: precio_costo = 900 x 2 = 1800 (the cost saved); Costo D = 1800 x 1.065 = 1917 on top, Total Gauss
        # 2000 - 1917 = 83, markup 83 / 1917 = 4.33%.
        assert (body["precio_costo"], body["precio_costo_pdf"], body["costo"]) == (1800.0, 1600.0, 1917.0)
        assert (body["total_gauss"], body["markup"]) == (83.0, 4.33)
        assert body["override"]["estado"] == "aplicado"
        assert (body["override"]["costo_unitario"], body["override"]["usuario"]) == (900.0, "Usuaria Ejemplo")
        fila = lineas(engine)[(101, 1)]
        assert (fila["precio_costo"], fila["precio_costo_pdf"], fila["override_estado"]) == (
            Decimal("1800.00"),
            Decimal("1600.00"),
            "aplicado",
        )
        # T4's trigger queues the line for offsets and sell in / sell out.
        assert _q(engine, "SELECT canal, venta_ref, item_id FROM sell_dirty") == [("fuera", linea_id, 501)]
        assert _op(_listado(engine), 101)["costo"] == 1917.0

    @pytest.mark.parametrize(
        ("guardado", "costo_d"),
        [(10000, 10650.0), (10720, 11416.8)],  # owner L4: 10000 with 0%, 10000 + 7.2% = 10720
    )
    def test_l4_the_saved_cost_is_precio_costo_and_costo_d_adds_the_6_5_percent_on_top(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch, guardado: int, costo_d: float
    ) -> None:
        _subir(engine, monkeypatch)
        linea_id = _linea_id(engine, 104, 1)  # one unit

        response = _put(engine, linea_id, {"costo_unitario": guardado})

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["override"]["costo_unitario"], body["precio_costo"], body["costo"]) == (
            float(guardado),
            float(guardado),
            costo_d,
        )
        assert lineas(engine)[(104, 1)]["precio_costo"] == Decimal(guardado)

    @pytest.mark.parametrize("costo", [0, -5])
    def test_a_cost_not_above_zero_is_422(self, engine: Engine, monkeypatch: pytest.MonkeyPatch, costo) -> None:
        _subir(engine, monkeypatch)

        response = _put(engine, _linea_id(engine, 101, 1), {"costo_unitario": costo})

        assert response.status_code == 422
        assert _q(engine, "SELECT COUNT(*) FROM ventas_fuera_linea_overrides") == [(0,)]

    def test_unknown_line_is_404(self, engine: Engine) -> None:
        assert _put(engine, 999999, {"costo_unitario": 10}).status_code == 404

    def test_fixes_need_subir_pdf(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _subir(engine, monkeypatch)
        linea_id = _linea_id(engine, 101, 1)
        client = _client(engine, {VER, GANANCIA})

        assert client.put(f"{BASE}/lineas/{linea_id}/override", json={"costo_unitario": 1}).status_code == 403
        assert client.delete(f"{BASE}/lineas/{linea_id}/override").status_code == 403
        assert client.post(f"{BASE}/lineas/{linea_id}/override/confirmar").status_code == 403
        assert lineas(engine)[(101, 1)]["precio_costo"] == Decimal("1600.00")


class TestOverrideProducto:
    def test_assigning_a_product_and_remembering_it_resolves_siblings_and_the_next_upload(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cables = reporte(doc(201, [linea(CABLE, "CABLE EJEMPLO")]), doc(202, [linea(CABLE, "CABLE EJEMPLO")]))
        _subir(engine, monkeypatch, cables)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_dirty"))

        response = _put(engine, _linea_id(engine, 201, 1), {"item_id": 502, "recordar_mapeo": True})

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["item_id"], body["item_origen"], body["producto"], body["sin_producto"]) == (
            502,
            "manual",
            "Libro Ejemplo",
            False,
        )
        filas = lineas(engine)
        assert (filas[(202, 1)]["item_id"], filas[(202, 1)]["item_origen"]) == (502, "mapeo")
        assert _q(engine, "SELECT clave, item_id, usuario_id FROM ventas_fuera_codigo_mapeos") == [
            (f"c:{CABLE}", 502, 7)
        ]
        assert sorted(r[0] for r in _q(engine, "SELECT venta_ref FROM sell_dirty")) == sorted(
            [filas[(201, 1)]["id"], filas[(202, 1)]["id"]]
        )

        _subir(engine, monkeypatch, reporte(doc(203, [linea(CABLE, "CABLE EJEMPLO")])))

        assert (lineas(engine)[(203, 1)]["item_id"], lineas(engine)[(203, 1)]["item_origen"]) == (502, "mapeo")

    def test_without_recordar_mapeo_only_the_line_changes(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch, reporte(doc(201, [linea(CABLE, "C")]), doc(202, [linea(CABLE, "C")])))

        assert _put(engine, _linea_id(engine, 201, 1), {"item_id": 502}).status_code == 200

        assert lineas(engine)[(202, 1)]["item_id"] is None
        assert _q(engine, "SELECT COUNT(*) FROM ventas_fuera_codigo_mapeos") == [(0,)]

    def test_an_item_in_neither_productos_erp_nor_tb_item_is_422(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)

        response = _put(engine, _linea_id(engine, 103, 1), {"item_id": 987654})

        assert response.status_code == 422
        assert lineas(engine)[(103, 1)]["item_id"] is None


class TestQuitarYConfirmar:
    def test_delete_restores_the_pdf_cost_and_the_automatic_product(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)
        linea_id = _linea_id(engine, 101, 1)
        assert _put(engine, linea_id, {"costo_unitario": 900, "item_id": 502}).status_code == 200

        response = _client(engine, {SUBIR}).delete(f"{BASE}/lineas/{linea_id}/override")

        assert response.status_code == 200, response.text
        fila = lineas(engine)[(101, 1)]
        assert (fila["precio_costo"], fila["item_id"], fila["item_origen"], fila["override_estado"]) == (
            Decimal("1600.00"),
            501,
            "codigo",
            None,
        )
        assert _q(engine, "SELECT COUNT(*) FROM ventas_fuera_linea_overrides") == [(0,)]
        assert _client(engine, {SUBIR}).delete(f"{BASE}/lineas/{linea_id}/override").status_code == 404


class TestPersistenciaL2:
    """Owner L2: "se perdía la data que cargaban ahí"."""

    def test_upload_edit_cost_reupload_same_range_cost_kept(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)
        assert _put(engine, _linea_id(engine, 101, 1), {"costo_unitario": 900}).status_code == 200

        resultado = _subir(engine, monkeypatch)

        fila = lineas(engine)[(101, 1)]
        assert (fila["precio_costo"], fila["precio_costo_pdf"], fila["override_estado"]) == (
            Decimal("1800.00"),
            Decimal("1600.00"),
            "aplicado",
        )
        assert (resultado["overrides_aplicados"], resultado["overrides_revisar"]) == (1, 0)
        assert _op(_listado(engine), 101)["costo"] == 1917.0

    def test_reupload_with_changed_line_flagged(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _subir(engine, monkeypatch)
        assert _put(engine, _linea_id(engine, 101, 1), {"costo_unitario": 900, "item_id": 502}).status_code == 200

        resultado = _subir(
            engine, monkeypatch, _mundo(monitor_cantidad="3", monitor_precio="3000", monitor_costo="2400")
        )

        fila = lineas(engine)[(101, 1)]
        # Not applied: the line keeps the PDF's values, the fix is kept and flagged for review.
        assert (fila["precio_costo"], fila["item_id"], fila["item_origen"], fila["override_estado"]) == (
            Decimal("2400.00"),
            501,
            "codigo",
            "revisar",
        )
        assert _q(engine, "SELECT estado, costo_unitario, item_id, cantidad FROM ventas_fuera_linea_overrides") == [
            ("revisar", Decimal("900.00"), 502, Decimal("2.00"))
        ]
        assert (resultado["overrides_aplicados"], resultado["overrides_revisar"]) == (0, 1)
        body = _listado(engine, revisar="true")
        assert [o["numero"] for o in body["operaciones"]] == [101]
        assert (body["totales"]["revisar_lineas"], _op(body, 101)["lineas"][0]["override"]["estado"]) == (1, "revisar")

    def test_old_screen_behaviour_of_losing_edits_must_not_exist_in_the_new_system(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)
        assert _put(engine, _linea_id(engine, 101, 1), {"costo_unitario": 900}).status_code == 200

        _subir(engine, monkeypatch, _mundo(monitor_cantidad="3", monitor_precio="3000", monitor_costo="2400"))
        _subir(engine, monkeypatch, reporte())  # the range re-uploaded empty: every document voided
        _subir(engine, monkeypatch)  # the original line comes back

        assert _q(engine, "SELECT estado, costo_unitario FROM ventas_fuera_linea_overrides") == [
            ("aplicado", Decimal("900.00"))
        ]
        fila = lineas(engine)[(101, 1)]
        assert (fila["precio_costo"], fila["override_estado"]) == (Decimal("1800.00"), "aplicado")

    def test_confirmar_takes_the_current_line_and_applies_the_fix(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)
        assert _put(engine, _linea_id(engine, 101, 1), {"costo_unitario": 900}).status_code == 200
        _subir(engine, monkeypatch, _mundo(monitor_cantidad="3", monitor_precio="3000", monitor_costo="2400"))
        linea_id = _linea_id(engine, 101, 1)

        response = _client(engine, {SUBIR}).post(f"{BASE}/lineas/{linea_id}/override/confirmar")

        assert response.status_code == 200, response.text
        # 900 x 3 = 2700
        fila = lineas(engine)[(101, 1)]
        assert (fila["precio_costo"], fila["override_estado"]) == (Decimal("2700.00"), "aplicado")
        assert _q(engine, "SELECT estado, cantidad, precio FROM ventas_fuera_linea_overrides") == [
            ("aplicado", Decimal("3.00"), Decimal("3000.00"))
        ]
        assert _client(engine, {SUBIR}).post(f"{BASE}/lineas/999999/override/confirmar").status_code == 404


class TestSinProductoVivo:
    """Sin producto is read live from `ventas_fuera_operacion_lineas` (owner: "computes it live ... like the listing,
    so manual fixes and mappings are reflected immediately"), never from the deprecated counters of the upload."""

    def _carga(self, engine: Engine) -> dict:
        response = _client(engine, {VER}).get(f"{BASE}/cargas")
        assert response.status_code == 200, response.text
        return response.json()[0]  # newest first

    def test_correcting_a_line_drops_the_cargas_view_count_at_once(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)
        assert (self._carga(engine)["sin_producto_lineas"], self._carga(engine)["sin_producto_monto"]) == (3, 800.0)

        assert _put(engine, _linea_id(engine, 103, 1), {"item_id": 502}).status_code == 200

        fila = self._carga(engine)
        assert (fila["sin_producto_lineas"], fila["sin_producto_monto"]) == (2, 500.0)
        assert _listado(engine)["totales"]["sin_producto_lineas"] == fila["sin_producto_lineas"]
        assert _q(engine, "SELECT sin_producto_lineas FROM ventas_fuera_pdf_cargas") == [(3,)]

    def test_a_remembered_mapping_drops_the_count_of_every_sibling(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch, reporte(doc(201, [linea(CABLE, "C", "1", "300")]), doc(202, [linea(CABLE, "C")])))
        assert self._carga(engine)["sin_producto_lineas"] == 2

        assert _put(engine, _linea_id(engine, 201, 1), {"item_id": 502, "recordar_mapeo": True}).status_code == 200

        assert (self._carga(engine)["sin_producto_lineas"], self._carga(engine)["sin_producto_monto"]) == (0, 0.0)

    def test_quitar_correccion_brings_the_count_back(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _subir(engine, monkeypatch)
        linea_id = _linea_id(engine, 103, 1)
        assert _put(engine, linea_id, {"item_id": 502}).status_code == 200

        assert _client(engine, {SUBIR}).delete(f"{BASE}/lineas/{linea_id}/override").status_code == 200

        assert self._carga(engine)["sin_producto_lineas"] == 3

    def test_the_upload_result_counts_the_lines_a_kept_fix_resolves(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _subir(engine, monkeypatch)
        assert _put(engine, _linea_id(engine, 103, 1), {"item_id": 502}).status_code == 200

        resultado = _subir(engine, monkeypatch)

        assert (resultado["sin_producto"]["lineas"], resultado["sin_producto"]["monto"]) == (2, 500.0)
        assert sorted(a["articulo"] for a in resultado["sin_producto"]["articulos"]) == [
            "Flete Ejemplo",
            "Servicio Tecnico (Manual)",
        ]
        assert self._carga(engine)["sin_producto_lineas"] == 2


def test_routes_are_registered_in_the_app() -> None:
    from app.main import app

    paths = set(app.openapi()["paths"])

    assert {
        "/api/ventas-fuera-pdf/operaciones/listado",
        "/api/ventas-fuera-pdf/sin-producto/resumen",
        "/api/ventas-fuera-pdf/lineas/{linea_id}/override",
        "/api/ventas-fuera-pdf/lineas/{linea_id}/override/confirmar",
    } <= paths
