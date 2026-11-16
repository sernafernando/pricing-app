"""Ventas por fuera from the GBP PDF reports as sales for offsets de ganancia and sell in / sell out (T4).

Owner (S18): "sell in / sell out van a aplicar sobre las operaciones que vayamos creando ahí, no se usa nada viejo".
So these engines read ventas por fuera ONLY from the PDF operations (`ventas_fuera_operacion_lineas` of
`ventas_fuera_operaciones`), never from the GBP sync (`ventas_fuera_ml_metricas`).

`VentasPdf` exposes each line with the columns the engines read from a synced sale table, so
`sell_in.costing.VENTAS_FACTURADAS` treats it like one under its own channel `pdf` (`venta_ref` = the line id):

- `it_transaction`: the line id. A re-upload replaces the lines of its scope with new ids; the `sell_dirty` row
  triggers queue the old and the new ones, so the allocation follows (`app.services.sell.queue`);
- `item_id`: the product of the line's code, set on load; a line "sin producto" (NULL) is never a sale here;
- `fecha_venta`: the document date at midnight UTC, like the synced tables;
- `signo` 1 and `cantidad` with GBP's sign: a credit note (Nc) line has a negative quantity, so it is a return;
- `cust_id`, the customer a return is matched with (`costing.resolver_objetivos`): the client code when the
  document has one (it comes from the summary report), else the company and the client name as the detailed report
  prints it. Names are cut at about 21 characters, so two clients may share one; codes are exact;
- `monto_total`: the line's price without VAT; `costo_total`: Costo D = 'Precio Costo' x 1.065 (owner, L14).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import DateTime, case, cast, func, literal
from sqlalchemy.sql.expression import select

from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea

CANAL = "pdf"
# Costo D: 'Precio Costo' x 1.065 (owner, L14: "Costo D (Precio Costo × 1,065)").
COSTO_D_FACTOR = Decimal("1.065")

_linea = VentaFueraOperacionLinea.__table__
_operacion = VentaFueraOperacion.__table__


def costo_d(precio_costo):
    """Costo D of a line total (`precio_costo`), as a SQL expression or a Decimal."""
    return precio_costo * COSTO_D_FACTOR


cliente_clave = case(
    (
        _operacion.c.cliente_codigo.isnot(None),
        literal("c:") + _operacion.c.empresa + literal("|") + _operacion.c.cliente_codigo,
    ),
    else_=literal("n:") + _operacion.c.empresa + literal("|") + _operacion.c.cliente,
)

_ventas = (
    select(
        _linea.c.id.label("it_transaction"),
        _linea.c.item_id.label("item_id"),
        func.timezone("UTC", cast(_operacion.c.fecha, DateTime)).label("fecha_venta"),
        literal(1).label("signo"),
        _linea.c.cantidad.label("cantidad"),
        cliente_clave.label("cust_id"),
        _linea.c.precio.label("monto_total"),
        costo_d(_linea.c.precio_costo).label("costo_total"),
    )
    .select_from(_linea.join(_operacion, _operacion.c.id == _linea.c.operacion_id))
    .where(_linea.c.item_id.isnot(None))
    .subquery("ventas_pdf")
)


class VentasPdf:
    """The PDF lines as a sale source, with the column names of `ventas_fuera_ml_metricas` (module docstring)."""

    it_transaction = _ventas.c.it_transaction
    item_id = _ventas.c.item_id
    fecha_venta = _ventas.c.fecha_venta
    signo = _ventas.c.signo
    cantidad = _ventas.c.cantidad
    cust_id = _ventas.c.cust_id
    monto_total = _ventas.c.monto_total
    costo_total = _ventas.c.costo_total
