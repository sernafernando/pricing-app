from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from pydantic import BaseModel
from datetime import datetime, date
from app.models.auditoria_precio import AuditoriaPrecio
from app.api.deps import get_current_user

router = APIRouter()

class ProductoResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    moneda_costo: Optional[str]
    costo: float
    costo_ars: Optional[float]
    iva: float
    stock: int
    precio_lista_ml: Optional[float]
    markup: Optional[float]
    usuario_modifico: Optional[str]
    fecha_modificacion: Optional[datetime]
    tiene_precio: bool
    necesita_revision: bool

    class Config:
        from_attributes = True

class ProductoListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    productos: List[ProductoResponse]

class PrecioUpdate(BaseModel):
    precio_lista_final: Optional[float] = None
    precio_contado_final: Optional[float] = None
    comentario: Optional[str] = None

@router.get("/productos", response_model=ProductoListResponse)
async def listar_productos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marca: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

    if search:
        # Normalizar búsqueda: quitar guiones, espacios extras, mayúsculas
        search_normalized = search.replace('-', '').replace(' ', '').upper()
        
        query = query.filter(
            or_(
                func.replace(func.replace(func.upper(ProductoERP.descripcion), '-', ''), ' ', '').like(f"%{search_normalized}%"),
                func.replace(func.replace(func.upper(ProductoERP.marca), '-', ''), ' ', '').like(f"%{search_normalized}%"),
                func.replace(func.upper(ProductoERP.codigo), '-', '').like(f"%{search_normalized}%")
            )
        )

    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)
    if marca:
        query = query.filter(ProductoERP.marca == marca)
    if con_stock is not None:
        query = query.filter(ProductoERP.stock > 0 if con_stock else ProductoERP.stock == 0)
    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(ProductoPricing.precio_lista_ml.is_(None))

    total = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    productos = []
    for producto_erp, producto_pricing in results:
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
            precio_lista_ml=producto_pricing.precio_lista_ml if producto_pricing else None,
            markup=producto_pricing.markup_calculado if producto_pricing else None,
            usuario_modifico=None,
            fecha_modificacion=producto_pricing.fecha_modificacion if producto_pricing else None,
            tiene_precio=producto_pricing.precio_lista_ml is not None if producto_pricing else False,
            necesita_revision=False
        ))

    return ProductoListResponse(total=total, page=page, page_size=page_size, productos=productos)

@router.get("/productos/{item_id}", response_model=ProductoResponse)
async def obtener_producto(item_id: int, db: Session = Depends(get_db)):
    result = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    ).filter(ProductoERP.item_id == item_id).first()

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
        precio_lista_ml=producto_pricing.precio_lista_ml if producto_pricing else None,
        markup=producto_pricing.markup_calculado if producto_pricing else None,
        usuario_modifico=None,
        fecha_modificacion=producto_pricing.fecha_modificacion if producto_pricing else None,
        tiene_precio=producto_pricing.precio_lista_ml is not None if producto_pricing else False,
        necesita_revision=False
    )

@router.get("/stats")
async def obtener_estadisticas(db: Session = Depends(get_db)):
    total_productos = db.query(ProductoERP).count()
    con_stock = db.query(ProductoERP).filter(ProductoERP.stock > 0).count()
    
    total_con_pricing = db.query(ProductoPricing).count()
    con_precio = db.query(ProductoPricing).filter(ProductoPricing.precio_lista_ml.isnot(None)).count()
    sin_precio = total_productos - con_precio

    return {
        "total_productos": total_productos,
        "con_stock": con_stock,
        "sin_stock": total_productos - con_stock,
        "sin_precio": sin_precio,
        "con_precio": con_precio
    }

@router.get("/categorias")
async def listar_categorias(db: Session = Depends(get_db)):
    categorias = db.query(ProductoERP.categoria).distinct().order_by(ProductoERP.categoria).all()
    return {"categorias": [c[0] for c in categorias if c[0]]}

@router.get("/marcas")
async def listar_marcas(db: Session = Depends(get_db)):
    marcas = db.query(ProductoERP.marca).distinct().order_by(ProductoERP.marca).all()
    return {"marcas": [m[0] for m in marcas if m[0]]}

