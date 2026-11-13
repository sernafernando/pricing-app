"""marcas-sin-stock S4/S6: every brand option list applies the shared rule (`app.services.marcas_visibles`).

One test per consumer family: the brand `Agotada` (no product in stock) is absent from the options, the brand
`Epson` (in stock) is present, and -- non-regression -- a brand listed before keeps being listed while it has
stock. `Excepcion` has no stock but sits in the admin list, so it is offered. Where the endpoint receives the
selected brands, a selected hidden brand stays offered (S3). The sales screens' rule (S2b) is covered by the
Métricas and Ventas ML facet tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.commercial_transaction import CommercialTransaction
from app.models.item_transaction import ItemTransaction
from app.models.marca_pm import MarcaPM
from app.models.marca_visible_excepcion import MarcaVisibleExcepcion
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.permiso import Permiso, RolPermisoBase
from app.models.producto import ProductoERP
from app.models.proveedor import Proveedor
from app.models.tb_brand import TBBrand
from app.models.tb_item import TBItem
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica

BRANDS = ("Epson", "Agotada", "Excepcion")
SOLD_AT = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
PERIOD = {"fecha_desde": "2026-11-01", "fecha_hasta": "2026-11-12"}


@pytest.fixture()
def catalog(db) -> None:
    """One product per brand: only Epson has stock; Excepcion is in the admin list."""
    for n, marca in enumerate(BRANDS):
        db.add(
            ProductoERP(
                item_id=100 + n,
                codigo=f"P{n}",
                marca=marca,
                categoria="Impresoras",
                subcategoria_id=10,
                activo=True,
                stock=4 if marca == "Epson" else 0,
            )
        )
    db.add(MarcaVisibleExcepcion(marca="Excepcion"))
    db.flush()


def _shown(options) -> set:
    return {m for m in options if m in BRANDS}


def _grant(db, rol, codigo: str) -> None:
    permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="test", orden=1)
    db.add(permiso)
    db.flush()
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


def test_productos_marcas(client, admin_auth_headers, catalog) -> None:
    """`GET /marcas`: Productos, Tienda, SellIn, Tactical, Aportes Ads and the Publicaciones ML fallback."""
    resp = client.get("/api/marcas", headers=admin_auth_headers)
    assert resp.status_code == 200
    assert _shown(resp.json()["marcas"]) == {"Epson", "Excepcion"}


def test_old_metricas_offers_every_brand_that_sold_in_the_period(db, client, admin_auth_headers, catalog) -> None:
    """`/dashboard-ml/marcas-disponibles` (old Métricas, S2b): its brands ARE the viewed sales, so a brand without
    stock that sold is offered, and one that did not sell (Excepcion's exception aside) is not there at all."""
    for n, marca in enumerate(("Agotada", "Epson")):
        db.add(
            MLVentaMetrica(
                id_operacion=500 + n,
                fecha_venta=SOLD_AT,
                cantidad=1,
                monto_total=Decimal("10"),
                marca=marca,
                is_cancelled=False,
            )
        )
    db.flush()
    resp = client.get("/api/dashboard-ml/marcas-disponibles", headers=admin_auth_headers)
    assert resp.status_code == 200
    assert _shown(resp.json()) == {"Agotada", "Epson"}


def test_rentabilidad_filtros(db, client, admin_auth_headers, catalog) -> None:
    """`/rentabilidad/filtros` (TabRentabilidad): not a sales screen of S2b, so a sold brand without stock hides;
    the selected one stays."""
    for n, marca in enumerate(BRANDS):
        db.add(
            MLVentaMetrica(
                id_operacion=600 + n, fecha_venta=SOLD_AT, cantidad=1, monto_total=Decimal("10"), marca=marca
            )
        )
    db.flush()
    resp = client.get("/api/rentabilidad/filtros", params=PERIOD, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert _shown(resp.json()["marcas"]) == {"Epson", "Excepcion"}
    selected = client.get(
        "/api/rentabilidad/filtros", params={**PERIOD, "marcas": "Agotada"}, headers=admin_auth_headers
    )
    assert _shown(selected.json()["marcas"]) == {"Epson", "Excepcion", "Agotada"}


def test_rentabilidad_fuera_filtros(db, client, admin_auth_headers, catalog) -> None:
    """`/rentabilidad-fuera/filtros` (TabRentabilidadFuera)."""
    for n, marca in enumerate(BRANDS):
        db.add(
            VentaFueraMLMetrica(
                it_transaction=700 + n,
                fecha_venta=SOLD_AT,
                cantidad=Decimal("1"),
                monto_total=Decimal("10"),
                marca=marca,
            )
        )
    db.flush()
    resp = client.get("/api/rentabilidad-fuera/filtros", params=PERIOD, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert _shown(resp.json()["marcas"]) == {"Epson", "Excepcion"}


def test_rentabilidad_tienda_nube_filtros(db, client, admin_auth_headers, catalog) -> None:
    """`/rentabilidad-tienda-nube/filtros` (TabRentabilidadTiendaNube)."""
    for n, marca in enumerate(BRANDS):
        db.add(
            VentaTiendaNubeMetrica(
                it_transaction=800 + n,
                fecha_venta=SOLD_AT,
                cantidad=Decimal("1"),
                monto_total=Decimal("10"),
                marca=marca,
            )
        )
    db.flush()
    resp = client.get("/api/rentabilidad-tienda-nube/filtros", params=PERIOD, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert _shown(resp.json()["marcas"]) == {"Epson", "Excepcion"}


def test_offset_filtros_opciones(client, admin_auth_headers, catalog) -> None:
    """`/offset-filtros-opciones` (ModalOffset): the brand list and the per-category brand lists."""
    resp = client.get("/api/offset-filtros-opciones", headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _shown(body["marcas"]) == {"Epson", "Excepcion"}
    assert _shown(body["marcas_por_categoria"]["Impresoras"]) == {"Epson", "Excepcion"}


def test_marcas_pm(db, client, admin_auth_headers, catalog) -> None:
    """`/marcas-pm` (GestionPM): a brand without stock is not offered for assignment."""
    for marca in BRANDS:
        db.add(MarcaPM(marca=marca, categoria="Impresoras"))
    db.flush()
    resp = client.get("/api/marcas-pm", headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert _shown(r["marca"] for r in resp.json()) == {"Epson", "Excepcion"}


def test_items_sin_mla_marcas(client, admin_auth_headers, catalog) -> None:
    """`/items-sin-mla/marcas` (ItemsSinMLA's brand filter)."""
    resp = client.get("/api/items-sin-mla/marcas", headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert _shown(r["marca"] for r in resp.json()) == {"Epson", "Excepcion"}


def test_proveedor_marcas(db, client, admin_auth_headers, rol_admin, catalog) -> None:
    """`/administracion/proveedores/{id}/marcas` (AdministracionProveedores): the brands bought from a supplier."""
    _grant(db, rol_admin, "administracion.ver_proveedores")
    proveedor = Proveedor(nombre="Prov", supp_id=77, comp_id=1)
    db.add(proveedor)
    for n, marca in enumerate(BRANDS):
        db.add(TBBrand(comp_id=1, brand_id=n + 1, brand_desc=marca))
        db.add(TBItem(comp_id=1, item_id=900 + n, item_code=f"I{n}", brand_id=n + 1))
        db.add(CommercialTransaction(comp_id=1, ct_transaction=9000 + n, ct_date=SOLD_AT.replace(tzinfo=None)))
        db.add(
            ItemTransaction(
                comp_id=1, it_transaction=9100 + n, ct_transaction=9000 + n, item_id=900 + n, supp_id=77, puco_id=10
            )
        )
    db.flush()
    resp = client.get(f"/api/administracion/proveedores/{proveedor.id}/marcas", headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert _shown(r["marca"] for r in resp.json()) == {"Epson", "Excepcion"}


def test_consultas_ranking_facets(db, client, admin_auth_headers, rol_admin, catalog) -> None:
    """`/consultas/ranking/facets` (ConsultasRanking): the selected hidden brand stays offered."""
    _grant(db, rol_admin, "consultas.ver_ranking")
    resp = client.get("/api/consultas/ranking/facets", headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert _shown(resp.json()["marcas"]) == {"Epson", "Excepcion"}
    selected = client.get("/api/consultas/ranking/facets", params={"marca": "Agotada"}, headers=admin_auth_headers)
    assert _shown(selected.json()["marcas"]) == {"Epson", "Excepcion", "Agotada"}
