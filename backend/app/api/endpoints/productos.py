from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from typing import Optional, List
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

# Schemas de respuesta
class ProductoResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    moneda_costo: Optional[str]
    costo: float
    costo_ars: Optional[float]  # Calculado con TC
    iva: float
    stock: int
    estado: Optional[str]
    mla: Optional[str]
    
    # Pricing
    precio_lista_ml: Optional[float]
    usuario_modifico: Optional[str]
    fecha_modificacion: Optional[datetime]
    
    # Estado del producto
    tiene_precio: bool
    necesita_revision: bool
    
    class Config:
        from_attributes = True

class ProductoListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    productos: List[ProductoResponse]

@router.get("/productos", response_model=ProductoListResponse)
async def listar_productos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marca: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Lista productos con filtros y paginación"""
    
    # Query base con join
    query = db.query(
        ProductoERP,
        ProductoPricing
    ).outerjoin(
        ProductoPricing,
        ProductoERP.item_id == ProductoPricing.item_id
    )
    
    # Aplicar filtros
    if search:
        search_filter = or_(
            ProductoERP.descripcion.ilike(f"%{search}%"),
            ProductoERP.codigo.ilike(f"%{search}%"),
            ProductoERP.mla.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)
    
    if marca:
        query = query.filter(ProductoERP.marca == marca)
    
    if con_stock is not None:
        if con_stock:
            query = query.filter(ProductoERP.stock > 0)
        else:
            query = query.filter(ProductoERP.stock == 0)
    
    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(ProductoPricing.precio_lista_ml.is_(None))
    
    if estado:
        query = query.filter(ProductoERP.estado == estado)
    
    # Total de resultados
    total = query.count()
    
    # Paginación
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    # Construir respuesta
    productos = []
    for producto_erp, producto_pricing in results:
        # TODO: Calcular costo en ARS según TC del día
        costo_ars = producto_erp.costo if producto_erp.moneda_costo == "ARS" else None
        
        productos.append(ProductoResponse(
            item_id=producto_erp.item_id,
            codigo=producto_erp.codigo,
            descripcion=producto_erp.descripcion,
            marca=producto_erp.marca,
            categoria=producto_erp.categoria,
            subcategoria_id=producto_erp.subcategoria_id,
            moneda_costo=producto_erp.moneda_costo,
            costo=producto_erp.costo,
            costo_ars=costo_ars,
            iva=producto_erp.iva,
            stock=producto_erp.stock,
            estado=producto_erp.estado,
            mla=producto_erp.mla,
            precio_lista_ml=producto_pricing.precio_lista_ml if producto_pricing else None,
            usuario_modifico=None,  # TODO: Join con usuario
            fecha_modificacion=producto_pricing.fecha_modificacion if producto_pricing else None,
            tiene_precio=producto_pricing.precio_lista_ml is not None if producto_pricing else False,
            necesita_revision=False  # TODO: Lógica de revisión
        ))
    
    return ProductoListResponse(
        total=total,
        page=page,
        page_size=page_size,
        productos=productos
    )

@router.get("/productos/{item_id}", response_model=ProductoResponse)
async def obtener_producto(
    item_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene un producto específico por ID"""
    
    result = db.query(
        ProductoERP,
        ProductoPricing
    ).outerjoin(
        ProductoPricing,
        ProductoERP.item_id == ProductoPricing.item_id
    ).filter(
        ProductoERP.item_id == item_id
    ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    producto_erp, producto_pricing = result
    
    costo_ars = producto_erp.costo if producto_erp.moneda_costo == "ARS" else None
    
    return ProductoResponse(
        item_id=producto_erp.item_id,
        codigo=producto_erp.codigo,
        descripcion=producto_erp.descripcion,
        marca=producto_erp.marca,
        categoria=producto_erp.categoria,
        subcategoria_id=producto_erp.subcategoria_id,
        moneda_costo=producto_erp.moneda_costo,
        costo=producto_erp.costo,
        costo_ars=costo_ars,
        iva=producto_erp.iva,
        stock=producto_erp.stock,
        estado=producto_erp.estado,
        mla=producto_erp.mla,
        precio_lista_ml=producto_pricing.precio_lista_ml if producto_pricing else None,
        usuario_modifico=None,
        fecha_modificacion=producto_pricing.fecha_modificacion if producto_pricing else None,
        tiene_precio=producto_pricing.precio_lista_ml is not None if producto_pricing else False,
        necesita_revision=False
    )

@router.get("/stats")
async def obtener_estadisticas(db: Session = Depends(get_db)):
    """Estadísticas generales de productos"""
    
    total_productos = db.query(ProductoERP).count()
    con_stock = db.query(ProductoERP).filter(ProductoERP.stock > 0).count()
    sin_precio = db.query(ProductoPricing).filter(ProductoPricing.precio_lista_ml.is_(None)).count()
    con_precio = db.query(ProductoPricing).filter(ProductoPricing.precio_lista_ml.isnot(None)).count()
    
    # Top categorías
    top_categorias = db.query(
        ProductoERP.categoria,
        func.count(ProductoERP.item_id).label('cantidad')
    ).group_by(
        ProductoERP.categoria
    ).order_by(
        func.count(ProductoERP.item_id).desc()
    ).limit(10).all()
    
    # Top marcas
    top_marcas = db.query(
        ProductoERP.marca,
        func.count(ProductoERP.item_id).label('cantidad')
    ).group_by(
        ProductoERP.marca
    ).order_by(
        func.count(ProductoERP.item_id).desc()
    ).limit(10).all()
    
    return {
        "total_productos": total_productos,
        "con_stock": con_stock,
        "sin_stock": total_productos - con_stock,
        "sin_precio": sin_precio,
        "con_precio": con_precio,
        "top_categorias": [{"categoria": c[0], "cantidad": c[1]} for c in top_categorias],
        "top_marcas": [{"marca": m[0], "cantidad": m[1]} for m in top_marcas]
    }

@router.get("/categorias")
async def listar_categorias(db: Session = Depends(get_db)):
    """Lista todas las categorías disponibles"""
    categorias = db.query(ProductoERP.categoria).distinct().order_by(ProductoERP.categoria).all()
    return {"categorias": [c[0] for c in categorias if c[0]]}

@router.get("/marcas")
async def listar_marcas(db: Session = Depends(get_db)):
    """Lista todas las marcas disponibles"""
    marcas = db.query(ProductoERP.marca).distinct().order_by(ProductoERP.marca).all()
    return {"marcas": [m[0] for m in marcas if m[0]]}
