from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP

router = APIRouter()

class MarcaPMResponse(BaseModel):
    id: int
    marca: str
    usuario_id: Optional[int]
    usuario_nombre: Optional[str] = None
    usuario_email: Optional[str] = None

    class Config:
        from_attributes = True

class MarcaPMUpdate(BaseModel):
    usuario_id: Optional[int] = None

@router.get("/marcas-pm", response_model=List[MarcaPMResponse])
async def listar_marcas_pm(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todas las marcas con sus PMs asignados (solo admin/superadmin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    marcas = db.query(MarcaPM).all()

    # Enriquecer con datos del usuario
    resultado = []
    for marca in marcas:
        marca_dict = {
            "id": marca.id,
            "marca": marca.marca,
            "usuario_id": marca.usuario_id,
            "usuario_nombre": marca.usuario.nombre if marca.usuario else None,
            "usuario_email": marca.usuario.email if marca.usuario else None
        }
        resultado.append(marca_dict)

    return resultado

@router.patch("/marcas-pm/{marca_id}")
async def actualizar_pm_marca(
    marca_id: int,
    datos: MarcaPMUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Asigna o desasigna un PM a una marca (solo admin/superadmin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    marca = db.query(MarcaPM).filter(MarcaPM.id == marca_id).first()
    if not marca:
        raise HTTPException(404, "Marca no encontrada")

    # Si se asigna un usuario, verificar que existe
    if datos.usuario_id is not None:
        usuario = db.query(Usuario).filter(Usuario.id == datos.usuario_id).first()
        if not usuario:
            raise HTTPException(404, "Usuario no encontrado")

    marca.usuario_id = datos.usuario_id
    db.commit()
    db.refresh(marca)

    return {
        "mensaje": "PM actualizado",
        "marca": marca.marca,
        "usuario_id": marca.usuario_id
    }

@router.post("/marcas-pm/sync")
async def sincronizar_marcas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Sincroniza marcas nuevas desde productos_erp (solo admin/superadmin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    # Obtener todas las marcas únicas de productos_erp
    marcas_erp = db.query(ProductoERP.marca).distinct().filter(
        ProductoERP.marca.isnot(None)
    ).all()

    marcas_nuevas = 0
    for (marca,) in marcas_erp:
        # Verificar si ya existe
        existe = db.query(MarcaPM).filter(MarcaPM.marca == marca).first()
        if not existe:
            nueva_marca = MarcaPM(marca=marca, usuario_id=None)
            db.add(nueva_marca)
            marcas_nuevas += 1

    db.commit()

    return {
        "mensaje": "Sincronización completada",
        "marcas_nuevas": marcas_nuevas
    }

@router.get("/usuarios/pms", response_model=List[dict])
async def listar_usuarios_pm(
    solo_con_marcas: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista usuarios disponibles para asignar como PMs"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    if solo_con_marcas:
        # Obtener solo usuarios que tienen al menos una marca asignada
        usuarios_con_marcas = db.query(Usuario).join(
            MarcaPM, Usuario.id == MarcaPM.usuario_id
        ).filter(
            Usuario.activo == True
        ).distinct().all()

        return [
            {
                "id": u.id,
                "nombre": u.nombre,
                "email": u.email,
                "rol": u.rol.value
            }
            for u in usuarios_con_marcas
        ]
    else:
        # Obtener todos los usuarios activos
        usuarios = db.query(Usuario).filter(Usuario.activo == True).all()

        return [
            {
                "id": u.id,
                "nombre": u.nombre,
                "email": u.email,
                "rol": u.rol.value
            }
            for u in usuarios
        ]
