"""Parser of GBP's sales PDF reports (Crystal Reports exports) for ventas por fuera.

Two reports are read:

- "Reporte de Ventas Detalladas": one header per document (client, document, dates, salesperson, VAT-inclusive
  Importe, Saldo) followed by its lines (code, article, quantity, currency, line total without VAT, Precio Costo,
  Precio CostoPP). It is the source of the operations.
- "Reporte de Ventas": one row per document with the client code, the condition of sale and the Importe without VAT
  (with the 4% surcharge of "CHEQUE 30 D" documents included) and the Saldo. It is the control.

The PDF draws every report field as its own run of characters, labels in bold and values in the regular font, and
fields can overlap on the page (the due date is drawn over the "Fecha Vencimiento" label). So the text is rebuilt
from the characters themselves: a run is a sequence of adjacent characters with the same baseline and weight, a row is
the runs that share a baseline, and a value belongs to the bold label to its left.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator, Optional

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfexceptions import PDFException
from pdfminer.psparser import PSException

TITULO_DETALLADA = "Reporte de Ventas Detalladas"
TITULO_RESUMEN = "Reporte de Ventas"
VENDEDOR_TODOS = "Todos"

_COMPROBANTE = re.compile(r"\b(Fc|Nc|Nd)\s+([A-Z])\s+(\d{1,5})-(\d{1,8})\b")
_IMPORTE = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")
_FECHA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_MONEDA = re.compile(r"^[A-Z]{3}$")

# A run is broken when the next character does not start where the previous one ended. Kerning makes some glyphs
# overlap their neighbour by a couple of points ("T" + "odos"); a real field gap is wider than a point.
_SOLAPE_MAX = 2.5
_HUECO_MAX = 1.0
# Fields of one printed row sit within a couple of points of each other (a client name is drawn 1pt below its label).
_TOLERANCIA_FILA = 2.0


class ReporteInvalido(ValueError):
    """The bytes are not a PDF, or not the GBP report that was expected."""


@dataclass(frozen=True)
class _Run:
    x0: float
    top: float
    texto: str
    negrita: bool


@dataclass
class LineaDetallada:
    codigo: Optional[str]
    articulo: str
    cantidad: Decimal
    moneda: str
    precio: Decimal
    precio_costo: Decimal
    precio_costo_pp: Decimal


@dataclass
class DocumentoDetallado:
    cliente: str
    tipo: str
    letra: str
    punto_venta: int
    numero: int
    fecha: date
    fecha_vencimiento: Optional[date]
    vendedor: str
    importe: Decimal
    saldo: Decimal
    lineas: list[LineaDetallada] = field(default_factory=list)

    @property
    def clave(self) -> tuple[str, str, int, int]:
        return (self.tipo, self.letra, self.punto_venta, self.numero)

    @property
    def total_lineas(self) -> Decimal:
        return sum((linea.precio for linea in self.lineas), Decimal("0"))


@dataclass
class ReporteDetallado:
    empresa: str
    vendedor: Optional[str]
    desde: date
    hasta: date
    documentos: list[DocumentoDetallado]
    total_impreso: Optional[Decimal]


@dataclass
class DocumentoResumen:
    cliente_codigo: Optional[str]
    cliente: str
    tipo: str
    letra: str
    punto_venta: int
    numero: int
    fecha: date
    fecha_vencimiento: Optional[date]
    vendedor: str
    condicion_venta: str
    importe: Decimal
    saldo: Decimal

    @property
    def clave(self) -> tuple[str, str, int, int]:
        return (self.tipo, self.letra, self.punto_venta, self.numero)


@dataclass
class ReporteResumen:
    empresa: str
    vendedor: Optional[str]
    desde: date
    hasta: date
    con_impuestos: Optional[bool]
    documentos: list[DocumentoResumen]
    total_impreso: Optional[Decimal]
    saldo_impreso: Optional[Decimal]


def _paginas(contenido: bytes) -> Iterator[list[_Run]]:
    """The runs of every page, in drawing order."""
    gestor = PDFResourceManager()
    agregador = PDFPageAggregator(gestor, laparams=None)
    interprete = PDFPageInterpreter(gestor, agregador)
    try:
        for pagina in PDFPage.get_pages(io.BytesIO(contenido)):
            interprete.process_page(pagina)
            layout = agregador.get_result()
            yield _runs(layout.height, [obj for obj in layout if isinstance(obj, LTChar)])
    except (PDFException, PSException, KeyError, IndexError, TypeError, ValueError) as exc:
        # A damaged PDF makes pdfminer fail in many ways; none of them is the expected report.
        raise ReporteInvalido("El archivo no es un PDF válido o está dañado") from exc


def _runs(alto: float, chars: list[LTChar]) -> list[_Run]:
    runs: list[_Run] = []
    texto: list[str] = []
    x0 = x1 = top = 0.0
    negrita = False
    for char in chars:
        char_top = alto - char.y1
        char_negrita = "Bold" in char.fontname
        contiguo = (
            texto
            and abs(char_top - top) < 0.1
            and char_negrita == negrita
            and -_SOLAPE_MAX <= char.x0 - x1 <= _HUECO_MAX
        )
        if not contiguo:
            if texto:
                runs.append(_Run(x0, top, "".join(texto), negrita))
            texto, x0, top, negrita = [], char.x0, char_top, char_negrita
        texto.append(char.get_text())
        x1 = char.x1
    if texto:
        runs.append(_Run(x0, top, "".join(texto), negrita))
    return [_Run(r.x0, r.top, " ".join(r.texto.split()), r.negrita) for r in runs if r.texto.strip()]


def _filas(runs: list[_Run]) -> list[list[_Run]]:
    """Runs grouped by printed row, top to bottom, each row left to right."""
    filas: list[list[_Run]] = []
    for run in sorted(runs, key=lambda r: r.top):
        if filas and run.top - filas[-1][0].top <= _TOLERANCIA_FILA:
            filas[-1].append(run)
        else:
            filas.append([run])
    return [sorted(fila, key=lambda r: r.x0) for fila in filas]


def _etiquetas(fila: list[_Run]) -> dict[str, str]:
    """Bold label -> the regular text printed after it, up to the next label."""
    valores: dict[str, list[str]] = {}
    actual: Optional[str] = None
    for run in fila:
        if run.negrita:
            actual = run.texto
            valores.setdefault(actual, [])
        elif actual is not None:
            valores[actual].append(run.texto)
    return {k: _juntar(v) for k, v in valores.items()}


def _juntar(partes: list[str]) -> str:
    # Kerned glyphs come out as separate runs with no space between them ("T", "odos").
    texto = ""
    for parte in partes:
        texto = f"{texto}{parte}" if texto and len(texto) == 1 else f"{texto} {parte}".strip()
    return texto


def _importe(texto: str) -> Decimal:
    if not _IMPORTE.match(texto):
        raise ReporteInvalido(f"Importe ilegible: {texto!r}")
    try:
        return Decimal(texto.replace(",", ""))
    except InvalidOperation as exc:
        raise ReporteInvalido(f"Importe ilegible: {texto!r}") from exc


def _fecha(texto: str) -> date:
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date()
    except ValueError as exc:
        raise ReporteInvalido(f"Fecha ilegible: {texto!r}") from exc


def _fecha_opcional(texto: Optional[str]) -> Optional[date]:
    return _fecha(texto) if texto and _FECHA.match(texto.strip()) else None


def _comprobante(texto: str) -> tuple[str, str, int, int]:
    m = _COMPROBANTE.search(texto)
    if not m:
        raise ReporteInvalido(f"Comprobante ilegible: {texto!r}")
    return m.group(1), m.group(2), int(m.group(3)), int(m.group(4))


def _vendedor(valor: Optional[str]) -> Optional[str]:
    """The header's salesperson filter; None when the report covers every salesperson."""
    if not valor or valor == VENDEDOR_TODOS:
        return None
    return valor


