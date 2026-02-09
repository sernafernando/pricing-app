from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import timedelta

from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_token
from app.core.config import settings
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.models.rol import Rol
from app.api.deps import get_current_user

router = APIRouter()

class LoginRequest(BaseModel):
    username: str  # Acepta username o email
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    usuario: dict

class RefreshRequest(BaseModel):
    refresh_token: str

class RegisterRequest(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    password: str
    nombre: str

@router.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Login con username o email (detecta automáticamente por presencia de @)"""
    
    # Detectar si es email o username por la presencia de @
    if '@' in request.username:
        # Es un email
        usuario = db.query(Usuario).filter(Usuario.email == request.username).first()
    else:
        # Es un username
        usuario = db.query(Usuario).filter(Usuario.username == request.username).first()
    
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )
    
    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo"
        )
    
    if not verify_password(request.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )
    
    # Crear tokens (access + refresh) usando username
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_data = {"sub": usuario.username}
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires,
    )
    refresh_token = create_refresh_token(data=token_data)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        usuario={
            "id": usuario.id,
            "username": usuario.username,
            "email": usuario.email,
            "nombre": usuario.nombre,
            "rol": usuario.rol_codigo  # Usar property en lugar del enum
        }
    )

@router.post("/auth/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """
    Registrar nuevo usuario.
    NOTA: Este endpoint requiere un token de invitación en producción.
    TODO: Implementar sistema de invitaciones.
    """
    # SEGURIDAD: En producción, este endpoint debería estar deshabilitado
    # o requerir un token de invitación. Por ahora se deshabilita.
    import os
    if os.getenv("ENVIRONMENT", "production") == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registro público deshabilitado. Contacta al administrador."
        )
    
    # Verificar que no exista username
    existing = db.query(Usuario).filter(Usuario.username == request.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username ya registrado"
        )
    
    # Verificar email si fue proporcionado
    if request.email:
        existing_email = db.query(Usuario).filter(Usuario.email == request.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email ya registrado"
            )
    
    # Buscar el rol VENTAS por defecto para nuevos registros
    rol_default = db.query(Rol).filter(Rol.codigo == "VENTAS").first()
    if not rol_default:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error de configuración: rol VENTAS no existe"
        )

    # Crear usuario
    nuevo_usuario = Usuario(
        username=request.username,
        email=request.email,
        nombre=request.nombre,
        password_hash=get_password_hash(request.password),
        rol=None,  # Deprecado, usar rol_id
        rol_id=rol_default.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True
    )
    
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    
    return {
        "message": "Usuario creado exitosamente",
        "usuario": {
            "id": nuevo_usuario.id,
            "username": nuevo_usuario.username,
            "email": nuevo_usuario.email,
            "nombre": nuevo_usuario.nombre,
            "rol": nuevo_usuario.rol_codigo  # Usar property en lugar del enum
        }
    }

@router.get("/auth/me")
async def get_me(current_user: Usuario = Depends(get_current_user)):
    """Obtiene información del usuario actual"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "nombre": current_user.nombre,
        "rol": current_user.rol_codigo,  # Usar property en lugar del enum
        "activo": current_user.activo
    }

@router.post("/auth/refresh")
async def refresh_access_token(request: RefreshRequest, db: Session = Depends(get_db)):
    """
    Renueva el access_token usando un refresh_token válido.
    Devuelve un nuevo access_token (el refresh_token sigue siendo el mismo hasta que expire).
    """
    payload = decode_token(request.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado"
        )
    
    # Verificar que sea un refresh token (no un access token reutilizado)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no es un refresh token"
        )
    
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido"
        )
    
    # Verificar que el usuario siga existiendo y activo
    usuario = db.query(Usuario).filter(
        (Usuario.username == username) | (Usuario.email == username)
    ).first()
    
    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo"
        )
    
    # Generar nuevo access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = create_access_token(
        data={"sub": usuario.username},
        expires_delta=access_token_expires,
    )
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }
