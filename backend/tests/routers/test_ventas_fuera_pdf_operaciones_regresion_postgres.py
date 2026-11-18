"""Regression tests from the independent verification of vpf-operaciones (S3, S3d, S4-L2). Every name, code and amount is INVENTED."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text

from app.models.sell_dirty import SellDirty
from tests.routers.test_ventas_fuera_pdf_operaciones_postgres import (
    BASE,
    GANANCIA,
    RANGO,
    SUBIR,
    TODOS,
    VER,
    _client,
    _listado,
    _put,
    _subir,
    _trigger,
)
from tests.services.sell._schema import throwaway_schema
from tests.services.ventas_fuera_pdf._mundo import STUBS, TABLAS, TRUNCATE, doc, linea, lineas, producto, reporte

pytestmark = pytest.mark.postgres

CODIGO, OTRO = "7791111111110", "7792222222229"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("vpf_verify_probes", [*TABLAS, SellDirty.__table__], STUBS, after=_trigger) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        producto(conn, 801, CODIGO, "Producto Probe")
        producto(conn, 802, OTRO, "Otro Probe")
    yield
    with engine.begin() as conn:
        conn.execute(text(TRUNCATE + ", sell_dirty"))


def _rep(cantidad: str = "7", precio: str = "1500", costo: str = "1000"):
    return reporte(doc(301, [linea(CODIGO, "PRODUCTO PROBE", cantidad, precio, costo)]))


def _modal_unit_cost(precio_costo: float, cantidad: float) -> float:
    # What ModalEditarCosto sends when saved unchanged: lineaParaModalCosto's costo_unitario x (1 + 6.5 / 100).
    return precio_costo / cantidad * (1 + 6.5 / 100)


def test_s4_modal_identity_survives_a_reupload_of_the_same_range(engine: Engine, monkeypatch) -> None:
    """S4-L2: upload -> edit cost (modal saved unchanged) -> re-upload same range -> cost kept."""
    _subir(engine, monkeypatch, _rep())
    linea_id = lineas(engine)[(301, 1)]["id"]
    r = _put(engine, linea_id, {"costo_unitario": _modal_unit_cost(1000.0, 7.0)})
    assert r.status_code == 200, r.text
    tras_put = lineas(engine)[(301, 1)]["precio_costo"]

    _subir(engine, monkeypatch, _rep())
    tras_recarga = lineas(engine)[(301, 1)]

    assert tras_put == Decimal("1000.00")
    assert tras_recarga["override_estado"] == "aplicado"
    assert tras_recarga["precio_costo"] == tras_put


def test_s4_changed_line_is_flagged_not_applied_and_override_kept(engine: Engine, monkeypatch) -> None:
    _subir(engine, monkeypatch, _rep())
    linea_id = lineas(engine)[(301, 1)]["id"]
    assert _put(engine, linea_id, {"costo_unitario": 500, "item_id": 802}).status_code == 200

    resultado = _subir(engine, monkeypatch, _rep(cantidad="8"))
    ln = lineas(engine)[(301, 1)]

    assert (resultado["overrides_aplicados"], resultado["overrides_revisar"]) == (0, 1)
    assert (ln["override_estado"], ln["item_id"], ln["precio_costo"]) == ("revisar", 801, Decimal("1000.00"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT estado, item_id FROM ventas_fuera_linea_overrides")).all() == [
            ("revisar", 802)
        ]
    body = _listado(engine, revisar="true")
    assert (
        body["totales"]["revisar_lineas"] == 1
        and body["operaciones"][0]["lineas"][0]["override"]["estado"] == "revisar"
    )

    # Back to the original line: applied again.
    resultado = _subir(engine, monkeypatch, _rep())
    ln = lineas(engine)[(301, 1)]
    assert resultado["overrides_aplicados"] == 1
    assert (ln["override_estado"], ln["item_id"], ln["item_origen"]) == ("aplicado", 802, "manual")


def test_s3_remembered_mapping_applies_on_the_next_upload(engine: Engine, monkeypatch) -> None:
    rep = reporte(doc(401, [linea("COD-SIN-PRODUCTO", "ARTICULO RARO", "1", "100", "50")]))
    _subir(engine, monkeypatch, rep)
    linea_id = lineas(engine)[(401, 1)]["id"]
    assert lineas(engine)[(401, 1)]["item_id"] is None
    assert _put(engine, linea_id, {"item_id": 802, "recordar_mapeo": True}).status_code == 200

    otro = reporte(doc(402, [linea("COD-SIN-PRODUCTO ", "ARTICULO RARO", "1", "100", "50")]))
    monkeypatch.undo()
    _subir(engine, monkeypatch, otro)
    ln = lineas(engine)[(402, 1)]
    assert (ln["item_id"], ln["item_origen"]) == (802, "mapeo")


def test_s3d_permissions(engine: Engine, monkeypatch) -> None:
    _subir(engine, monkeypatch, _rep())
    linea_id = lineas(engine)[(301, 1)]["id"]
    sin_subir = {VER, GANANCIA}
    assert _put(engine, linea_id, {"costo_unitario": 10}, sin_subir).status_code == 403
    c = _client(engine, sin_subir)
    assert c.delete(f"{BASE}/lineas/{linea_id}/override").status_code == 403
    assert c.post(f"{BASE}/lineas/{linea_id}/override/confirmar").status_code == 403
    assert _client(engine, {SUBIR}).get(f"{BASE}/operaciones/listado", params=RANGO).status_code == 403
    body = _listado(engine, {VER})
    assert body["totales"]["total_gauss"] is None and body["totales"]["markup"] is None
    op = body["operaciones"][0]
    assert op["total_gauss"] is None and op["markup"] is None
    assert op["lineas"][0]["total_gauss"] is None and op["lineas"][0]["markup"] is None
    assert _put(engine, linea_id, {"costo_unitario": 0}, TODOS).status_code == 422
    assert _put(engine, linea_id, {"item_id": 999999}, TODOS).status_code == 422
    assert _put(engine, 987654, {"costo_unitario": 5}, TODOS).status_code == 404