@dataclass
class _Encabezado:
    empresa: str
    titulo: str
    parametros: dict[str, str]
    filas: list[list[_Run]]


def _leer(contenido: bytes, titulo: str) -> _Encabezado:
    """Every row of the report, plus the company, title and parameters of page 1 (up to the column header)."""
    if not contenido.startswith(b"%PDF"):
        raise ReporteInvalido("El archivo no es un PDF")
    filas: list[list[_Run]] = []
    for runs in _paginas(contenido):
        filas.extend(_filas(runs))
    if len(filas) < 3:
        raise ReporteInvalido("El PDF no tiene el formato de un reporte de GBP")
    empresa, titulo_leido = filas[0][0].texto, filas[1][0].texto
    if titulo_leido != titulo:
        raise ReporteInvalido(f"Se esperaba el '{titulo}' de GBP y llegó '{titulo_leido}'")
    parametros: dict[str, str] = {}
    for fila in filas[2:]:
        if fila[0].negrita and fila[0].texto == "Código":
            break
        parametros.update(_etiquetas(fila))
    return _Encabezado(empresa, titulo_leido, parametros, filas)


def _rango(parametros: dict[str, str], desde: str, hasta: str) -> tuple[date, date]:
    if desde not in parametros or hasta not in parametros:
        raise ReporteInvalido("El PDF no tiene el rango de fechas en el encabezado")
    return _fecha(parametros[desde]), _fecha(parametros[hasta])


