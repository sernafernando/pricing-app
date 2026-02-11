from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date

from app.core.database import get_db
from app.api.deps import get_current_user, get_current_admin
from app.models.usuario import Usuario
from app.models.comision_config import SubcategoriaGrupo, ComisionListaGrupo
from app.models.configuracion import Configuracion

router = APIRouter()

@router.get("/admin/comisiones/{grupo_id}")
async def obtener_comisiones_grupo(grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene todas las comisiones de un grupo"""
    comisiones = db.query(ComisionListaGrupo).filter(
        ComisionListaGrupo.grupo_id == grupo_id
    ).all()
    
    return {
        "grupo_id": grupo_id,
        "comisiones": [
            {
                "pricelist_id": c.pricelist_id,
                "comision": c.comision_porcentaje
            }
            for c in comisiones
        ]
    }

@router.get("/admin/comision/{pricelist_id}/{grupo_id}")
async def obtener_comision_especifica(
    pricelist_id: int,
    grupo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene la comisión para una lista y grupo específicos"""
    comision = db.query(ComisionListaGrupo).filter(
        ComisionListaGrupo.pricelist_id == pricelist_id,
        ComisionListaGrupo.grupo_id == grupo_id
    ).first()
    
    if not comision:
        raise HTTPException(404, "Comisión no encontrada")
    
    return {
        "pricelist_id": pricelist_id,
        "grupo_id": grupo_id,
        "comision": comision.comision_porcentaje
    }

@router.get("/admin/subcategorias-grupos")
async def listar_subcategorias_grupos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Lista todas las subcategorías y sus grupos asignados"""
    mappings = db.query(SubcategoriaGrupo).all()
    return {
        "mappings": [
            {
                "subcat_id": m.subcat_id,
                "grupo_id": m.grupo_id
            }
            for m in mappings
        ]
    }

from app.services.bna_scraper import actualizar_tipo_cambio

@router.post("/admin/actualizar-tipo-cambio")
async def actualizar_tc_manual(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_admin)):
    """Actualiza el tipo de cambio scrapeando el BNA"""
    resultado = await actualizar_tipo_cambio(db)
    return resultado

@router.get("/admin/tipo-cambio-actual")
async def obtener_tc_actual(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el tipo de cambio actual"""
    from app.models.tipo_cambio import TipoCambio

    # Buscar primero el de hoy, si no el más reciente
    tc = db.query(TipoCambio).filter(
        TipoCambio.moneda == "USD",
        TipoCambio.fecha == date.today()
    ).first()

    if not tc:
        tc = db.query(TipoCambio).filter(
            TipoCambio.moneda == "USD"
        ).order_by(TipoCambio.fecha.desc()).first()

    if not tc:
        raise HTTPException(404, "No hay tipo de cambio disponible")

    return {
        "moneda": "USD",
        "compra": tc.compra,
        "venta": tc.venta,
        "fecha": tc.fecha.isoformat(),
        "actualizado": tc.timestamp_actualizacion.isoformat() if tc.timestamp_actualizacion else None
    }

# Endpoints de configuración
class ConfiguracionUpdate(BaseModel):
    valor: str

@router.get("/admin/configuracion")
async def obtener_configuraciones(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_admin)):
    """Obtiene todas las configuraciones"""
    configs = db.query(Configuracion).all()
    return {
        "configuraciones": [
            {
                "clave": c.clave,
                "valor": c.valor,
                "descripcion": c.descripcion,
                "tipo": c.tipo
            }
            for c in configs
        ]
    }

@router.get("/admin/configuracion/{clave}")
async def obtener_configuracion(clave: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_admin)):
    """Obtiene una configuración específica"""
    config = db.query(Configuracion).filter(Configuracion.clave == clave).first()

    if not config:
        raise HTTPException(404, f"Configuración '{clave}' no encontrada")

    return {
        "clave": config.clave,
        "valor": config.valor,
        "descripcion": config.descripcion,
        "tipo": config.tipo
    }

@router.patch("/admin/configuracion/{clave}")
async def actualizar_configuracion(
    clave: str,
    update: ConfiguracionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin)
):
    """Actualiza una configuración"""
    config = db.query(Configuracion).filter(Configuracion.clave == clave).first()

    if not config:
        raise HTTPException(404, f"Configuración '{clave}' no encontrada")

    config.valor = update.valor
    db.commit()
    db.refresh(config)

    return {
        "clave": config.clave,
        "valor": config.valor,
        "descripcion": config.descripcion,
        "tipo": config.tipo
    }
