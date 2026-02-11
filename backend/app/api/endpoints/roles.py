"""
Endpoints para gestión de roles
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.services.roles_service import RolesService
from app.services.permisos_service import verificar_permiso

router = APIRouter(prefix="/roles", tags=["roles"])


# =============================================================================
# SCHEMAS
# =============================================================================


class RolBase(BaseModel):
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    orden: int = 0


class RolCreate(BaseModel):
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    orden: int = 0


class RolUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None


class RolResponse(BaseModel):
    id: int
    codigo: str
    nombre: str
    descripcion: Optional[str]
    es_sistema: bool
    orden: int
    activo: bool
    usuarios_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class RolConPermisosResponse(RolResponse):
    permisos: List[str]


class SetPermisosRequest(BaseModel):
    permisos: List[str]


class ClonarRolRequest(BaseModel):
    nuevo_codigo: str
    nuevo_nombre: str
    descripcion: Optional[str] = None


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=List[RolResponse])
async def listar_roles(
    incluir_inactivos: bool = False, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los roles del sistema"""
    if not verificar_permiso(db, current_user, "admin.ver_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para ver roles")

    service = RolesService(db)
    roles = service.listar_roles(incluir_inactivos=incluir_inactivos)

    return [
        RolResponse(
            id=rol.id,
            codigo=rol.codigo,
            nombre=rol.nombre,
            descripcion=rol.descripcion,
            es_sistema=rol.es_sistema,
            orden=rol.orden,
            activo=rol.activo,
            usuarios_count=service.contar_usuarios_rol(rol.id),
        )
        for rol in roles
    ]


@router.get("/{rol_id}", response_model=RolConPermisosResponse)
async def obtener_rol(rol_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene un rol con sus permisos"""
    if not verificar_permiso(db, current_user, "admin.ver_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para ver roles")

    service = RolesService(db)
    rol = service.obtener_rol(rol_id)

    if not rol:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    permisos = service.obtener_permisos_rol(rol_id)

    return RolConPermisosResponse(
        id=rol.id,
        codigo=rol.codigo,
        nombre=rol.nombre,
        descripcion=rol.descripcion,
        es_sistema=rol.es_sistema,
        orden=rol.orden,
        activo=rol.activo,
        usuarios_count=service.contar_usuarios_rol(rol.id),
        permisos=permisos,
    )


@router.post("", response_model=RolResponse)
async def crear_rol(
    request: RolCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo rol"""
    if not verificar_permiso(db, current_user, "admin.gestionar_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar roles")

    service = RolesService(db)

    try:
        rol = service.crear_rol(
            codigo=request.codigo, nombre=request.nombre, descripcion=request.descripcion, orden=request.orden
        )
        return RolResponse(
            id=rol.id,
            codigo=rol.codigo,
            nombre=rol.nombre,
            descripcion=rol.descripcion,
            es_sistema=rol.es_sistema,
            orden=rol.orden,
            activo=rol.activo,
            usuarios_count=0,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{rol_id}", response_model=RolResponse)
async def actualizar_rol(
    rol_id: int, request: RolUpdate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza un rol existente"""
    if not verificar_permiso(db, current_user, "admin.gestionar_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar roles")

    service = RolesService(db)
    rol = service.actualizar_rol(
        rol_id=rol_id,
        nombre=request.nombre,
        descripcion=request.descripcion,
        orden=request.orden,
        activo=request.activo,
    )

    if not rol:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    return RolResponse(
        id=rol.id,
        codigo=rol.codigo,
        nombre=rol.nombre,
        descripcion=rol.descripcion,
        es_sistema=rol.es_sistema,
        orden=rol.orden,
        activo=rol.activo,
        usuarios_count=service.contar_usuarios_rol(rol.id),
    )


@router.delete("/{rol_id}")
async def eliminar_rol(rol_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Elimina un rol (si no es de sistema y no tiene usuarios)"""
    if not verificar_permiso(db, current_user, "admin.gestionar_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar roles")

    service = RolesService(db)

    try:
        eliminado = service.eliminar_rol(rol_id)
        if eliminado:
            return {"success": True, "message": "Rol eliminado correctamente"}
        else:
            raise HTTPException(status_code=404, detail="Rol no encontrado")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# PERMISOS DEL ROL
# =============================================================================


@router.get("/{rol_id}/permisos")
async def obtener_permisos_rol(
    rol_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene los permisos de un rol con detalles"""
    if not verificar_permiso(db, current_user, "admin.ver_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para ver roles")

    service = RolesService(db)
    rol = service.obtener_rol(rol_id)

    if not rol:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    permisos = service.obtener_permisos_rol_detallados(rol_id)

    return {"rol_id": rol_id, "rol_codigo": rol.codigo, "permisos": permisos}


@router.put("/{rol_id}/permisos")
async def set_permisos_rol(
    rol_id: int,
    request: SetPermisosRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Establece los permisos de un rol (reemplaza todos)"""
    if not verificar_permiso(db, current_user, "admin.gestionar_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar roles")

    service = RolesService(db)

    try:
        cantidad = service.set_permisos_rol(rol_id, request.permisos)
        return {"success": True, "message": f"Se asignaron {cantidad} permisos al rol", "permisos_asignados": cantidad}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# CLONAR ROL
# =============================================================================


@router.post("/{rol_id}/clonar", response_model=RolResponse)
async def clonar_rol(
    rol_id: int,
    request: ClonarRolRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Clona un rol existente con sus permisos"""
    if not verificar_permiso(db, current_user, "admin.gestionar_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar roles")

    service = RolesService(db)

    try:
        nuevo_rol = service.clonar_rol(
            rol_origen_id=rol_id,
            nuevo_codigo=request.nuevo_codigo,
            nuevo_nombre=request.nuevo_nombre,
            descripcion=request.descripcion,
        )
        return RolResponse(
            id=nuevo_rol.id,
            codigo=nuevo_rol.codigo,
            nombre=nuevo_rol.nombre,
            descripcion=nuevo_rol.descripcion,
            es_sistema=nuevo_rol.es_sistema,
            orden=nuevo_rol.orden,
            activo=nuevo_rol.activo,
            usuarios_count=0,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# USUARIOS DEL ROL
# =============================================================================


@router.get("/{rol_id}/usuarios")
async def obtener_usuarios_rol(
    rol_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene los usuarios que tienen un rol específico"""
    if not verificar_permiso(db, current_user, "admin.ver_roles"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para ver roles")

    service = RolesService(db)
    rol = service.obtener_rol(rol_id)

    if not rol:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    usuarios = service.obtener_usuarios_rol(rol_id)

    return {"rol_id": rol_id, "rol_codigo": rol.codigo, "usuarios": usuarios}
