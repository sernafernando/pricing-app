"""vpf-metricas-canal-fe T1: the two-step upload, its structured result and the upload history (C1, C2).

Owner (L22), verbatim: "Al cargar el pdf leerlo y seleccionar que vendedores se van a importar." Step 1
(`POST /cargas/preview`) reads the reports and lists their salespeople, storing nothing; step 2 (`POST /cargas` with
`vendedores`) imports only the chosen ones and replaces company + chosen salespeople + range. Without `vendedores` the
upload is the one of #2291. Real Postgres; the fixtures are the anonymized GBP captures of #2291 (invented names,
numbers, dates and amounts), reshaped per test like GBP would export them (`_como`).
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from typing import Iterator, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.core.database import get_async_db, get_db
from app.models.combo_componente import ComboComponente
from app.models.costo_si import CostoSiPaso
from app.models.cur_exch_history import CurExchHistory
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
from app.services.ventas_fuera_pdf.carga import es_excluido
from app.services.ventas_fuera_pdf.parser import parse_detallada, parse_resumen
from tests.routers.test_ventas_fuera_pdf_postgres import DETALLADA, RESUMEN, SUBIR, VER, _como, _de, _rango, _todos
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

URL = "/api/ventas-fuera-pdf/cargas"
OTRO = "Otro Vendedor"
# The salesperson as the fixture's documents print it (GBP cuts it to 12 characters) and as its header names it.
CARLA_IMPRESO = parse_detallada(DETALLADA).documentos[0].vendedor
CARLA = "Carla Ejemplo"


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
        ItemCostListHistory.__table__,
        TipoCambio.__table__,
        CurExchHistory.__table__,
        ProductoERP.__table__,
        MarcaPM.__table__,
        # The costo SI the load costs each line with since sell-in-costo-si T3 PR 9 (`costo_si.lote`); empty here.
        CostoSiPaso.__table__,
        ComboComponente.__table__,
        VendedorExcluido.__table__,
    ]
    stubs = [
        "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre VARCHAR(255) NOT NULL)",
        "INSERT INTO usuarios VALUES (7, 'Usuaria Ejemplo')",
    ]
    with throwaway_schema("vf_pdf_cargas", tablas, stubs) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE ventas_fuera_pdf_resumen_documentos, ventas_fuera_pdf_alcances, ventas_fuera_operacion_lineas, "
                "ventas_fuera_operaciones, ventas_fuera_pdf_cargas, productos_erp, vendedores_excluidos"
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
    app.dependency_overrides[get_current_user] = lambda: SimpleUser(permisos)
    return TestClient(app)


@dataclasses.dataclass
class SimpleUser:
    _permisos_cache: set
    id: int = 7
    es_superadmin: bool = False


def _files(detallada: Optional[bytes] = DETALLADA, resumen: Optional[bytes] = RESUMEN) -> dict:
    files = {}
    if detallada is not None:
        files["detallada"] = ("detallada.pdf", detallada, "application/pdf")
    if resumen is not None:
        files["resumen"] = ("resumen.pdf", resumen, "application/pdf")
    return files


def _preview(client: TestClient, **kwargs):
    return client.post(f"{URL}/preview", files=_files(**kwargs))


def _subir(client: TestClient, vendedores=None, raw: Optional[str] = None, **kwargs):
    data = {}
    if vendedores is not None:
        data["vendedores"] = json.dumps(vendedores)
    if raw is not None:
        data["vendedores"] = raw
    return client.post(URL, files=_files(**kwargs), data=data)


def _q(engine: Engine, sql: str) -> list:
    with engine.connect() as conn:
        return conn.execute(text(sql)).all()


def _conteos(engine: Engine) -> tuple:
    return tuple(
        _q(engine, f"SELECT COUNT(*) FROM {t}")[0][0]
        for t in ("ventas_fuera_pdf_cargas", "ventas_fuera_operaciones", "ventas_fuera_pdf_alcances")
    )


def _dos(reporte):
    """The odd-numbered documents belong to "Otro Vendedor" (a "Todos" report of two salespeople)."""
    docs = [dataclasses.replace(d, vendedor=OTRO) if d.numero % 2 else d for d in reporte.documentos]
    return dataclasses.replace(reporte, vendedor=None, documentos=docs)


def _excluir(engine: Engine, *nombres: str) -> None:
    with engine.begin() as conn:
        for i, nombre in enumerate(nombres, start=1):
            conn.execute(
                text("INSERT INTO vendedores_excluidos (sm_id, sm_name) VALUES (:i, :n)"), {"i": 900 + i, "n": nombre}
            )


def _por_vendedor(engine: Engine) -> dict:
    return dict(_q(engine, "SELECT vendedor, COUNT(*) FROM ventas_fuera_operaciones GROUP BY vendedor"))


class TestPreview:
    def test_lists_the_salespeople_most_sold_first_marks_the_excluded_and_stores_nothing(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _como(monkeypatch, detallada=_dos, resumen=_dos)
        _excluir(engine, "  otro   VENDEDOR ")
        docs = _dos(parse_detallada(DETALLADA)).documentos
        esperado = {
            nombre: (
                sum(1 for d in docs if d.vendedor == nombre),
                float(sum((d.total_lineas for d in docs if d.vendedor == nombre), Decimal(0))),
            )
            for nombre in (CARLA_IMPRESO, OTRO)
        }

        response = _preview(_client(engine, {SUBIR}))

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["empresa"], body["desde"], body["hasta"], body["vendedor_filtro"]) == (
            "GRUPO GAUSS SRL",
            "2025-03-01",
            "2025-03-31",
            None,
        )
        assert (body["archivo_detallado"], body["archivo_resumen"]) == ("detallada.pdf", "resumen.pdf")
        filas = [(v["vendedor"], v["documentos"], v["total_lineas"], v["excluido"]) for v in body["vendedores"]]
        assert filas == sorted([(n, *esperado[n], n == OTRO) for n in esperado], key=lambda f: -f[2])
        assert _conteos(engine) == (0, 0, 0)

    def test_a_salesperson_report_lists_its_salesperson_by_the_header_name(self, engine: Engine) -> None:
        body = _preview(_client(engine, {SUBIR}), resumen=None).json()

        assert body["vendedor_filtro"] == CARLA
        assert body["archivo_resumen"] is None
        assert body["vendedores"] == [
            {"vendedor": CARLA, "documentos": 166, "total_lineas": 169632759.59, "excluido": False}
        ]

    def test_a_summary_alone_lists_its_salespeople_by_its_importe(self, engine: Engine) -> None:
        total = float(sum((d.importe for d in parse_resumen(RESUMEN).documentos), Decimal(0)))

        body = _preview(_client(engine, {SUBIR}), detallada=None).json()

        assert body["archivo_detallado"] is None
        assert [(v["vendedor"], v["documentos"], v["total_lineas"]) for v in body["vendedores"]] == [
            (CARLA, 166, total)
        ]

    @pytest.mark.parametrize(
        "files",
        [
            {"detallada": None, "resumen": None},
            {"detallada": RESUMEN, "resumen": DETALLADA},
            {"detallada": b"hola", "resumen": None},
        ],
    )
    def test_refuses_what_the_upload_refuses_with_422(self, engine: Engine, files: dict) -> None:
        assert _preview(_client(engine, {SUBIR}), **files).status_code == 422
        assert _conteos(engine) == (0, 0, 0)

    def test_a_pair_of_different_scopes_is_422(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _como(monkeypatch, resumen=_todos)

        response = _preview(_client(engine, {SUBIR}))

        assert response.status_code == 422
        assert "no corresponde al detallado" in response.text

    @pytest.mark.parametrize("permisos", [set(), {VER}])
    def test_needs_the_upload_permission(self, engine: Engine, permisos: set) -> None:
        assert _preview(_client(engine, permisos)).status_code == 403


@pytest.mark.parametrize(
    ("nombre", "excluidos", "esperado"),
    [
        ("Vendedor ML", ["vendedor ml"], True),
        ("VENDEDOR  TN ", ["Vendedor TN"], True),
        ("Vendedor Mer", ["Vendedor Mercado Libre"], True),  # cut by GBP to 12 characters
        ("Vendedor", ["Vendedor ML"], False),  # a shorter name is not a cut one
        ("Carla Ejemplo", ["", None, "Otro Vendedor"], False),
    ],
)
def test_es_excluido_is_case_and_space_insensitive(nombre: str, excluidos: list, esperado: bool) -> None:
    assert es_excluido(nombre, excluidos) is esperado


class TestElegirVendedores:
    def test_without_vendedores_every_salesperson_is_imported_as_before(self, engine: Engine) -> None:
        body = _subir(_client(engine, {SUBIR})).json()

        assert (body["documentos"], body["reemplazados"], body["vendedores"]) == (166, 0, [CARLA])
        assert _q(engine, "SELECT vendedor FROM ventas_fuera_pdf_alcances") == [(CARLA,)]
        assert _q(engine, "SELECT vendedores::text FROM ventas_fuera_pdf_cargas") == [(f'["{CARLA}"]',)]

    def test_only_the_chosen_salespeople_are_stored(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _como(monkeypatch, detallada=_dos, resumen=_dos)
        otros = sum(1 for d in _dos(parse_detallada(DETALLADA)).documentos if d.vendedor == OTRO)

        response = _subir(_client(engine, {SUBIR}), vendedores=[OTRO])

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["vendedor"], body["vendedores"], body["documentos"]) == (None, [OTRO], otros)
        assert _por_vendedor(engine) == {OTRO: otros}
        # The upload never claims the salespeople left out: one scope, of the chosen salesperson.
        assert _q(engine, "SELECT vendedor FROM ventas_fuera_pdf_alcances") == [(OTRO,)]
        assert (body["falta_detallada"], body["falta_resumen"], body["avisos"]) == (False, False, [])

    def test_the_replace_covers_only_the_chosen_salespeople(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_dos, resumen=_dos)
        primera = _subir(client).json()["carga_id"]
        antes = _por_vendedor(engine)

        body = _subir(client, vendedores=[OTRO]).json()

        assert body["reemplazados"] == antes[OTRO]
        assert _por_vendedor(engine) == antes
        cargas = dict(
            _q(engine, "SELECT vendedor, array_agg(DISTINCT carga_id) FROM ventas_fuera_operaciones GROUP BY 1")
        )
        assert cargas == {CARLA_IMPRESO: [primera], OTRO: [body["carga_id"]]}
        assert body["reemplazo"]["documentos"] == antes[OTRO]
        assert body["reemplazo"]["carga_anterior_at"] is not None

    def test_a_subset_of_a_todos_pdf_misses_the_summary_only_for_the_chosen_salesperson(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L8/L11 stay coherent: the Todos detailed imported for Carla only is Carla's scope; it misses the summary
        for Carla alone, never for "Todos" nor for the salesperson left out."""
        _como(monkeypatch, detallada=_dos)

        body = _subir(_client(engine, {SUBIR}), vendedores=[CARLA_IMPRESO], resumen=None).json()

        assert body["faltantes"] == [
            {"reporte": "resumen", "vendedor": CARLA_IMPRESO, "desde": "2025-03-01", "hasta": "2025-03-31"}
        ]
        alcances = _q(engine, "SELECT vendedor, faltantes::text FROM ventas_fuera_pdf_alcances")
        assert [v for v, _ in alcances] == [CARLA_IMPRESO]
        assert OTRO not in alcances[0][1]

    def test_choosing_every_salesperson_is_the_upload_without_vendedores(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _como(monkeypatch, detallada=_dos, resumen=_dos)

        body = _subir(_client(engine, {SUBIR}), vendedores=[OTRO, CARLA_IMPRESO]).json()

        assert body["documentos"] == 166
        assert _q(engine, "SELECT vendedor FROM ventas_fuera_pdf_alcances") == [(None,)]

    @pytest.mark.parametrize(
        ("raw", "mensaje"),
        [
            ("[]", "al menos un vendedor"),
            (json.dumps(["Nadie Ejemplo"]), "Nadie Ejemplo"),
            ("no es json", "lista JSON"),
            (json.dumps([1, 2]), "lista JSON"),
        ],
    )
    def test_an_empty_or_unknown_choice_is_422_and_stores_nothing(self, engine: Engine, raw: str, mensaje: str) -> None:
        response = _subir(_client(engine, {SUBIR}), raw=raw)

        assert response.status_code == 422
        assert mensaje in response.text
        assert _conteos(engine) == (0, 0, 0)


def _sin_resto(resto: int):
    """The detailed report without the documents whose number leaves `resto` divided by 3."""

    def cambiar(reporte):
        return dataclasses.replace(reporte, documentos=[d for d in reporte.documentos if d.numero % 3 != resto])

    return cambiar


class TestReemplazoNuevosYAnulados:
    """C5: reemplazo.nuevos (documents of this upload not loaded before for that scope) and reemplazo.anulados
    (previously loaded documents of the chosen salespeople/range absent from this PDF, deleted)."""

    def test_counts_the_new_documents_and_those_gone_from_gbp(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        numeros = [d.numero for d in parse_detallada(DETALLADA).documentos]
        cero, uno = sum(1 for n in numeros if n % 3 == 0), sum(1 for n in numeros if n % 3 == 1)
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_sin_resto(0))
        primera = _subir(client, resumen=None).json()
        _como(monkeypatch, detallada=_sin_resto(1))

        body = _subir(client, resumen=None).json()

        assert (primera["reemplazo"]["nuevos"], primera["reemplazo"]["anulados"]) == (len(numeros) - cero, 0)
        assert body["reemplazo"]["documentos"] == len(numeros) - cero
        assert (body["reemplazo"]["nuevos"], body["reemplazo"]["anulados"]) == (cero, uno)
        assert _q(engine, "SELECT COUNT(*) FROM ventas_fuera_operaciones")[0][0] == len(numeros) - uno

    def test_a_subset_counts_only_the_chosen_salespeople(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(engine, {SUBIR})
        _como(monkeypatch, detallada=_dos)
        _subir(client, resumen=None)
        otros = _por_vendedor(engine)[OTRO]
        _como(monkeypatch, detallada=_de(_dos, _sin_resto(1)))

        body = _subir(client, resumen=None, vendedores=[OTRO]).json()

        idos = sum(1 for d in _dos(parse_detallada(DETALLADA)).documentos if d.vendedor == OTRO and d.numero % 3 == 1)
        assert (body["reemplazo"]["nuevos"], body["reemplazo"]["anulados"]) == (0, idos)
        assert body["reemplazo"]["documentos"] == otros


class TestResultado:
    def test_the_result_carries_the_whole_upload_and_keeps_it_on_the_upload_row(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO productos_erp (item_id, codigo) VALUES (501, '198154111069')"))
        reporte = parse_detallada(DETALLADA)
        lineas = [ln for d in reporte.documentos for ln in d.lineas]
        sin = [ln for ln in lineas if ln.codigo != "198154111069"]
        tipos = sorted({(d.tipo, d.letra) for d in reporte.documentos})

        body = _subir(_client(engine, {SUBIR})).json()

        assert body["usuario"] == "Usuaria Ejemplo"
        assert body["created_at"]
        assert body["unidades"] == float(sum((ln.cantidad for ln in lineas), Decimal(0)))
        assert [(t["tipo"], t["letra"]) for t in body["documentos_por_tipo"]] == tipos
        assert sum(t["cantidad"] for t in body["documentos_por_tipo"]) == 166
        assert body["sin_producto"]["lineas"] == len(sin)
        assert body["sin_producto"]["monto"] == float(sum((ln.precio for ln in sin), Decimal(0)))
        assert sum(a["lineas"] for a in body["sin_producto"]["articulos"]) == len(sin)
        assert body["reemplazo"] == {"documentos": 0, "carga_anterior_at": None, "nuevos": 166, "anulados": 0}
        control = body["control"]
        assert (control["resumen"], control["documentos_coinciden"], control["total_lineas"]) == (
            True,
            True,
            169632759.59,
        )
        assert round(control["diferencia"], 2) == 480390.91
        assert round(control["total_resumen"] - control["total_lineas"], 2) == 480390.91
        assert len(control["cheques"]) == 7
        assert round(sum(c["recargo"] for c in control["cheques"]), 2) == 480390.91
        fila = (
            _q(
                engine,
                "SELECT lineas, unidades, total_lineas::text, sin_producto_lineas, recargo_financiero::text, "
                "control_estado, control->>'resumen' FROM ventas_fuera_pdf_cargas",
            )
        )[0]
        assert tuple(fila) == (
            len(lineas),
            sum((ln.cantidad for ln in lineas), Decimal(0)),
            "169632759.59",
            len(sin),
            "480390.91",
            "ok",
            "true",
        )

    def test_a_detailed_alone_has_no_summary_control(self, engine: Engine) -> None:
        body = _subir(_client(engine, {SUBIR}), resumen=None).json()

        assert body["control"] == {
            "resumen": False,
            "documentos_coinciden": None,
            "total_resumen": None,
            "total_lineas": 169632759.59,
            "diferencia": None,
            "cheques": [],
        }
        assert _q(engine, "SELECT control_estado FROM ventas_fuera_pdf_cargas") == [("sin_resumen",)]


def _historial(engine: Engine, permisos: set[str] = frozenset({VER}), **params) -> list[dict]:
    response = _client(engine, set(permisos)).get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestHistorial:
    def test_lists_the_uploads_newest_first_with_their_state_and_control(self, engine: Engine) -> None:
        client = _client(engine, {SUBIR})
        _subir(client, resumen=None)
        _subir(client, resumen=None)
        _subir(client, detallada=None)

        filas = _historial(engine)

        assert [(f["archivo_detallado"], f["estado"], f["control"]) for f in filas] == [
            (None, "vigente", "ok"),
            ("detallada.pdf", "vigente", "sin_resumen"),
            ("detallada.pdf", "reemplazada", "sin_resumen"),
        ]
        ultima = filas[1]
        assert (ultima["usuario"], ultima["empresa"], ultima["vendedor"], ultima["vendedores"]) == (
            "Usuaria Ejemplo",
            "GRUPO GAUSS SRL",
            CARLA,
            [CARLA],
        )
        assert (ultima["documentos"], ultima["reemplazados"], ultima["total_lineas"]) == (166, 166, 169632759.59)
        assert ultima["control_detalle"]["resumen"] is False
        assert filas[0]["control_detalle"]["resumen"] is True

    def test_each_row_has_its_documents_per_type_and_the_upload_it_replaced(self, engine: Engine) -> None:
        client = _client(engine, {SUBIR})
        primera = _subir(client, resumen=None).json()
        segunda = _subir(client, resumen=None).json()
        resumen = _subir(client, detallada=None).json()

        filas = {f["id"]: f for f in _historial(engine)}

        assert filas[segunda["carga_id"]]["documentos_por_tipo"] == segunda["documentos_por_tipo"]
        assert sum(t["cantidad"] for t in filas[segunda["carga_id"]]["documentos_por_tipo"]) == 166
        assert filas[segunda["carga_id"]]["carga_anterior_at"] == filas[primera["carga_id"]]["created_at"]
        assert filas[primera["carga_id"]]["carga_anterior_at"] is None
        assert (filas[resumen["carga_id"]]["documentos_por_tipo"], filas[resumen["carga_id"]]["carga_anterior_at"]) == (
            [],
            None,
        )
        anterior = _q(
            engine,
            f"SELECT carga_anterior_at IS NOT NULL FROM ventas_fuera_pdf_cargas WHERE id = {segunda['carga_id']}",
        )
        assert anterior == [(True,)]

    def test_an_upload_from_before_the_migration_comes_with_nulls(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO ventas_fuera_pdf_cargas (empresa, vendedor, desde, hasta, archivo_detallado,
                        archivo_resumen, documentos, reemplazados, avisos, usuario_id)
                    VALUES ('EMPRESA EJEMPLO SA', NULL, '2025-02-01', '2025-02-28', 'd.pdf', 'r.pdf', 3, 0, '[]', NULL)
                """)
            )

        (fila,) = _historial(engine)

        nulos = (
            "vendedores",
            "lineas",
            "unidades",
            "total_lineas",
            "sin_producto_lineas",
            "sin_producto_monto",
            "recargo_financiero",
            "control_detalle",
            "usuario",
            "documentos_por_tipo",
            "carga_anterior_at",
        )
        assert {k: fila[k] for k in nulos} == dict.fromkeys(nulos)
        assert (fila["estado"], fila["control"], fila["vendedor"]) == ("reemplazada", "ok", None)

    def test_filters_and_pages(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _client(engine, {SUBIR})
        _subir(client, resumen=None)
        _como(monkeypatch, detallada=_de(_dos, _rango(1, 15, vendedor=None)))
        _subir(client, resumen=None, vendedores=[OTRO])
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO ventas_fuera_pdf_cargas (empresa, desde, hasta, documentos, reemplazados, avisos,
                        created_at)
                    VALUES ('OTRA EMPRESA SRL', '2024-01-01', '2024-01-31', 0, 0, '[]', now() - interval '200 days')
                """)
            )

        assert len(_historial(engine)) == 2
        assert len(_historial(engine, dias=365)) == 3
        assert [f["empresa"] for f in _historial(engine, dias=365, empresa="OTRA EMPRESA SRL")] == ["OTRA EMPRESA SRL"]
        assert [f["vendedores"] for f in _historial(engine, vendedor=OTRO)] == [[OTRO]]
        assert [f["vendedor"] for f in _historial(engine, vendedor=CARLA)] == [CARLA]
        assert [f["vendedores"] for f in _historial(engine, page_size=1, page=2)] == [[CARLA]]

    def test_salesperson_filter_finds_the_uploads_stored_with_the_printed_name(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A subset of a "Todos" PDF stores the salesperson as documents print it (cut to 12 characters); the
        history filtered by the full name still lists that upload, and the printed name finds the full-name one."""
        client = _client(engine, {SUBIR})
        _subir(client, resumen=None)
        _como(monkeypatch, detallada=_de(_dos, _rango(1, 15, vendedor=None)))
        _subir(client, resumen=None, vendedores=[CARLA_IMPRESO])

        assert CARLA_IMPRESO != CARLA
        por_nombre = [(f["vendedor"], f["vendedores"]) for f in _historial(engine, vendedor=CARLA)]
        assert sorted(por_nombre, key=str) == sorted([(None, [CARLA_IMPRESO]), (CARLA, [CARLA])], key=str)
        assert len(_historial(engine, vendedor=CARLA_IMPRESO)) == 2
        assert _historial(engine, vendedor=CARLA[:5]) == []

    @pytest.mark.parametrize(("permisos", "status"), [(set(), 403), ({VER}, 200), ({SUBIR}, 200)])
    def test_needs_either_permission(self, engine: Engine, permisos: set, status: int) -> None:
        assert _client(engine, permisos).get(URL).status_code == status


def test_the_new_routes_are_registered_in_the_app() -> None:
    from app.main import app

    paths = app.openapi()["paths"]

    assert set(paths["/api/ventas-fuera-pdf/cargas"]) >= {"get", "post"}
    assert "post" in paths["/api/ventas-fuera-pdf/cargas/preview"]
