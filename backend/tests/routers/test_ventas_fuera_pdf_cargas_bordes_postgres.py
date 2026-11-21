"""vpf-metricas-canal-fe T1 edge cases of the upload (C1, C2, S7, L8/L11): what a subset of salespeople covers, that a
refused upload or a preview changes nothing, and the history state. Invented data only (the anonymized fixtures)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Iterator, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.core.database import get_async_db, get_db
from app.models.cur_exch_history import CurExchHistory
from app.models.item_cost_list import ItemCostList
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.vendedor_excluido import VendedorExcluido
from app.models.tb_item import TBItem
from app.models.tipo_cambio import TipoCambio
from app.models.venta_fuera_pdf import (
    VentaFueraCodigoMapeo,
    VentaFueraLineaOverride,
    VentaFueraOperacion,
    VentaFueraOperacionLinea,
    VentaFueraPdfAlcance,
    VentaFueraPdfCarga,
    VentaFueraPdfResumenDocumento,
)
from app.routers import ventas_fuera_pdf
from app.services.ventas_fuera_pdf.parser import parse_detallada
from tests.routers.test_ventas_fuera_pdf_postgres import DETALLADA, RESUMEN, SUBIR, VER, _como
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

URL = "/api/ventas-fuera-pdf/cargas"
OTRO = "Otro Vendedor"
CARLA_IMPRESO = parse_detallada(DETALLADA).documentos[0].vendedor
TABLAS = (
    "ventas_fuera_pdf_cargas",
    "ventas_fuera_operaciones",
    "ventas_fuera_operacion_lineas",
    "ventas_fuera_pdf_alcances",
    "ventas_fuera_pdf_resumen_documentos",
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    tablas = [
        VentaFueraPdfCarga.__table__,
        VentaFueraOperacion.__table__,
        VentaFueraOperacionLinea.__table__,
        VentaFueraPdfAlcance.__table__,
        VentaFueraPdfResumenDocumento.__table__,
        # Read by the load since vpf-operaciones (product resolution, manual fixes re-applied).
        VentaFueraLineaOverride.__table__,
        VentaFueraCodigoMapeo.__table__,
        TBItem.__table__,
        # The ERP cost list and USD rates the load costs each line with (vpf-costo-d-erp); empty here.
        ItemCostList.__table__,
        ItemCostListHistory.__table__,
        TipoCambio.__table__,
        CurExchHistory.__table__,
        ProductoERP.__table__,
        MarcaPM.__table__,
        VendedorExcluido.__table__,
    ]
    stubs = [
        "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre VARCHAR(255) NOT NULL)",
        "INSERT INTO usuarios VALUES (7, 'Usuaria Ejemplo')",
    ]
    with throwaway_schema("vf_pdf_bordes", tablas, stubs) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(TABLAS) + ", productos_erp, vendedores_excluidos RESTART IDENTITY"))


@dataclasses.dataclass
class SimpleUser:
    _permisos_cache: set
    id: int = 7
    es_superadmin: bool = False


def _client(engine: Engine, permisos=frozenset({SUBIR, VER})) -> TestClient:
    app = FastAPI()
    app.include_router(ventas_fuera_pdf.router, prefix="/api")
    factory = sessionmaker(bind=engine, autoflush=False)

    def db() -> Iterator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_async_db] = db
    app.dependency_overrides[get_current_user] = lambda: SimpleUser(set(permisos))
    return TestClient(app)


def _files(detallada: Optional[bytes] = DETALLADA, resumen: Optional[bytes] = RESUMEN) -> dict:
    files = {}
    if detallada is not None:
        files["detallada"] = ("detallada.pdf", detallada, "application/pdf")
    if resumen is not None:
        files["resumen"] = ("resumen.pdf", resumen, "application/pdf")
    return files


def _subir(client, vendedores=None, raw=None, **kw):
    data = {}
    if vendedores is not None:
        data["vendedores"] = json.dumps(vendedores)
    if raw is not None:
        data["vendedores"] = raw
    return client.post(URL, files=_files(**kw), data=data)


def _q(engine, sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).all()


def _hash(engine) -> str:
    h = hashlib.sha256()
    for t in TABLAS:
        for row in _q(engine, f"SELECT to_jsonb(x)::text FROM {t} x ORDER BY 1"):
            h.update(row[0].encode())
    return h.hexdigest()


def _dos(reporte):
    docs = [dataclasses.replace(d, vendedor=OTRO) if d.numero % 2 else d for d in reporte.documentos]
    return dataclasses.replace(reporte, vendedor=None, documentos=docs)


def _solo_otro(reporte):
    docs = [d for d in _dos(reporte).documentos if d.vendedor == OTRO]
    return dataclasses.replace(reporte, vendedor=OTRO, documentos=docs)


def _alcances(engine):
    resp = _client(engine).get("/api/ventas-fuera-pdf/alcances")
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestSubsetCoverage:
    def test_l8_a_subset_never_covers_the_unchosen_salesperson_summary(self, engine, monkeypatch) -> None:
        """OTRO's summary alone is 'falta la detallada'; a Todos detailed imported for Carla only must not cover it."""
        client = _client(engine)
        _como(monkeypatch, resumen=_solo_otro)
        assert _subir(client, detallada=None).status_code == 200
        _como(monkeypatch, detallada=_dos)
        resp = _subir(client, vendedores=[CARLA_IMPRESO], resumen=None)
        assert resp.status_code == 200, resp.text
        alcances = _alcances(engine)
        otro = [a for a in alcances if a["vendedor"] == OTRO]
        assert len(otro) == 1
        assert any(f["reporte"] == "detallada" for f in otro[0]["faltantes"]), otro[0]

    def test_l11_a_todos_summary_still_misses_the_detailed_for_the_unchosen(self, engine, monkeypatch) -> None:
        client = _client(engine)
        _como(monkeypatch, resumen=_dos)
        assert _subir(client, detallada=None).status_code == 200
        _como(monkeypatch, detallada=_dos)
        resp = _subir(client, vendedores=[OTRO], resumen=None)
        assert resp.status_code == 200, resp.text
        alcances = _alcances(engine)
        todos = [a for a in alcances if a["vendedor"] is None]
        assert len(todos) == 1
        faltan = todos[0]["faltantes"]
        assert faltan, "the Todos summary must still miss the detailed report for the salesperson left out"
        assert all(f["vendedor"] != OTRO for f in faltan), faltan
        otro = [a for a in alcances if a["vendedor"] == OTRO]
        assert otro and not any(f["reporte"] == "resumen" for f in otro[0]["faltantes"]), otro

    def test_subset_pair_stores_only_the_chosen_summary_documents_and_cheques(self, engine, monkeypatch) -> None:
        client = _client(engine)
        _como(monkeypatch, detallada=_dos, resumen=_dos)
        resp = _subir(client, vendedores=[OTRO])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        vendedores_resumen = {
            r[0] for r in _q(engine, "SELECT DISTINCT vendedor FROM ventas_fuera_pdf_resumen_documentos")
        }
        assert vendedores_resumen == {OTRO}
        assert all(c["numero"] % 2 == 1 for c in body["control"]["cheques"])
        assert body["control"]["documentos_coinciden"] is True
        ops_total = _q(engine, "SELECT COALESCE(SUM(total_lineas), 0)::float FROM ventas_fuera_operaciones")[0][0]
        assert body["total_lineas"] in (ops_total, str(ops_total), f"{ops_total:.2f}")


