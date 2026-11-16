"""Ventas por fuera from GBP's PDF reports: upload and operations.

- `POST /ventas-fuera-pdf/cargas` (`ventas_fuera.subir_pdf`): the detailed report creates the operations of its
  company, salesperson and range, replacing what was loaded for them; the summary report, optional, is the control
  (cross-check warnings, cheque surcharge kept apart).
- `POST /ventas-fuera-pdf/cargas/preview` (`ventas_fuera.subir_pdf`): step 1 of the upload (owner L22), the
  salespeople the reports hold, nothing stored; `POST /cargas` with `vendedores` imports only the chosen ones.
- `GET /ventas-fuera-pdf/cargas` (either permission): the upload history.
- `GET /ventas-fuera-pdf/alcances` (either permission): each load scope and which of its two reports is missing.
- `GET /ventas-fuera-pdf/operaciones` (`ventas_fuera.ver_metricas_pdf`): the loaded operations with their lines and
  each line's product, brand, category and PM by code ("sin producto" when the code is not in productos_erp).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import require_algun_permiso, require_permiso
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.services.ventas_fuera_pdf.carga import (
    CargaHistorial,
    CargaInvalida,
    cargar,
    listar_alcances,
    listar_cargas,
    previsualizar,
    listar_operaciones,
    productos_por_codigo,
)
from app.services.ventas_fuera_pdf.parser import ReporteInvalido, parse_detallada, parse_resumen

PERMISO_SUBIR = "ventas_fuera.subir_pdf"
PERMISO_VER = "ventas_fuera.ver_metricas_pdf"
MAX_BYTES = 20 * 1024 * 1024

router = APIRouter(prefix="/ventas-fuera-pdf", tags=["Ventas por fuera (PDF)"])


class FaltanteResponse(BaseModel):
    """A part of a scope no report of the other kind covers yet: `vendedor` None means every salesperson."""

    reporte: Literal["detallada", "resumen"]
    vendedor: Optional[str]
    desde: date
    hasta: date


class DocumentosPorTipo(BaseModel):
    tipo: str
    letra: str
    cantidad: int


class ArticuloSinProducto(BaseModel):
    articulo: str
    codigo: Optional[str]
    lineas: int
    monto: float


class SinProducto(BaseModel):
    """Imported lines whose code is not in productos_erp (or without code); `monto` is their `precio` (without VAT)."""

    lineas: int
    monto: float
    articulos: list[ArticuloSinProducto]


class Reemplazo(BaseModel):
    """Stored documents this upload replaced, and when the newest upload they came from was made; `nuevos`: its
    documents not stored before, `anulados`: the replaced ones no longer in the PDF (deleted)."""

    documentos: int
    carga_anterior_at: Optional[datetime]
    nuevos: int
    anulados: int


class Cheque(BaseModel):
    tipo: str
    letra: str
    punto_venta: int
    numero: int
    cliente: str
    recargo: float


class Control(BaseModel):
    """The summary cross-check: whether a summary controls the upload, whether every document is in both reports
    (null without summary), the summary's total, the lines' total and their difference, and the cheque documents
    with their 4% surcharge."""

    resumen: bool
    documentos_coinciden: Optional[bool]
    total_resumen: Optional[float]
    total_lineas: float
    diferencia: Optional[float]
    cheques: list[Cheque]


class CargaResponse(BaseModel):
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
    faltantes: list[FaltanteResponse]
    avisos: list[str]
    created_at: datetime
    usuario: Optional[str]
    vendedores: list[str]
    unidades: float
    documentos_por_tipo: list[DocumentosPorTipo]
    sin_producto: SinProducto
    reemplazo: Reemplazo
    control: Control


class VendedorPreview(BaseModel):
    vendedor: str
    documentos: int
    total_lineas: float
    excluido: bool


class PreviewResponse(BaseModel):
    """Step 1 of the upload: the salespeople found, most sold first. `vendedor_filtro` null = the PDF says "Todos";
    `excluido` = in the excluded salespeople list (they come unticked)."""

    empresa: str
    desde: date
    hasta: date
    vendedor_filtro: Optional[str]
    archivo_detallado: Optional[str]
    archivo_resumen: Optional[str]
    vendedores: list[VendedorPreview]


class CargaHistorialResponse(BaseModel):
    """An upload of the history. The per-upload figures are null for uploads made before they were recorded."""

    id: int
    created_at: datetime
    usuario: Optional[str]
    empresa: str
    vendedor: Optional[str]
    vendedores: Optional[list[str]]
    desde: date
    hasta: date
    documentos: int
    lineas: Optional[int]
    unidades: Optional[float]
    total_lineas: Optional[float]
    reemplazados: int
    sin_producto_lineas: Optional[int]
    sin_producto_monto: Optional[float]
    recargo_financiero: Optional[float]
    archivo_detallado: Optional[str]
    archivo_resumen: Optional[str]
    avisos: list[str]
    estado: Literal["vigente", "reemplazada"]
    control: Literal["ok", "avisos", "sin_resumen", "sin_detallada"]
    control_detalle: Optional[Control]
    documentos_por_tipo: Optional[list[DocumentosPorTipo]]
    carga_anterior_at: Optional[datetime]

    @classmethod
    def de(cls, item: CargaHistorial) -> "CargaHistorialResponse":
        c = item.carga
        return cls(
            id=c.id,
            created_at=c.created_at,
            usuario=item.usuario,
            empresa=c.empresa,
            vendedor=c.vendedor,
            vendedores=c.vendedores,
            desde=c.desde,
            hasta=c.hasta,
            documentos=c.documentos,
            lineas=c.lineas,
            unidades=c.unidades,
            total_lineas=c.total_lineas,
            reemplazados=c.reemplazados,
            sin_producto_lineas=c.sin_producto_lineas,
            sin_producto_monto=c.sin_producto_monto,
            recargo_financiero=c.recargo_financiero,
            archivo_detallado=c.archivo_detallado,
            archivo_resumen=c.archivo_resumen,
            avisos=list(c.avisos or []),
            estado="vigente" if item.vigente else "reemplazada",
            control=item.control,
            control_detalle=c.control,
            documentos_por_tipo=c.documentos_por_tipo,
            carga_anterior_at=c.carga_anterior_at,
        )


class AlcanceResponse(BaseModel):
    """A load scope and which of its two reports is missing."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa: str
    vendedor: Optional[str]
    desde: date
    hasta: date
    falta_detallada: bool
    falta_resumen: bool
    faltantes: list[FaltanteResponse]
    avisos: list[str]
    updated_at: datetime


class LineaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    renglon: int
    codigo: Optional[str]
    articulo: str
    cantidad: Decimal
    moneda: str
    precio: Decimal
    precio_costo: Decimal
    precio_costo_pp: Decimal
    item_id: Optional[int] = None
    marca: Optional[str] = None
    categoria: Optional[str] = None
    pm_usuario_id: Optional[int] = None
    pm_nombre: Optional[str] = None
    sin_producto: bool = True


class OperacionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa: str
    vendedor: str
    cliente: str
    cliente_codigo: Optional[str]
    tipo: str
    letra: str
    punto_venta: int
    numero: int
    fecha: date
    fecha_vencimiento: Optional[date]
    condicion_venta: Optional[str]
    importe: Decimal
    saldo: Decimal
    total_lineas: Decimal
    importe_resumen: Optional[Decimal]
    recargo_financiero: Decimal
    lineas: list[LineaResponse]


def _leer(archivo: UploadFile) -> bytes:
    contenido = archivo.file.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        raise api_error(413, ErrorCode.VALIDATION_ERROR, f"{archivo.filename}: el PDF supera los 20 MB")
    return contenido


def _vendedores(raw: Optional[str]) -> Optional[list[str]]:
    """The `vendedores` field: a JSON array of names, or absent (every salesperson)."""
    if raw is None:
        return None
    try:
        valor = json.loads(raw)
    except ValueError as exc:
        raise CargaInvalida("vendedores tiene que ser una lista JSON de nombres") from exc
    if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor):
        raise CargaInvalida("vendedores tiene que ser una lista JSON de nombres")
    return valor


