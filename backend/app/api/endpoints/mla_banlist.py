from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.mla_banlist import MLABanlist
import re

router = APIRouter()

class MLABanlistCreate(BaseModel):
    mlas: str  # Puede ser "MLA123456789" o "123456789" o múltiples separados por comas/espacios/saltos
    motivo: Optional[str] = None

class MLABanlistResponse(BaseModel):
    id: int
    mla: str
    motivo: Optional[str]
    usuario_id: int
    usuario_nombre: str
    fecha_creacion: datetime
    activo: bool

    model_config = ConfigDict(from_attributes=True)

def normalizar_mla(mla_input: str) -> str:
    """Normaliza un MLA a formato MLA123456789"""
    mla_clean = mla_input.strip().upper()

    # Si ya tiene el prefijo MLA, validar formato
    if mla_clean.startswith('MLA'):
        # Extraer solo los números después de MLA
        numeros = re.sub(r'[^0-9]', '', mla_clean[3:])
        if numeros:
            return f"MLA{numeros}"
    else:
        # Si no tiene MLA, extraer solo números y agregar prefijo
        numeros = re.sub(r'[^0-9]', '', mla_clean)
        if numeros:
            return f"MLA{numeros}"

    return None

@router.get("/mla-banlist", response_model=List[MLABanlistResponse])
async def listar_banlist(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los MLAs baneados"""
    mlas = db.query(MLABanlist).filter(MLABanlist.activo == True).all()

    resultado = []
    for mla in mlas:
        resultado.append({
            "id": mla.id,
            "mla": mla.mla,
            "motivo": mla.motivo,
            "usuario_id": mla.usuario_id,
            "usuario_nombre": mla.usuario.nombre if mla.usuario else "Usuario desconocido",
            "fecha_creacion": mla.fecha_creacion,
            "activo": mla.activo
        })

    return resultado

@router.post("/mla-banlist")
async def agregar_a_banlist(
    datos: MLABanlistCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Agrega uno o múltiples MLAs a la banlist (todos los usuarios)"""

    # Separar por comas, espacios, saltos de línea
    mlas_input = re.split(r'[,\s\n]+', datos.mlas)

    agregados = []
    duplicados = []
    invalidos = []

    for mla_input in mlas_input:
        if not mla_input.strip():
            continue

        # Normalizar MLA
        mla_normalizado = normalizar_mla(mla_input)

        if not mla_normalizado:
            invalidos.append(mla_input)
            continue

        # Verificar si ya existe
        existe = db.query(MLABanlist).filter(
            MLABanlist.mla == mla_normalizado,
            MLABanlist.activo == True
        ).first()

        if existe:
            duplicados.append(mla_normalizado)
            continue

        # Crear nuevo registro
        nuevo_mla = MLABanlist(
            mla=mla_normalizado,
            motivo=datos.motivo,
            usuario_id=current_user.id,
            activo=True
        )
        db.add(nuevo_mla)
        agregados.append(mla_normalizado)

    db.commit()

    return {
        "mensaje": "MLAs procesados",
        "agregados": agregados,
        "duplicados": duplicados,
        "invalidos": invalidos,
        "total_agregados": len(agregados)
    }

@router.delete("/mla-banlist/{mla_id}")
async def eliminar_de_banlist(
    mla_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un MLA de la banlist (solo admin/superadmin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "Solo administradores pueden eliminar de la banlist")

    mla = db.query(MLABanlist).filter(MLABanlist.id == mla_id).first()
    if not mla:
        raise HTTPException(404, "MLA no encontrado en banlist")

    # Marcar como inactivo en lugar de eliminar
    mla.activo = False
    db.commit()

    return {"mensaje": f"MLA {mla.mla} eliminado de la banlist"}

@router.get("/mla-banlist/check/{mla}")
async def verificar_mla_baneado(
    mla: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Verifica si un MLA está en la banlist"""
    mla_normalizado = normalizar_mla(mla)

    if not mla_normalizado:
        return {"baneado": False, "mensaje": "MLA inválido"}

    existe = db.query(MLABanlist).filter(
        MLABanlist.mla == mla_normalizado,
        MLABanlist.activo == True
    ).first()

    if existe:
        return {
            "baneado": True,
            "mla": existe.mla,
            "motivo": existe.motivo,
            "fecha_creacion": existe.fecha_creacion
        }

    return {"baneado": False}
