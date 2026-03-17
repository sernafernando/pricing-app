"""
Router para Sistema de Document Templates
CRUD de templates + endpoint de variables por contexto.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.usuario import Usuario
from app.schemas.document_template import (
    DocumentTemplateCreate,
    DocumentTemplateUpdate,
    DocumentTemplateResponse,
    DocumentTemplateListResponse,
    ContextVariablesResponse,
)
from app.services.document_template_service import (
    DocumentTemplateService,
    obtener_variables_contexto,
    obtener_contextos_disponibles,
)
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/document-templates", tags=["Document Templates"])


def require_permission(permission: str):
    """Dependency para verificar permisos"""

    def _check_permission(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes permiso: {permission}",
            )
        return current_user

    return _check_permission


# =============================================================================
# ENDPOINTS DE CONSULTA (requieren documentos.imprimir)
# =============================================================================


@router.get("/contextos", response_model=List[str])
def listar_contextos(
    current_user: Usuario = Depends(get_current_user),
) -> List[str]:
    """
    Lista los contextos disponibles para templates de documentos.
    Cualquier usuario autenticado puede consultar.
    """
    return obtener_contextos_disponibles()


@router.get("/variables/{contexto}", response_model=ContextVariablesResponse)
def obtener_variables(
    contexto: str,
    current_user: Usuario = Depends(get_current_user),
) -> ContextVariablesResponse:
    """
    Obtiene las variables disponibles para un contexto dado.
    Usado por el Designer para mostrar las variables arrastrables.
    """
    variables = obtener_variables_contexto(contexto)
    if variables is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contexto no encontrado: '{contexto}'. Disponibles: {obtener_contextos_disponibles()}",
        )
    return ContextVariablesResponse(contexto=contexto, variables=variables)


@router.get("", response_model=List[DocumentTemplateListResponse])
def listar_templates(
    contexto: Optional[str] = None,
    activo: Optional[bool] = True,
    limit: int = 100,
    offset: int = 0,
    current_user: Usuario = Depends(require_permission("documentos.imprimir")),
    db: Session = Depends(get_db),
) -> List[DocumentTemplateListResponse]:
    """
    Lista templates con filtros opcionales.
    Por defecto retorna solo activos.
    Requiere permiso: documentos.imprimir
    """
    service = DocumentTemplateService(db)
    return service.listar_templates(
        contexto=contexto,
        activo=activo,
        limit=limit,
        offset=offset,
    )


@router.get("/{template_id}", response_model=DocumentTemplateResponse)
def obtener_template(
    template_id: int,
    current_user: Usuario = Depends(require_permission("documentos.imprimir")),
    db: Session = Depends(get_db),
) -> DocumentTemplateResponse:
    """
    Obtiene un template por ID (incluye template_json completo).
    Requiere permiso: documentos.imprimir
    """
    service = DocumentTemplateService(db)
    template = service.obtener_template(template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template no encontrado",
        )
    return template


# =============================================================================
# ENDPOINTS DE GESTIÓN (requieren documentos.disenar)
# =============================================================================


@router.post("", response_model=DocumentTemplateResponse, status_code=status.HTTP_201_CREATED)
def crear_template(
    data: DocumentTemplateCreate,
    current_user: Usuario = Depends(require_permission("documentos.disenar")),
    db: Session = Depends(get_db),
) -> DocumentTemplateResponse:
    """
    Crea un nuevo template de documento.
    Requiere permiso: documentos.disenar
    """
    service = DocumentTemplateService(db)
    template = service.crear_template(
        nombre=data.nombre,
        descripcion=data.descripcion,
        contexto=data.contexto,
        template_json=data.template_json,
        creado_por_id=current_user.id,
    )
    return template


@router.put("/{template_id}", response_model=DocumentTemplateResponse)
def actualizar_template(
    template_id: int,
    data: DocumentTemplateUpdate,
    current_user: Usuario = Depends(require_permission("documentos.disenar")),
    db: Session = Depends(get_db),
) -> DocumentTemplateResponse:
    """
    Actualiza un template existente.
    Requiere permiso: documentos.disenar
    """
    service = DocumentTemplateService(db)
    template = service.obtener_template(template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template no encontrado",
        )

    updated = service.actualizar_template(
        template=template,
        actualizado_por_id=current_user.id,
        nombre=data.nombre,
        descripcion=data.descripcion,
        contexto=data.contexto,
        template_json=data.template_json,
        activo=data.activo,
    )
    return updated


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_template(
    template_id: int,
    current_user: Usuario = Depends(require_permission("documentos.disenar")),
    db: Session = Depends(get_db),
) -> None:
    """
    Soft-delete: marca el template como inactivo.
    Requiere permiso: documentos.disenar
    """
    service = DocumentTemplateService(db)
    template = service.obtener_template(template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template no encontrado",
        )

    service.soft_delete_template(
        template=template,
        actualizado_por_id=current_user.id,
    )
    return None