@router.get("/productos/{item_id}/ofertas-vigentes")
async def obtener_ofertas_vigentes(item_id: int, db: Session = Depends(get_db)):
    from app.models.publicacion_ml import PublicacionML
    from app.models.oferta_ml import OfertaML
    from app.services.pricing_calculator import (
        obtener_tipo_cambio_actual, 
        convertir_a_pesos,
        obtener_grupo_subcategoria,
        obtener_comision_base,
        calcular_comision_ml_total,
        calcular_limpio,
        calcular_markup,
        VARIOS_DEFAULT
    )
    
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        return {"item_id": item_id, "publicaciones": []}
    
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
    costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
    
    publicaciones = db.query(PublicacionML).filter(PublicacionML.item_id == item_id).all()
    if not publicaciones:
        return {"item_id": item_id, "publicaciones": []}
    
    hoy = date.today()
    resultado = []
    
    for pub in publicaciones:
        oferta = db.query(OfertaML).filter(
            OfertaML.mla == pub.mla,
            OfertaML.fecha_desde <= hoy,
            OfertaML.fecha_hasta >= hoy
        ).first()
        
        markup_oferta = None
        if oferta and oferta.pvp_seller and oferta.pvp_seller > 0:
            grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
            comision_base = obtener_comision_base(db, pub.pricelist_id, grupo_id)
            
            if comision_base:
                comisiones = calcular_comision_ml_total(
                    oferta.pvp_seller,
                    comision_base,
                    producto.iva,
                    VARIOS_DEFAULT
                )
                limpio = calcular_limpio(
                    oferta.pvp_seller,
                    producto.iva,
                    producto.envio or 0,
                    comisiones["comision_total"]
                )
                markup_oferta = round(calcular_markup(limpio, costo_ars) * 100, 2)
        
        resultado.append({
            "mla": pub.mla,
            "item_title": pub.item_title,
            "pricelist_id": pub.pricelist_id,
            "lista_nombre": pub.lista_nombre,
            "tiene_oferta": oferta is not None,
            "oferta": {
                "precio_final": oferta.precio_final,
                "pvp_seller": oferta.pvp_seller,
                "markup_oferta": markup_oferta,
                "aporte_meli_pesos": oferta.aporte_meli_pesos,
                "aporte_meli_porcentaje": oferta.aporte_meli_porcentaje,
                "fecha_desde": oferta.fecha_desde.isoformat(),
                "fecha_hasta": oferta.fecha_hasta.isoformat(),
            } if oferta else None
        })
    
    return {
        "item_id": item_id,
        "total_publicaciones": len(resultado),
        "con_oferta": sum(1 for r in resultado if r["tiene_oferta"]),
        "publicaciones": resultado
    }
    
@router.patch("/productos/{producto_id}/precio")
async def actualizar_precio(
    producto_id: int,
    datos: PrecioUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza precio de un producto y registra en auditoría"""
    
    producto = db.query(ProductoPricing).filter(ProductoPricing.id == producto_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")
    
    # Guardar valores anteriores para auditoría
    precio_ant = producto.precio_lista_final
    contado_ant = producto.precio_contado_final
    
    # Actualizar precios
    if datos.precio_lista_final is not None:
        producto.precio_lista_final = datos.precio_lista_final
    if datos.precio_contado_final is not None:
        producto.precio_contado_final = datos.precio_contado_final
    
    # Registrar en auditoría SOLO si cambió algún precio
    if (datos.precio_lista_final is not None and precio_ant != datos.precio_lista_final) or \
       (datos.precio_contado_final is not None and contado_ant != datos.precio_contado_final):
        
        auditoria = AuditoriaPrecio(
            producto_id=producto_id,
            usuario_id=current_user.id,
            precio_anterior=precio_ant,
            precio_contado_anterior=contado_ant,
            precio_nuevo=producto.precio_lista_final,
            precio_contado_nuevo=producto.precio_contado_final,
            comentario=datos.comentario if hasattr(datos, 'comentario') else None
        )
        db.add(auditoria)
    
    db.commit()
    db.refresh(producto)
    
    return producto
