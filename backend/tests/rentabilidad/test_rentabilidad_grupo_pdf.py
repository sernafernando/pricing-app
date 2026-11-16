"""`GET /api/rentabilidad`: a group offset computed in real time (no summary yet) counts ventas por fuera from the PDF
reports (VPF T4, S15/S18), an Nc line subtracting its units (owner, L18: "Restan"), and never the GBP sync rows.

Invented data only (the repo is public).
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea, VentaFueraPdfCarga

MARCA = "MarcaGrupoPdf"
ITEM = 7301
PARAMS = {"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"}


def _venta_ml(db) -> None:
    db.add(
        MLVentaMetrica(
            id_operacion=930_001,
            mla_id="930001",
            item_id=ITEM,
            codigo="C7301",
            descripcion="Producto demo",
            marca=MARCA,
            categoria="CategoriaDemo",
            fecha_venta=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            cantidad=1,
            monto_unitario=1000.0,
            monto_total=1000.0,
            costo_unitario_sin_iva=600.0,
            costo_total_sin_iva=600.0,
            comision_ml=100.0,
            costo_envio_ml=0.0,
            ganancia=300.0,
            markup_porcentaje=50.0,
        )
    )


def _linea_pdf(db, carga: VentaFueraPdfCarga, numero: int, cantidad: int) -> None:
    """A Fc line, or an Nc one with a negative quantity and amounts (GBP's sign)."""
    signo = 1 if cantidad > 0 else -1
    operacion = VentaFueraOperacion(
        carga_id=carga.id,
        empresa="EMPRESA DEMO SRL",
        vendedor="Vendedor Demo",
        cliente="Cliente Demo",
        tipo="Fc" if signo == 1 else "Nc",
        letra="A",
        punto_venta=9,
        numero=numero,
        fecha=date(2026, 6, 10 + numero),
        importe=Decimal(500 * cantidad),
        saldo=0,
        total_lineas=Decimal(500 * cantidad),
        recargo_financiero=0,
    )
    db.add(operacion)
    db.flush()
    db.add(
        VentaFueraOperacionLinea(
            operacion_id=operacion.id,
            renglon=1,
            codigo="C7301",
            articulo="Articulo demo",
            cantidad=Decimal(cantidad),
            moneda="ARS",
            precio=Decimal(500 * cantidad),
            precio_costo=Decimal(300 * cantidad),
            precio_costo_pp=Decimal(300 * cantidad),
            item_id=ITEM,
        )
    )


@pytest.fixture()
def mundo(db, offset_grupo_factory, offset_ganancia_factory):
    """One ML sale of 1 unit and a group per-unit offset of 10 on the brand, without summary (real time)."""
    db.add(
        ProductoERP(item_id=ITEM, codigo="C7301", descripcion="Producto demo", marca=MARCA, categoria="CategoriaDemo")
    )
    _venta_ml(db)
    grupo = offset_grupo_factory()
    db.add(OffsetGrupoFiltro(grupo_id=grupo.id, marca=MARCA))
    offset_ganancia_factory(grupo_id=grupo.id, tipo_offset="monto_por_unidad", monto=10.0, fecha_desde=date(2026, 1, 1))
    carga = VentaFueraPdfCarga(
        empresa="EMPRESA DEMO SRL", desde=date(2026, 6, 1), hasta=date(2026, 6, 30), documentos=2, reemplazados=0
    )
    db.add(carga)
    db.flush()
    return carga


def _offset_total(client, headers) -> float:
    resp = client.get("/api/rentabilidad", params=PARAMS, headers=headers)
    assert resp.status_code == 200, resp.text
    [card] = [c for c in resp.json()["cards"] if c["nombre"] == MARCA]
    return card["offset_total"]


def test_pdf_lines_add_their_units_and_an_nc_subtracts(client, db, admin_auth_headers, mundo) -> None:
    _linea_pdf(db, mundo, 1, 3)
    _linea_pdf(db, mundo, 2, -1)
    db.commit()

    assert _offset_total(client, admin_auth_headers) == pytest.approx((1 + 3 - 1) * 10.0)


def test_a_gbp_synced_sale_adds_nothing(client, db, admin_auth_headers, mundo) -> None:
    db.add(
        VentaFueraMLMetrica(
            it_transaction=930_101,
            ct_transaction=930_102,
            item_id=ITEM,
            codigo="C7301",
            marca=MARCA,
            categoria="CategoriaDemo",
            fecha_venta=datetime(2026, 6, 15, tzinfo=timezone.utc),
            cantidad=5,
            monto_total=1000.0,
            costo_total=600.0,
        )
    )
    db.commit()

    assert _offset_total(client, admin_auth_headers) == pytest.approx(1 * 10.0)
