"""
Endpoints para gestión de items sin MLA asociado
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.producto import ProductoERP
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.item_sin_mla_banlist import ItemSinMLABanlist
from app.models.usuario import Usuario

router = APIRouter()

# Mapeo de IDs de listas a nombres
LISTAS_PRECIOS = {
    4: "Clásica",
    17: "Web 3 Cuotas",
    14: "Web 6 Cuotas",
    13: "Web 9 Cuotas",
    23: "Web 12 Cuotas"
}

# Schemas
class ItemSinMLAResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: str
    categoria: Optional[str]
    stock: int
    listas_sin_mla: List[str]  # Lista de nombres de listas donde NO tiene MLA
    listas_con_mla: List[str]  # Lista de nombres de listas donde SÍ tiene MLA

    class Config:
        from_attributes = True

class ItemBaneadoResponse(BaseModel):
    id: int
    item_id: int
    codigo: str
    descripcion: str
    marca: str
    motivo: Optional[str]
    usuario_nombre: str
    fecha_creacion: str

    class Config:
        from_attributes = True

class BanItemRequest(BaseModel):
    item_id: int
    motivo: Optional[str] = None

class UnbanItemRequest(BaseModel):
    banlist_id: int


@router.get("/items-sin-mla", response_model=List[ItemSinMLAResponse])
async def get_items_sin_mla(
    prli_id: Optional[int] = Query(None, description="Filtrar por lista de precios específica"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    buscar: Optional[str] = Query(None, description="Buscar en código o descripción"),
    con_stock: Optional[bool] = Query(None, description="Filtrar solo items con stock"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene todos los productos que NO tienen MLA en las listas relevantes (Clásica, Web 3, 6, 9, 12),
    excluyendo los que están en la banlist.
    """

    # IDs de las listas relevantes
    listas_relevantes = list(LISTAS_PRECIOS.keys())

    # Subquery: items en banlist
    items_baneados_subq = db.query(
        ItemSinMLABanlist.item_id
    ).subquery()

    # Query principal: productos activos y no baneados
    query = db.query(ProductoERP).filter(
        and_(
            ProductoERP.activo == True,
            ProductoERP.item_id.notin_(items_baneados_subq)
        )
    )

    # Aplicar filtros opcionales
    if marca:
        query = query.filter(ProductoERP.marca == marca)

    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)

    if buscar:
        search_term = f"%{buscar}%"
        query = query.filter(
            or_(
                ProductoERP.codigo.ilike(search_term),
                ProductoERP.descripcion.ilike(search_term)
            )
        )

    if con_stock is not None:
        if con_stock:
            query = query.filter(ProductoERP.stock > 0)
        else:
            query = query.filter(ProductoERP.stock == 0)

    productos = query.order_by(ProductoERP.descripcion).limit(500).all()

    # Para cada producto, determinar en qué listas NO tiene MLA
    resultados = []
    for producto in productos:
        # Obtener todas las listas RELEVANTES donde este item tiene publicación
        listas_con_mla = db.query(MercadoLibreItemPublicado.prli_id).distinct().filter(
            and_(
                MercadoLibreItemPublicado.item_id == producto.item_id,
                MercadoLibreItemPublicado.prli_id.in_(listas_relevantes)
            )
        ).all()

        listas_con_mla_ids = [l[0] for l in listas_con_mla if l[0] is not None]

        # Determinar listas donde NO está
        listas_sin_mla_ids = [lid for lid in listas_relevantes if lid not in listas_con_mla_ids]

        # Si no le falta ninguna lista, no lo incluimos en los resultados
        if not listas_sin_mla_ids:
            continue

        # Si se filtra por prli_id específico, verificar que le falte esa lista
        if prli_id and prli_id not in listas_sin_mla_ids:
            continue

        # Convertir IDs a nombres
        listas_sin_mla_nombres = [LISTAS_PRECIOS[lid] for lid in listas_sin_mla_ids]
        listas_con_mla_nombres = [LISTAS_PRECIOS[lid] for lid in listas_con_mla_ids]

        resultados.append(ItemSinMLAResponse(
            item_id=producto.item_id,
            codigo=producto.codigo or "",
            descripcion=producto.descripcion or "",
            marca=producto.marca or "",
            categoria=producto.categoria,
            stock=producto.stock or 0,
            listas_sin_mla=listas_sin_mla_nombres,
            listas_con_mla=listas_con_mla_nombres
        ))

    return resultados


