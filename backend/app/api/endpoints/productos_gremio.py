"""
Productos - Gremio price override endpoints.

Handles manual gremio price overrides (set, delete individual, delete all).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


@router.patch("/productos/{item_id}/precio-gremio-override")
def set_precio_gremio_override(
    item_id: int,
    precio_sin_iva: float,
    precio_con_iva: float,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Establece un precio gremio manual que sobrescribe el cálculo automático.
    Requiere permiso 'tienda.editar_precio_gremio_manual'.
    """
    from app.models.precio_gremio_override import PrecioGremioOverride
    from app.services.permisos_service import verificar_permiso

    # Verificar permiso
    if not verificar_permiso(db, current_user, "tienda.editar_precio_gremio_manual"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar precios gremio manualmente")

    # Validar que el producto existe
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Buscar si ya existe un override
    override = db.query(PrecioGremioOverride).filter(PrecioGremioOverride.item_id == item_id).first()

    if override:
        # Actualizar existente
        override.precio_gremio_sin_iva_manual = precio_sin_iva
        override.precio_gremio_con_iva_manual = precio_con_iva
        override.updated_by_id = current_user.id
    else:
        # Crear nuevo
        override = PrecioGremioOverride(
            item_id=item_id,
            precio_gremio_sin_iva_manual=precio_sin_iva,
            precio_gremio_con_iva_manual=precio_con_iva,
            created_by_id=current_user.id,
            updated_by_id=current_user.id,
        )
        db.add(override)

    db.commit()
    db.refresh(override)

    return {
        "success": True,
        "item_id": item_id,
        "precio_gremio_sin_iva_manual": float(override.precio_gremio_sin_iva_manual),
        "precio_gremio_con_iva_manual": float(override.precio_gremio_con_iva_manual),
    }


@router.delete("/productos/{item_id}/precio-gremio-override")
def delete_precio_gremio_override(
    item_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina el precio gremio manual, volviendo al cálculo automático.
    Requiere permiso 'tienda.editar_precio_gremio_manual'.
    """
    from app.models.precio_gremio_override import PrecioGremioOverride
    from app.services.permisos_service import verificar_permiso

    # Verificar permiso
    if not verificar_permiso(db, current_user, "tienda.editar_precio_gremio_manual"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar precios gremio manualmente")

    # Buscar override
    override = db.query(PrecioGremioOverride).filter(PrecioGremioOverride.item_id == item_id).first()

    if not override:
        raise HTTPException(status_code=404, detail="No existe precio manual para este producto")

    db.delete(override)
    db.commit()

    return {"success": True, "message": "Precio manual eliminado, volviendo al cálculo automático"}


@router.delete("/productos/precio-gremio-override/todos")
def delete_all_precio_gremio_overrides(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina TODOS los precios gremio manuales, volviendo al cálculo automático.
    Requiere permiso 'tienda.editar_precio_gremio_manual'.
    """
    from app.models.precio_gremio_override import PrecioGremioOverride
    from app.services.permisos_service import verificar_permiso

    # Verificar permiso
    if not verificar_permiso(db, current_user, "tienda.editar_precio_gremio_manual"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar precios gremio manualmente")

    # Contar cuántos overrides hay
    count = db.query(PrecioGremioOverride).count()

    if count == 0:
        return {"success": True, "message": "No hay precios manuales para eliminar", "deleted_count": 0}

    # Eliminar todos los overrides
    db.query(PrecioGremioOverride).delete()
    db.commit()

    return {
        "success": True,
        "message": f"Se eliminaron {count} precios manuales. Todos volvieron al cálculo automático",
        "deleted_count": count,
    }
