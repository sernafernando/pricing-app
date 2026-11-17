"""Load of GBP's sales PDFs into the ventas por fuera operations.

Rules (spec vpf-pdf-metricas, T1):

- The detailed report is the source: every document becomes an operation with its lines (S3, S18).
- The summary report is the control: a document missing in either report, or whose summary Importe differs from the
  sum of its lines, is reported as a warning. On "CHEQUE 30 D" documents the difference is the 4% financing surcharge:
  it is not a sale, so it is stored apart in `recargo_financiero` and the sale stays the sum of the lines (S12).
- "El último PDF manda en su vendedor y rango" (S5): everything already loaded for the company, within the PDF's
  date range and for the PDF's salesperson (every salesperson when the PDF says "Todos") is replaced by the PDF, so a
  document voided in GBP disappears and loading the same PDF twice changes nothing. A document of the PDF that was
  loaded before under another scope is replaced too (one document exists once per company).
- Either report may come alone (owner, L8: "habría que marcar que falta subir el resumen o viceversa"). Each scope
  (company + salesperson + exact range) records its last detailed and summary upload. A summary alone is kept as
  control and creates no operations. Coverage is by parts (owner, L11: "No, que cubra por partes"): a scope is
  controlled by the reports of the other kind of any scope of its company whose range and salesperson ("Todos" covers
  everyone) cover it, and it is missing a report only for the salespeople and dates none covers. Every upload runs
  the cross-check again on the company's scopes overlapping its range.
"""

from __future__ import annotations

import dataclasses
import re

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional, Union

from sqlalchemy import String, and_, cast, delete, exists, func, literal, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, selectinload

from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.models.vendedor_excluido import VendedorExcluido
from app.models.venta_fuera_pdf import (
    VentaFueraOperacion,
    VentaFueraOperacionLinea,
    VentaFueraPdfAlcance,
    VentaFueraPdfCarga,
    VentaFueraPdfResumenDocumento,
)
from app.services.ventas_fuera_pdf.parser import (
    DocumentoDetallado,
    DocumentoResumen,
    ReporteDetallado,
    ReporteResumen,
    nombre_comprobante,
)

CONDICION_CHEQUE = "CHEQUE"
# GBP's financing surcharge on "CHEQUE 30 D" documents, and how far (in pesos) a surcharge may be from it.
RECARGO_CHEQUE = Decimal("0.04")
TOLERANCIA_RECARGO = Decimal("0.05")
CERO = Decimal("0")
CENTAVO = Decimal("0.01")


class CargaInvalida(ValueError):
    """The summary report does not belong to the same company, salesperson and range as the detailed one."""


@dataclass
class ResultadoCarga:
    carga_id: int
    alcance_id: int
    empresa: str
    vendedor: Optional[str]
    desde: date
    hasta: date
    documentos: int
    lineas: int
    reemplazados: int
    total_lineas: Decimal
    recargo_financiero: Decimal
    falta_detallada: bool
    falta_resumen: bool
    faltantes: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    # The upload's structured result (vpf-metricas-canal-fe C1), also kept on the upload row for the history (C2).
    created_at: Optional[datetime] = None
    usuario: Optional[str] = None
    vendedores: list[str] = field(default_factory=list)
    unidades: Decimal = Decimal("0")
    documentos_por_tipo: list[dict] = field(default_factory=list)
    sin_producto: dict = field(default_factory=dict)
    reemplazo: dict = field(default_factory=dict)
    control: dict = field(default_factory=dict)


def _validar_par(detallada: ReporteDetallado, resumen: ReporteResumen) -> None:
    propio = (detallada.empresa, detallada.vendedor, detallada.desde, detallada.hasta)
    otro = (resumen.empresa, resumen.vendedor, resumen.desde, resumen.hasta)
    if propio != otro:
        raise CargaInvalida(
            "El reporte de ventas no corresponde al detallado: "
            f"detallado {detallada.empresa} / {detallada.vendedor or 'Todos'} / {detallada.desde:%d/%m/%Y}-"
            f"{detallada.hasta:%d/%m/%Y}, resumen {resumen.empresa} / {resumen.vendedor or 'Todos'} / "
            f"{resumen.desde:%d/%m/%Y}-{resumen.hasta:%d/%m/%Y}"
        )


# GBP prints the salesperson on each document cut to this many characters ("Carla Ejempl").
LARGO_VENDEDOR_IMPRESO = 12


def _es_vendedor(nombre: str):
    """Stored documents of the salesperson `nombre`: the same name, or the name as GBP cuts it on documents (the
    first 12 characters of the header's full name). An empty or shorter stored name is never a match."""
    return or_(
        VentaFueraOperacion.vendedor == nombre,
        and_(
            func.char_length(VentaFueraOperacion.vendedor) >= LARGO_VENDEDOR_IMPRESO,
            func.strpos(literal(nombre, String), VentaFueraOperacion.vendedor) == 1,
        ),
    )


def _alcance(detallada: ReporteDetallado, elegidos: Optional[list[str]] = None):
    """The operations this PDF replaces: its company and range, and its salesperson unless the PDF says "Todos".
    `elegidos` (owner L22: only some salespeople of the PDF imported): only those salespeople's."""
    condiciones = [
        VentaFueraOperacion.empresa == detallada.empresa,
        VentaFueraOperacion.fecha.between(detallada.desde, detallada.hasta),
    ]
    if elegidos is not None:
        condiciones.append(or_(*(_es_vendedor(nombre) for nombre in elegidos)))
    elif detallada.vendedor is not None:
        condiciones.append(_es_vendedor(detallada.vendedor))
    return and_(*condiciones)


