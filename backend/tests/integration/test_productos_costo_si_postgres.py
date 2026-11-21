"""The costo SI column next to the list cost (sell-in-costo-si T3 PR 2, inventory §3, §4, §10): `costo_si` on
GET /productos, /productos/{id}, /productos/tienda and /productos/{id}/detalle, the `costo_si` sort key, and the two
vista-actual export columns. Display only: no other number, sort or filter moves.

The reader (`app.services.costo_si.lote`) is Postgres SQL, so these run on a throwaway Postgres schema holding the
app's tables. Invented data only (the repo is public).
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from openpyxl import load_workbook
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

# Register every model (and the ERP stubs only imported inside endpoint bodies) in Base.metadata.
import app.main  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.item_cost_list_history  # noqa: F401
import app.models.precio_gremio_override  # noqa: F401
import app.models.tb_supplier  # noqa: F401
from app.api.deps import get_current_user
from app.core.database import Base, get_async_db, get_db
from app.main import app as fastapi_app
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.equipo import Equipo
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.precio_ml import PrecioML
from app.models.producto import ProductoERP, ProductoPricing
from app.models.rol import Rol
from app.models.tipo_cambio import TipoCambio
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.costo_ppp_service import PPP_KEY_CLASICA, PPP_KEY_PVP_CLASICA, PPP_KEY_REBATE
from tests.conftest import _PRISTINE_PG_COLUMN_TYPES
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

USD, LISTA, NADA = 6301, 6302, 6303
TC = 1000.0
PERMISOS = {"productos.ver", "productos.ver_info_pricing", "productos.exportar_vista_actual"}


def _tables():
    """The app's tables, without the pgvector ones (the test database has no `vector` extension)."""

    def vector(column) -> bool:
        # The SQLite suite may have patched the type already: judge by the real one.
        return isinstance(_PRISTINE_PG_COLUMN_TYPES.get(column, column.type), Vector)

    return [t for t in Base.metadata.sorted_tables if not any(vector(c) for c in t.columns)]


@pytest.fixture(scope="module")
def pg_engine_costo_si() -> Iterator[Engine]:
    with throwaway_schema("productos_costo_si", _tables()) as engine:
        yield engine


def _guard_raw_sql(session: Session) -> None:
    """The Tienda Nube price and ML catalog status lookups read views this schema does not hold: answer them empty
    (they feed fields this test does not read), as the SQLite listing tests do."""
    original = session.execute

    class _Empty:
        def fetchall(self):
            return []

    def execute(statement, *args, **kwargs):
        sql = str(statement)
        if "tienda_nube_productos" in sql or "v_ml_catalog_status_latest" in sql:
            return _Empty()
        return original(statement, *args, **kwargs)

    session.execute = execute


@pytest.fixture()
def pg(pg_engine_costo_si: Engine) -> Iterator[Session]:
    connection = pg_engine_costo_si.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    _guard_raw_sql(session)
    session.add(Equipo(nombre="Global", es_global=True))
    session.flush()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def permisos() -> set:
    return set(PERMISOS)


@pytest.fixture()
def client(pg: Session, permisos: set) -> Iterator[TestClient]:
    rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
    pg.add(rol)
    pg.flush()
    user = Usuario(
        username="costo-si",
        email="costo-si@example.com",
        nombre="Costo SI",
        password_hash="x",
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    pg.add(user)
    pg.flush()
    user._permisos_cache = permisos

    def _db():
        yield pg

    async def _async_db():
        yield pg

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_async_db] = _async_db
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


def _paso(db: Session, item_id: int, fecha: date, promedio: str, moneda: str = "USD") -> None:
    db.execute(
        text(
            "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
            " promedio_usd, moneda) VALUES (:i, 0, 'inicio', :f, 0, 0, 0, 0, :p, :m)"
        ),
        {"i": item_id, "f": fecha, "p": promedio, "m": moneda},
    )


