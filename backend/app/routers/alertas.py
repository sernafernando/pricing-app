"""
Router para Sistema de Alertas
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.usuario import Usuario
from app.schemas.alerta import (
    AlertaCreate,
    AlertaUpdate,
    AlertaResponse,
    AlertaActivaResponse,
    ConfiguracionAlertaResponse,
    ConfiguracionAlertaUpdate,
)
from app.services.alertas_service import AlertasService
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/alertas", tags=["Alertas"])


def require_permission(permission: str):
    """Dependency para verificar permisos"""

    def _check_permission(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {permission}")
        return current_user

    return _check_permission


# =============================================================================
# ENDPOINTS PÚBLICOS (cualquier usuario autenticado)
# =============================================================================


@router.get("/activas", response_model=List[AlertaActivaResponse])
def obtener_alertas_activas(
    page: int = 1, page_size: int = 50, current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Obtiene las alertas activas para el usuario actual con paginación.
    El frontend se encarga de la rotación según max_alertas_visibles y duracion_segundos.
    Filtra por roles, usuarios específicos, vigencia y estado de cierre.
    Ordenadas por prioridad DESC (mayor prioridad primero).
    """
    service = AlertasService(db)
    offset = (page - 1) * page_size
    alertas = service.obtener_alertas_activas_para_usuario(current_user, limit=page_size, offset=offset)
    return alertas


