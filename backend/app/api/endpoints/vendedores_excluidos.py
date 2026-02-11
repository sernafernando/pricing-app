"""
Endpoints para gestionar vendedores excluidos de los reportes de ventas por fuera de ML
Solo accesible por administradores
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.core.database import get_db
from app.models.vendedor_excluido import VendedorExcluido
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


# ============================================================================
# Schemas
# ============================================================================


class VendedorExcluidoCreate(BaseModel):
    sm_id: int
    sm_name: Optional[str] = None
    motivo: Optional[str] = None


class VendedorExcluidoResponse(BaseModel):
    id: int
    sm_id: int
    sm_name: Optional[str]
    motivo: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VendedorDisponible(BaseModel):
    sm_id: int
    sm_name: str
    bra_id: Optional[int] = None
    ya_excluido: bool = False


# ============================================================================
# Helpers
# ============================================================================


def verificar_admin(current_user: Usuario):
    """Verifica que el usuario sea admin o superadmin"""
    if current_user.rol not in ["ADMIN", "SUPERADMIN"]:
        raise HTTPException(status_code=403, detail="Solo los administradores pueden gestionar vendedores excluidos")


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/vendedores-excluidos", response_model=List[VendedorExcluidoResponse])
async def listar_vendedores_excluidos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Lista todos los vendedores excluidos"""
    verificar_admin(current_user)

    vendedores = db.query(VendedorExcluido).order_by(VendedorExcluido.sm_name).all()
    return vendedores


@router.get("/vendedores-excluidos/disponibles", response_model=List[VendedorDisponible])
async def listar_vendedores_disponibles(
    buscar: Optional[str] = Query(None, description="Buscar por nombre"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista vendedores disponibles del ERP para excluir.
    Incluye vendedores activos y también los que aparecen en ventas por fuera de ML.
    """
    verificar_admin(current_user)

    # Obtener IDs ya excluidos
    excluidos = db.query(VendedorExcluido.sm_id).all()
    excluidos_ids = {e.sm_id for e in excluidos}

    # Traer TODOS los vendedores (habilitados y deshabilitados)
    query = """
    SELECT sm_id, sm_name, bra_id
    FROM tb_salesman
    WHERE sm_name IS NOT NULL
    """

    params = {}
    if buscar:
        query += " AND sm_name ILIKE :buscar"
        params["buscar"] = f"%{buscar}%"

    query += " ORDER BY sm_name LIMIT 100"

    result = db.execute(text(query), params).fetchall()

    return [
        VendedorDisponible(
            sm_id=r.sm_id,
            sm_name=r.sm_name or f"Vendedor {r.sm_id}",
            bra_id=r.bra_id,
            ya_excluido=r.sm_id in excluidos_ids,
        )
        for r in result
    ]


@router.post("/vendedores-excluidos", response_model=VendedorExcluidoResponse)
async def agregar_vendedor_excluido(
    vendedor: VendedorExcluidoCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Agrega un vendedor a la lista de excluidos"""
    verificar_admin(current_user)

    # Verificar que no esté ya excluido
    existente = db.query(VendedorExcluido).filter(VendedorExcluido.sm_id == vendedor.sm_id).first()

    if existente:
        raise HTTPException(status_code=400, detail="Este vendedor ya está en la lista de excluidos")

    # Si no viene el nombre, buscarlo en el ERP
    sm_name = vendedor.sm_name
    if not sm_name:
        result = db.execute(
            text("SELECT sm_name FROM tb_salesman WHERE sm_id = :sm_id"), {"sm_id": vendedor.sm_id}
        ).fetchone()
        if result:
            sm_name = result.sm_name

    nuevo = VendedorExcluido(sm_id=vendedor.sm_id, sm_name=sm_name, motivo=vendedor.motivo, creado_por=current_user.id)

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo


@router.delete("/vendedores-excluidos/{sm_id}")
async def eliminar_vendedor_excluido(
    sm_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Elimina un vendedor de la lista de excluidos"""
    verificar_admin(current_user)

    vendedor = db.query(VendedorExcluido).filter(VendedorExcluido.sm_id == sm_id).first()

    if not vendedor:
        raise HTTPException(status_code=404, detail="Vendedor no encontrado en la lista de excluidos")

    db.delete(vendedor)
    db.commit()

    return {"message": f"Vendedor {sm_id} eliminado de la lista de excluidos"}


@router.get("/vendedores-excluidos/ids")
async def obtener_ids_excluidos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene solo los IDs de vendedores excluidos (para uso interno)"""
    vendedores = db.query(VendedorExcluido.sm_id).all()
    return [v.sm_id for v in vendedores]