FALTA_DETALLADA = "Falta subir el reporte detallado de este período."
FALTA_RESUMEN = "Falta subir el reporte de ventas (resumen) de este período."


def _alcance_de(db: Session, empresa: str, vendedor: Optional[str], desde: date, hasta: date) -> VentaFueraPdfAlcance:
    """The scope row of a company, salesperson filter and exact range, created on first upload."""
    vendedor_igual = (
        VentaFueraPdfAlcance.vendedor.is_(None) if vendedor is None else VentaFueraPdfAlcance.vendedor == vendedor
    )
    alcance = db.execute(
        select(VentaFueraPdfAlcance).where(
            VentaFueraPdfAlcance.empresa == empresa,
            vendedor_igual,
            VentaFueraPdfAlcance.desde == desde,
            VentaFueraPdfAlcance.hasta == hasta,
        )
    ).scalar_one_or_none()
    if alcance is None:
        alcance = VentaFueraPdfAlcance(empresa=empresa, vendedor=vendedor, desde=desde, hasta=hasta, avisos=[])
        db.add(alcance)
        db.flush()
    return alcance


def _guardar_resumen(db: Session, alcance: VentaFueraPdfAlcance, resumen: ReporteResumen, carga_id: int) -> None:
    """The summary replaces the scope's previous one; it is only control, it creates no operations."""
    alcance.documentos_resumen = [
        VentaFueraPdfResumenDocumento(
            cliente_codigo=doc.cliente_codigo,
            cliente=doc.cliente[:255],
            tipo=doc.tipo,
            letra=doc.letra,
            punto_venta=doc.punto_venta,
            numero=doc.numero,
            fecha=doc.fecha,
            fecha_vencimiento=doc.fecha_vencimiento,
            vendedor=doc.vendedor[:100],
            condicion_venta=doc.condicion_venta[:100],
            importe=doc.importe,
            saldo=doc.saldo,
        )
        for doc in resumen.documentos
    ]
    alcance.resumen_carga_id = carga_id
    alcance.resumen_con_impuestos = resumen.con_impuestos


def _crear_operaciones(
    db: Session, detallada: ReporteDetallado, carga_id: int, elegidos: Optional[list[str]] = None
) -> tuple[int, dict[int, int], dict[str, int]]:
    """Replace the operations of the PDF's scope (and any of its documents loaded under another scope) with the
    PDF's documents. Returns how many stored operations were replaced, how many of them each earlier upload
    (`carga_id`) lost, and `{"nuevos", "anulados"}` (C5): the PDF's documents not stored before, and the replaced
    ones the PDF no longer has (GBP voided them)."""
    claves = [doc.clave for doc in detallada.documentos]
    mismo_doc = and_(
        VentaFueraOperacion.empresa == detallada.empresa,
        tuple_(
            VentaFueraOperacion.tipo,
            VentaFueraOperacion.letra,
            VentaFueraOperacion.punto_venta,
            VentaFueraOperacion.numero,
        ).in_(claves),
    )
    reemplazo = or_(_alcance(detallada, elegidos), mismo_doc)
    perdidas = dict(
        db.execute(
            select(VentaFueraOperacion.carga_id, func.count()).where(reemplazo).group_by(VentaFueraOperacion.carga_id)
        ).all()
    )
    previas = {
        tuple(clave)
        for clave in db.execute(
            select(
                VentaFueraOperacion.tipo,
                VentaFueraOperacion.letra,
                VentaFueraOperacion.punto_venta,
                VentaFueraOperacion.numero,
            ).where(reemplazo)
        ).all()
    }
    nuevas = set(claves)
    cambios = {"nuevos": len(nuevas - previas), "anulados": len(previas - nuevas)}
    reemplazados = db.execute(
        delete(VentaFueraOperacion).where(reemplazo), execution_options={"synchronize_session": False}
    ).rowcount
    # The product of each code, for offsets and sell in / sell out (VPF T4); NULL "sin producto".
    productos = productos_por_codigo(db, {ln.codigo for doc in detallada.documentos for ln in doc.lineas if ln.codigo})
    for doc in detallada.documentos:
        db.add(
            VentaFueraOperacion(
                carga_id=carga_id,
                empresa=detallada.empresa,
                vendedor=doc.vendedor,
                cliente=doc.cliente[:255],
                tipo=doc.tipo,
                letra=doc.letra,
                punto_venta=doc.punto_venta,
                numero=doc.numero,
                fecha=doc.fecha,
                fecha_vencimiento=doc.fecha_vencimiento,
                importe=doc.importe,
                saldo=doc.saldo,
                total_lineas=doc.total_lineas,
                recargo_financiero=CERO,
                lineas=[
                    VentaFueraOperacionLinea(
                        renglon=i,
                        codigo=linea.codigo,
                        articulo=linea.articulo[:255],
                        cantidad=linea.cantidad,
                        moneda=linea.moneda,
                        precio=linea.precio,
                        precio_costo=linea.precio_costo,
                        precio_costo_pp=linea.precio_costo_pp,
                        item_id=productos[linea.codigo].item_id if linea.codigo in productos else None,
                    )
                    for i, linea in enumerate(doc.lineas, start=1)
                ],
            )
        )
    db.flush()
    return reemplazados, perdidas, cambios


REPORTE = {"detallada": "reporte detallado", "resumen": "reporte de ventas (resumen)"}


def _mismo_vendedor(a: str, b: str) -> bool:
    """The same salesperson: equal names, or one is the other as GBP cuts it on documents (12+ characters)."""
    if a == b:
        return True
    corto, largo = sorted((a, b), key=len)
    return len(corto) >= LARGO_VENDEDOR_IMPRESO and largo.startswith(corto)


