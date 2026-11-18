"""HTTP of the ventas por fuera PDF upload and operations (T1: S5, S7, S13).

Owner on permissions (S13): "Permisos nuevos: subir y ver". `ventas_fuera.subir_pdf` opens only the upload and
`ventas_fuera.ver_metricas_pdf` only the operations. The real `require_permiso` runs, reading the user's permission
cache as `get_current_user` leaves it. Real Postgres; the fixtures are anonymized copies of real GBP captures (see test_parser).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.core.database import get_async_db, get_db
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.tb_item import TBItem
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
from app.services.ventas_fuera_pdf.parser import parse_detallada, parse_resumen
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ventas_fuera_pdf"
DETALLADA = (FIXTURES / "gbp_detallada_anonimizada.pdf").read_bytes()
RESUMEN = (FIXTURES / "gbp_resumen_anonimizado.pdf").read_bytes()
SUBIR, VER = "ventas_fuera.subir_pdf", "ventas_fuera.ver_metricas_pdf"
RANGO = {"desde": "2025-03-01", "hasta": "2025-03-31", "empresa": "GRUPO GAUSS SRL"}


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
        ProductoERP.__table__,
        MarcaPM.__table__,
    ]
    stubs = [
        "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre VARCHAR(255) NOT NULL)",
        "INSERT INTO usuarios VALUES (7, 'U')",
    ]
    with throwaway_schema("vf_pdf_http", tablas, stubs) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE ventas_fuera_pdf_resumen_documentos, ventas_fuera_pdf_alcances, ventas_fuera_operacion_lineas, "
                "ventas_fuera_operaciones, ventas_fuera_pdf_cargas, productos_erp"
            )
        )


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


def _subir(client: TestClient, detallada: bytes | None = DETALLADA, resumen: bytes | None = RESUMEN):
    files = {}
    if detallada is not None:
        files["detallada"] = ("detallada.pdf", detallada, "application/pdf")
    if resumen is not None:
        files["resumen"] = ("resumen.pdf", resumen, "application/pdf")
    return client.post("/api/ventas-fuera-pdf/cargas", files=files)


def _ops(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM ventas_fuera_operaciones")).scalar_one()


class TestPermisos:
    def test_upload_without_permission_is_403_and_loads_nothing(self, engine: Engine) -> None:
        response = _subir(_client(engine, set()))

        assert response.status_code == 403
        assert _ops(engine) == 0

    def test_the_view_permission_does_not_open_the_upload(self, engine: Engine) -> None:
        assert _subir(_client(engine, {VER})).status_code == 403
        assert _ops(engine) == 0

    def test_operations_without_permission_is_403(self, engine: Engine) -> None:
        response = _client(engine, set()).get("/api/ventas-fuera-pdf/operaciones", params=RANGO)

        assert response.status_code == 403

    def test_the_upload_permission_does_not_open_the_operations(self, engine: Engine) -> None:
        response = _client(engine, {SUBIR}).get("/api/ventas-fuera-pdf/operaciones", params=RANGO)

        assert response.status_code == 403


class TestCarga:
    def test_upload_loads_the_operations_and_reports_the_load(self, engine: Engine) -> None:
        response = _subir(_client(engine, {SUBIR}))

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["empresa"], body["vendedor"], body["desde"], body["hasta"]) == (
            "GRUPO GAUSS SRL",
            "Carla Ejemplo",
            "2025-03-01",
            "2025-03-31",
        )
        assert (body["documentos"], body["reemplazados"], body["avisos"]) == (166, 0, [])
        assert (body["total_lineas"], body["recargo_financiero"]) == ("169632759.59", "480390.91")
        assert _ops(engine) == 166

    def test_uploading_twice_does_not_duplicate(self, engine: Engine) -> None:
        client = _client(engine, {SUBIR})
        _subir(client)

        body = _subir(client).json()

        assert (body["documentos"], body["reemplazados"]) == (166, 166)
        assert _ops(engine) == 166

    def test_the_summary_is_optional(self, engine: Engine) -> None:
        response = _subir(_client(engine, {SUBIR}), resumen=None)

        assert response.status_code == 200, response.text
        assert response.json()["recargo_financiero"] == "0.00"

    def test_files_swapped_are_refused_with_422_and_load_nothing(self, engine: Engine) -> None:
        response = _subir(_client(engine, {SUBIR}), detallada=RESUMEN, resumen=DETALLADA)

        assert response.status_code == 422
        assert "Reporte de Ventas Detalladas" in response.text
        assert _ops(engine) == 0

    def test_a_document_printed_twice_is_refused_with_422_naming_it(self, engine: Engine) -> None:
        repetido = (FIXTURES / "gbp_detallada_documento_repetido.pdf").read_bytes()

        response = _subir(_client(engine, {SUBIR}), detallada=repetido, resumen=None)

        assert response.status_code == 422
        assert "Fc A 00008-00018011 aparece más de una vez" in response.text
        assert _ops(engine) == 0

    def test_a_file_that_is_not_a_pdf_is_refused_with_422(self, engine: Engine) -> None:
        response = _subir(_client(engine, {SUBIR}), detallada=b"hola", resumen=None)

        assert response.status_code == 422


class TestOperaciones:
    def test_lists_operations_with_product_or_sin_producto(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, marca, categoria) "
                    "VALUES (501, '198154111069', 'LENOVO', 'Notebooks')"
                )
            )
        _subir(_client(engine, {SUBIR}))

        response = _client(engine, {VER}).get("/api/ventas-fuera-pdf/operaciones", params={**RANGO, "page_size": 200})

        assert response.status_code == 200, response.text
        ops = response.json()
        assert len(ops) == 166
        op = next(o for o in ops if o["numero"] == 17982)
        assert [(ln["codigo"], ln["item_id"], ln["marca"], ln["sin_producto"]) for ln in op["lineas"]] == [
            ("198154111069", 501, "LENOVO", False),
            (None, None, None, True),
        ]
        unknown = [ln for o in ops for ln in o["lineas"] if ln["codigo"] == "1210002613118"]
        assert unknown and all(ln["sin_producto"] and ln["item_id"] is None for ln in unknown)


class TestPaginacion:
    def test_an_inverted_range_is_refused_with_422(self, engine: Engine) -> None:
        response = _client(engine, {VER}).get(
            "/api/ventas-fuera-pdf/operaciones", params={**RANGO, "desde": "2025-03-31", "hasta": "2025-03-01"}
        )

        assert response.status_code == 422

    def test_scopes_come_in_pages(self, engine: Engine) -> None:
        client = _client(engine, {SUBIR})
        _subir(client, detallada=None)
        _subir(client, resumen=None)
        ver = _client(engine, {VER})

        assert len(ver.get("/api/ventas-fuera-pdf/alcances", params={"page_size": 1}).json()) == 1
        assert ver.get("/api/ventas-fuera-pdf/alcances", params={"page": 2}).json() == []
        assert ver.get("/api/ventas-fuera-pdf/alcances", params={"page_size": 501}).status_code == 422

    def test_operations_come_in_pages(self, engine: Engine) -> None:
        _subir(_client(engine, {SUBIR}))
        client = _client(engine, {VER})

        primera = client.get("/api/ventas-fuera-pdf/operaciones", params=RANGO).json()
        ultima = client.get("/api/ventas-fuera-pdf/operaciones", params={**RANGO, "page": 4}).json()
        todas = [
            o["id"]
            for page in (1, 2, 3, 4)
            for o in client.get("/api/ventas-fuera-pdf/operaciones", params={**RANGO, "page": page}).json()
        ]

        assert (len(primera), len(ultima)) == (50, 16)
        assert len(set(todas)) == 166

    def test_page_size_is_capped(self, engine: Engine) -> None:
        response = _client(engine, {VER}).get("/api/ventas-fuera-pdf/operaciones", params={**RANGO, "page_size": 501})

        assert response.status_code == 422


def _alcances(engine: Engine) -> list[dict]:
    response = _client(engine, {VER}).get("/api/ventas-fuera-pdf/alcances", params={"empresa": "GRUPO GAUSS SRL"})
    assert response.status_code == 200, response.text
    return response.json()


def _faltas(engine: Engine) -> list[tuple]:
    return [
        (a["vendedor"], a["desde"], a["hasta"], a["falta_detallada"], a["falta_resumen"]) for a in _alcances(engine)
    ]


def _recargos(engine: Engine) -> tuple[int, str]:
    with engine.connect() as conn:
        return tuple(
            conn.execute(
                text(
                    "SELECT COUNT(*) FILTER (WHERE recargo_financiero <> 0), COALESCE(SUM(recargo_financiero), 0)::text "
                    "FROM ventas_fuera_operaciones"
                )
            ).one()
        )


class TestFaltaResumenODetallada:
    """Owner (L8): "sí, me parece bien pero habría que marcar que falta subir el resumen o viceversa"."""

    def test_a_detailed_upload_alone_marks_its_scope_as_missing_the_summary(self, engine: Engine) -> None:
        body = _subir(_client(engine, {SUBIR}), resumen=None).json()

        assert (body["falta_detallada"], body["falta_resumen"]) == (False, True)
        assert "Falta subir el reporte de ventas (resumen) de este período." in body["avisos"]
        assert _faltas(engine) == [("Carla Ejemplo", "2025-03-01", "2025-03-31", False, True)]

    def test_a_summary_upload_alone_creates_no_operations_and_marks_the_detailed_as_missing(
        self, engine: Engine
    ) -> None:
        response = _subir(_client(engine, {SUBIR}), detallada=None)

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["documentos"], body["lineas"], body["falta_detallada"], body["falta_resumen"]) == (
            0,
            0,
            True,
            False,
        )
        assert "Falta subir el reporte detallado de este período." in body["avisos"]
        assert _ops(engine) == 0
        assert _faltas(engine) == [("Carla Ejemplo", "2025-03-01", "2025-03-31", True, False)]

    def test_a_detailed_upload_pairs_with_the_summary_loaded_before(self, engine: Engine) -> None:
        client = _client(engine, {SUBIR})
        _subir(client, detallada=None)

        body = _subir(client, resumen=None).json()

        assert (body["falta_detallada"], body["falta_resumen"], body["avisos"]) == (False, False, [])
        assert body["recargo_financiero"] == "480390.91"
        assert _recargos(engine) == (7, "480390.91")
        assert _faltas(engine) == [("Carla Ejemplo", "2025-03-01", "2025-03-31", False, False)]

    def test_a_summary_upload_pairs_with_the_detailed_loaded_before_and_reruns_the_cross_check(
        self, engine: Engine
    ) -> None:
        client = _client(engine, {SUBIR})
        _subir(client, resumen=None)
        assert _recargos(engine) == (0, "0.00")

        body = _subir(client, detallada=None).json()

        assert (body["falta_detallada"], body["falta_resumen"], body["avisos"]) == (False, False, [])
        assert (body["documentos"], body["recargo_financiero"]) == (0, "480390.91")
        assert _recargos(engine) == (7, "480390.91")
        assert _ops(engine) == 166
        assert _faltas(engine) == [("Carla Ejemplo", "2025-03-01", "2025-03-31", False, False)]

    def test_both_reports_together_leave_nothing_missing(self, engine: Engine) -> None:
        body = _subir(_client(engine, {SUBIR})).json()

        assert (body["falta_detallada"], body["falta_resumen"]) == (False, False)
        assert _faltas(engine) == [("Carla Ejemplo", "2025-03-01", "2025-03-31", False, False)]

    def test_no_file_is_refused_with_422(self, engine: Engine) -> None:
        assert _subir(_client(engine, {SUBIR}), detallada=None, resumen=None).status_code == 422

    def test_scopes_without_permission_is_403(self, engine: Engine) -> None:
        assert _client(engine, set()).get("/api/ventas-fuera-pdf/alcances").status_code == 403


def _como(monkeypatch: pytest.MonkeyPatch, detallada=None, resumen=None) -> None:
    """The next uploads read the fixtures changed by `detallada` / `resumen` (a salesperson filter "Todos", a shorter
    range, another salesperson): GBP exports those reports, the fixtures are one export."""
    monkeypatch.setattr(ventas_fuera_pdf, "parse_detallada", lambda b: (detallada or (lambda r: r))(parse_detallada(b)))
    monkeypatch.setattr(ventas_fuera_pdf, "parse_resumen", lambda b: (resumen or (lambda r: r))(parse_resumen(b)))


def _todos(reporte):
    return dataclasses.replace(reporte, vendedor=None)


QUINCENA = date(2025, 3, 15)


def _primera_quincena(reporte):
    docs = [d for d in reporte.documentos if d.fecha <= QUINCENA]
    return dataclasses.replace(reporte, hasta=QUINCENA, documentos=docs)


def _otro_vendedor_en_impares(reporte):
    """A "Todos" detailed report where the odd-numbered documents belong to another salesperson."""
    docs = [dataclasses.replace(d, vendedor="Otro Vendedor") if d.numero % 2 else d for d in reporte.documentos]
    return dataclasses.replace(reporte, vendedor=None, documentos=docs)


def _sin_impares(reporte):
    return dataclasses.replace(reporte, documentos=[d for d in reporte.documentos if not d.numero % 2])


def _rango(desde: int, hasta: int, vendedor: str | None = "igual"):
    """The report as GBP exports it for days `desde`-`hasta` of March 2025 (and another salesperson filter)."""

    def cambiar(reporte):
        d, h = date(2025, 3, desde), date(2025, 3, hasta)
        docs = [doc for doc in reporte.documentos if d <= doc.fecha <= h]
        filtro = reporte.vendedor if vendedor == "igual" else vendedor
        return dataclasses.replace(reporte, desde=d, hasta=h, vendedor=filtro, documentos=docs)

    return cambiar


def _dos_vendedores(reporte):
    """The odd-numbered documents belong to "Otro Vendedor"; a salesperson-filtered report keeps only its own."""
    docs = [dataclasses.replace(d, vendedor="Otro Vendedor") if d.numero % 2 else d for d in reporte.documentos]
    if reporte.vendedor == "Otro Vendedor":
        docs = [d for d in docs if d.numero % 2]
    elif reporte.vendedor is not None:
        docs = [d for d in docs if not d.numero % 2]
    return dataclasses.replace(reporte, documentos=docs)


def _de(*cambios):
    def aplicar(reporte):
        for cambio in cambios:
            reporte = cambio(reporte)
        return reporte

    return aplicar


def _faltantes(engine: Engine) -> dict:
    return {(a["vendedor"], a["desde"], a["hasta"]): a["faltantes"] for a in _alcances(engine)}


def _sin_control(avisos: list[str]) -> list[str]:
    return [a for a in avisos if "pero no en" in a]


class TestCoberturaPorPartes:
    """Owner (L11): "No, que cubra por partes". A "Todos" (or wider) detailed report is controlled by the
    per-salesperson summaries inside its company and range, and the reverse; a scope is missing a report only for
    the salespeople and dates no report of the other kind covers."""

    def test_a_todos_detailed_is_controlled_by_the_salesperson_summary(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_todos)
        _subir(client, resumen=None)

        body = _subir(client, detallada=None).json()

        assert (body["falta_detallada"], body["falta_resumen"], body["avisos"]) == (False, False, [])
        assert _recargos(engine) == (7, "480390.91")
        assert sorted(_faltas(engine), key=str) == [
            ("Carla Ejemplo", "2025-03-01", "2025-03-31", False, False),
            (None, "2025-03-01", "2025-03-31", False, False),
        ]

    def test_a_todos_summary_controls_the_salesperson_detailed(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(engine, {SUBIR})
        _como(monkeypatch, resumen=_todos)
        _subir(client, detallada=None)

        body = _subir(client, resumen=None).json()

        assert (body["falta_detallada"], body["falta_resumen"], body["avisos"]) == (False, False, [])
        assert body["recargo_financiero"] == "480390.91"
        assert all(not a["falta_detallada"] and not a["falta_resumen"] for a in _alcances(engine))

    def test_a_detailed_month_with_a_half_month_summary_misses_only_the_other_half(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_todos, resumen=_primera_quincena)
        _subir(client, resumen=None)

        body = _subir(client, detallada=None).json()

        assert (body["falta_detallada"], body["falta_resumen"]) == (False, False)
        mes = _alcances(engine)
        todos = next(a for a in mes if a["vendedor"] is None)
        assert (todos["falta_detallada"], todos["falta_resumen"]) == (False, True)
        assert todos["faltantes"] == [
            {"reporte": "resumen", "vendedor": "Carla Ejemplo", "desde": "2025-03-16", "hasta": "2025-03-31"}
        ]
        assert todos["avisos"][0] == (
            "Falta subir el reporte de ventas (resumen) de Carla Ejemplo del 16/03/2025 al 31/03/2025."
        )
        # The second half has no summary yet: its documents are pending, not "missing in the summary".
        assert _sin_control(todos["avisos"]) == []

    def test_a_salesperson_no_summary_covers_is_the_only_one_missing(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_otro_vendedor_en_impares, resumen=_sin_impares)
        _subir(client, resumen=None)
        _subir(client, detallada=None)

        todos = next(a for a in _alcances(engine) if a["vendedor"] is None)

        assert todos["faltantes"] == [
            {"reporte": "resumen", "vendedor": "Otro Vendedor", "desde": "2025-03-01", "hasta": "2025-03-31"}
        ]
        assert _sin_control(todos["avisos"]) == []

    @pytest.mark.parametrize(("nombre_conocido", "esperado"), [(True, "Carla Ejemplo"), (False, "Carla Ejempl")])
    def test_a_missing_salesperson_is_named_in_full_when_a_header_names_them(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch, nombre_conocido: bool, esperado: str
    ) -> None:
        """GBP cuts the salesperson to 12 characters on documents ("Carla Ejempl"); a report header of the company
        names them in full, and that is the name shown. Without one, GBP's prefix stays."""
        client = _client(engine, {SUBIR})
        if nombre_conocido:
            _como(
                monkeypatch,
                detallada=lambda r: dataclasses.replace(
                    r, desde=date(2025, 2, 1), hasta=date(2025, 2, 28), documentos=[]
                ),
            )
            _subir(client, resumen=None)
        largo = "Otro Vendedor Largo"
        _como(
            monkeypatch,
            detallada=lambda r: dataclasses.replace(
                r,
                vendedor=None,
                documentos=[dataclasses.replace(d, vendedor=largo[:12]) if d.numero % 2 else d for d in r.documentos],
            ),
            resumen=lambda r: dataclasses.replace(
                r,
                vendedor=largo,
                documentos=[dataclasses.replace(d, vendedor=largo) for d in r.documentos if d.numero % 2],
            ),
        )
        _subir(client, resumen=None)
        _subir(client, detallada=None)

        todos = next(a for a in _alcances(engine) if a["vendedor"] is None)

        assert todos["faltantes"] == [
            {"reporte": "resumen", "vendedor": esperado, "desde": "2025-03-01", "hasta": "2025-03-31"}
        ]
        assert todos["avisos"][0] == (
            f"Falta subir el reporte de ventas (resumen) de {esperado} del 01/03/2025 al 31/03/2025."
        )

    def test_a_gap_between_two_summaries_is_the_only_part_missing_until_it_is_uploaded(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) Todos detailed + Carla summaries for 01-10 and 21-31: only 11-20 is missing; uploading it clears it."""
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_todos)
        _subir(client, resumen=None)
        for desde, hasta in ((1, 10), (21, 31)):
            _como(monkeypatch, resumen=_rango(desde, hasta))
            _subir(client, detallada=None)

        todos = next(a for a in _alcances(engine) if a["vendedor"] is None)
        assert todos["faltantes"] == [
            {"reporte": "resumen", "vendedor": "Carla Ejemplo", "desde": "2025-03-11", "hasta": "2025-03-20"}
        ]

        _como(monkeypatch, resumen=_rango(11, 20))
        _subir(client, detallada=None)

        assert all(a["faltantes"] == [] for a in _alcances(engine))
        assert _recargos(engine) == (7, "480390.91")

    def test_with_two_salespeople_only_the_half_covered_one_misses_its_second_half(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(b) Todos detailed of two salespeople; the other one's summary covers the month, Carla's only 01-15."""
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_de(_todos, _dos_vendedores))
        _subir(client, resumen=None)
        _como(monkeypatch, resumen=_de(lambda r: dataclasses.replace(r, vendedor="Otro Vendedor"), _dos_vendedores))
        _subir(client, detallada=None)
        _como(monkeypatch, resumen=_de(_rango(1, 15), _dos_vendedores))
        _subir(client, detallada=None)

        todos = next(a for a in _alcances(engine) if a["vendedor"] is None)

        assert todos["faltantes"] == [
            {"reporte": "resumen", "vendedor": "Carla Ejemplo", "desde": "2025-03-16", "hasta": "2025-03-31"}
        ]
        assert _sin_control(todos["avisos"]) == []

    def test_a_salesperson_detailed_wider_than_its_summary_misses_only_the_uncovered_dates(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(d) Carla's detailed report covers the month, her summary only 01-15."""
        client = _client(engine, {SUBIR})
        _subir(client, resumen=None)
        _como(monkeypatch, resumen=_rango(1, 15))

        body = _subir(client, detallada=None).json()

        assert body["faltantes"] == []
        carla = _faltantes(engine)[("Carla Ejemplo", "2025-03-01", "2025-03-31")]
        assert carla == [
            {"reporte": "resumen", "vendedor": "Carla Ejemplo", "desde": "2025-03-16", "hasta": "2025-03-31"}
        ]

    def test_a_todos_summary_and_salesperson_summaries_together_leave_nothing_missing(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(e) Todos detailed controlled by a Todos summary for 01-15 and Carla's summary for 16-31."""
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_todos, resumen=_rango(1, 15, vendedor=None))
        _subir(client, resumen=None)
        _subir(client, detallada=None)
        _como(monkeypatch, resumen=_rango(16, 31))
        _subir(client, detallada=None)

        assert all(a["faltantes"] == [] for a in _alcances(engine))
        assert all(_sin_control(a["avisos"]) == [] for a in _alcances(engine))
        assert _recargos(engine) == (7, "480390.91")

    def test_a_todos_summary_alone_misses_the_detailed_of_everyone(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(f) A Todos summary alone: the detailed report is missing for every salesperson, no operations."""
        _como(monkeypatch, resumen=_todos)

        body = _subir(_client(engine, {SUBIR}), detallada=None).json()

        esperado = [{"reporte": "detallada", "vendedor": None, "desde": "2025-03-01", "hasta": "2025-03-31"}]
        assert (body["faltantes"], body["falta_detallada"], body["documentos"]) == (esperado, True, 0)
        assert _faltantes(engine) == {(None, "2025-03-01", "2025-03-31"): esperado}
        assert _ops(engine) == 0

    def test_a_todos_half_month_replaces_the_salesperson_load_and_reuploading_it_changes_nothing(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(g) After Carla's full load, a Todos detailed for 01-15 replaces her documents of those days; her scope
        says so, and uploading the Todos report again keeps everything as it was."""
        client = _client(engine, {SUBIR})
        _subir(client)
        _como(monkeypatch, detallada=_rango(1, 15, vendedor=None))
        primera = _subir(client, resumen=None).json()
        reemplazados = primera["reemplazados"]
        antes = (_ops(engine), _recargos(engine), _alcances(engine))

        segunda = _subir(client, resumen=None).json()

        assert reemplazados == primera["documentos"] > 0
        carla = next(a for a in _alcances(engine) if a["vendedor"] == "Carla Ejemplo")
        assert carla["avisos"][0] == (
            f"{reemplazados} comprobantes de este período se reemplazaron por una carga posterior "
            "(Todos, 01/03/2025-15/03/2025)."
        )
        assert (segunda["reemplazados"], segunda["documentos"]) == (reemplazados, reemplazados)
        despues = (_ops(engine), _recargos(engine), _alcances(engine))
        sin_fecha = lambda xs: [{k: v for k, v in a.items() if k != "updated_at"} for a in xs]  # noqa: E731
        assert (despues[0], despues[1], sin_fecha(despues[2])) == (antes[0], antes[1], sin_fecha(antes[2]))

    def test_a_summary_month_with_a_half_month_detailed_misses_only_the_other_half(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_primera_quincena, resumen=_todos)
        _subir(client, detallada=None)

        body = _subir(client, resumen=None).json()

        assert (body["falta_detallada"], body["falta_resumen"], body["avisos"]) == (False, False, [])
        todos = next(a for a in _alcances(engine) if a["vendedor"] is None)
        assert todos["faltantes"] == [
            {"reporte": "detallada", "vendedor": "Carla Ejemplo", "desde": "2025-03-16", "hasta": "2025-03-31"}
        ]
        assert _sin_control(todos["avisos"]) == []


# Verifier probes on #2291 (L8 pairing, S5 replace), kept as regression tests.


def _snap(engine: Engine):
    with engine.connect() as c:
        return tuple(
            c.execute(text(q)).all()
            for q in (
                "SELECT id, carga_id, numero, total_lineas, recargo_financiero, importe_resumen FROM ventas_fuera_operaciones ORDER BY id",
                "SELECT id, empresa, vendedor, desde, hasta, detallada_carga_id, resumen_carga_id, avisos::text FROM ventas_fuera_pdf_alcances ORDER BY id",
                "SELECT COUNT(*) FROM ventas_fuera_pdf_resumen_documentos",
                "SELECT COUNT(*) FROM ventas_fuera_pdf_cargas",
            )
        )


def test_summary_alone_after_full_load_keeps_operations(engine: Engine) -> None:
    c = _client(engine, {SUBIR})
    _subir(c)
    body = _subir(c, detallada=None).json()
    assert (body["reemplazados"], body["documentos"], body["falta_detallada"], body["falta_resumen"]) == (
        0,
        0,
        False,
        False,
    )
    assert body["avisos"] == []
    assert _ops(engine) == 166 and _recargos(engine) == (7, "480390.91")
    assert len(_faltas(engine)) == 1


def test_detailed_reupload_after_pairing_keeps_pair_and_replaces(engine: Engine) -> None:
    c = _client(engine, {SUBIR})
    _subir(c, detallada=None)
    _subir(c, resumen=None)
    body = _subir(c, resumen=None).json()
    assert (body["reemplazados"], body["falta_resumen"], body["avisos"]) == (166, False, [])
    assert _ops(engine) == 166 and _recargos(engine) == (7, "480390.91")


def test_rejected_uploads_change_nothing(engine: Engine) -> None:
    c = _client(engine, {SUBIR})
    _subir(c, resumen=None)
    antes = _snap(engine)
    assert _subir(c, detallada=None, resumen=DETALLADA).status_code == 422
    assert _subir(c, detallada=RESUMEN, resumen=None).status_code == 422
    assert _subir(c, detallada=None, resumen=b"x").status_code == 422
    assert _subir(c, detallada=None, resumen=None).status_code == 422
    assert _snap(engine) == antes


def test_alcances_view_permission_and_empty(engine: Engine) -> None:
    assert _client(engine, {VER}).get("/api/ventas-fuera-pdf/alcances").json() == []
    assert _client(engine, {SUBIR}).get("/api/ventas-fuera-pdf/alcances").status_code == 200
    assert _client(engine, {VER}).get("/api/ventas-fuera-pdf/alcances", params={"page": 0}).status_code == 422


def test_routes_are_registered_in_the_app() -> None:
    from app.main import app

    paths = set(app.openapi()["paths"])

    assert {
        "/api/ventas-fuera-pdf/cargas",
        "/api/ventas-fuera-pdf/operaciones",
        "/api/ventas-fuera-pdf/alcances",
    } <= paths
