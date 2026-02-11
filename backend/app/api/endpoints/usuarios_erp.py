"""
Endpoint para gestión de usuarios del ERP (tb_user)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
import logging

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.tb_user import TBUser

router = APIRouter()
logger = logging.getLogger(__name__)


class UsuarioERPResponse(BaseModel):
    """Response schema para usuarios del ERP"""
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: Optional[str]
    user_loginname: Optional[str]
    user_email: Optional[str]
    user_isactive: Optional[bool]


@router.get("/usuarios-erp", response_model=List[UsuarioERPResponse])
async def listar_usuarios_erp(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    solo_activos: bool = True
):
    """
    Lista usuarios del ERP.
    Por defecto solo muestra usuarios activos.
    """
    query = db.query(TBUser)
    
    if solo_activos:
        query = query.filter(TBUser.user_isactive == True)
    
    query = query.order_by(TBUser.user_name)
    
    usuarios = query.all()
    
    return usuarios


@router.get("/usuarios-erp/{user_id}", response_model=UsuarioERPResponse)
async def obtener_usuario_erp(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Obtiene un usuario específico del ERP por su ID"""
    usuario = db.query(TBUser).filter(TBUser.user_id == user_id).first()
    
    if not usuario:
        raise HTTPException(404, f"Usuario {user_id} no encontrado")
    
    return usuario
