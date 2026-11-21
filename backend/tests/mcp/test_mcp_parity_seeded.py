"""S12 (L6, FULL parity) for the tools whose endpoint declares no object response model, so the schema-based field
check in test_mcp_parity.py cannot see their fields, plus `ventas_ml` (merged with its KPIs, also outside it).

Each case seeds data, calls the endpoint as the app does and the tool through /api/mcp (real in-process call, same
params), and asserts the tool returns every key of the endpoint's answer at every depth, list items included, and
the same values. Invented data.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.commercial_transaction import CommercialTransaction
from app.models.item_transaction import ItemTransaction
from app.models.marca_pm import MarcaPM
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.precio_ml import PrecioML
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tb_supplier import TBSupplier
from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea, VentaFueraPdfCarga
from app.mcp import tools
from app.routers import ml_ventas_ops
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from tests.conftest import make_access_token
from tests.integration.test_ml_ventas_ops_sales_router import _grant_ml_ops_ver, _seed_order
from tests.mcp.conftest import call_tool, connect, tool_text
from tests.costo_si_lista import costo_si_lista  # noqa: F401 (the costo SI reader's SQLite stand-in)

pytestmark = pytest.mark.usefixtures("costo_si_lista")

SEP_1 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def deep_keys(value: Any, prefix: str = "$") -> set[str]:
    """Every key path of a JSON value; list items share the path `[]`, so every item's keys count."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            keys.add(path)
            keys |= deep_keys(child, path)
    elif isinstance(value, list):
        for child in value:
            keys |= deep_keys(child, f"{prefix}[]")
    return keys


def _assert_same(endpoint: Any, tool: Any) -> None:
    missing = sorted(deep_keys(endpoint) - deep_keys(tool))
    assert missing == [], f"the tool drops fields the endpoint returns: {missing}"
    assert deep_keys(tool) == deep_keys(endpoint)
    assert tool == endpoint


def _both(mcp_client, user, tool_name: str, path: str, params: dict, path_args: dict | None = None) -> tuple[Any, Any]:
    app_headers = {"Authorization": f"Bearer {make_access_token(user)}"}
    response = mcp_client.get(path, params=params, headers=app_headers)
    assert response.status_code == 200, response.text
    conn = connect(mcp_client, user)
    result = call_tool(mcp_client, conn.headers, tool_name, {**params, **(path_args or {})})
    assert result["isError"] is False, tool_text(result)
    return response.json(), json.loads(tool_text(result))


def test_the_five_untyped_endpoints_are_the_ones_covered_here():
    """If an endpoint gains an object model it moves to the schema check; a new untyped one must be added here."""
    from tests.mcp.test_mcp_parity import _response_fields

    untyped = sorted(s.name for s in tools.all_specs() if not s.companions and not _response_fields(s.path))
    assert untyped == sorted(UNTYPED)


UNTYPED = ("producto_detalle", "productos_precios_listas", "ventas_por_fuera", "ventas_fuera_cargas", "pms")


# ---------------------------------------------------------------- productos


@pytest.fixture()
def productos(db, mcp_user):
    for item_id, codigo in ((9101, "PAR-001"), (9102, "PAR-002")):
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=codigo,
                descripcion=f"Producto {codigo}",
                marca="Acme",
                categoria="Audio",
                subcategoria_id=7,
                stock=4,
                costo=1000,
                moneda_costo="ARS",
                iva=21.0,
                activo=True,
            )
        )
        db.add(
            ProductoPricing(
                item_id=item_id,
                precio_lista_ml=2500,
                markup_calculado=30,
                participa_rebate=True,
                porcentaje_rebate=4,
                participa_web_transferencia=True,
                porcentaje_markup_web=10,
                precio_web_transferencia=2200,
                markup_web_real=12,
                precio_3_cuotas=2700,
                usuario_id=mcp_user.id,
                fecha_modificacion=datetime(2026, 10, 1, 12, 0),
            )
        )
        db.add(PrecioML(item_id=item_id, pricelist_id=4, precio=2500, mla=f"MLA{item_id}", cotizacion_dolar=1000))
    db.add(TBSupplier(comp_id=1, supp_id=55, supp_name="Proveedor SA"))
    db.add(CommercialTransaction(comp_id=1, ct_transaction=7001, supp_id=55))
    db.add(
        ItemTransaction(
            comp_id=1,
            ct_transaction=7001,
            it_transaction=8001,
            item_id=9101,
            puco_id=10,
            it_cd=datetime(2026, 9, 15, 10, 0),
            it_qty=3,
            it_price=800,
            curr_id=1,
        )
    )
    db.commit()


