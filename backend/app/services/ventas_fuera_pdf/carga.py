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

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import String, and_, delete, func, literal, or_, select, text, tuple_
from sqlalchemy.orm import Session, selectinload

from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.models.venta_fuera_pdf import (
    VentaFueraOperacion,
    VentaFueraOperacionLinea,
    VentaFueraPdfAlcance,
    VentaFueraPdfCarga,
    VentaFueraPdfResumenDocumento,
)
from app.services.ventas_fuera_pdf.parser import ReporteDetallado, ReporteResumen, nombre_comprobante

CONDICION_CHEQUE = "CHEQUE"
# GBP's financing surcharge on "CHEQUE 30 D" documents, and how far (in pesos) a surcharge may be from it.
RECARGO_CHEQUE = Decimal("0.04")
TOLERANCIA_RECARGO = Decimal("0.05")
CERO = Decimal("0")


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


def _alcance(detallada: ReporteDetallado):
    """The operations this PDF replaces: its company and range, and its salesperson unless the PDF says "Todos"."""
    condiciones = [
        VentaFueraOperacion.empresa == detallada.empresa,
        VentaFueraOperacion.fecha.between(detallada.desde, detallada.hasta),
    ]
    if detallada.vendedor is not None:
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


def _crear_operaciones(db: Session, detallada: ReporteDetallado, carga_id: int) -> tuple[int, dict[int, int]]:
    """Replace the operations of the PDF's scope (and any of its documents loaded under another scope) with the
    PDF's documents. Returns how many stored operations were replaced, and how many of them each earlier upload
    (`carga_id`) lost."""
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
    reemplazo = or_(_alcance(detallada), mismo_doc)
    perdidas = dict(
        db.execute(
            select(VentaFueraOperacion.carga_id, func.count()).where(reemplazo).group_by(VentaFueraOperacion.carga_id)
        ).all()
    )
    reemplazados = db.execute(
        delete(VentaFueraOperacion).where(reemplazo), execution_options={"synchronize_session": False}
    ).rowcount
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
                    )
                    for i, linea in enumerate(doc.lineas, start=1)
                ],
            )
        )
    db.flush()
    return reemplazados, perdidas


REPORTE = {"detallada": "reporte detallado", "resumen": "reporte de ventas (resumen)"}


def _mismo_vendedor(a: str, b: str) -> bool:
    """The same salesperson: equal names, or one is the other as GBP cuts it on documents (12+ characters)."""
    if a == b:
        return True
    corto, largo = sorted((a, b), key=len)
    return len(corto) >= LARGO_VENDEDOR_IMPRESO and largo.startswith(corto)


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


def _sin_cubrir(
    alcance: VentaFueraPdfAlcance, reporte: str, otros: list[VentaFueraPdfAlcance], documentos: list[tuple[date, str]]
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
            nombre = propios[0].vendedor if propios else persona
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

    faltantes: list[dict] = []
    if alcance.detallada_carga_id is not None:
        faltantes += _sin_cubrir(alcance, "resumen", con_resumen, [(op.fecha, op.vendedor) for op in propias])
    if alcance.resumen_carga_id is not None:
        faltantes += _sin_cubrir(
            alcance, "detallada", con_detallada, [(doc.fecha, doc.vendedor) for doc in resumen_propio]
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


def _refrescar(
    db: Session, alcance: VentaFueraPdfAlcance, perdidas: dict[int, int], cabecera: ReporteDetallado | ReporteResumen
) -> tuple[list[str], list[VentaFueraOperacion]]:
    """Cross-check again every scope of the company this upload may change: the ones overlapping its range (their
    coverage changes) and the ones whose operations it replaced, which say how many documents a later upload
    replaced so they no longer look complete. Returns the uploaded scope's warnings and operations."""

    def del_periodo_de(a: VentaFueraPdfAlcance) -> list[VentaFueraPdfAlcance]:
        consulta = select(VentaFueraPdfAlcance).where(
            VentaFueraPdfAlcance.empresa == a.empresa,
            VentaFueraPdfAlcance.desde <= a.hasta,
            VentaFueraPdfAlcance.hasta >= a.desde,
        )
        return list(db.execute(consulta).scalars())

    afectados = {a.id: a for a in del_periodo_de(alcance)}
    if perdidas:
        afectados.update(
            (a.id, a)
            for a in db.execute(
                select(VentaFueraPdfAlcance).where(VentaFueraPdfAlcance.detallada_carga_id.in_(list(perdidas)))
            ).scalars()
        )
    resultado: tuple[list[str], list[VentaFueraOperacion]] = ([], [])
    for otro in sorted(afectados.values(), key=lambda a: a.id != alcance.id):
        avisos, operaciones = _cruzar(db, otro, del_periodo_de(otro))
        if otro.id != alcance.id and otro.detallada_carga_id in perdidas:
            avisos = [
                f"{perdidas[otro.detallada_carga_id]} comprobantes de este período se reemplazaron por una carga "
                f"posterior ({cabecera.vendedor or 'Todos'}, {cabecera.desde:%d/%m/%Y}-{cabecera.hasta:%d/%m/%Y}).",
                *avisos,
            ]
        otro.avisos = avisos
        if otro.id == alcance.id:
            resultado = (avisos, operaciones)
    return resultado


def cargar(
    db: Session,
    detallada: Optional[ReporteDetallado],
    resumen: Optional[ReporteResumen],
    archivo_detallado: Optional[str],
    archivo_resumen: Optional[str],
    usuario_id: Optional[int],
) -> ResultadoCarga:
    """Load one or both reports of a scope (company + salesperson + range). The detailed report replaces the scope's
    operations; the summary is kept as the scope's control. Either one pairs with the other report uploaded before
    for the same scope, and the cross-check runs again over the pair. Commits."""
    if detallada is None and resumen is None:
        raise CargaInvalida("Subí el reporte detallado, el reporte de ventas o los dos.")
    if detallada is not None and resumen is not None:
        _validar_par(detallada, resumen)
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
    alcance = _alcance_de(db, cabecera.empresa, cabecera.vendedor, cabecera.desde, cabecera.hasta)
    if resumen is not None:
        _guardar_resumen(db, alcance, resumen, carga.id)
    perdidas: dict[int, int] = {}
    if detallada is not None:
        carga.reemplazados, perdidas = _crear_operaciones(db, detallada, carga.id)
        alcance.detallada_carga_id = carga.id
    db.flush()

    avisos, operaciones = _refrescar(db, alcance, perdidas, cabecera)
    carga.avisos = list(avisos)
    db.commit()
    return ResultadoCarga(
        carga_id=carga.id,
        alcance_id=alcance.id,
        empresa=cabecera.empresa,
        vendedor=cabecera.vendedor,
        desde=cabecera.desde,
        hasta=cabecera.hasta,
        documentos=carga.documentos,
        lineas=sum(len(doc.lineas) for doc in detallada.documentos) if detallada is not None else 0,
        reemplazados=carga.reemplazados,
        total_lineas=sum((op.total_lineas for op in operaciones), CERO),
        recargo_financiero=sum((op.recargo_financiero for op in operaciones), CERO),
        falta_detallada=alcance.falta_detallada,
        falta_resumen=alcance.falta_resumen,
        faltantes=list(alcance.faltantes),
        avisos=avisos,
    )


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
