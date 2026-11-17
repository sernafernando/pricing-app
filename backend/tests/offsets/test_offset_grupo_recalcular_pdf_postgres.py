"""`POST /api/offset-grupos/{id}/recalcular` (and `app.scripts.recalcular_consumo_grupos`, run after deploy) reads ventas por fuera from the PDF reports (VPF T4, S15/S18/L14/L18).

Owner (S18): "sell in / sell out van a aplicar sobre las operaciones que vayamos creando ahí, no se usa nada viejo";
offsets de ganancia read the PDF lines too, never the GBP sync (`ventas_fuera_ml_metricas`). A percentage on cost
takes Costo D = 'Precio Costo' x 1.065 (L14); a USD amount converts at the rate of the sale date; an Nc line subtracts
its units and its amount, a fixed amount included (owner, L18: "Restan").

Postgres only (`= ANY(:item_ids)`). Invented data only (the repo is public).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.api.endpoints.offsets_ganancia import _consumo_grupos
from app.core.database import get_db
from app.models.cur_exch_history import CurExchHistory
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.tipo_cambio import TipoCambio
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.scripts import recalcular_consumo_grupos
from tests.services.sell._schema import PDF_TABLES, USUARIOS, throwaway_schema
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

TABLES = [
    ProductoERP.__table__,
    OffsetGrupo.__table__,
    OffsetGrupoFiltro.__table__,
    OffsetGanancia.__table__,
    OffsetGrupoConsumo.__table__,
    OffsetGrupoResumen.__table__,
    TipoCambio.__table__,
    CurExchHistory.__table__,
    MLVentaMetrica.__table__,
    VentaFueraMLMetrica.__table__,
    VentaTiendaNubeMetrica.__table__,  # the script also reads Tienda Nube
    *PDF_TABLES,
]
DIA = date(2026, 10, 15)


def _install(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria) VALUES "
                "(2964, 'C2964', 'Router', 'TP-LINK', 'Routers'), (950, 'C950', 'Router', 'MERCUSYS', 'Routers')"
            )
        )
        # The rate of the sale date and a later (current) one.
        conn.execute(
            text(
                "INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES "
                "('2026-10-01', 'USD', 990, 1000), ('2026-11-01', 'USD', 1190, 1200)"
            )
        )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("offsets_pdf", TABLES, [USUARIOS], after=_install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        for table in (
            "offset_grupo_consumo",
            "offset_grupo_resumen",
            "offsets_ganancia",
            "offset_grupo_filtros",
            "offset_grupos",
            "ventas_fuera_ml_metricas",
            "ventas_fuera_operaciones",  # its lines cascade
            "ventas_fuera_pdf_cargas",
        ):
            conn.execute(text(f"DELETE FROM {table}"))


@pytest.fixture
def client(engine: Engine, monkeypatch) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(_consumo_grupos.router, prefix="/api")
    factory = sessionmaker(bind=engine)

    def db() -> Iterator:
        with factory() as session:
            yield session

    monkeypatch.setattr(_consumo_grupos, "verificar_permiso", lambda db, user, codigo: True)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    with TestClient(app) as c:
        yield c


def _grupo(engine: Engine, *, filtro_marca: str = None, **offset) -> int:
    """A group with one offset (ARS, from October, on ML and fuera) and, optionally, a brand filter."""
    with engine.begin() as conn:
        grupo = conn.execute(
            text("INSERT INTO offset_grupos (nombre, oculto) VALUES ('Grupo demo', false) RETURNING id")
        )
        grupo = grupo.scalar()
        if filtro_marca:
            conn.execute(
                text("INSERT INTO offset_grupo_filtros (grupo_id, marca) VALUES (:g, :m)"),
                {"g": grupo, "m": filtro_marca},
            )
        valores = {
            "grupo_id": grupo,
            "moneda": "ARS",
            "fecha_desde": date(2026, 10, 1),
            "aplica_ml": True,
            "aplica_fuera": True,
            "aplica_tienda_nube": True,
            **offset,
        }
        columnas = ", ".join(valores)
        conn.execute(
            text(f"INSERT INTO offsets_ganancia ({columnas}) VALUES ({', '.join(':' + c for c in valores)})"), valores
        )
    return grupo


def _recalcular(client: TestClient, grupo: int) -> dict:
    response = client.post(f"/api/offset-grupos/{grupo}/recalcular")
    assert response.status_code == 200, response.text
    return response.json()


def _consumos(engine: Engine) -> List[tuple]:
    with engine.connect() as conn:
        return [
            (r[0], r[1], r[2], round(float(r[3]), 2), round(float(r[4]), 4))
            for r in conn.execute(
                text(
                    "SELECT venta_fuera_id, tipo_venta, cantidad, monto_offset_aplicado, monto_offset_usd "
                    "FROM offset_grupo_consumo ORDER BY venta_fuera_id"
                )
            )
        ]


class TestFuente:
    def test_a_pdf_line_consumes_the_offset_of_its_product(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, item_id=2964, tipo_offset="monto_por_unidad", monto=100)
        linea = w.venta(engine, "fuera", 2964, 3, DIA)

        resultado = _recalcular(client, grupo)

        assert _consumos(engine) == [(linea, "fuera_pdf", 3, 300.0, 0.3)]
        assert (resultado["consumos_creados"], resultado["total_unidades"]) == (1, 3)

    def test_a_gbp_synced_sale_consumes_nothing(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, item_id=2964, tipo_offset="monto_por_unidad", monto=100)
        w.venta(engine, "gbp", 2964, 3, DIA)

        _recalcular(client, grupo)

        assert _consumos(engine) == []

    def test_a_group_filter_reaches_the_pdf_lines_of_its_brand(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, filtro_marca="TP-LINK", tipo_offset="monto_por_unidad", monto=100)
        linea = w.venta(engine, "fuera", 2964, 2, DIA)
        w.venta(engine, "fuera", 950, 2, DIA)  # MERCUSYS

        _recalcular(client, grupo)

        assert _consumos(engine) == [(linea, "fuera_pdf", 2, 200.0, 0.2)]


class TestMontos:
    def test_a_percentage_on_cost_takes_costo_d(self, engine: Engine, client: TestClient) -> None:
        """10% of Costo D: 'Precio Costo' 1000.00 for 2 units x 1.065 = 1065.00 -> 106.50."""
        grupo = _grupo(engine, item_id=2964, tipo_offset="porcentaje_costo", porcentaje=10)
        linea = w.venta(engine, "fuera", 2964, 2, DIA, precio_costo=Decimal("1000.00"))

        _recalcular(client, grupo)

        assert _consumos(engine) == [(linea, "fuera_pdf", 2, 106.5, 0.11)]  # USD stored to the cent

    def test_a_usd_amount_converts_at_the_rate_of_the_sale_date(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, item_id=2964, tipo_offset="monto_por_unidad", monto=1, moneda="USD")
        linea = w.venta(engine, "fuera", 2964, 2, DIA)  # 2026-10-15: the 2026-10-01 rate, 1000, not the current 1200

        _recalcular(client, grupo)

        assert _consumos(engine) == [(linea, "fuera_pdf", 2, 2000.0, 2.0)]


class TestNotaDeCredito:
    """L18, owner: "Restan" - an Nc line subtracts its units and its amount from the group."""

    def test_an_nc_line_subtracts_its_units_and_amount(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, item_id=2964, tipo_offset="monto_por_unidad", monto=100)
        venta = w.venta(engine, "fuera", 2964, 3, DIA)
        nc = w.venta(engine, "fuera", 2964, 1, date(2026, 10, 20), signo=-1)

        resultado = _recalcular(client, grupo)

        assert _consumos(engine) == [(venta, "fuera_pdf", 3, 300.0, 0.3), (nc, "fuera_pdf", -1, -100.0, -0.1)]
        assert (resultado["total_unidades"], resultado["total_monto_ars"]) == (2, 200.0)

    def test_an_nc_line_subtracts_a_percentage_on_its_cost(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, item_id=2964, tipo_offset="porcentaje_costo", porcentaje=10)
        w.venta(engine, "fuera", 2964, 2, DIA, precio_costo=Decimal("1000.00"))
        w.venta(engine, "fuera", 2964, 2, date(2026, 10, 20), signo=-1, precio_costo=Decimal("1000.00"))

        resultado = _recalcular(client, grupo)

        assert (resultado["total_unidades"], resultado["total_monto_ars"]) == (0, 0.0)

    def test_an_nc_line_reverses_a_fixed_amount(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, filtro_marca="TP-LINK", tipo_offset="monto_fijo", monto=500)
        venta = w.venta(engine, "fuera", 2964, 1, DIA)
        nc = w.venta(engine, "fuera", 2964, 1, date(2026, 10, 20), signo=-1)

        resultado = _recalcular(client, grupo)

        assert _consumos(engine) == [(venta, "fuera_pdf", 1, 500.0, 0.5), (nc, "fuera_pdf", -1, -500.0, -0.5)]
        assert (resultado["total_unidades"], resultado["total_monto_ars"]) == (0, 0.0)

    def test_a_price_only_nc_line_reverses_a_fixed_amount_too(self, engine: Engine, client: TestClient) -> None:
        """An Nc line with no quantity (a price correction) is still a credit note: the document type decides."""
        grupo = _grupo(engine, item_id=2964, tipo_offset="monto_fijo", monto=500)
        nc = w.venta(engine, "fuera", 2964, 0, DIA, signo=-1)

        _recalcular(client, grupo)

        assert _consumos(engine) == [(nc, "fuera_pdf", 0, -500.0, -0.5)]


class TestPeriodo:
    def test_a_line_dated_on_the_offset_start_counts(self, engine: Engine, client: TestClient) -> None:
        grupo = _grupo(engine, item_id=2964, tipo_offset="monto_por_unidad", monto=100)  # from 2026-10-01
        linea = w.venta(engine, "fuera", 2964, 1, date(2026, 10, 1))
        w.venta(engine, "fuera", 2964, 1, date(2026, 9, 30))  # the day before

        _recalcular(client, grupo)

        assert _consumos(engine) == [(linea, "fuera_pdf", 1, 100.0, 0.1)]


class TestScript:
    """The post-deploy recompute (`recalcular_consumo_grupos.recalcular_grupo`) reads the same lines."""

    def _recalcular(self, engine: Engine, grupo: int) -> dict:
        with sessionmaker(bind=engine)() as db:
            return recalcular_consumo_grupos.recalcular_grupo(db, grupo, cotizacion=1200.0, verbose=False)

    def test_it_reads_the_pdf_lines_and_not_the_gbp_sync(self, engine: Engine) -> None:
        grupo = _grupo(engine, item_id=2964, tipo_offset="monto_por_unidad", monto=100)
        linea = w.venta(engine, "fuera", 2964, 3, DIA)
        w.venta(engine, "gbp", 2964, 5, DIA)

        resultado = self._recalcular(engine, grupo)

        assert _consumos(engine) == [(linea, "fuera_pdf", 3, 300.0, 0.3)]
        assert (resultado["consumos_creados"], resultado["total_unidades"]) == (1, 3)

    def test_an_nc_line_reverses_a_fixed_amount(self, engine: Engine) -> None:
        grupo = _grupo(engine, filtro_marca="TP-LINK", tipo_offset="monto_fijo", monto=500)
        venta = w.venta(engine, "fuera", 2964, 1, DIA)
        nc = w.venta(engine, "fuera", 2964, 1, date(2026, 10, 20), signo=-1)

        resultado = self._recalcular(engine, grupo)

        assert _consumos(engine) == [(venta, "fuera_pdf", 1, 500.0, 0.5), (nc, "fuera_pdf", -1, -500.0, -0.5)]
        assert resultado["total_unidades"] == 0