@contextmanager
def _pricing_stubs():
    with (
        patch("app.api.endpoints.productos_detail.resolver_costo_envio", return_value=150.0),
        patch("app.services.pricing_calculator.obtener_tipo_cambio_actual", return_value=1000.0),
        patch("app.services.pricing_calculator.obtener_grupo_subcategoria", return_value=3),
        patch("app.services.pricing_calculator.obtener_comision_base", return_value=15.5),
    ):
        yield


@pytest.fixture()
def ve_todo_productos(mcp_user, rol_admin, grant_permiso):
    for codigo in ("productos.ver_info_basica", "productos.ver_info_pricing", "productos.ver_info_compras"):
        grant_permiso(rol_admin, codigo)
    grant_permiso(rol_admin, "productos.ver_costos")
    return mcp_user


def test_producto_detalle_returns_everything_the_endpoint_does(mcp_client, ve_todo_productos, productos):
    with _pricing_stubs():
        endpoint, tool = _both(
            mcp_client, ve_todo_productos, "producto_detalle", "/api/productos/9101/detalle", {}, {"item_id": 9101}
        )
    assert endpoint["ultimas_compras"], "seed must reach the purchases list"
    _assert_same(endpoint, tool)


def test_productos_precios_listas_returns_everything_the_endpoint_does(mcp_client, ve_todo_productos, productos):
    params = {"page": 1, "page_size": 20}
    endpoint, tool = _both(
        mcp_client, ve_todo_productos, "productos_precios_listas", "/api/productos/precios-listas", params
    )
    assert len(endpoint["productos"]) == 2
    _assert_same(endpoint, tool)


def test_without_ver_costos_only_cost_fields_are_missing(mcp_client, mcp_user, rol_admin, grant_permiso, productos):
    """L3 Q4: the one deliberate difference, and nothing else goes with it."""
    for codigo in ("productos.ver_info_basica", "productos.ver_info_pricing", "productos.ver_info_compras"):
        grant_permiso(rol_admin, codigo)
    with _pricing_stubs():
        endpoint, tool = _both(
            mcp_client, mcp_user, "producto_detalle", "/api/productos/9101/detalle", {}, {"item_id": 9101}
        )
    dropped = deep_keys(endpoint) - deep_keys(tool)
    assert dropped, "cost fields are present in the endpoint answer"
    # a cost key goes whole: its children (e.g. `costo_si.moneda`) go with it, and nothing outside a cost key
    assert all(any(tools._COST_KEY.search(key) for key in path.split(".")[1:]) for path in dropped), sorted(dropped)


# ---------------------------------------------------------------- ventas por fuera


@pytest.fixture()
def ventas_fuera(db, mcp_user, rol_admin, grant_permiso):
    grant_permiso(rol_admin, "ventas_fuera.ver_metricas_pdf")
    grant_permiso(rol_admin, "ventas_fuera.subir_pdf")
    db.add(ProductoERP(item_id=9201, codigo="VF-1", descripcion="Parlante", marca="Acme", categoria="Audio"))
    db.add(MarcaPM(marca="Acme", categoria="Audio", usuario_id=mcp_user.id))
    carga = VentaFueraPdfCarga(
        empresa="EMPRESA DEMO SRL",
        vendedor="VENDEDOR UNO",
        desde=date(2026, 10, 1),
        hasta=date(2026, 10, 31),
        archivo_detallado="detallada.pdf",
        documentos=1,
        reemplazados=0,
        avisos=["aviso de prueba"],
        usuario_id=mcp_user.id,
        vendedores=["VENDEDOR UNO"],
        lineas=1,
        unidades=Decimal("2"),
        total_lineas=Decimal("2000"),
        sin_producto_lineas=0,
        sin_producto_monto=Decimal("0"),
        recargo_financiero=Decimal("0"),
        documentos_por_tipo=[{"tipo": "FC", "letra": "A", "cantidad": 1}],
        control={
            "resumen": True,
            "documentos_coinciden": True,
            "total_resumen": 2000.0,
            "total_lineas": 2000.0,
            "diferencia": 0.0,
            "cheques": [
                {"tipo": "FC", "letra": "A", "punto_venta": 1, "numero": 100, "cliente": "Cliente Demo", "recargo": 0.0}
            ],
        },
        control_estado="ok",
    )
    db.add(carga)
    db.flush()
    operacion = VentaFueraOperacion(
        carga_id=carga.id,
        empresa="EMPRESA DEMO SRL",
        vendedor="VENDEDOR UNO",
        cliente="Cliente Demo",
        cliente_codigo="C1",
        tipo="FC",
        letra="A",
        punto_venta=1,
        numero=100,
        fecha=date(2026, 10, 15),
        condicion_venta="Contado",
        importe=Decimal("2420"),
        saldo=Decimal("0"),
        total_lineas=Decimal("2000"),
        recargo_financiero=Decimal("0"),
    )
    db.add(operacion)
    db.flush()
    db.add(
        VentaFueraOperacionLinea(
            operacion_id=operacion.id,
            renglon=1,
            codigo="VF-1",
            item_id=9201,
            articulo="Parlante",
            cantidad=Decimal("2"),
            moneda="ARS",
            precio=Decimal("1000"),
            precio_costo=Decimal("600"),
            precio_costo_pp=Decimal("610"),
        )
    )
    db.commit()
    return mcp_user