@pytest.fixture()
def mundo(pg: Session) -> None:
    db = pg
    """USD: USD list cost 30, costo SI 25 from 10-01, PPP 25. LISTA: ARS list cost 20000, no costo SI. NADA: no cost (0).
    Every product has a classic ML price. USD rate 1000."""
    db.add(TipoCambio(moneda="USD", fecha=date(2026, 1, 1), compra=TC, venta=TC))
    # A commission for the default group, so the markups have a `limpio`.
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    for item_id, moneda, costo, precio in ((USD, "USD", 30.0, 60000.0), (LISTA, "ARS", 20000.0, 40000.0)):
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"C{item_id}",
                descripcion=f"Producto {item_id}",
                marca="DEMO",
                costo=costo,
                moneda_costo=moneda,
                iva=21.0,
                envio=0.0,
                stock=5,
                activo=True,
            )
        )
        db.add(
            ProductoPricing(
                item_id=item_id,
                precio_lista_ml=precio,
                markup_calculado=10.0,
                # USD also has a rebate, so the rebate markup site records into the costo SI too
                participa_rebate=item_id == USD,
                porcentaje_rebate=5.0 if item_id == USD else None,
            )
        )
    db.add(
        ProductoERP(
            item_id=NADA,
            codigo=f"C{NADA}",
            descripcion="Sin costo",
            marca="DEMO",
            costo=0.0,
            moneda_costo="ARS",
            iva=21.0,
            envio=0.0,
            stock=5,
            activo=True,
        )
    )
    db.flush()
    # A PPP of 25 USD for USD, the same as its costo SI (the PPP needs a sane list price next to it).
    db.add(
        ItemCostListHistory(
            iclh_id=96301,
            coslis_id=1,
            item_id=USD,
            iclh_price=30.0,
            iclh_price_aw=25.0,
            curr_id=2,
            iclh_cd=datetime(2026, 10, 1),
        )
    )
    _paso(db, USD, date(2026, 10, 1), "25.00000")
    # A PVP price for USD, so the listing's second (PVP) markup pass records into the costo SI too.
    db.add(PrecioML(item_id=USD, pricelist_id=12, precio=70000.0))
    db.flush()


def _listado(client: TestClient, **params) -> dict:
    response = client.get("/api/productos", params={"page_size": 50, **params})
    assert response.status_code == 200, response.text
    return {p["item_id"]: p for p in response.json()["productos"]}


def _orden(client: TestClient, path: str, campo: str, direccion: str) -> list[int]:
    response = client.get(path, params={"page_size": 50, "orden_campos": campo, "orden_direcciones": direccion})
    assert response.status_code == 200, response.text
    return [p["item_id"] for p in response.json()["productos"]]


class TestListado:
    def test_each_product_carries_its_costo_si_next_to_the_unchanged_list_cost(self, client, mundo) -> None:
        productos = _listado(client)

        usd = productos[USD]["costo_si"]
        assert {k: usd[k] for k in ("costo", "moneda", "fuente", "desde", "tipo_cambio", "costo_ars")} == {
            "costo": 25.0,
            "moneda": "USD",
            "fuente": "costo_si",
            "desde": "2026-10-01",
            "tipo_cambio": TC,
            "costo_ars": 25000.0,
        }
        lista = productos[LISTA]["costo_si"]
        assert {k: lista[k] for k in ("costo", "moneda", "fuente", "desde", "tipo_cambio", "costo_ars")} == {
            "costo": 20000.0,
            "moneda": "ARS",
            "fuente": "lista",
            "desde": None,
            "tipo_cambio": None,
            "costo_ars": 20000.0,
        }
        assert productos[NADA]["costo_si"] is None
        # Show only: the list cost stays what it was.
        assert (productos[USD]["costo"], productos[USD]["costo_ars"]) == (30.0, None)
        assert productos[LISTA]["costo"] == 20000.0

    def test_its_markups_are_the_ppp_markups_on_the_costo_si_in_pesos(self, client, mundo) -> None:
        # The PPP of USD is 25 USD too: the same `limpio` on the same pesos gives the same markups, key by key.
        usd = _listado(client)[USD]

        assert {PPP_KEY_CLASICA, PPP_KEY_REBATE, PPP_KEY_PVP_CLASICA} <= set(usd["costo_si"]["markups"])
        assert usd["costo_si"]["markups"] == usd["ppp"]["markups"]
        assert _listado(client)[LISTA]["costo_si"]["markups"]  # an ARS list cost has pesos too

    def test_orden_costo_si_sorts_by_the_costo_si_in_pesos_with_unknown_last(self, client, mundo) -> None:
        assert _orden(client, "/api/productos", "costo_si", "asc") == [LISTA, USD, NADA]
        assert _orden(client, "/api/productos", "costo_si", "desc") == [USD, LISTA, NADA]

    def test_orden_costo_keeps_sorting_the_list_cost(self, client, mundo) -> None:
        # The list cost column as stored (30 USD < 20000 ARS), not the costo SI.
        assert _orden(client, "/api/productos", "costo", "asc") == [NADA, USD, LISTA]
        assert _orden(client, "/api/productos", "costo", "desc") == [LISTA, USD, NADA]