def _mismo_vendedor_sql(guardado, nombre: str):
    """`_mismo_vendedor` in SQL, for a stored name column: equal, or one is the other as GBP cuts it on documents."""
    buscado = literal(nombre, String)
    return or_(
        guardado == nombre,
        and_(func.char_length(guardado) >= LARGO_VENDEDOR_IMPRESO, func.strpos(buscado, guardado) == 1),
        and_(func.char_length(buscado) >= LARGO_VENDEDOR_IMPRESO, func.strpos(guardado, buscado) == 1),
    )


def _cubre(otro: VentaFueraPdfAlcance, vendedor: Optional[str]) -> bool:
    return otro.vendedor is None or (vendedor is not None and _mismo_vendedor(otro.vendedor, vendedor))


def _restar(desde: date, hasta: date, tramos: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """The days of [desde, hasta] outside every tramo, as ranges."""
    huecos = [(desde, hasta)]
    for d, h in sorted(tramos):
        quedan = []
        for a, b in huecos:
            if h < a or d > b:
                quedan.append((a, b))
                continue
            if d > a:
                quedan.append((a, d - timedelta(days=1)))
            if h < b:
                quedan.append((h + timedelta(days=1), b))
        huecos = quedan
    return huecos


def _faltante(reporte: str, vendedor: Optional[str], desde: date, hasta: date) -> dict:
    return {"reporte": reporte, "vendedor": vendedor, "desde": desde.isoformat(), "hasta": hasta.isoformat()}


def _nombre_completo(persona: str, conocidos: list[str]) -> str:
    """The salesperson's full name from a report header of the company, when GBP cut it on the documents."""
    return next((n for n in conocidos if len(n) > len(persona) and _mismo_vendedor(n, persona)), persona)


def _sin_cubrir(
    alcance: VentaFueraPdfAlcance,
    reporte: str,
    otros: list[VentaFueraPdfAlcance],
    documentos: list[tuple[date, str]],
    conocidos: list[str],
) -> list[dict]:
    """What of the scope no report of kind `reporte` covers (owner, L11: "que cubra por partes"). `otros` are the
    company's scopes that have that report; `documentos` are the scope's own (date, salesperson) pairs, which name the
    salespeople of a "Todos" scope."""
    if alcance.vendedor is not None:
        tramos = [(o.desde, o.hasta) for o in otros if _cubre(o, alcance.vendedor)]
        return [_faltante(reporte, alcance.vendedor, a, b) for a, b in _restar(alcance.desde, alcance.hasta, tramos)]
    faltan: list[dict] = []
    for a, b in _restar(alcance.desde, alcance.hasta, [(o.desde, o.hasta) for o in otros if o.vendedor is None]):
        por_persona = {}
        for persona in sorted({v for fecha, v in documentos if a <= fecha <= b}):
            propios = [o for o in otros if o.vendedor is not None and _mismo_vendedor(o.vendedor, persona)]
            nombre = propios[0].vendedor if propios else _nombre_completo(persona, conocidos)
            por_persona[nombre] = _restar(a, b, [(o.desde, o.hasta) for o in propios])
        if all(huecos == [(a, b)] for huecos in por_persona.values()):
            # Nothing of the other kind touches this range: the whole range is missing, for everyone.
            faltan.append(_faltante(reporte, None, a, b))
            continue
        for nombre, huecos in por_persona.items():
            faltan.extend(_faltante(reporte, nombre, x, y) for x, y in huecos)
    return faltan


def _mensaje_faltante(alcance: VentaFueraPdfAlcance, faltante: dict) -> str:
    todo = (faltante["vendedor"], faltante["desde"], faltante["hasta"]) == (
        alcance.vendedor,
        alcance.desde.isoformat(),
        alcance.hasta.isoformat(),
    )
    if todo:
        return FALTA_DETALLADA if faltante["reporte"] == "detallada" else FALTA_RESUMEN
    desde, hasta = date.fromisoformat(faltante["desde"]), date.fromisoformat(faltante["hasta"])
    return (
        f"Falta subir el {REPORTE[faltante['reporte']]} de {faltante['vendedor'] or 'Todos'} "
        f"del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}."
    )


def _en(otros: list[VentaFueraPdfAlcance], fecha: date, vendedor: str) -> bool:
    return any(o.desde <= fecha <= o.hasta and _cubre(o, vendedor) for o in otros)


def _cruzar(
    db: Session, alcance: VentaFueraPdfAlcance, del_periodo: list[VentaFueraPdfAlcance]
) -> tuple[list[str], list[VentaFueraOperacion]]:
    """Cross-check the scope with the reports of the other kind that cover it, whichever scope they were uploaded
    under (`del_periodo`: the company's scopes overlapping it). Records what is still missing, writes the control
    fields of the operations involved and returns the warnings and the scope's operations (its own when it has a
    detailed report, else the ones its summary controls)."""
    con_detallada = [o for o in del_periodo if o.detallada_carga_id is not None]
    con_resumen = [o for o in del_periodo if o.resumen_carga_id is not None]

    propias: list[VentaFueraOperacion] = []
    if alcance.detallada_carga_id is not None:
        propias = list(
            db.execute(
                select(VentaFueraOperacion)
                .where(VentaFueraOperacion.carga_id == alcance.detallada_carga_id)
                .order_by(VentaFueraOperacion.id)
            ).scalars()
        )
        carga = db.get(VentaFueraPdfCarga, alcance.detallada_carga_id)
        if alcance.vendedor is not None and carga is not None and carga.vendedor is None:
            # A "Todos" PDF imported for some salespeople only (L22) has one scope per chosen salesperson, all of
            # them on the same upload: each scope is its own salesperson's documents.
            propias = [op for op in propias if _mismo_vendedor(alcance.vendedor, op.vendedor)]
    resumen_propio = list(alcance.documentos_resumen) if alcance.resumen_carga_id is not None else []

    # The control of a document is its row in a summary of the company; the latest summary wins.
    controles: dict[tuple, tuple[VentaFueraPdfResumenDocumento, bool]] = {}
    for otro in sorted(con_resumen, key=lambda o: o.resumen_carga_id):
        for doc in otro.documentos_resumen:
            controles[doc.clave] = (doc, bool(otro.resumen_con_impuestos))

    claves_resumen = [doc.clave for doc in resumen_propio]
    ajenas = []
    if claves_resumen:
        ajenas = list(
            db.execute(
                select(VentaFueraOperacion).where(
                    VentaFueraOperacion.empresa == alcance.empresa,
                    tuple_(
                        VentaFueraOperacion.tipo,
                        VentaFueraOperacion.letra,
                        VentaFueraOperacion.punto_venta,
                        VentaFueraOperacion.numero,
                    ).in_(claves_resumen),
                )
            ).scalars()
        )
    operaciones = {(op.tipo, op.letra, op.punto_venta, op.numero): op for op in [*ajenas, *propias]}

    conocidos = sorted(
        n
        for n in db.execute(
            select(VentaFueraPdfAlcance.vendedor)
            .where(VentaFueraPdfAlcance.empresa == alcance.empresa, VentaFueraPdfAlcance.vendedor.is_not(None))
            .distinct()
        ).scalars()
    )
    faltantes: list[dict] = []
    if alcance.detallada_carga_id is not None:
        faltantes += _sin_cubrir(
            alcance, "resumen", con_resumen, [(op.fecha, op.vendedor) for op in propias], conocidos
        )
    if alcance.resumen_carga_id is not None:
        faltantes += _sin_cubrir(
            alcance, "detallada", con_detallada, [(doc.fecha, doc.vendedor) for doc in resumen_propio], conocidos
        )
    if alcance.detallada_carga_id is None and alcance.resumen_carga_id is None:
        faltantes = [_faltante("detallada", alcance.vendedor, alcance.desde, alcance.hasta)]
    alcance.faltantes = faltantes
    avisos = [_mensaje_faltante(alcance, f) for f in faltantes]

    con_impuestos = False
    faltan_en_detalle: list[str] = []
    por_documento: list[str] = []
    for clave in sorted(operaciones.keys() | set(claves_resumen)):
        op = operaciones.get(clave)
        control, impuestos = controles.get(clave, (None, False))
        if op is None:
            if control is not None and _en(con_detallada, control.fecha, control.vendedor):
                faltan_en_detalle.append(
                    f"{nombre_comprobante(*clave)} está en el reporte de ventas pero no en el detallado."
                )
            continue
        op.cliente_codigo = op.condicion_venta = op.importe_resumen = None
        op.recargo_financiero = CERO
        if control is None:
            if _en(con_resumen, op.fecha, op.vendedor):
                por_documento.append(
                    f"{nombre_comprobante(*clave)} está en el detallado pero no en el reporte de ventas."
                )
            continue
        op.cliente = control.cliente
        op.cliente_codigo = control.cliente_codigo
        op.condicion_venta = control.condicion_venta
        op.importe_resumen = control.importe
        con_impuestos = con_impuestos or impuestos
        if control.importe == op.total_lineas or impuestos:
            # With taxes the summary Importe carries VAT: neither a surcharge nor a mismatch can be told apart.
            continue
        if control.condicion_venta.upper().startswith(CONDICION_CHEQUE):
            recargo = control.importe - op.total_lineas
            op.recargo_financiero = recargo
            esperado = (op.total_lineas * RECARGO_CHEQUE).quantize(Decimal("0.01"))
            # Stored anyway; a surcharge against the document's sign or away from 4% is worth a look in GBP.
            if recargo * op.total_lineas < 0 or abs(recargo - esperado) > TOLERANCIA_RECARGO:
                por_documento.append(
                    f"{nombre_comprobante(*clave)}: el recargo del cheque es {recargo} y el 4% de las líneas es "
                    f"{esperado}."
                )
        else:
            por_documento.append(
                f"{nombre_comprobante(*clave)}: el reporte de ventas dice {control.importe} y las líneas suman "
                f"{op.total_lineas}."
            )
    if con_impuestos:
        avisos.append("El reporte de ventas está exportado con impuestos: los importes no se pueden comparar.")
    avisos += faltan_en_detalle + por_documento
    return avisos, propias if alcance.detallada_carga_id is not None else ajenas


REEMPLAZADOS = re.compile(r"se reemplazaron por una carga posterior \((.+)\)\.$")


def _reemplazo(
    db: Session, alcance: VentaFueraPdfAlcance, perdidas: dict[int, int], cabecera: ReporteDetallado | ReporteResumen
) -> Optional[str]:
    """How many documents of the scope's detailed upload a later upload replaced, counted from what is stored, so
    loading that later upload again keeps saying it. Names the upload that replaced them last."""
    carga = db.get(VentaFueraPdfCarga, alcance.detallada_carga_id)
    quedan = db.execute(
        select(func.count()).where(VentaFueraOperacion.carga_id == alcance.detallada_carga_id)
    ).scalar_one()
    if carga is None or carga.documentos <= quedan:
        return None
    if alcance.detallada_carga_id in perdidas:
        origen = f"{cabecera.vendedor or 'Todos'}, {cabecera.desde:%d/%m/%Y}-{cabecera.hasta:%d/%m/%Y}"
    else:
        anterior = next((m for m in map(REEMPLAZADOS.search, alcance.avisos or []) if m), None)
        origen = anterior.group(1) if anterior else None
    sufijo = f" ({origen})" if origen else ""
    return f"{carga.documentos - quedan} comprobantes de este período se reemplazaron por una carga posterior{sufijo}."


def _refrescar(
    db: Session,
    propios: list[VentaFueraPdfAlcance],
    perdidas: dict[int, int],
    cabecera: ReporteDetallado | ReporteResumen,
) -> dict[int, tuple[list[str], list[VentaFueraOperacion]]]:
    """Cross-check again every scope of the company this upload may change: the ones overlapping its range (their
    coverage changes) and the ones whose operations it replaced, which say how many documents a later upload
    replaced so they no longer look complete. Returns the warnings and operations of each uploaded scope
    (`propios`: one, or one per chosen salesperson of a "Todos" PDF), by scope id."""

    def del_periodo_de(a: VentaFueraPdfAlcance) -> list[VentaFueraPdfAlcance]:
        consulta = select(VentaFueraPdfAlcance).where(
            VentaFueraPdfAlcance.empresa == a.empresa,
            VentaFueraPdfAlcance.desde <= a.hasta,
            VentaFueraPdfAlcance.hasta >= a.desde,
        )
        return list(db.execute(consulta).scalars())

    afectados = {a.id: a for alcance in propios for a in del_periodo_de(alcance)}
    ids_propios = [a.id for a in propios]
    if perdidas:
        afectados.update(
            (a.id, a)
            for a in db.execute(
                select(VentaFueraPdfAlcance).where(VentaFueraPdfAlcance.detallada_carga_id.in_(list(perdidas)))
            ).scalars()
        )
    resultado: dict[int, tuple[list[str], list[VentaFueraOperacion]]] = {}
    for otro in sorted(afectados.values(), key=lambda a: (a.id not in ids_propios, a.id)):
        avisos, operaciones = _cruzar(db, otro, del_periodo_de(otro))
        if otro.id not in ids_propios and otro.detallada_carga_id is not None:
            reemplazo = _reemplazo(db, otro, perdidas, cabecera)
            avisos = [reemplazo, *avisos] if reemplazo else avisos
        otro.avisos = avisos
        if otro.id in ids_propios:
            resultado[otro.id] = (avisos, operaciones)
    return resultado


# ── The salespeople of a report (owner L22: "Al cargar el pdf leerlo y seleccionar que vendedores se van a importar")

Documento = Union[DocumentoDetallado, DocumentoResumen]


def normalizar_nombre(nombre: Optional[str]) -> str:
    """A salesperson's name for comparing: case-insensitive, spaces collapsed and trimmed."""
    return " ".join((nombre or "").split()).casefold()


def es_excluido(nombre: str, excluidos: Iterable[Optional[str]]) -> bool:
    """Whether the salesperson `nombre` of a PDF is in the excluded list (`vendedores_excluidos.sm_name`, e.g. "Vendedor
    ML"): THE matching rule of the upload preview. Both names are compared case-insensitively with their spaces
    collapsed and trimmed (`normalizar_nombre`); they match when equal, or when one is the other as GBP cuts it on
    documents (its first `LARGO_VENDEDOR_IMPRESO` characters or more, `_mismo_vendedor`). An empty excluded name
    matches nothing."""
    propio = normalizar_nombre(nombre)
    return any(bool(otro) and _mismo_vendedor(propio, otro) for otro in (normalizar_nombre(e) for e in excluidos))


def nombres_excluidos(db: Session) -> list[str]:
    """The excluded salespeople's names (`vendedores_excluidos.sm_name`)."""
    return [n for n in db.execute(select(VendedorExcluido.sm_name)).scalars() if n]


def _nombre_de(documento: Documento, cabecera: Optional[str]) -> str:
    """The name a document's salesperson is listed and chosen by: as printed on the document, or the report header's
    full name when the header names one salesperson and the document carries it cut by GBP."""
    if cabecera is not None and _mismo_vendedor(cabecera, documento.vendedor):
        return cabecera
    return documento.vendedor


def _por_vendedor(reporte: ReporteDetallado | ReporteResumen) -> dict[str, list[Documento]]:
    grupos: dict[str, list[Documento]] = {}
    for documento in reporte.documentos:
        grupos.setdefault(_nombre_de(documento, reporte.vendedor), []).append(documento)
    return grupos


@dataclass
class VendedorEncontrado:
    vendedor: str
    documentos: int
    # The sum of its documents' lines (without VAT); of their summary Importe when only the summary was uploaded.
    total_lineas: Decimal
    excluido: bool


@dataclass
class Previsualizacion:
    empresa: str
    desde: date
    hasta: date
    vendedor_filtro: Optional[str]
    vendedores: list[VendedorEncontrado]


def previsualizar(
    db: Session, detallada: Optional[ReporteDetallado], resumen: Optional[ReporteResumen]
) -> Previsualizacion:
    """Step 1 of the upload (L22): the salespeople the reports hold, with their documents and amount, most sold first;
    the excluded ones are marked so the screen leaves them unticked. Same checks as `cargar`; stores nothing."""
    if detallada is None and resumen is None:
        raise CargaInvalida("Subí el reporte detallado, el reporte de ventas o los dos.")
    if detallada is not None and resumen is not None:
        _validar_par(detallada, resumen)
    fuente = detallada if detallada is not None else resumen
    excluidos = nombres_excluidos(db)
    vendedores = [
        VendedorEncontrado(
            vendedor=nombre,
            documentos=len(docs),
            total_lineas=sum((d.total_lineas if isinstance(d, DocumentoDetallado) else d.importe for d in docs), CERO),
            excluido=es_excluido(nombre, excluidos),
        )
        for nombre, docs in _por_vendedor(fuente).items()
    ]
    vendedores.sort(key=lambda v: (-v.total_lineas, v.vendedor))
    return Previsualizacion(fuente.empresa, fuente.desde, fuente.hasta, fuente.vendedor, vendedores)


def _elegir(
    detallada: Optional[ReporteDetallado], resumen: Optional[ReporteResumen], elegidos: Optional[list[str]]
) -> tuple[Optional[ReporteDetallado], Optional[ReporteResumen], list[str], bool]:
    """The reports narrowed to the chosen salespeople: `(detallada, resumen, imported names, only some of them)`.
    `elegidos` None imports every salesperson, as before L22. An empty choice or a name the report does not hold is
    refused."""
    fuente = detallada if detallada is not None else resumen
    todos = list(_por_vendedor(fuente))
    if elegidos is None:
        return detallada, resumen, todos, False
    if not elegidos:
        raise CargaInvalida("Elegí al menos un vendedor para importar.")
    desconocidos = [n for n in elegidos if n not in todos]
    if desconocidos:
        raise CargaInvalida(f"El PDF no tiene comprobantes de: {', '.join(desconocidos)}.")
    elegidos = [n for n in todos if n in set(elegidos)]
    if len(elegidos) == len(todos):
        return detallada, resumen, todos, False

    def de_elegidos(reporte):
        if reporte is None:
            return None
        docs = [
            d
            for d in reporte.documentos
            if _nombre_de(d, reporte.vendedor) in elegidos or any(_mismo_vendedor(n, d.vendedor) for n in elegidos)
        ]
        return dataclasses.replace(reporte, documentos=docs)

    return de_elegidos(detallada), de_elegidos(resumen), elegidos, True


# ── The structured result (vpf-metricas-canal-fe C1)

EN_RESUMEN_NO_EN_DETALLE = "está en el reporte de ventas pero no en el detallado."
EN_DETALLE_NO_EN_RESUMEN = "está en el detallado pero no en el reporte de ventas."


def _sin_producto(db: Session, detallada: Optional[ReporteDetallado]) -> dict:
    """The imported lines whose code is not in productos_erp, or without code (S7: "sin producto"), by code (or by
    article text when there is none): their count and amount (line `precio`, without VAT, as in the PDF)."""
    lineas = [ln for doc in (detallada.documentos if detallada else []) for ln in doc.lineas]
    conocidos = productos_por_codigo(db, {ln.codigo for ln in lineas if ln.codigo})
    articulos: dict[tuple, dict] = {}
    for ln in lineas:
        if ln.codigo and ln.codigo in conocidos:
            continue
        clave = (ln.codigo, None) if ln.codigo else (None, ln.articulo)
        item = articulos.setdefault(clave, {"articulo": ln.articulo, "codigo": ln.codigo, "lineas": 0, "monto": CERO})
        item["lineas"] += 1
        item["monto"] += ln.precio
    lista = sorted(articulos.values(), key=lambda a: (-a["monto"], a["articulo"]))
    return {
        "lineas": sum(a["lineas"] for a in lista),
        "monto": sum((a["monto"] for a in lista), CERO),
        "articulos": lista,
    }


def _control(
    resumen: Optional[ReporteResumen], operaciones: list[VentaFueraOperacion], avisos: list[str], total: Decimal
) -> dict:
    """The summary cross-check of the upload: whether a summary controls it, whether every document is in both
    reports, the summary's total against the lines' and the cheque documents with their surcharge."""
    controladas = [op.importe_resumen for op in operaciones if op.importe_resumen is not None]
    hay_resumen = resumen is not None or bool(controladas)
    if controladas:
        total_resumen: Optional[Decimal] = sum(controladas, CERO)
    elif resumen is not None:
        total_resumen = sum((d.importe for d in resumen.documentos), CERO)
    else:
        total_resumen = None
    sin_par = any(a.endswith((EN_RESUMEN_NO_EN_DETALLE, EN_DETALLE_NO_EN_RESUMEN)) for a in avisos)
    return {
        "resumen": hay_resumen,
        "documentos_coinciden": (not sin_par) if hay_resumen else None,
        "total_resumen": total_resumen,
        "total_lineas": total,
        "diferencia": total_resumen - total if total_resumen is not None and operaciones else None,
        "cheques": [
            {
                "tipo": op.tipo,
                "letra": op.letra,
                "punto_venta": op.punto_venta,
                "numero": op.numero,
                "cliente": op.cliente,
                "recargo": op.recargo_financiero,
            }
            for op in sorted(operaciones, key=lambda o: (o.tipo, o.letra, o.punto_venta, o.numero))
            if op.recargo_financiero
        ],
    }


def estado_control(falta_detallada: bool, control: dict, avisos: list[str]) -> str:
    """The upload's control status in the history: "sin_detallada" while no detailed report covers it, "sin_resumen"
    while no summary controls it, "avisos" with any warning, else "ok"."""
    if falta_detallada:
        return "sin_detallada"
    if not control["resumen"]:
        return "sin_resumen"
    return "avisos" if avisos else "ok"


def _json(valor):
    """A result dict as the JSON column keeps it (amounts as strings, exact)."""
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    return str(valor) if isinstance(valor, Decimal) else valor


def cargar(
    db: Session,
    detallada: Optional[ReporteDetallado],
    resumen: Optional[ReporteResumen],
    archivo_detallado: Optional[str],
    archivo_resumen: Optional[str],
    usuario_id: Optional[int],
    vendedores: Optional[list[str]] = None,
) -> ResultadoCarga:
    """Load one or both reports of a scope (company + salesperson + range). The detailed report replaces the scope's
    operations; the summary is kept as the scope's control. Either one pairs with the other report uploaded before
    for the same scope, and the cross-check runs again over the pair. Commits.

    `vendedores` (owner L22): the salespeople of the PDF to import; None imports all of them, as before. When only
    some of a "Todos" PDF's salespeople are chosen, only their documents are stored and replaced (company + chosen
    salespeople + range) and the upload gets one scope per chosen salesperson instead of the "Todos" scope, so it
    never claims coverage (L8/L11) for the salespeople left out."""
    if detallada is None and resumen is None:
        raise CargaInvalida("Subí el reporte detallado, el reporte de ventas o los dos.")
    if detallada is not None and resumen is not None:
        _validar_par(detallada, resumen)
    detallada, resumen, importados, algunos = _elegir(detallada, resumen, vendedores)
    cabecera = detallada if detallada is not None else resumen

    # Two uploads of one company must not interleave their delete and insert.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:clave))"), {"clave": f"ventas_fuera_pdf:{cabecera.empresa}"}
    )

    carga = VentaFueraPdfCarga(
        empresa=cabecera.empresa,
        vendedor=cabecera.vendedor,
        desde=cabecera.desde,
        hasta=cabecera.hasta,
        archivo_detallado=archivo_detallado[:255] if detallada is not None and archivo_detallado else None,
        archivo_resumen=archivo_resumen[:255] if resumen is not None and archivo_resumen else None,
        documentos=len(detallada.documentos) if detallada is not None else 0,
        reemplazados=0,
        avisos=[],
        usuario_id=usuario_id,
    )
    db.add(carga)
    db.flush()
    alcances = [
        _alcance_de(db, cabecera.empresa, vendedor, cabecera.desde, cabecera.hasta)
        for vendedor in (importados if algunos else [cabecera.vendedor])
    ]
    if resumen is not None:
        for alcance in alcances:
            propio = resumen
            if algunos:
                propio = dataclasses.replace(
                    resumen,
                    documentos=[
                        d
                        for d in resumen.documentos
                        if _mismo_vendedor(alcance.vendedor, d.vendedor)
                        or _nombre_de(d, resumen.vendedor) == alcance.vendedor
                    ],
                )
            _guardar_resumen(db, alcance, propio, carga.id)
    perdidas: dict[int, int] = {}
    cambios = {"nuevos": 0, "anulados": 0}
    if detallada is not None:
        carga.reemplazados, perdidas, cambios = _crear_operaciones(
            db, detallada, carga.id, importados if algunos else None
        )
        for alcance in alcances:
            alcance.detallada_carga_id = carga.id
    db.flush()

    por_alcance = _refrescar(db, alcances, perdidas, cabecera)
    avisos: list[str] = []
    operaciones: dict[int, VentaFueraOperacion] = {}
    for alcance in alcances:
        propios, ops = por_alcance.get(alcance.id, ([], []))
        avisos += [a for a in propios if a not in avisos]
        operaciones.update((op.id, op) for op in ops)
    ops = list(operaciones.values())
    faltantes = [f for alcance in alcances for f in alcance.faltantes]
    falta_detallada = any(a.falta_detallada for a in alcances)
    # Amounts to the cent, as the stored columns read them back.
    total_lineas = sum((op.total_lineas for op in ops), CERO).quantize(CENTAVO)
    recargo = sum((op.recargo_financiero for op in ops), CERO).quantize(CENTAVO)
    sin_producto = _sin_producto(db, detallada)
    control = _control(resumen, ops, avisos, total_lineas)
    documentos = detallada.documentos if detallada is not None else []
    por_tipo = Counter((doc.tipo, doc.letra) for doc in documentos)
    anteriores = [c for c in perdidas if c != carga.id]
    carga_anterior_at = (
        db.execute(
            select(func.max(VentaFueraPdfCarga.created_at)).where(VentaFueraPdfCarga.id.in_(anteriores))
        ).scalar_one()
        if anteriores
        else None
    )

    carga.avisos = list(avisos)
    carga.vendedores = importados
    carga.lineas = sum(len(doc.lineas) for doc in documentos)
    carga.unidades = sum((ln.cantidad for doc in documentos for ln in doc.lineas), CERO)
    carga.total_lineas = total_lineas
    carga.recargo_financiero = recargo
    carga.sin_producto_lineas = sin_producto["lineas"]
    carga.sin_producto_monto = sin_producto["monto"]
    carga.documentos_por_tipo = [
        {"tipo": tipo, "letra": letra, "cantidad": n} for (tipo, letra), n in sorted(por_tipo.items())
    ]
    carga.carga_anterior_at = carga_anterior_at
    carga.control = _json(control)
    carga.control_estado = estado_control(falta_detallada, control, avisos)
    db.commit()
    usuario = (
        db.execute(select(Usuario.nombre).where(Usuario.id == usuario_id)).scalar_one_or_none()
        if usuario_id is not None
        else None
    )
    return ResultadoCarga(
        carga_id=carga.id,
        alcance_id=alcances[0].id,
        empresa=cabecera.empresa,
        vendedor=cabecera.vendedor,
        desde=cabecera.desde,
        hasta=cabecera.hasta,
        documentos=carga.documentos,
        lineas=carga.lineas,
        reemplazados=carga.reemplazados,
        total_lineas=total_lineas,
        recargo_financiero=recargo,
        falta_detallada=falta_detallada,
        falta_resumen=any(a.falta_resumen for a in alcances),
        faltantes=faltantes,
        avisos=avisos,
        created_at=carga.created_at,
        usuario=usuario,
        vendedores=importados,
        unidades=carga.unidades,
        documentos_por_tipo=list(carga.documentos_por_tipo),
        sin_producto=sin_producto,
        reemplazo={"documentos": carga.reemplazados, "carga_anterior_at": carga_anterior_at, **cambios},
        control=control,
    )