@router.post("/cargas/preview", response_model=PreviewResponse)
def previsualizar_pdfs(
    detallada: Optional[UploadFile] = File(None, description="Reporte de Ventas Detalladas de GBP"),
    resumen: Optional[UploadFile] = File(None, description="Reporte de Ventas de GBP (control)"),
    _: Usuario = Depends(require_permiso(PERMISO_SUBIR)),
    db: Session = Depends(get_db),
) -> PreviewResponse:
    """Step 1 of the upload (owner L22: "Al cargar el pdf leerlo y seleccionar que vendedores se van a importar"):
    reads the reports and lists the salespeople they hold, with their documents and amount (the lines' sum without
    VAT; the summary's Importe when only the summary is sent), most sold first. Salespeople in the excluded list come
    marked `excluido`. Nothing is stored. Same checks and 422s as `POST /cargas`."""
    try:
        reporte = parse_detallada(_leer(detallada)) if detallada is not None else None
        control = parse_resumen(_leer(resumen)) if resumen is not None else None
        vista = previsualizar(db, reporte, control)
    except (ReporteInvalido, CargaInvalida) as exc:
        raise api_error(422, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    return PreviewResponse(
        empresa=vista.empresa,
        desde=vista.desde,
        hasta=vista.hasta,
        vendedor_filtro=vista.vendedor_filtro,
        archivo_detallado=(detallada.filename or "detallada.pdf") if detallada is not None else None,
        archivo_resumen=(resumen.filename or "resumen.pdf") if resumen is not None else None,
        vendedores=[VendedorPreview(**v.__dict__) for v in vista.vendedores],
    )


@router.post("/cargas", response_model=CargaResponse)
def subir_pdfs(
    detallada: Optional[UploadFile] = File(None, description="Reporte de Ventas Detalladas de GBP"),
    resumen: Optional[UploadFile] = File(None, description="Reporte de Ventas de GBP (control)"),
    vendedores: Optional[str] = Form(
        None,
        description="Lista JSON de los vendedores a importar, como los lista /cargas/preview; sin el campo se "
        "importan todos",
    ),
    usuario: Usuario = Depends(require_permiso(PERMISO_SUBIR)),
    db: Session = Depends(get_db),
) -> CargaResponse:
    """Load one or both GBP reports of a scope. The detailed report becomes the operations of its company, salesperson
    and range ("el último PDF manda en su vendedor y rango"); the summary is the scope's control (cross-check, cheque
    surcharge) and creates no operations. Either one pairs with the other report uploaded before for the same scope;
    the response says which one is still missing. A file that is not the expected GBP report, a pair that does not
    match, or no file at all is refused with 422 and nothing changes.

    `vendedores` (owner L22): only those salespeople's documents are stored, and the replace covers the company, the
    chosen salespeople and the range. Without it every salesperson is imported, as before; an empty list or a name
    the PDF does not hold is 422."""
    try:
        elegidos = _vendedores(vendedores)
        reporte = parse_detallada(_leer(detallada)) if detallada is not None else None
        control = parse_resumen(_leer(resumen)) if resumen is not None else None
        resultado = cargar(
            db,
            reporte,
            control,
            (detallada.filename or "detallada.pdf") if detallada is not None else None,
            (resumen.filename or "resumen.pdf") if resumen is not None else None,
            usuario.id,
            elegidos,
        )
    except (ReporteInvalido, CargaInvalida) as exc:
        db.rollback()
        raise api_error(422, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    return CargaResponse(**resultado.__dict__)


@router.get("/cargas", response_model=list[CargaHistorialResponse])
def historial_cargas(
    empresa: Optional[str] = Query(None),
    vendedor: Optional[str] = Query(None, description="Filtro de vendedor del PDF o uno de los vendedores importados"),
    dias: int = Query(90, ge=1, le=3660),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _: Usuario = Depends(require_algun_permiso([PERMISO_SUBIR, PERMISO_VER])),
    db: Session = Depends(get_db),
) -> list[CargaHistorialResponse]:
    """The uploads of the last `dias` days, newest first: who uploaded what, the salespeople imported, the figures,
    whether the upload still holds ("vigente") or later uploads replaced all of it ("reemplazada"), and its summary
    cross-check status. Uploads made before the per-upload figures existed come with them null."""
    return [
        CargaHistorialResponse.de(item)
        for item in listar_cargas(db, empresa, vendedor, dias, limite=page_size, desplazamiento=(page - 1) * page_size)
    ]


@router.get("/alcances", response_model=list[AlcanceResponse])
def alcances(
    empresa: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _: Usuario = Depends(require_algun_permiso([PERMISO_SUBIR, PERMISO_VER])),
    db: Session = Depends(get_db),
) -> list[AlcanceResponse]:
    """Every load scope (company + salesperson + range) with "falta el detallado" / "falta el resumen" and the
    salespeople and dates no report of the other kind covers yet (reports of other scopes cover it by parts)."""
    return [
        AlcanceResponse.model_validate(alcance)
        for alcance in listar_alcances(db, empresa, limite=page_size, desplazamiento=(page - 1) * page_size)
    ]


@router.get("/operaciones", response_model=list[OperacionResponse])
def operaciones(
    desde: date = Query(...),
    hasta: date = Query(...),
    empresa: Optional[str] = Query(None),
    vendedor: Optional[str] = Query(None, description="Nombre completo o como lo imprime GBP en el comprobante"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_db),
) -> list[OperacionResponse]:
    """Operations loaded from the PDFs in a date range, a page at a time, with each line's product by code. Lines whose code is not in
    productos_erp (or manual lines without code) come with `sin_producto` true and are never dropped."""
    if desde > hasta:
        raise api_error(422, ErrorCode.VALIDATION_ERROR, "La fecha desde no puede ser posterior a la fecha hasta")
    ops = listar_operaciones(
        db, empresa, desde, hasta, vendedor, limite=page_size, desplazamiento=(page - 1) * page_size
    )
    productos = productos_por_codigo(db, {ln.codigo for op in ops for ln in op.lineas if ln.codigo})
    respuesta = []
    for op in ops:
        item = OperacionResponse.model_validate(op)
        for linea in item.lineas:
            producto = productos.get(linea.codigo) if linea.codigo else None
            if producto is not None:
                linea.item_id, linea.marca, linea.categoria = producto.item_id, producto.marca, producto.categoria
                linea.pm_usuario_id, linea.pm_nombre = producto.pm_usuario_id, producto.pm_nombre
                linea.sin_producto = False
        respuesta.append(item)
    return respuesta
