"""Ventas por fuera from the GBP PDF reports as sales for offsets de ganancia and sell in / sell out (T4).

Owner (S18): "sell in / sell out van a aplicar sobre las operaciones que vayamos creando ahí, no se usa nada viejo".
So these engines read ventas por fuera ONLY from the PDF operations (`ventas_fuera_operacion_lineas` of
`ventas_fuera_operaciones`), never from the GBP sync (`ventas_fuera_ml_metricas`).

`VentasPdf` exposes each line with the columns the engines read from a synced sale table, so
`sell_in.costing.VENTAS_FACTURADAS` treats it like one under the channel `fuera` (`venta_ref` = the line id; the
consumptions the GBP sync produced under `fuera` were purged by `20261119_vpf_offsets_sell_pdf`):

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

from sqlalchemy import DateTime, case, literal
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement, select
from sqlalchemy.sql.functions import FunctionElement

from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea

CANAL = "fuera"
# Costo D: 'Precio Costo' x 1.065 (owner, L14: "Costo D (Precio Costo × 1,065)"). The ONE backend constant
# (board, list, manual costs, offsets); owner L3: management may switch it to VARIOS later, a one-line change here
# and in the frontend's `utils/ventasFueraOperaciones.js`.
COSTO_D_FACTOR = Decimal("1.065")

_linea = VentaFueraOperacionLinea.__table__
_operacion = VentaFueraOperacion.__table__


class _MedianocheUtc(FunctionElement):
    """A DATE as a timestamp at midnight UTC: `timezone('UTC', d::timestamp)` on Postgres (a timestamptz whatever the
    session's time zone), `datetime(d)` elsewhere (SQLite tests; a CAST there would give the NUMERIC year)."""

    type = DateTime(timezone=True)
    inherit_cache = True
    name = "medianoche_utc"


@compiles(_MedianocheUtc)
def _medianoche_utc(element: _MedianocheUtc, compiler, **kw) -> str:
    return f"datetime({compiler.process(element.clauses, **kw)})"


@compiles(_MedianocheUtc, "postgresql")
def _medianoche_utc_pg(element: _MedianocheUtc, compiler, **kw) -> str:
    return f"timezone('UTC', CAST({compiler.process(element.clauses, **kw)} AS TIMESTAMP WITHOUT TIME ZONE))"


def medianoche_utc(fecha) -> ColumnElement:
    return _MedianocheUtc(fecha)


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
        medianoche_utc(_operacion.c.fecha).label("fecha_venta"),
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


# Offsets de ganancia (T4, S15) read the same lines as a `ventas_fuera_ml_metricas`-shaped row source, in raw SQL like
# the rest of their queries: Costo D as `costo_total`, the USD rate of the sale date (`tipo_cambio`, the latest on or
# before it; NULL falls back to the current rate), brand and category from the product. An Nc line keeps its negative
# quantity and cost, so per-unit and percentage amounts subtract by themselves; `monto_offset_pdf` also reverses a fixed
# amount (owner, L18: "Restan").
TIPO_VENTA_OFFSET = "fuera_pdf"
VENTAS_FUERA_OFFSETS_SQL = f"""(
    SELECT
        l.id,
        o.fecha AS fecha_venta,
        l.item_id,
        p.marca,
        p.categoria,
        l.cantidad,
        o.tipo AS tipo_documento,
        l.precio_costo * {COSTO_D_FACTOR} AS costo_total,
        (
            SELECT tc.venta FROM tipo_cambio tc
            WHERE tc.moneda = 'USD' AND tc.fecha <= o.fecha
            ORDER BY tc.fecha DESC LIMIT 1
        ) AS cotizacion_dolar
    FROM ventas_fuera_operacion_lineas l
    JOIN ventas_fuera_operaciones o ON o.id = l.operacion_id
    JOIN productos_erp p ON p.item_id = l.item_id
)"""


def monto_offset_pdf(tipo_offset: str, tipo_documento: str, montos: tuple) -> tuple:
    """The (ARS, USD) amounts of an offset on a PDF line: a fixed amount is reversed by a line of a credit note (Nc),
    whatever its quantity (a price-only Nc line has none); the other types already carry the line's sign."""
    if tipo_offset == "monto_fijo" and tipo_documento == "Nc":
        return -montos[0], -montos[1]
    return montos