# ── The upload history (vpf-metricas-canal-fe C2)


@dataclass
class CargaHistorial:
    carga: VentaFueraPdfCarga
    usuario: Optional[str]
    vigente: bool

    @property
    def control(self) -> str:
        """The stored status; for an upload made before it was stored, what its files and warnings say."""
        c = self.carga
        if c.control_estado:
            return c.control_estado
        if c.archivo_detallado is None:
            return "sin_detallada"
        if c.archivo_resumen is None:
            return "sin_resumen"
        return "avisos" if c.avisos else "ok"


def listar_cargas(
    db: Session,
    empresa: Optional[str] = None,
    vendedor: Optional[str] = None,
    dias: int = 90,
    limite: int = 50,
    desplazamiento: int = 0,
) -> list[CargaHistorial]:
    """The uploads of the last `dias` days, newest first, with who uploaded them and whether they still hold: an
    upload with documents is "vigente" while any of its operations remains (a later upload replaced them all
    otherwise); one without (a summary alone, an empty report) while it is still a scope's last report of its kind.
    `vendedor` matches the PDF's salesperson filter or one of the salespeople imported, also when one of the two
    is the name as GBP cuts it on documents."""
    C = VentaFueraPdfCarga
    con_operaciones = exists().where(VentaFueraOperacion.carga_id == C.id)
    de_un_alcance = exists().where(
        or_(VentaFueraPdfAlcance.detallada_carga_id == C.id, VentaFueraPdfAlcance.resumen_carga_id == C.id)
    )
    vigente = or_(and_(C.documentos > 0, con_operaciones), and_(C.documentos == 0, de_un_alcance))
    consulta = (
        select(C, Usuario.nombre, vigente.label("vigente"))
        .outerjoin(Usuario, Usuario.id == C.usuario_id)
        .where(C.created_at >= func.now() - timedelta(days=dias))
        .order_by(C.created_at.desc(), C.id.desc())
        .limit(limite)
        .offset(desplazamiento)
    )
    if empresa:
        consulta = consulta.where(C.empresa == empresa)
    if vendedor:
        importado = func.jsonb_array_elements_text(cast(C.vendedores, JSONB)).table_valued("value").alias("importado")
        consulta = consulta.where(
            or_(
                _mismo_vendedor_sql(C.vendedor, vendedor),
                exists(
                    select(literal(1)).select_from(importado).where(_mismo_vendedor_sql(importado.c.value, vendedor))
                ),
            )
        )
    return [CargaHistorial(carga, usuario, bool(v)) for carga, usuario, v in db.execute(consulta).all()]


