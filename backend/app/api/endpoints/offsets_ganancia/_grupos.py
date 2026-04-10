from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.services.permisos_service import verificar_permiso

from ._schemas import OffsetGrupoCreate, OffsetGrupoResponse

router = APIRouter()


@router.get("/offset-grupos", response_model=List[OffsetGrupoResponse])
def listar_grupos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Lista todos los grupos de offsets con sus filtros"""
    grupos = db.query(OffsetGrupo).order_by(OffsetGrupo.nombre).all()

    resultado = []
    for grupo in grupos:
        filtros_response = []
        for f in grupo.filtros:
            filtro_dict = {
                "id": f.id,
                "grupo_id": f.grupo_id,
                "marca": f.marca,
                "categoria": f.categoria,
                "subcategoria_id": f.subcategoria_id,
                "item_id": f.item_id,
                "producto_descripcion": f.producto.descripcion if f.producto else None,
            }
            filtros_response.append(filtro_dict)

        resultado.append(
            {"id": grupo.id, "nombre": grupo.nombre, "descripcion": grupo.descripcion, "filtros": filtros_response}
        )

    return resultado


@router.post("/offset-grupos")
def crear_grupo(
    grupo: OffsetGrupoCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo grupo de offsets con filtros opcionales"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    nuevo_grupo = OffsetGrupo(nombre=grupo.nombre, descripcion=grupo.descripcion, usuario_id=current_user.id)
    db.add(nuevo_grupo)
    db.flush()  # Para obtener el ID

    # Crear filtros si se enviaron
    filtros_creados = []
    if grupo.filtros:
        for filtro_data in grupo.filtros:
            # Validar que al menos un campo esté definido
            if not any([filtro_data.marca, filtro_data.categoria, filtro_data.subcategoria_id, filtro_data.item_id]):
                continue

            nuevo_filtro = OffsetGrupoFiltro(
                grupo_id=nuevo_grupo.id,
                marca=filtro_data.marca,
                categoria=filtro_data.categoria,
                subcategoria_id=filtro_data.subcategoria_id,
                item_id=filtro_data.item_id,
            )
            db.add(nuevo_filtro)
            filtros_creados.append(nuevo_filtro)

    db.commit()
    db.refresh(nuevo_grupo)

    # Construir respuesta
    filtros_response = []
    for f in nuevo_grupo.filtros:
        filtros_response.append(
            {
                "id": f.id,
                "grupo_id": f.grupo_id,
                "marca": f.marca,
                "categoria": f.categoria,
                "subcategoria_id": f.subcategoria_id,
                "item_id": f.item_id,
                "producto_descripcion": f.producto.descripcion if f.producto else None,
            }
        )

    return {
        "id": nuevo_grupo.id,
        "nombre": nuevo_grupo.nombre,
        "descripcion": nuevo_grupo.descripcion,
        "filtros": filtros_response,
    }


@router.delete("/offset-grupos/{grupo_id}")
def eliminar_grupo(grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Elimina un grupo de offsets (solo si no tiene offsets asociados)"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Verificar si tiene offsets asociados
    offsets_count = db.query(OffsetGanancia).filter(OffsetGanancia.grupo_id == grupo_id).count()
    if offsets_count > 0:
        raise HTTPException(400, f"No se puede eliminar el grupo, tiene {offsets_count} offsets asociados")

    # Los filtros se eliminan automáticamente por el cascade
    db.delete(grupo)
    db.commit()
    return {"mensaje": "Grupo eliminado"}
