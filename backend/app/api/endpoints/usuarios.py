from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.models.usuario import RolUsuario
from passlib.context import CryptContext

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UsuarioCreate(BaseModel):
    email: EmailStr
    nombre: str
    password: str
    rol: str = "AUDITOR"

class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = None  # ← AGREGAR ESTA LÍNEA
    activo: Optional[bool] = None
    rol: Optional[str] = None

class UsuarioResponse(BaseModel):
    id: int
    email: str
    nombre: str
    rol: str
    activo: bool
    
    class Config:
        from_attributes = True

@router.get("/usuarios", response_model=List[UsuarioResponse])
async def listar_usuarios(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los usuarios (solo admin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")
    
    usuarios = db.query(Usuario).all()
    return usuarios

@router.post("/usuarios", response_model=UsuarioResponse)
async def crear_usuario(
    usuario: UsuarioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo usuario (solo admin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")
    
    # Verificar si ya existe
    existe = db.query(Usuario).filter(Usuario.email == usuario.email).first()
    if existe:
        raise HTTPException(400, "El email ya está registrado")
    
    # Crear usuario
    nuevo_usuario = Usuario(
        email=usuario.email,
        nombre=usuario.nombre,
        password_hash=pwd_context.hash(usuario.password),
        rol=usuario.rol,
        auth_provider="local",
        activo=True
    )
    
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    
    return nuevo_usuario

@router.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse)
async def actualizar_usuario(
    usuario_id: int,
    datos: UsuarioUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza un usuario (solo admin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")
    
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")
    
    # PROTECCIÓN: Solo superadmin puede modificar a otro superadmin
    if usuario.rol.value == "SUPERADMIN" and current_user.rol.value != "SUPERADMIN":
        raise HTTPException(403, "No puedes modificar un superadministrador")
    
    # No permitir desactivarse a sí mismo
    if usuario.id == current_user.id and datos.activo == False:
        raise HTTPException(400, "No puedes desactivarte a ti mismo")
    
    # No permitir quitarse el rol de superadmin a sí mismo
    if usuario.id == current_user.id and usuario.rol.value == "SUPERADMIN" and current_user.rol.value != "SUPERADMIN":
        raise HTTPException(400, "No puedes quitarte el rol de superadmin")
    
    if datos.activo is not None:
        usuario.activo = datos.activo
    
    if datos.rol is not None:
        usuario.rol = datos.rol

    if datos.nombre is not None:  # ← AGREGAR ESTAS 2 LÍNEAS
        usuario.nombre = datos.nombre
    
    db.commit()
    db.refresh(usuario)
    
    return usuario

@router.delete("/usuarios/{usuario_id}")
async def eliminar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un usuario (solo admin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")
    
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")
    
    # PROTECCIÓN: No se puede eliminar un superadmin
    if usuario.rol == "SUPERADMIN":
        raise HTTPException(403, "No puedes eliminar un superadministrador")
    
    # No permitir eliminarse a sí mismo
    if usuario.id == current_user.id:
        raise HTTPException(400, "No puedes eliminarte a ti mismo")
    
    db.delete(usuario)
    db.commit()
    
    return {"message": "Usuario eliminado"}