class TestProducto:
    def test_the_product_carries_its_costo_si_with_the_listing_markups(self, client, mundo) -> None:
        response = client.get(f"/api/productos/{USD}")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["costo_si"]["costo"] == 25.0 and body["costo_si"]["fuente"] == "costo_si"
        assert body["costo_si"]["costo_ars"] == 25000.0
        assert body["costo_si"]["markups"] and body["costo_si"]["markups"] == body["ppp"]["markups"]
        assert body["costo"] == 30.0

    def test_a_product_without_cost_has_no_costo_si(self, client, mundo) -> None:
        assert client.get(f"/api/productos/{NADA}").json()["costo_si"] is None


class TestTienda:
    def test_each_store_product_carries_its_costo_si(self, client, mundo) -> None:
        response = client.get("/api/productos/tienda", params={"page_size": 50})
        assert response.status_code == 200, response.text
        productos = {p["item_id"]: p for p in response.json()["productos"]}

        assert productos[USD]["costo_si"]["costo_ars"] == 25000.0
        assert productos[USD]["costo_si"]["fuente"] == "costo_si"
        assert PPP_KEY_REBATE in productos[USD]["costo_si"]["markups"]
        assert productos[USD]["costo_si"]["markups"] == productos[USD]["ppp"]["markups"]
        assert productos[LISTA]["costo_si"]["fuente"] == "lista"
        assert productos[NADA]["costo_si"] is None
        assert productos[USD]["costo"] == 30.0

    def test_orden_costo_si_sorts_the_store_by_the_costo_si(self, client, mundo) -> None:
        assert _orden(client, "/api/productos/tienda", "costo_si", "asc") == [LISTA, USD, NADA]
        assert _orden(client, "/api/productos/tienda", "costo_si", "desc") == [USD, LISTA, NADA]

    def test_orden_costo_keeps_sorting_the_store_by_the_list_cost(self, client, mundo) -> None:
        assert _orden(client, "/api/productos/tienda", "costo", "asc") == [NADA, USD, LISTA]


class TestDetalle:
    def test_with_ver_info_pricing_the_detail_carries_the_costo_si(self, client, mundo) -> None:
        producto = client.get(f"/api/productos/{USD}/detalle").json()["producto"]

        assert producto["costo"] == 30.0
        assert producto["costo_si"]["costo"] == 25.0
        assert producto["costo_si"]["moneda"] == "USD"
        assert producto["costo_si"]["fuente"] == "costo_si"
        assert producto["costo_si"]["costo_ars"] == 25000.0

    @pytest.mark.parametrize("permisos", [{"productos.ver", "productos.ver_info_basica"}])
    def test_without_ver_info_pricing_the_costo_si_is_hidden_like_the_cost(self, client, mundo) -> None:
        producto = client.get(f"/api/productos/{USD}/detalle").json()["producto"]

        assert producto["costo"] is None
        assert producto["costo_si"] is None


class TestExportVistaActual:
    def _hoja(self, client: TestClient):
        response = client.get("/api/exportar-vista-actual", params={"page_size": 50})
        assert response.status_code == 200, response.text
        ws = load_workbook(BytesIO(response.content)).active
        headers = [c.value for c in ws[1]]
        return headers, {row[0]: dict(zip(headers, row)) for row in ws.iter_rows(min_row=2, values_only=True)}

    def test_two_columns_after_the_cost_carry_the_costo_si_and_its_source(self, client, mundo) -> None:
        headers, filas = self._hoja(client)

        assert headers[headers.index("Costo") + 1 : headers.index("Costo") + 3] == ["Costo SI", "Fuente costo SI"]
        assert (filas[f"C{USD}"]["Costo SI"], filas[f"C{USD}"]["Fuente costo SI"]) == (25.0, "costo SI")
        assert (filas[f"C{LISTA}"]["Costo SI"], filas[f"C{LISTA}"]["Fuente costo SI"]) == (20000.0, "lista")
        assert filas[f"C{NADA}"]["Costo SI"] is None
        assert filas[f"C{NADA}"]["Fuente costo SI"] in (None, "")
        # The other columns keep their values under their headers.
        assert filas[f"C{USD}"]["Costo"] == 30.0
        assert filas[f"C{USD}"]["Precio Clásica"] == 60000.0
        assert headers[-1] == "Color"