class TestRejectionsKeepData:
    @pytest.mark.parametrize(
        "raw",
        [
            "[]",
            json.dumps(["Nadie Ejemplo"]),
            "no es json",
            json.dumps([1]),
            "{}",
            json.dumps("Otro Vendedor"),
            json.dumps([None]),
        ],
    )
    def test_422_with_existing_data_changes_nothing(self, engine, monkeypatch, raw) -> None:
        client = _client(engine)
        _como(monkeypatch, detallada=_dos, resumen=_dos)
        assert _subir(client).status_code == 200
        antes = _hash(engine)
        resp = _subir(client, raw=raw)
        assert resp.status_code == 422, resp.text
        assert _hash(engine) == antes

    def test_preview_with_existing_data_changes_nothing(self, engine, monkeypatch) -> None:
        client = _client(engine)
        _como(monkeypatch, detallada=_dos, resumen=_dos)
        assert _subir(client).status_code == 200
        antes = _hash(engine)
        assert client.post(f"{URL}/preview", files=_files()).status_code == 200
        assert _hash(engine) == antes

    def test_duplicate_names(self, engine, monkeypatch) -> None:
        """A name sent twice imports that salesperson once: the same operations and one scope as sending it once."""
        _como(monkeypatch, detallada=_dos, resumen=_dos)
        client = _client(engine)
        assert _subir(client, vendedores=[OTRO]).status_code == 200
        una_vez = sorted(_q(engine, "SELECT vendedor, COUNT(*) FROM ventas_fuera_operaciones GROUP BY vendedor"))
        resp = _subir(client, vendedores=[OTRO, OTRO])
        assert resp.status_code == 200
        assert resp.json()["vendedores"] == [OTRO]
        assert (
            sorted(_q(engine, "SELECT vendedor, COUNT(*) FROM ventas_fuera_operaciones GROUP BY vendedor")) == una_vez
        )
        assert [a["vendedor"] for a in _alcances(engine)].count(OTRO) == 1


class TestHistorialEstado:
    def test_partial_then_full_replace(self, engine, monkeypatch) -> None:
        client = _client(engine)
        _como(monkeypatch, detallada=_dos, resumen=None)
        primera = _subir(client, resumen=None).json()["carga_id"]
        _subir(client, vendedores=[OTRO], resumen=None)
        estados = {f["id"]: f["estado"] for f in client.get(URL).json()}
        assert estados[primera] == "vigente"
        _subir(client, vendedores=[CARLA_IMPRESO], resumen=None)
        filas = client.get(URL).json()
        assert {f["id"]: f["estado"] for f in filas}[primera] == "reemplazada"
        assert [f["id"] for f in filas] == sorted((f["id"] for f in filas), reverse=True)

    def test_superseded_summary_is_reemplazada(self, engine) -> None:
        client = _client(engine)
        primera = _subir(client, detallada=None).json()["carga_id"]
        _subir(client, detallada=None)
        estados = {f["id"]: f["estado"] for f in client.get(URL).json()}
        assert estados[primera] == "reemplazada"

    @pytest.mark.parametrize("params", [{"dias": 0}, {"page": 0}, {"page_size": 0}, {"page_size": 501}])
    def test_bad_params_422(self, engine, params) -> None:
        assert _client(engine).get(URL, params=params).status_code == 422
