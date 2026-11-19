"""A small invented world for the vpf-operaciones tests: detailed reports built in code (no PDF), the tables the load
and the operations list read, and products of productos_erp / tb_item. Every name, code and amount is INVENTED (the
repository is public)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.models.cur_exch_history import CurExchHistory
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.tb_item import TBItem
from app.models.tipo_cambio import TipoCambio
from app.models.vendedor_excluido import VendedorExcluido
from app.models.venta_fuera_pdf import (
    VentaFueraCodigoMapeo,
    VentaFueraLineaOverride,
    VentaFueraOperacion,
    VentaFueraOperacionLinea,
    VentaFueraPdfAlcance,
    VentaFueraPdfCarga,
    VentaFueraPdfResumenDocumento,
)
from app.services.ventas_fuera_pdf.parser import DocumentoDetallado, LineaDetallada, ReporteDetallado

EMPRESA = "EMPRESA EJEMPLO SA"
VENDEDOR = "Vendedor Uno"
DESDE, HASTA = date(2026, 10, 1), date(2026, 10, 31)

# Every table the load, the overrides and the operations list read.
TABLAS = [
    VentaFueraPdfCarga.__table__,
    VentaFueraOperacion.__table__,
    VentaFueraOperacionLinea.__table__,
    VentaFueraPdfAlcance.__table__,
    VentaFueraPdfResumenDocumento.__table__,
    VentaFueraLineaOverride.__table__,
    VentaFueraCodigoMapeo.__table__,
    ProductoERP.__table__,
    TBItem.__table__,
    MarcaPM.__table__,
    VendedorExcluido.__table__,
    # The ERP cost list and the USD rates the load costs each line with (vpf-costo-d-erp).
    ItemCostListHistory.__table__,
    TipoCambio.__table__,
    CurExchHistory.__table__,
]
STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre VARCHAR(255) NOT NULL)",
    "INSERT INTO usuarios VALUES (7, 'Usuaria Ejemplo')",
]
TRUNCATE = (
    "TRUNCATE ventas_fuera_pdf_resumen_documentos, ventas_fuera_pdf_alcances, ventas_fuera_operacion_lineas, "
    "ventas_fuera_operaciones, ventas_fuera_pdf_cargas, ventas_fuera_linea_overrides, ventas_fuera_codigo_mapeos, "
    "productos_erp, tb_item, marcas_pm, vendedores_excluidos, tb_item_cost_list_history, tipo_cambio, "
    "tb_cur_exch_history"
)


def linea(
    codigo: Optional[str],
    articulo: str,
    cantidad: str = "1",
    precio: str = "1000",
    costo: str = "800",
    moneda: str = "ARS",
) -> LineaDetallada:
    return LineaDetallada(
        codigo=codigo,
        articulo=articulo,
        cantidad=Decimal(cantidad),
        moneda=moneda,
        precio=Decimal(precio),
        precio_costo=Decimal(costo),
        precio_costo_pp=Decimal(costo),
    )


def doc(
    numero: int,
    lineas: Sequence[LineaDetallada],
    *,
    tipo: str = "Fc",
    fecha: date = date(2026, 10, 5),
    vendedor: str = VENDEDOR,
    cliente: str = "CLIENTE EJEMPLO",
) -> DocumentoDetallado:
    total = sum((ln.precio for ln in lineas), Decimal("0"))
    return DocumentoDetallado(
        cliente=cliente,
        tipo=tipo,
        letra="A",
        punto_venta=9,
        numero=numero,
        fecha=fecha,
        fecha_vencimiento=None,
        vendedor=vendedor,
        importe=(total * Decimal("1.21")).quantize(Decimal("0.01")),
        saldo=Decimal("0"),
        lineas=list(lineas),
    )


def reporte(*documentos: DocumentoDetallado) -> ReporteDetallado:
    return ReporteDetallado(
        empresa=EMPRESA, vendedor=None, desde=DESDE, hasta=HASTA, documentos=list(documentos), total_impreso=None
    )


def producto(conn: Connection, item_id: int, codigo: str, descripcion: str = "Producto Ejemplo") -> None:
    conn.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, iva) "
            "VALUES (:i, :c, :d, 'MarcaEjemplo', 'CategoriaEjemplo', 21)"
        ),
        {"i": item_id, "c": codigo, "d": descripcion},
    )


def item(conn: Connection, item_id: int, item_code: str, comp_id: int = 1, descripcion: str = "Item Ejemplo") -> None:
    conn.execute(
        text("INSERT INTO tb_item (comp_id, item_id, item_code, item_desc) VALUES (:co, :i, :c, :d)"),
        {"co": comp_id, "i": item_id, "c": item_code, "d": descripcion},
    )


def costo_erp(
    conn: Connection,
    item_id: int,
    precio: str,
    creado: datetime,
    *,
    curr_id: Optional[int] = 2,
    coslis_id: int = 1,
    iclh_id: Optional[int] = None,
) -> None:
    """A row of the ERP cost list history (curr_id 1 pesos, 2 dollars)."""
    conn.execute(
        text(
            "INSERT INTO tb_item_cost_list_history (iclh_id, comp_id, coslis_id, item_id, iclh_price, curr_id, iclh_cd) "
            "VALUES (COALESCE(:id, (SELECT COALESCE(max(iclh_id), 0) + 1 FROM tb_item_cost_list_history)), 1, :cl, "
            ":i, :p, :cu, :cd)"
        ),
        {"id": iclh_id, "cl": coslis_id, "i": item_id, "p": Decimal(precio), "cu": curr_id, "cd": creado},
    )


def cambio(conn: Connection, fecha: date, venta: float) -> None:
    """The app's USD rate (`tipo_cambio`) of a day."""
    conn.execute(
        text("INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (:f, 'USD', :v, :v)"),
        {"f": fecha, "v": venta},
    )


def lineas(engine: Engine) -> dict:
    """`{(numero, renglon): row}` of every stored line."""
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                "SELECT o.numero, l.renglon, l.id, l.codigo, l.articulo, l.cantidad, l.precio, l.precio_costo, "
                "l.precio_costo_pdf, l.item_id, l.item_origen, l.override_estado "
                "FROM ventas_fuera_operacion_lineas l JOIN ventas_fuera_operaciones o ON o.id = l.operacion_id"
            )
        ).mappings()
        return {(f["numero"], f["renglon"]): dict(f) for f in filas}
