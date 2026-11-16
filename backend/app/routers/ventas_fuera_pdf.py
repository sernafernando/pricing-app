"""Ventas por fuera from GBP's PDF reports: upload and operations.

- `POST /ventas-fuera-pdf/cargas` (`ventas_fuera.subir_pdf`): the detailed report creates the operations of its
  company, salesperson and range, replacing what was loaded for them; the summary report, optional, is the control
  (cross-check warnings, cheque surcharge kept apart).
- `GET /ventas-fuera-pdf/alcances` (either permission): each load scope and which of its two reports is missing.
- `GET /ventas-fuera-pdf/operaciones` (`ventas_fuera.ver_metricas_pdf`): the loaded operations with their lines and
  each line's product, brand, category and PM by code ("sin producto" when the code is not in productos_erp).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import require_algun_permiso, require_permiso
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.services.ventas_fuera_pdf.carga import (
    CargaInvalida,
    cargar,
    listar_alcances,
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


@router.post("/cargas", response_model=CargaResponse)
def subir_pdfs(
    detallada: Optional[UploadFile] = File(None, description="Reporte de Ventas Detalladas de GBP"),
    resumen: Optional[UploadFile] = File(None, description="Reporte de Ventas de GBP (control)"),
    usuario: Usuario = Depends(require_permiso(PERMISO_SUBIR)),
    db: Session = Depends(get_db),
) -> CargaResponse:
    """Load one or both GBP reports of a scope. The detailed report becomes the operations of its company, salesperson
    and range ("el último PDF manda en su vendedor y rango"); the summary is the scope's control (cross-check, cheque
    surcharge) and creates no operations. Either one pairs with the other report uploaded before for the same scope;
    the response says which one is still missing. A file that is not the expected GBP report, a pair that does not
    match, or no file at all is refused with 422 and nothing changes."""
    try:
        reporte = parse_detallada(_leer(detallada)) if detallada is not None else None
        control = parse_resumen(_leer(resumen)) if resumen is not None else None
        resultado = cargar(
            db,
            reporte,
            control,
            (detallada.filename or "detallada.pdf") if detallada is not None else None,
            (resumen.filename or "resumen.pdf") if resumen is not None else None,
            usuario.id,
        )
    except (ReporteInvalido, CargaInvalida) as exc:
        db.rollback()
        raise api_error(422, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    return CargaResponse(**resultado.__dict__)


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
