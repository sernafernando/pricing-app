from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.exceptions import api_error, ErrorCode
from app.core.security import decode_token
from app.models.usuario import Usuario, RolUsuario

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Usuario:
    """Obtiene el usuario actual desde el token JWT"""
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise api_error(401, ErrorCode.INVALID_TOKEN, "Token inválido o expirado")
    
    username: str = payload.get("sub")
    if username is None:
        raise api_error(401, ErrorCode.INVALID_TOKEN, "Token inválido")
    
    # Buscar por username (nuevo) o email (backward compatibility)
    usuario = db.query(Usuario).filter(
        (Usuario.username == username) | (Usuario.email == username)
    ).first()
    
    if usuario is None:
        raise api_error(401, ErrorCode.INVALID_TOKEN, "Usuario no encontrado")
    
    if not usuario.activo:
        raise api_error(401, ErrorCode.INACTIVE_USER, "Usuario inactivo")
    
    return usuario

def require_role(allowed_roles: list[RolUsuario]):
    """Decorator para requerir roles específicos"""
    async def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if current_user.rol not in allowed_roles:
            raise api_error(403, ErrorCode.INSUFFICIENT_PERMISSIONS, "No tienes permisos para realizar esta acción")
        return current_user
    return role_checker

# Dependencias específicas por rol
async def get_current_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise api_error(403, ErrorCode.INSUFFICIENT_PERMISSIONS, "Solo administradores pueden realizar esta acción")
    return current_user

async def get_current_pricing_manager(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.PRICING_MANAGER]:
        raise api_error(403, ErrorCode.INSUFFICIENT_PERMISSIONS, "Necesitas permisos de pricing manager")
    return current_user


async def get_user_or_localhost(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: Session = Depends(get_db)
) -> Optional[Usuario]:
    """
    Permite acceso sin auth desde localhost (scripts internos/crons).
    Desde cualquier otra IP, requiere JWT válido.
    
    Retorna el Usuario autenticado o None si es localhost sin token.
    """
    client_ip = request.client.host if request.client else None
    
    if client_ip in LOCALHOST_IPS:
        # Localhost: si trae token lo validamos, si no, pasá igual
        if credentials:
            payload = decode_token(credentials.credentials)
            if payload:
                username: str = payload.get("sub")
                if username:
                    usuario = db.query(Usuario).filter(
                        (Usuario.username == username) | (Usuario.email == username)
                    ).first()
                    if usuario and usuario.activo:
                        return usuario
        return None
    
    # No es localhost: JWT obligatorio
    if not credentials:
        raise api_error(401, ErrorCode.MISSING_TOKEN, "Token requerido")
    
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise api_error(401, ErrorCode.INVALID_TOKEN, "Token inválido o expirado")
    
    username: str = payload.get("sub")
    if username is None:
        raise api_error(401, ErrorCode.INVALID_TOKEN, "Token inválido")
    
    usuario = db.query(Usuario).filter(
        (Usuario.username == username) | (Usuario.email == username)
    ).first()
    
    if usuario is None:
        raise api_error(401, ErrorCode.INVALID_TOKEN, "Usuario no encontrado")
    
    if not usuario.activo:
        raise api_error(401, ErrorCode.INACTIVE_USER, "Usuario inactivo")
    
    return usuario


async def get_admin_or_localhost(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: Session = Depends(get_db)
) -> Optional[Usuario]:
    """
    Permite acceso sin auth desde localhost (scripts internos/crons).
    Desde cualquier otra IP, requiere JWT válido con rol admin.
    
    Retorna el Usuario admin autenticado o None si es localhost sin token.
    """
    usuario = await get_user_or_localhost(request, credentials, db)
    
    # Localhost sin token: pasá
    if usuario is None:
        client_ip = request.client.host if request.client else None
        if client_ip in LOCALHOST_IPS:
            return None
        raise api_error(401, ErrorCode.MISSING_TOKEN, "Token requerido")
    
    # Con usuario: verificar que sea admin
    if usuario.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise api_error(403, ErrorCode.INSUFFICIENT_PERMISSIONS, "Solo administradores pueden realizar esta acción")
    
    return usuario