def parse_detallada(contenido: bytes) -> ReporteDetallado:
    """Documents and lines of a "Reporte de Ventas Detalladas" PDF. Amounts keep the PDF's sign (Nc negative)."""
    leido = _leer(contenido, TITULO_DETALLADA)
    desde, hasta = _rango(leido.parametros, "Desde Fecha", "Hasta Fecha")
    documentos: list[DocumentoDetallado] = []
    total_impreso: Optional[Decimal] = None
    for fila in leido.filas:
        primero = fila[0]
        if primero.negrita and primero.texto == "Cliente" and len(fila) > 2:
            documentos.append(_documento_detallado(_etiquetas(fila)))
        elif primero.negrita and primero.texto == "Totales":
            numeros = [r.texto for r in fila if _IMPORTE.match(r.texto)]
            total_impreso = _importe(numeros[1]) if len(numeros) > 1 else None
        elif not primero.negrita and documentos:
            linea = _linea(fila)
            if linea is not None:
                documentos[-1].lineas.append(linea)
    if not documentos:
        raise ReporteInvalido("El reporte detallado no tiene comprobantes")
    _sin_repetidos(documentos)
    return ReporteDetallado(
        empresa=leido.empresa,
        vendedor=_vendedor(leido.parametros.get("Vendedor")),
        desde=desde,
        hasta=hasta,
        documentos=documentos,
        total_impreso=total_impreso,
    )


def _documento_detallado(campos: dict[str, str]) -> DocumentoDetallado:
    tipo, letra, punto_venta, numero = _comprobante(campos.get("Comprobante", ""))
    return DocumentoDetallado(
        cliente=campos.get("Cliente", ""),
        tipo=tipo,
        letra=letra,
        punto_venta=punto_venta,
        numero=numero,
        fecha=_fecha(campos.get("Fecha", "")),
        fecha_vencimiento=_fecha_opcional(campos.get("Fecha Vencimiento")),
        vendedor=campos.get("Vendedor", ""),
        importe=_importe(campos.get("Importe", "")),
        saldo=_importe(campos.get("Saldo", "")),
    )


def _linea(fila: list[_Run]) -> Optional[LineaDetallada]:
    """A line row: [code] article quantity currency price cost costPP markup% profit%. None for any other row."""
    i_moneda = next((i for i, r in enumerate(fila) if _MONEDA.match(r.texto)), None)
    if i_moneda is None or i_moneda < 2:
        return None
    numeros = [r.texto for r in fila[i_moneda + 1 :]]
    if len(numeros) < 3 or not all(_IMPORTE.match(n) for n in numeros[:3]):
        return None
    cantidad = fila[i_moneda - 1].texto
    textos = [r.texto for r in fila[: i_moneda - 1]]
    codigo = textos[0] if len(textos) > 1 and textos[0].isdigit() else None
    articulo = " ".join(textos[1:] if codigo else textos)
    return LineaDetallada(
        codigo=codigo,
        articulo=articulo,
        cantidad=_importe(cantidad),
        moneda=fila[i_moneda].texto,
        precio=_importe(numeros[0]),
        precio_costo=_importe(numeros[1]),
        precio_costo_pp=_importe(numeros[2]),
    )


def nombre_comprobante(tipo: str, letra: str, punto_venta: int, numero: int) -> str:
    return f"{tipo} {letra} {punto_venta:05d}-{numero:08d}"


def _sin_repetidos(documentos: list) -> None:
    """A document printed twice in one report (e.g. a page exported twice) cannot be loaded unambiguously."""
    vistos: set[tuple[str, str, int, int]] = set()
    for doc in documentos:
        if doc.clave in vistos:
            raise ReporteInvalido(
                f"El comprobante {nombre_comprobante(*doc.clave)} aparece más de una vez en el PDF: "
                "volvé a exportar el reporte de GBP."
            )
        vistos.add(doc.clave)


def parse_resumen(contenido: bytes) -> ReporteResumen:
    """Documents of a "Reporte de Ventas" PDF: Importe without VAT (cheque surcharge included) and Saldo."""
    leido = _leer(contenido, TITULO_RESUMEN)
    desde, hasta = _rango(leido.parametros, "Desde Fecha de Emisión", "Hasta Fecha de Emisión")
    impuestos = leido.parametros.get("Con Impuestos")
    documentos: list[DocumentoResumen] = []
    total_impreso = saldo_impreso = None
    for fila in leido.filas:
        textos = [r.texto for r in fila]
        if any(r.negrita for r in fila):
            if "Totales" in textos:
                numeros = [t for t in textos if _IMPORTE.match(t)]
                if len(numeros) >= 2:
                    total_impreso, saldo_impreso = _importe(numeros[0]), _importe(numeros[1])
            continue
        i_comp = next((i for i, t in enumerate(textos) if _COMPROBANTE.search(t)), None)
        if i_comp is not None:
            documentos.append(_documento_resumen(textos, i_comp))
        elif documentos and len(fila) == 1:
            # The client name wraps onto the following rows under the NOMBRE column.
            anterior = documentos[-1]
            anterior.cliente = f"{anterior.cliente} {textos[0]}".strip()
    if not documentos:
        raise ReporteInvalido("El reporte de ventas no tiene comprobantes")
    _sin_repetidos(documentos)
    return ReporteResumen(
        empresa=leido.empresa,
        vendedor=_vendedor(leido.parametros.get("Vendedor")),
        desde=desde,
        hasta=hasta,
        con_impuestos=None if impuestos is None else impuestos == "Si",
        documentos=documentos,
        total_impreso=total_impreso,
        saldo_impreso=saldo_impreso,
    )


def _documento_resumen(textos: list[str], i_comp: int) -> DocumentoResumen:
    antes, despues = textos[:i_comp], textos[i_comp + 1 :]
    codigo = antes[0] if antes and antes[0].isdigit() else None
    cliente = " ".join(antes[1:] if codigo else antes)
    tipo, letra, punto_venta, numero = _comprobante(textos[i_comp])
    fechas = [t for t in despues if _FECHA.match(t)]
    numeros = [t for t in despues if _IMPORTE.match(t)]
    resto = [t for t in despues if not _FECHA.match(t) and not _IMPORTE.match(t)]
    if not fechas or len(numeros) < 2 or len(resto) < 2:
        raise ReporteInvalido(f"Fila ilegible en el reporte de ventas: {' '.join(textos)!r}")
    return DocumentoResumen(
        cliente_codigo=codigo,
        cliente=cliente,
        tipo=tipo,
        letra=letra,
        punto_venta=punto_venta,
        numero=numero,
        fecha=_fecha(fechas[0]),
        fecha_vencimiento=_fecha(fechas[1]) if len(fechas) > 1 else None,
        vendedor=resto[0],
        condicion_venta=resto[1],
        importe=_importe(numeros[0]),
        saldo=_importe(numeros[1]),
    )