def listar_alcances(
    db: Session, empresa: Optional[str] = None, limite: Optional[int] = None, desplazamiento: int = 0
) -> list[VentaFueraPdfAlcance]:
    """Load scopes, newest range first, each saying whether its summary or its detailed report is missing."""
    consulta = select(VentaFueraPdfAlcance).order_by(
        VentaFueraPdfAlcance.desde.desc(), VentaFueraPdfAlcance.hasta.desc(), VentaFueraPdfAlcance.empresa
    )
    if empresa:
        consulta = consulta.where(VentaFueraPdfAlcance.empresa == empresa)
    consulta = consulta.order_by(VentaFueraPdfAlcance.id.desc())
    if limite is not None:
        consulta = consulta.limit(limite).offset(desplazamiento)
    return list(db.execute(consulta).scalars())


def listar_operaciones(
    db: Session,
    empresa: Optional[str],
    desde: date,
    hasta: date,
    vendedor: Optional[str] = None,
    limite: Optional[int] = None,
    desplazamiento: int = 0,
) -> list[VentaFueraOperacion]:
    """Operations of a range (optionally one company / salesperson, by full or printed name), with their lines
    loaded in one extra query, newest first."""
    consulta = (
        select(VentaFueraOperacion)
        .options(selectinload(VentaFueraOperacion.lineas))
        .where(VentaFueraOperacion.fecha.between(desde, hasta))
    )
    if empresa:
        consulta = consulta.where(VentaFueraOperacion.empresa == empresa)
    if vendedor:
        consulta = consulta.where(_es_vendedor(vendedor))
    consulta = consulta.order_by(
        VentaFueraOperacion.fecha.desc(),
        VentaFueraOperacion.empresa,
        VentaFueraOperacion.tipo,
        VentaFueraOperacion.letra,
        VentaFueraOperacion.punto_venta,
        VentaFueraOperacion.numero,
    )
    if limite is not None:
        consulta = consulta.limit(limite).offset(desplazamiento)
    return list(db.execute(consulta).scalars())


@dataclass(frozen=True)
class ProductoDeLinea:
    item_id: int
    marca: Optional[str]
    categoria: Optional[str]
    pm_usuario_id: Optional[int]
    pm_nombre: Optional[str]


def productos_por_codigo(db: Session, codigos: set[str]) -> dict[str, ProductoDeLinea]:
    """Product, brand, category and PM of each line code (code = productos_erp.codigo, unique per S21). A code that
    is not in productos_erp, and a manual line without code, are missing from the result: "sin producto" (S7)."""
    if not codigos:
        return {}
    filas = db.execute(
        select(
            ProductoERP.codigo,
            ProductoERP.item_id,
            ProductoERP.marca,
            ProductoERP.categoria,
            MarcaPM.usuario_id,
            Usuario.nombre,
        )
        .outerjoin(MarcaPM, and_(MarcaPM.marca == ProductoERP.marca, MarcaPM.categoria == ProductoERP.categoria))
        .outerjoin(Usuario, Usuario.id == MarcaPM.usuario_id)
        .where(ProductoERP.codigo.in_(codigos))
    ).all()
    return {fila[0]: ProductoDeLinea(*fila[1:]) for fila in filas}
