from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal

from app.core.database import get_db
from app.models.calculo_pricing import CalculoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()

class CalculoRequest(BaseModel):
    descripcion: str = Field(..., min_length=1, max_length=500)
    ean: Optional[str] = Field(None, max_length=50)
    costo: float = Field(..., gt=0)
    moneda_costo: str = Field(..., regex="^(ARS|USD)$")
    iva: float = Field(..., regex="^(10.5|21|10.50)$")
    comision_ml: float = Field(..., ge=0, le=100)
    costo_envio: float = Field(default=0, ge=0)
    precio_final: float = Field(..., gt=0)
    markup_porcentaje: Optional[float] = None
    limpio: Optional[float] = None
    comision_total: Optional[float] = None

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
    fecha_creacion: datetime
    fecha_modificacion: datetime

    class Config:
        from_attributes = True

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
        comision_total=calculo.comision_total
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
    calculo_db.fecha_modificacion = datetime.now()

    db.commit()
    db.refresh(calculo_db)

    return calculo_db

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