@router.get("/configuracion", response_model=ConfiguracionAlertaResponse)
def obtener_configuracion_publica(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Obtiene la configuración global de alertas (solo lectura).
    Endpoint público para que el frontend conozca max_alertas_visibles.
    """
    service = AlertasService(db)
    config = service.obtener_configuracion()
    return config


@router.post("/{alerta_id}/cerrar", status_code=status.HTTP_204_NO_CONTENT)
def cerrar_alerta(alerta_id: int, current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Marca una alerta como cerrada para el usuario actual.
    """
    service = AlertasService(db)

    # Verificar que la alerta existe
    alerta = service.obtener_alerta(alerta_id)
    if not alerta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta no encontrada")

    service.marcar_alerta_cerrada(alerta_id, current_user.id)
    return None


# =============================================================================
# ENDPOINTS DE CONFIGURACIÓN (requieren permiso alertas.configurar)
# =============================================================================
# IMPORTANTE: Estas rutas DEBEN estar ANTES de /{alerta_id} para evitar colisiones


@router.get("/configuracion/global", response_model=ConfiguracionAlertaResponse)
def obtener_configuracion_admin(
    current_user: Usuario = Depends(require_permission("alertas.configurar")), db: Session = Depends(get_db)
):
    """
    Obtiene la configuración global de alertas (admin).
    Requiere permiso: alertas.configurar
    """
    service = AlertasService(db)
    config = service.obtener_configuracion()
    return config


@router.put("/configuracion/global", response_model=ConfiguracionAlertaResponse)
def actualizar_configuracion(
    config_data: ConfiguracionAlertaUpdate,
    current_user: Usuario = Depends(require_permission("alertas.configurar")),
    db: Session = Depends(get_db),
):
    """
    Actualiza la configuración global de alertas.
    Requiere permiso: alertas.configurar
    """
    service = AlertasService(db)
    config = service.actualizar_configuracion(
        max_alertas_visibles=config_data.max_alertas_visibles, updated_by_id=current_user.id
    )
    return config


# =============================================================================
# ENDPOINTS DE GESTIÓN (requieren permiso alertas.gestionar)
# =============================================================================


@router.get("", response_model=List[AlertaResponse])
def listar_alertas(
    activo: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: Usuario = Depends(require_permission("alertas.gestionar")),
    db: Session = Depends(get_db),
):
    """
    Lista todas las alertas del sistema (para panel admin).
    Requiere permiso: alertas.gestionar
    """
    service = AlertasService(db)
    alertas = service.listar_alertas(activo=activo, limit=limit, offset=offset)

    # Cargar relaciones de usuarios destinatarios
    for alerta in alertas:
        alerta.usuarios_destinatarios = [dest.usuario for dest in alerta.usuarios_destinatarios]

    return alertas


@router.get("/{alerta_id}", response_model=AlertaResponse)
def obtener_alerta(
    alerta_id: int,
    current_user: Usuario = Depends(require_permission("alertas.gestionar")),
    db: Session = Depends(get_db),
):
    """
    Obtiene una alerta por ID.
    Requiere permiso: alertas.gestionar
    """
    service = AlertasService(db)
    alerta = service.obtener_alerta(alerta_id)

    if not alerta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta no encontrada")

    # Cargar relaciones
    alerta.usuarios_destinatarios = [dest.usuario for dest in alerta.usuarios_destinatarios]

    return alerta


@router.post("", response_model=AlertaResponse, status_code=status.HTTP_201_CREATED)
def crear_alerta(
    alerta_data: AlertaCreate,
    current_user: Usuario = Depends(require_permission("alertas.gestionar")),
    db: Session = Depends(get_db),
):
    """
    Crea una nueva alerta.
    Requiere permiso: alertas.gestionar
    """
    service = AlertasService(db)

    alerta = service.crear_alerta(
        titulo=alerta_data.titulo,
        mensaje=alerta_data.mensaje,
        variant=alerta_data.variant,
        roles_destinatarios=alerta_data.roles_destinatarios,
        usuarios_destinatarios_ids=alerta_data.usuarios_destinatarios_ids,
        action_label=alerta_data.action_label,
        action_url=alerta_data.action_url,
        dismissible=alerta_data.dismissible,
        persistent=alerta_data.persistent,
        activo=alerta_data.activo,
        fecha_desde=alerta_data.fecha_desde,
        fecha_hasta=alerta_data.fecha_hasta,
        prioridad=alerta_data.prioridad,
        duracion_segundos=alerta_data.duracion_segundos,
        created_by_id=current_user.id,
    )

    # Cargar relaciones
    db.refresh(alerta)
    alerta.usuarios_destinatarios = [dest.usuario for dest in alerta.usuarios_destinatarios]

    return alerta


@router.put("/{alerta_id}", response_model=AlertaResponse)
def actualizar_alerta(
    alerta_id: int,
    alerta_data: AlertaUpdate,
    current_user: Usuario = Depends(require_permission("alertas.gestionar")),
    db: Session = Depends(get_db),
):
    """
    Actualiza una alerta existente.
    Requiere permiso: alertas.gestionar
    """
    service = AlertasService(db)

    alerta = service.actualizar_alerta(
        alerta_id=alerta_id,
        titulo=alerta_data.titulo,
        mensaje=alerta_data.mensaje,
        variant=alerta_data.variant,
        roles_destinatarios=alerta_data.roles_destinatarios,
        usuarios_destinatarios_ids=alerta_data.usuarios_destinatarios_ids,
        action_label=alerta_data.action_label,
        action_url=alerta_data.action_url,
        dismissible=alerta_data.dismissible,
        persistent=alerta_data.persistent,
        activo=alerta_data.activo,
        fecha_desde=alerta_data.fecha_desde,
        fecha_hasta=alerta_data.fecha_hasta,
        prioridad=alerta_data.prioridad,
        duracion_segundos=alerta_data.duracion_segundos,
    )

    if not alerta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta no encontrada")

    # Cargar relaciones
    alerta.usuarios_destinatarios = [dest.usuario for dest in alerta.usuarios_destinatarios]

    return alerta


@router.patch("/{alerta_id}/desactivar", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_alerta(
    alerta_id: int,
    current_user: Usuario = Depends(require_permission("alertas.gestionar")),
    db: Session = Depends(get_db),
):
    """
    Desactiva una alerta (soft delete: marca activo=False).
    Requiere permiso: alertas.gestionar

    Nota: Usamos PATCH en lugar de DELETE porque no eliminamos físicamente,
    solo cambiamos el estado activo. DELETE implica eliminación permanente.
    """
    service = AlertasService(db)

    success = service.eliminar_alerta(alerta_id)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta no encontrada")

    return None
