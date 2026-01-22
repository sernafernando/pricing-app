"""
Endpoints para gestión de permisos
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.services.permisos_service import PermisosService, verificar_permiso

router = APIRouter(prefix="/permisos", tags=["permisos"])


# =============================================================================
# SCHEMAS
# =============================================================================

class PermisoResponse(BaseModel):
    codigo: str
    nombre: str
    descripcion: Optional[str]
    es_critico: bool

    model_config = ConfigDict(from_attributes=True)


class OverrideRequest(BaseModel):
    usuario_id: int
    permiso_codigo: str
    concedido: bool
    motivo: Optional[str] = None


class OverrideResponse(BaseModel):
    permiso_codigo: str
    permiso_nombre: str
    concedido: bool
    motivo: Optional[str]
    created_at: Optional[str]


class PermisoDetalladoResponse(BaseModel):
    codigo: str
    nombre: str
    descripcion: Optional[str]
    es_critico: bool
    tiene_por_rol: bool
    override: Optional[bool]
    efectivo: bool
    origen: str


class PermisosUsuarioResponse(BaseModel):
    usuario_id: int
    usuario_nombre: str
    rol: str
    permisos: List[str]
    permisos_detallados: dict


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/catalogo")
async def obtener_catalogo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene el catálogo completo de permisos agrupado por categoría.
    Útil para el panel de administración.
    """
    service = PermisosService(db)
    return service.obtener_catalogo_permisos()


@router.get("/mis-permisos")
async def obtener_mis_permisos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los permisos del usuario actual.
    Devuelve lista de códigos de permisos que el usuario tiene.
    """
    service = PermisosService(db)
    permisos = service.obtener_permisos_usuario(current_user)
    return {
        "usuario_id": current_user.id,
        "rol": current_user.rol_codigo,
        "rol_id": current_user.rol_id,
        "permisos": list(permisos)
    }


@router.get("/usuario/{usuario_id}")
async def obtener_permisos_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los permisos de un usuario específico con detalle.
    Requiere permiso admin.gestionar_permisos.
    """
    if not verificar_permiso(db, current_user, 'admin.gestionar_permisos'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver permisos de otros usuarios"
        )

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    service = PermisosService(db)
    permisos = service.obtener_permisos_usuario(usuario)
    permisos_detallados = service.obtener_permisos_detallados_usuario(usuario)

    return {
        "usuario_id": usuario.id,
        "usuario_nombre": usuario.nombre,
        "rol": usuario.rol_codigo,
        "rol_id": usuario.rol_id,
        "permisos": list(permisos),
        "permisos_detallados": permisos_detallados
    }


@router.get("/usuario/{usuario_id}/overrides")
async def obtener_overrides_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene solo los overrides de un usuario"""
    if not verificar_permiso(db, current_user, 'admin.gestionar_permisos'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver permisos de otros usuarios"
        )

    service = PermisosService(db)
    return service.obtener_overrides_usuario(usuario_id)


@router.post("/override")
async def crear_override(
    request: OverrideRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Crea o actualiza un override de permiso para un usuario.
    """
    if not verificar_permiso(db, current_user, 'admin.gestionar_permisos'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar permisos"
        )

    # Verificar que el usuario objetivo existe
    usuario_objetivo = db.query(Usuario).filter(Usuario.id == request.usuario_id).first()
    if not usuario_objetivo:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # No permitir modificar permisos de SUPERADMIN si no eres SUPERADMIN
    if usuario_objetivo.es_superadmin and not current_user.es_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes modificar permisos de un SUPERADMIN"
        )

    service = PermisosService(db)
    try:
        override = service.agregar_override(
            usuario_id=request.usuario_id,
            permiso_codigo=request.permiso_codigo,
            concedido=request.concedido,
            otorgado_por_id=current_user.id,
            motivo=request.motivo
        )
        return {
            "success": True,
            "message": f"Override {'agregado' if request.concedido else 'quitado'} correctamente",
            "permiso": request.permiso_codigo,
            "concedido": request.concedido
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/override/{usuario_id}/{permiso_codigo}")
async def eliminar_override(
    usuario_id: int,
    permiso_codigo: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina un override, volviendo el permiso a su estado base por rol.
    """
    if not verificar_permiso(db, current_user, 'admin.gestionar_permisos'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar permisos"
        )

    # Verificar que el usuario objetivo existe
    usuario_objetivo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario_objetivo:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # No permitir modificar permisos de SUPERADMIN si no eres SUPERADMIN
    if usuario_objetivo.es_superadmin and not current_user.es_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes modificar permisos de un SUPERADMIN"
        )

    service = PermisosService(db)
    eliminado = service.eliminar_override(usuario_id, permiso_codigo)

    if eliminado:
        return {"success": True, "message": "Override eliminado, permiso vuelve al estado base del rol"}
    else:
        return {"success": False, "message": "No existía override para este permiso"}


@router.get("/verificar/{permiso_codigo}")
async def verificar_mi_permiso(
    permiso_codigo: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Verifica si el usuario actual tiene un permiso específico.
    Útil para el frontend.
    """
    tiene = verificar_permiso(db, current_user, permiso_codigo)
    return {
        "permiso": permiso_codigo,
        "tiene": tiene
    }


@router.post("/verificar-multiples")
async def verificar_multiples_permisos(
    permisos: List[str],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Verifica múltiples permisos de una vez.
    Devuelve un diccionario con cada permiso y si el usuario lo tiene.
    """
    service = PermisosService(db)
    permisos_usuario = service.obtener_permisos_usuario(current_user)

    return {
        permiso: permiso in permisos_usuario
        for permiso in permisos
    }


@router.get("/roles/{rol_codigo}/permisos")
async def obtener_permisos_rol(
    rol_codigo: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene los permisos base de un rol por código"""
    from app.models.rol import Rol

    if not verificar_permiso(db, current_user, 'admin.gestionar_permisos'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver permisos de roles"
        )

    # Buscar rol por código
    rol = db.query(Rol).filter(Rol.codigo == rol_codigo).first()
    if not rol:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    permisos = db.query(Permiso).join(
        RolPermisoBase, RolPermisoBase.permiso_id == Permiso.id
    ).filter(
        RolPermisoBase.rol_id == rol.id
    ).order_by(Permiso.orden).all()

    return {
        "rol": rol_codigo,
        "rol_id": rol.id,
        "permisos": [
            {
                "codigo": p.codigo,
                "nombre": p.nombre,
                "descripcion": p.descripcion,
                "es_critico": p.es_critico
            }
            for p in permisos
        ]
    }
