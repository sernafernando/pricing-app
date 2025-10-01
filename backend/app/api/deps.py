from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import decode_token
from app.models.usuario import Usuario, RolUsuario

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Usuario:
    """Obtiene el usuario actual desde el token JWT"""
    
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado"
        )
    
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado"
        )
    
    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo"
        )
    
    return usuario

def require_role(allowed_roles: list[RolUsuario]):
    """Decorator para requerir roles específicos"""
    async def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if current_user.rol not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para realizar esta acción"
            )
        return current_user
    return role_checker

# Dependencias específicas por rol
async def get_current_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.rol != RolUsuario.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden realizar esta acción"
        )
    return current_user

async def get_current_pricing_manager(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.PRICING_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Necesitas permisos de pricing manager"
        )
    return current_user