@router.get("/items-baneados", response_model=List[ItemBaneadoResponse])
async def get_items_baneados(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene todos los items en la banlist (que no deben aparecer en el reporte de sin MLA)
    """

    baneados = db.query(
        ItemSinMLABanlist,
        ProductoERP,
        Usuario
    ).join(
        ProductoERP, ProductoERP.item_id == ItemSinMLABanlist.item_id
    ).join(
        Usuario, Usuario.id == ItemSinMLABanlist.usuario_id
    ).order_by(ItemSinMLABanlist.fecha_creacion.desc()).all()

    resultados = []
    for banlist_entry, producto, usuario in baneados:
        resultados.append(ItemBaneadoResponse(
            id=banlist_entry.id,
            item_id=producto.item_id,
            codigo=producto.codigo or "",
            descripcion=producto.descripcion or "",
            marca=producto.marca or "",
            motivo=banlist_entry.motivo,
            usuario_nombre=usuario.nombre,
            fecha_creacion=banlist_entry.fecha_creacion.isoformat()
        ))

    return resultados


@router.post("/banear-item")
async def banear_item(
    request: BanItemRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Agrega un item a la banlist para que no aparezca en el reporte de items sin MLA
    """

    # Verificar que el item existe
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == request.item_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Verificar que no esté ya baneado
    existente = db.query(ItemSinMLABanlist).filter(
        ItemSinMLABanlist.item_id == request.item_id
    ).first()

    if existente:
        raise HTTPException(status_code=400, detail="El item ya está en la banlist")

    # Crear entrada en banlist
    nuevo_ban = ItemSinMLABanlist(
        item_id=request.item_id,
        motivo=request.motivo,
        usuario_id=current_user.id
    )

    db.add(nuevo_ban)
    db.commit()
    db.refresh(nuevo_ban)

    return {
        "success": True,
        "message": f"Item {request.item_id} agregado a la banlist",
        "banlist_id": nuevo_ban.id
    }


@router.post("/desbanear-item")
async def desbanear_item(
    request: UnbanItemRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Quita un item de la banlist
    """

    # Buscar la entrada en banlist
    ban_entry = db.query(ItemSinMLABanlist).filter(
        ItemSinMLABanlist.id == request.banlist_id
    ).first()

    if not ban_entry:
        raise HTTPException(status_code=404, detail="Entrada de banlist no encontrada")

    item_id = ban_entry.item_id

    # Eliminar de banlist
    db.delete(ban_entry)
    db.commit()

    return {
        "success": True,
        "message": f"Item {item_id} removido de la banlist"
    }


@router.get("/listas-precios")
async def get_listas_precios(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las listas de precios relevantes (Clásica, Web 3, 6, 9, 12)
    """

    return [
        {"prli_id": prli_id, "nombre": nombre}
        for prli_id, nombre in LISTAS_PRECIOS.items()
    ]


@router.get("/marcas")
async def get_marcas_sin_mla(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las marcas de productos sin MLA (para filtros)
    """

    # Items con MLA
    items_con_mla_subq = db.query(
        MercadoLibreItemPublicado.item_id
    ).distinct().filter(
        MercadoLibreItemPublicado.item_id.isnot(None)
    ).subquery()

    # Items baneados
    items_baneados_subq = db.query(
        ItemSinMLABanlist.item_id
    ).subquery()

    # Marcas de productos sin MLA y no baneados
    marcas = db.query(
        ProductoERP.marca
    ).distinct().filter(
        and_(
            ProductoERP.activo == True,
            ProductoERP.marca.isnot(None),
            ProductoERP.item_id.notin_(items_con_mla_subq),
            ProductoERP.item_id.notin_(items_baneados_subq)
        )
    ).order_by(ProductoERP.marca).all()

    return [{"marca": m[0]} for m in marcas if m[0]]
