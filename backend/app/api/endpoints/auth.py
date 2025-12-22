from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import timedelta

from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
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
    token_type: str
    usuario: dict

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
    
    # Crear token usando username (no email)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": usuario.username,  # Ahora usamos username en el token
            "rol": usuario.rol.value
        },
        expires_delta=access_token_expires
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        usuario={
            "id": usuario.id,
            "username": usuario.username,
            "email": usuario.email,
            "nombre": usuario.nombre,
            "rol": usuario.rol.value
        }
    )

@router.post("/auth/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Registrar nuevo usuario (solo para desarrollo - en producción usar invitaciones)"""
    
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
        rol=RolUsuario.VENTAS,  # Por defecto ventas
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
            "rol": nuevo_usuario.rol.value
        }
    }

@router.get("/auth/me")
async def get_me(current_user: Usuario = Depends(get_current_user)):
    """Obtiene información del usuario actual"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "nombre": current_user.nombre,
        "rol": current_user.rol.value,
        "activo": current_user.activo
    }
