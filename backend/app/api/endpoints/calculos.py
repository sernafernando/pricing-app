from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from app.core.database import get_db
from app.models.calculo_pricing import CalculoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()

class CalculoRequest(BaseModel):
    descripcion: str = Field(..., min_length=1, max_length=500)
    ean: Optional[str] = Field(None, max_length=50)
    costo: float = Field(..., gt=0)
    moneda_costo: str = Field(..., pattern="^(ARS|USD)$")
    iva: float
    comision_ml: float = Field(..., ge=0, le=100)
    costo_envio: float = Field(default=0, ge=0)
    precio_final: float = Field(..., gt=0)
    markup_porcentaje: Optional[float] = None
    limpio: Optional[float] = None
    comision_total: Optional[float] = None
    cantidad: int = Field(default=0, ge=0)

class CalculoResponse(BaseModel):
    id: int
    usuario_id: int
    descripcion: str
    ean: Optional[str]
    costo: float
    moneda_costo: str
    iva: float
    comision_ml: float
    costo_envio: float
    precio_final: float
    markup_porcentaje: Optional[float]
    limpio: Optional[float]
    comision_total: Optional[float]
    cantidad: int
    fecha_creacion: datetime
    fecha_modificacion: datetime

    class Config:
        from_attributes = True

class CantidadUpdate(BaseModel):
    cantidad: int = Field(..., ge=0)

@router.post("/calculos", response_model=CalculoResponse)
async def crear_calculo(
    calculo: CalculoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo cálculo de pricing guardado"""

    if not calculo.descripcion and not calculo.ean:
        raise HTTPException(status_code=400, detail="Debe proporcionar al menos descripción o EAN")

    nuevo_calculo = CalculoPricing(
        usuario_id=current_user.id,
        descripcion=calculo.descripcion,
        ean=calculo.ean,
        costo=calculo.costo,
        moneda_costo=calculo.moneda_costo,
        iva=calculo.iva,
        comision_ml=calculo.comision_ml,
        costo_envio=calculo.costo_envio,
        precio_final=calculo.precio_final,
        markup_porcentaje=calculo.markup_porcentaje,
        limpio=calculo.limpio,
        comision_total=calculo.comision_total,
        cantidad=calculo.cantidad
    )

    db.add(nuevo_calculo)
    db.commit()
    db.refresh(nuevo_calculo)

    return nuevo_calculo

@router.get("/calculos", response_model=List[CalculoResponse])
async def listar_calculos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los cálculos del usuario"""

    calculos = db.query(CalculoPricing).filter(
        CalculoPricing.usuario_id == current_user.id
    ).order_by(CalculoPricing.fecha_creacion.desc()).all()

    return calculos

@router.get("/calculos/{calculo_id}", response_model=CalculoResponse)
async def obtener_calculo(
    calculo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene un cálculo específico"""

    calculo = db.query(CalculoPricing).filter(
        CalculoPricing.id == calculo_id,
        CalculoPricing.usuario_id == current_user.id
    ).first()

    if not calculo:
        raise HTTPException(status_code=404, detail="Cálculo no encontrado")

    return calculo

@router.put("/calculos/{calculo_id}", response_model=CalculoResponse)
async def actualizar_calculo(
    calculo_id: int,
    calculo: CalculoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza un cálculo existente"""

    if not calculo.descripcion and not calculo.ean:
        raise HTTPException(status_code=400, detail="Debe proporcionar al menos descripción o EAN")

    calculo_db = db.query(CalculoPricing).filter(
        CalculoPricing.id == calculo_id,
        CalculoPricing.usuario_id == current_user.id
    ).first()

    if not calculo_db:
        raise HTTPException(status_code=404, detail="Cálculo no encontrado")

    calculo_db.descripcion = calculo.descripcion
    calculo_db.ean = calculo.ean
    calculo_db.costo = calculo.costo
    calculo_db.moneda_costo = calculo.moneda_costo
    calculo_db.iva = calculo.iva
    calculo_db.comision_ml = calculo.comision_ml
    calculo_db.costo_envio = calculo.costo_envio
    calculo_db.precio_final = calculo.precio_final
    calculo_db.markup_porcentaje = calculo.markup_porcentaje
    calculo_db.limpio = calculo.limpio
    calculo_db.comision_total = calculo.comision_total
    calculo_db.cantidad = calculo.cantidad
    calculo_db.fecha_modificacion = datetime.now()

    db.commit()
    db.refresh(calculo_db)

    return calculo_db

@router.patch("/calculos/{calculo_id}/cantidad")
async def actualizar_cantidad(
    calculo_id: int,
    cantidad_data: CantidadUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza solo la cantidad de un cálculo (endpoint rápido)"""

    calculo = db.query(CalculoPricing).filter(
        CalculoPricing.id == calculo_id,
        CalculoPricing.usuario_id == current_user.id
    ).first()

    if not calculo:
        raise HTTPException(status_code=404, detail="Cálculo no encontrado")

    calculo.cantidad = cantidad_data.cantidad
    calculo.fecha_modificacion = datetime.now()

    db.commit()
    db.refresh(calculo)

    return {"mensaje": "Cantidad actualizada", "cantidad": calculo.cantidad}

@router.delete("/calculos/{calculo_id}")
async def eliminar_calculo(
    calculo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un cálculo"""

    calculo = db.query(CalculoPricing).filter(
        CalculoPricing.id == calculo_id,
        CalculoPricing.usuario_id == current_user.id
    ).first()

    if not calculo:
        raise HTTPException(status_code=404, detail="Cálculo no encontrado")

    db.delete(calculo)
    db.commit()

    return {"mensaje": "Cálculo eliminado correctamente"}

class AccionMasivaRequest(BaseModel):
    calculo_ids: List[int]

@router.post("/calculos/acciones/eliminar-masivo")
async def eliminar_calculos_masivo(
    request: AccionMasivaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina múltiples cálculos"""

    if not request.calculo_ids:
        raise HTTPException(status_code=400, detail="No se proporcionaron IDs")

    calculos = db.query(CalculoPricing).filter(
        CalculoPricing.id.in_(request.calculo_ids),
        CalculoPricing.usuario_id == current_user.id
    ).all()

    count = len(calculos)

    for calculo in calculos:
        db.delete(calculo)

    db.commit()

    return {"mensaje": f"{count} cálculos eliminados", "count": count}

@router.get("/calculos/exportar/excel")
async def exportar_calculos_excel(
    filtro: Optional[str] = None,  # 'todos', 'con_cantidad', 'seleccionados'
    ids: Optional[str] = None,  # comma-separated IDs for 'seleccionados'
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Exporta cálculos a Excel según el filtro seleccionado"""

    query = db.query(CalculoPricing).filter(
        CalculoPricing.usuario_id == current_user.id
    )

    # Aplicar filtros
    if filtro == 'con_cantidad':
        query = query.filter(CalculoPricing.cantidad > 0)
    elif filtro == 'seleccionados' and ids:
        id_list = [int(id.strip()) for id in ids.split(',') if id.strip()]
        query = query.filter(CalculoPricing.id.in_(id_list))

    calculos = query.order_by(CalculoPricing.fecha_creacion.desc()).all()

    # Crear workbook de Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Cálculos de Pricing"

    # Estilos para encabezado
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    header_alignment = Alignment(horizontal="center", vertical="center")

    # Encabezados
    headers = [
        'ID', 'Descripción', 'EAN', 'Cantidad', 'Costo', 'Moneda',
        'IVA %', 'Comisión ML %', 'Costo Envío', 'Precio Final',
        'Markup %', 'Limpio', 'Comisión Total', 'Fecha Creación'
    ]

    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    # Datos
    for row_idx, calc in enumerate(calculos, start=2):
        ws.cell(row=row_idx, column=1, value=calc.id)
        ws.cell(row=row_idx, column=2, value=calc.descripcion)
        ws.cell(row=row_idx, column=3, value=calc.ean or '')
        ws.cell(row=row_idx, column=4, value=calc.cantidad)
        ws.cell(row=row_idx, column=5, value=float(calc.costo))
        ws.cell(row=row_idx, column=6, value=calc.moneda_costo)
        ws.cell(row=row_idx, column=7, value=float(calc.iva))
        ws.cell(row=row_idx, column=8, value=float(calc.comision_ml))
        ws.cell(row=row_idx, column=9, value=float(calc.costo_envio))
        ws.cell(row=row_idx, column=10, value=float(calc.precio_final))
        ws.cell(row=row_idx, column=11, value=float(calc.markup_porcentaje) if calc.markup_porcentaje else '')
        ws.cell(row=row_idx, column=12, value=float(calc.limpio) if calc.limpio else '')
        ws.cell(row=row_idx, column=13, value=float(calc.comision_total) if calc.comision_total else '')
        ws.cell(row=row_idx, column=14, value=calc.fecha_creacion.strftime('%Y-%m-%d %H:%M:%S'))

    # Ajustar anchos de columna
    column_widths = [8, 40, 15, 10, 12, 10, 8, 12, 12, 15, 10, 12, 15, 20]
    for col, width in enumerate(column_widths, start=1):
        ws.column_dimensions[chr(64 + col)].width = width

    # Guardar en memoria
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    # Nombre de archivo según filtro
    filename = f"calculos_{filtro or 'todos'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