def test_ventas_por_fuera_returns_everything_the_endpoint_does(mcp_client, ventas_fuera):
    params = {"desde": "2026-10-01", "hasta": "2026-10-31", "empresa": "EMPRESA DEMO SRL", "page": 1, "page_size": 20}
    endpoint, tool = _both(mcp_client, ventas_fuera, "ventas_por_fuera", "/api/ventas-fuera-pdf/operaciones", params)
    assert endpoint and any(isinstance(v, list) and v for op in endpoint for v in op.values()), "seed reaches lines"
    _assert_same(endpoint, tool)


def test_ventas_fuera_cargas_returns_everything_the_endpoint_does(mcp_client, ventas_fuera):
    params = {"dias": 3660, "page": 1, "page_size": 20}
    endpoint, tool = _both(mcp_client, ventas_fuera, "ventas_fuera_cargas", "/api/ventas-fuera-pdf/cargas", params)
    assert len(endpoint) == 1 and endpoint[0]["control_detalle"]["cheques"], "seed reaches the nested lists"
    _assert_same(endpoint, tool)


# ---------------------------------------------------------------- PMs


def test_pms_returns_everything_the_endpoint_does(mcp_client, mcp_user, db):
    db.add(MarcaPM(marca="Acme", categoria="Audio", usuario_id=mcp_user.id))
    db.commit()
    for params in ({}, {"solo_con_marcas": True}):
        endpoint, tool = _both(mcp_client, mcp_user, "pms", "/api/usuarios/pms", params)
        assert endpoint
        _assert_same(endpoint, tool)


# ---------------------------------------------------------------- ventas ML (sales + KPIs companion)


@pytest.fixture()
def ventas_ml(db, mcp_user, rol_admin, monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

    @contextmanager
    def _background():
        session = Session(bind=db.get_bind())
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(ml_ventas_ops, "get_background_db", _background, raising=False)
    _grant_ml_ops_ver(db, rol_admin)
    for order_id in (95001, 95002):
        _seed_order(db, order_id, date_created=SEP_1)
        db.add(
            MlOrderItemOps(
                order_id=order_id, item_id="MLA1", quantity=2, unit_price=2500, listing_type_id="gold_special"
            )
        )
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id="MLA1",
                costo_origen=Decimal("1000.00"),
                moneda="ARS",
                costo_unitario_ars=Decimal("1000.00"),
                iva_pct=Decimal("21.00"),
                precio_unitario=Decimal("2500.00"),
                fuente="sku",
                producto_item_id=2964,
            )
        )
        db.add(
            MlOrderMetrics(
                order_id=order_id,
                neto=Decimal("5000.00"),
                neto_sin_iva=Decimal("4132.23"),
                iva_reconcilia=True,
                costo_mercaderia=Decimal("2000.00"),
                total_gauss=Decimal("2132.23"),
                markup_pct=Decimal("106.61"),
                gauss_status="ok",
                formula_version=CURRENT_FORMULA_VERSION,
                computed_at=SEP_1,
            )
        )
    db.commit()
    return mcp_user


def test_ventas_ml_returns_the_sales_and_kpis_endpoints_whole(mcp_client, ventas_ml):
    params = {"include_unknown": True, "include_in_dispute": True, "limit": 20, "offset": 0}
    app_headers = {"Authorization": f"Bearer {make_access_token(ventas_ml)}"}
    sales = mcp_client.get("/api/ml-ventas-ops/sales", params=params, headers=app_headers)
    kpis_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    kpis = mcp_client.get("/api/ml-ventas-ops/sales/kpis", params=kpis_params, headers=app_headers)
    assert sales.status_code == 200 and kpis.status_code == 200, (sales.text, kpis.text)
    assert sales.json()["sales"], "seed must reach the sales list"

    conn = connect(mcp_client, ventas_ml)
    result = call_tool(mcp_client, conn.headers, "ventas_ml", params)
    assert result["isError"] is False, tool_text(result)
    tool = json.loads(tool_text(result))
    _assert_same({"ventas": sales.json(), "kpis": kpis.json()}, tool)
