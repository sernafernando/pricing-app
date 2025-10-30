from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from pydantic import BaseModel, Field
from datetime import datetime, date
from app.models.auditoria_precio import AuditoriaPrecio
from app.api.deps import get_current_user
from fastapi.responses import Response
from decimal import Decimal

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
    participa_rebate: Optional[bool] = False
    porcentaje_rebate: Optional[float] = 3.8
    precio_rebate: Optional[float] = None
    markup_rebate: Optional[float] = None
    participa_web_transferencia: Optional[bool] = False
    porcentaje_markup_web: Optional[float] = 6.0
    precio_web_transferencia: Optional[float] = None
    markup_web_real: Optional[float] = None
    mejor_oferta_precio: Optional[float] = None
    mejor_oferta_monto_rebate: Optional[float] = None
    mejor_oferta_pvp_seller: Optional[float] = None
    mejor_oferta_markup: Optional[float] = None
    mejor_oferta_porcentaje_rebate: Optional[float] = None
    mejor_oferta_fecha_hasta: Optional[date] = None
    out_of_cards: Optional[bool] = False

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

class RebateUpdate(BaseModel):
    participa_rebate: bool
    porcentaje_rebate: float = Field(ge=0, le=100)

@router.get("/productos", response_model=ProductoListResponse)
async def listar_productos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    orden_campos: Optional[str] = None,
    orden_direcciones: Optional[str] = None,
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    con_rebate: Optional[bool] = None,
    con_oferta: Optional[bool] = None,
    con_web_transf: Optional[bool] = None,
    markup_clasica_positivo: Optional[bool] = None,
    markup_rebate_positivo: Optional[bool] = None,
    markup_oferta_positivo: Optional[bool] = None,
    markup_web_transf_positivo: Optional[bool] = None,
    out_of_cards: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

    # FILTRADO POR AUDITORÍA
    if audit_usuarios or audit_tipos_accion or audit_fecha_desde or audit_fecha_hasta:
        from app.models.auditoria import Auditoria
        from datetime import datetime
        
        audit_query = db.query(Auditoria.item_id).filter(Auditoria.item_id.isnot(None))
        
        if audit_usuarios:
            usuarios_ids = [int(u) for u in audit_usuarios.split(',')]
            audit_query = audit_query.filter(Auditoria.usuario_id.in_(usuarios_ids))
        
        if audit_tipos_accion:
            tipos_list = audit_tipos_accion.split(',')
            audit_query = audit_query.filter(Auditoria.tipo_accion.in_(tipos_list))
        
        if audit_fecha_desde:
            try:
                fecha_desde_dt = datetime.strptime(audit_fecha_desde, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    fecha_desde_dt = datetime.strptime(audit_fecha_desde, '%Y-%m-%d')
                except ValueError:
                    # Si falla todo, usar fecha de hoy
                    from datetime import date
                    fecha_desde_dt = datetime.combine(date.today(), datetime.min.time())
            audit_query = audit_query.filter(Auditoria.fecha >= fecha_desde_dt)
        
        if audit_fecha_hasta:
            try:
                fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, '%Y-%m-%d')
                    fecha_hasta_dt = fecha_hasta_dt.replace(hour=23, minute=59, second=59)
                except ValueError:
                    from datetime import date
                    fecha_hasta_dt = datetime.combine(date.today(), datetime.max.time())
            audit_query = audit_query.filter(Auditoria.fecha <= fecha_hasta_dt)
        
        item_ids = [item_id for (item_id,) in audit_query.distinct().all()]
        
        if item_ids:
            query = query.filter(ProductoERP.item_id.in_(item_ids))
        else:
            return ProductoListResponse(total=0, page=page, page_size=page_size, productos=[])

    if search:
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

    if subcategorias:
        subcat_list = [int(s.strip()) for s in subcategorias.split(',')]
        query = query.filter(ProductoERP.subcategoria_id.in_(subcat_list))
    
    if marcas:
        marcas_list = [m.strip().upper() for m in marcas.split(',')]
        query = query.filter(func.upper(ProductoERP.marca).in_(marcas_list))
    
    if con_stock is not None:
        query = query.filter(ProductoERP.stock > 0 if con_stock else ProductoERP.stock == 0)
    
    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(ProductoPricing.precio_lista_ml.is_(None))

    # Filtros de valores específicos
    if con_rebate is not None:
        if con_rebate:
            query = query.filter(ProductoPricing.participa_rebate == True)
        else:
            query = query.filter(
                or_(
                    ProductoPricing.participa_rebate == False,
                    ProductoPricing.participa_rebate.is_(None)
                )
            )

    if con_web_transf is not None:
        if con_web_transf:
            query = query.filter(ProductoPricing.participa_web_transferencia == True)
        else:
            query = query.filter(
                or_(
                    ProductoPricing.participa_web_transferencia == False,
                    ProductoPricing.participa_web_transferencia.is_(None)
                )
            )

    # Filtros de markup
    if markup_clasica_positivo is not None:
        if markup_clasica_positivo:
            query = query.filter(ProductoPricing.markup_calculado > 0)
        else:
            query = query.filter(ProductoPricing.markup_calculado < 0)

    if markup_web_transf_positivo is not None:
        if markup_web_transf_positivo:
            query = query.filter(ProductoPricing.markup_web_real > 0)
        else:
            query = query.filter(ProductoPricing.markup_web_real < 0)

    if out_of_cards is not None:
        if out_of_cards:
            query = query.filter(ProductoPricing.out_of_cards == True)
        else:
            query = query.filter(
                or_(
                    ProductoPricing.out_of_cards == False,
                    ProductoPricing.out_of_cards.is_(None)
                )
            )

    # Ordenamiento
    orden_requiere_calculo = False
    if orden_campos and orden_direcciones:
        campos = orden_campos.split(',')
        direcciones = orden_direcciones.split(',')

        for campo, direccion in zip(campos, direcciones):
            # Mapeo de campos del frontend a columnas de la DB
            if campo == 'item_id':
                col = ProductoERP.item_id
            elif campo == 'codigo':
                col = ProductoERP.codigo
            elif campo == 'descripcion':
                col = ProductoERP.descripcion
            elif campo == 'marca':
                col = ProductoERP.marca
            elif campo == 'moneda_costo':
                col = ProductoERP.moneda_costo
            elif campo == 'costo':
                col = ProductoERP.costo
            elif campo == 'stock':
                col = ProductoERP.stock
            elif campo == 'precio_lista_ml':
                col = ProductoPricing.precio_lista_ml
            elif campo == 'markup' or campo == 'precio_clasica':
                col = ProductoPricing.markup_calculado
            elif campo == 'precio_rebate':
                # Markup rebate requiere cálculo dinámico
                orden_requiere_calculo = True
                continue
            elif campo == 'mejor_oferta':
                # Mejor oferta requiere cálculo dinámico
                orden_requiere_calculo = True
                continue
            elif campo == 'web_transf':
                col = ProductoPricing.markup_web_real
            else:
                continue

            if direccion == 'asc':
                query = query.order_by(col.asc().nullslast())
            else:
                query = query.order_by(col.desc().nullslast())

    # Para filtros de oferta y markup rebate/oferta, necesitamos procesar después
    # ya que estos valores se calculan dinámicamente

    # Contar total antes de aplicar filtros complejos y ordenamientos dinámicos
    total_productos = None
    if con_oferta is None and markup_rebate_positivo is None and markup_oferta_positivo is None and not orden_requiere_calculo:
        total_productos = query.count()
        offset = (page - 1) * page_size
        results = query.offset(offset).limit(page_size).all()
    else:
        # Obtener todos los resultados para filtrar/ordenar después
        results = query.all()
        total_antes_filtro = len(results)

    from app.models.oferta_ml import OfertaML
    from app.models.publicacion_ml import PublicacionML
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
    from datetime import date
    
    hoy = date.today()
    
    productos = []
    for producto_erp, producto_pricing in results:
        costo_ars = producto_erp.costo if producto_erp.moneda_costo == "ARS" else None
        # Buscar mejor oferta vigente
        mejor_oferta_precio = None
        mejor_oferta_monto = None
        mejor_oferta_pvp = None
        mejor_oferta_markup = None
        mejor_oferta_porcentaje = None
        mejor_oferta_fecha_hasta = None
        
        # Buscar publicación del producto
        pubs = db.query(PublicacionML).filter(PublicacionML.item_id == producto_erp.item_id).all()
                                
        mejor_oferta = None
        mejor_pub = None
        
        for pub in pubs:
            # Buscar oferta vigente para esta publicación
            oferta = db.query(OfertaML).filter(
                OfertaML.mla == pub.mla,
                OfertaML.fecha_desde <= hoy,
                OfertaML.fecha_hasta >= hoy,
                OfertaML.pvp_seller.isnot(None)
            ).order_by(OfertaML.fecha_desde.desc()).first()
            
            if oferta:
                # Tomar la primera que encuentre (o implementar lógica para elegir la mejor)
                if not mejor_oferta:
                    mejor_oferta = oferta
                    mejor_pub = pub
        
        
        if mejor_oferta and mejor_pub:
            mejor_oferta_precio = float(mejor_oferta.precio_final) if mejor_oferta.precio_final else None
            mejor_oferta_pvp = float(mejor_oferta.pvp_seller) if mejor_oferta.pvp_seller else None
            mejor_oferta_porcentaje = float(mejor_oferta.aporte_meli_porcentaje) if mejor_oferta.aporte_meli_porcentaje else None  # ← AGREGAR
            mejor_oferta_fecha_hasta = mejor_oferta.fecha_hasta
            
            # Calcular monto rebate
            if mejor_oferta_precio and mejor_oferta_pvp:
                mejor_oferta_monto = mejor_oferta_pvp - mejor_oferta_precio
            
            # Calcular markup de la oferta
            if mejor_oferta_pvp and mejor_oferta_pvp > 0:
                tipo_cambio = None
                if producto_erp.moneda_costo == "USD":
                    tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
                
                costo_calc = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)
                grupo_id = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)
                comision_base = obtener_comision_base(db, mejor_pub.pricelist_id, grupo_id)
                
                if comision_base:
                    comisiones = calcular_comision_ml_total(
                        mejor_oferta_pvp,
                        comision_base,
                        producto_erp.iva,
                        VARIOS_DEFAULT
                    )
                    limpio = calcular_limpio(
                        mejor_oferta_pvp,
                        producto_erp.iva,
                        producto_erp.envio or 0,
                        comisiones["comision_total"]
                    )
                    mejor_oferta_markup = calcular_markup(limpio, costo_calc)

        # Calcular precio_rebate y markup_rebate
        precio_rebate = None
        markup_rebate = None
        if producto_pricing and producto_pricing.precio_lista_ml and producto_pricing.participa_rebate:
            porcentaje_rebate_val = float(producto_pricing.porcentaje_rebate if producto_pricing.porcentaje_rebate is not None else 3.8)
            precio_rebate = float(producto_pricing.precio_lista_ml) / (1 - porcentaje_rebate_val / 100)

            # Calcular markup del rebate
            tipo_cambio_rebate = None
            if producto_erp.moneda_costo == "USD":
                tipo_cambio_rebate = obtener_tipo_cambio_actual(db, "USD")

            costo_rebate = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_rebate)
            grupo_id_rebate = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)
            comision_base_rebate = obtener_comision_base(db, 4, grupo_id_rebate)  # Lista clásica

            if comision_base_rebate and precio_rebate > 0:
                comisiones_rebate = calcular_comision_ml_total(
                    precio_rebate,
                    comision_base_rebate,
                    producto_erp.iva,
                    VARIOS_DEFAULT
                )
                limpio_rebate = calcular_limpio(
                    precio_rebate,
                    producto_erp.iva,
                    producto_erp.envio or 0,
                    comisiones_rebate["comision_total"]
                )
                markup_rebate = calcular_markup(limpio_rebate, costo_rebate) * 100

        # Si el producto tiene rebate y está out_of_cards, replicar el rebate a mejor_oferta
        if producto_pricing and producto_pricing.out_of_cards and precio_rebate is not None and markup_rebate is not None:
            # Replicar datos del rebate a mejor_oferta
            mejor_oferta_precio = precio_rebate
            mejor_oferta_pvp = precio_rebate  # El PVP es el mismo que el precio rebate
            mejor_oferta_markup = markup_rebate / 100  # Convertir de porcentaje a decimal
            mejor_oferta_porcentaje = None  # No hay aporte de Meli en rebate
            mejor_oferta_monto = None  # No hay monto de rebate en este caso
            mejor_oferta_fecha_hasta = None  # No aplica fecha para rebate

        producto_obj = ProductoResponse(
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
            necesita_revision=False,
            participa_rebate=producto_pricing.participa_rebate if producto_pricing else False,
            porcentaje_rebate=float(producto_pricing.porcentaje_rebate) if producto_pricing and producto_pricing.porcentaje_rebate is not None else 3.8,
            precio_rebate=precio_rebate,
            markup_rebate=markup_rebate,
            participa_web_transferencia=producto_pricing.participa_web_transferencia if producto_pricing else False,
            porcentaje_markup_web=float(producto_pricing.porcentaje_markup_web) if producto_pricing and producto_pricing.porcentaje_markup_web else 6.0,
            precio_web_transferencia=float(producto_pricing.precio_web_transferencia) if producto_pricing and producto_pricing.precio_web_transferencia else None,
            markup_web_real=float(producto_pricing.markup_web_real) if producto_pricing and producto_pricing.markup_web_real else None,
            mejor_oferta_precio=mejor_oferta_precio,
            mejor_oferta_monto_rebate=mejor_oferta_monto,
            mejor_oferta_pvp_seller=mejor_oferta_pvp,
            mejor_oferta_markup=mejor_oferta_markup,
            mejor_oferta_porcentaje_rebate=mejor_oferta_porcentaje,
            mejor_oferta_fecha_hasta=mejor_oferta_fecha_hasta,
            out_of_cards=producto_pricing.out_of_cards if producto_pricing else False,
        )

        # Aplicar filtros dinámicos
        incluir = True

        if con_oferta is not None:
            tiene_oferta = mejor_oferta_precio is not None
            if con_oferta and not tiene_oferta:
                incluir = False
            elif not con_oferta and tiene_oferta:
                incluir = False

        if markup_rebate_positivo is not None and incluir:
            if markup_rebate is not None:
                if markup_rebate_positivo and markup_rebate < 0:
                    incluir = False
                elif not markup_rebate_positivo and markup_rebate >= 0:
                    incluir = False
            else:
                incluir = False

        if markup_oferta_positivo is not None and incluir:
            if mejor_oferta_markup is not None:
                markup_oferta_pct = mejor_oferta_markup * 100
                if markup_oferta_positivo and markup_oferta_pct < 0:
                    incluir = False
                elif not markup_oferta_positivo and markup_oferta_pct >= 0:
                    incluir = False
            else:
                incluir = False

        if incluir:
            productos.append(producto_obj)

    # Si aplicamos filtros dinámicos o ordenamiento dinámico, necesitamos paginar manualmente
    if con_oferta is not None or markup_rebate_positivo is not None or markup_oferta_positivo is not None or orden_requiere_calculo:
        # Ordenamiento dinámico si es necesario
        if orden_requiere_calculo and orden_campos and orden_direcciones:
            campos = orden_campos.split(',')
            direcciones = orden_direcciones.split(',')

            # Ordenar por cada columna con su dirección (en orden inverso para aplicar prioridad correcta)
            for i in range(len(campos) - 1, -1, -1):
                campo = campos[i]
                direccion = direcciones[i]
                reverse = (direccion == 'desc')

                if campo in ['precio_rebate', 'mejor_oferta', 'precio_clasica', 'web_transf']:
                    def get_sort_value(prod, campo=campo):
                        if campo == 'precio_rebate':
                            val = prod.markup_rebate
                        elif campo == 'mejor_oferta':
                            val = prod.mejor_oferta_markup
                            if val is not None:
                                val = val * 100
                        elif campo == 'precio_clasica':
                            val = prod.markup
                        elif campo == 'web_transf':
                            val = prod.markup_web_real
                        else:
                            val = None
                        return (val is None, val if val is not None else float('-inf'))

                    productos.sort(key=get_sort_value, reverse=reverse)

        total = len(productos)
        offset = (page - 1) * page_size
        productos = productos[offset:offset + page_size]
    else:
        # Si no hay filtros dinámicos, usar el total pre-calculado
        total = total_productos if total_productos is not None else len(productos)

    return ProductoListResponse(total=total, page=page, page_size=page_size, productos=productos)

@router.get("/productos/precios-listas")
async def listar_productos_con_precios_listas(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marca: Optional[str] = None,
    con_stock: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista productos con sus precios en todas las listas de ML"""
    from app.models.precio_ml import PrecioML
    from app.models.publicacion_ml import PublicacionML

    # Query base
    query = db.query(ProductoERP).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

    # Filtros
    if search:
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

    total = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    productos = []
    for producto_erp in results:
        # Obtener precios de todas las listas directamente por item_id
        precios_listas = {}
    
        for pricelist_id in [4, 17, 14, 13, 23]:
            precio_ml = db.query(PrecioML).filter(
                PrecioML.item_id == producto_erp.item_id,
                PrecioML.pricelist_id == pricelist_id
            ).first()
        
            if precio_ml:
                precios_listas[pricelist_id] = {
                    "precio": float(precio_ml.precio) if precio_ml.precio else None,
                    "mla": precio_ml.mla,
                    "cotizacion_dolar": float(precio_ml.cotizacion_dolar) if precio_ml.cotizacion_dolar else None
                }
        
        productos.append({
            "item_id": producto_erp.item_id,
            "codigo": producto_erp.codigo,
            "descripcion": producto_erp.descripcion,
            "marca": producto_erp.marca,
            "categoria": producto_erp.categoria,
            "stock": producto_erp.stock,
            "costo": float(producto_erp.costo),
            "moneda_costo": producto_erp.moneda_costo,
            "precios_listas": precios_listas
        })
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "productos": productos
    }


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


@router.patch("/productos/{item_id}/rebate")
async def actualizar_rebate(
    item_id: int,
    datos: RebateUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Actualiza configuración de rebate de un producto"""
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    # Guardar valores anteriores
    valores_anteriores = {
        "participa_rebate": pricing.participa_rebate if pricing else False,
        "porcentaje_rebate": float(pricing.porcentaje_rebate) if pricing and pricing.porcentaje_rebate is not None else None
    }

    if not pricing:
        pricing = ProductoPricing(
            item_id=item_id,
            participa_rebate=datos.participa_rebate,
            porcentaje_rebate=datos.porcentaje_rebate,
            usuario_id=current_user.id
        )
        db.add(pricing)
    else:
        pricing.participa_rebate = datos.participa_rebate
        pricing.porcentaje_rebate = datos.porcentaje_rebate
        pricing.fecha_modificacion = datetime.now()

    db.commit()
    db.refresh(pricing)

    # Determinar tipo de acción
    if datos.participa_rebate and not valores_anteriores["participa_rebate"]:
        tipo_accion = TipoAccion.ACTIVAR_REBATE
    elif not datos.participa_rebate and valores_anteriores["participa_rebate"]:
        tipo_accion = TipoAccion.DESACTIVAR_REBATE
    else:
        tipo_accion = TipoAccion.MODIFICAR_PORCENTAJE_REBATE

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=tipo_accion,
        item_id=item_id,
        valores_anteriores=valores_anteriores,
        valores_nuevos={
            "participa_rebate": datos.participa_rebate,
            "porcentaje_rebate": datos.porcentaje_rebate
        }
    )

    return {
        "item_id": item_id,
        "participa_rebate": datos.participa_rebate,
        "porcentaje_rebate": datos.porcentaje_rebate
    }
        
@router.post("/productos/exportar-rebate")
async def exportar_rebate(
    fecha_desde: str = None,
    fecha_hasta: str = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Exporta productos con rebate a Excel"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    from datetime import datetime, date
    from calendar import monthrange
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from app.models.publicacion_ml import PublicacionML
    
    # Fechas por defecto
    hoy = date.today()
    if not fecha_desde:
        fecha_desde = hoy.strftime('%Y-%m-%d')
    if not fecha_hasta:
        ultimo_dia = monthrange(hoy.year, hoy.month)[1]
        fecha_hasta = f"{hoy.year}-{hoy.month:02d}-{ultimo_dia:02d}"
    
    # Obtener productos con rebate
    productos = db.query(ProductoERP, ProductoPricing).join(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    ).filter(
        ProductoPricing.participa_rebate == True,
        ProductoPricing.out_of_cards != True
    ).all()
    
    # Crear Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Rebate Export"
    
    # Headers
    headers = [
        "REBATE", "MARCA", "DESDE", "HASTA", "TIPO DE OFERTA", "CATEGORÍA",
        "DESCRIPCIÓN DE LA PUBLICACIÓN", "TIPO DE PUBLICACIÓN", "STOCK",
        "FULL", "MLAs", "PVP LLENO", "PVP SELLER"
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
    
    # Datos
    row = 2
    for producto_erp, producto_pricing in productos:
        # Buscar MLAs de lista clásica (pricelist_id = 4)
        mlas = db.query(PublicacionML).filter(
            PublicacionML.item_id == producto_erp.item_id,
            PublicacionML.pricelist_id == 4,
            PublicacionML.activo == True
        ).all()
        
        # Si no tiene MLAs, skip
        if not mlas:
            continue
        
        # Obtener precio de lista clásica
        from app.models.precio_ml import PrecioML
        precio_clasica = db.query(PrecioML).filter(
            PrecioML.item_id == producto_erp.item_id,
            PrecioML.pricelist_id == 4
        ).first()
        
        pvp_lleno = float(precio_clasica.precio) if precio_clasica else 0
        
        # Calcular PVP Seller (precio con rebate aplicado)
        porcentaje_rebate = float(producto_pricing.porcentaje_rebate or 3.8)
        pvp_seller = pvp_lleno * (1 - porcentaje_rebate / 100)
        
        # Una fila por cada MLA
        for mla in mlas:
            ws.cell(row=row, column=1, value=f"{porcentaje_rebate}%")
            ws.cell(row=row, column=2, value=producto_erp.marca or "")
            ws.cell(row=row, column=3, value=fecha_desde)
            ws.cell(row=row, column=4, value=fecha_hasta)
            ws.cell(row=row, column=5, value="DXI")
            ws.cell(row=row, column=6, value="")  # Categoría vacía
            ws.cell(row=row, column=7, value=mla.item_title or producto_erp.descripcion or "")
            ws.cell(row=row, column=8, value="Clásica")
            ws.cell(row=row, column=9, value=producto_erp.stock)
            ws.cell(row=row, column=10, value="FALSE")
            ws.cell(row=row, column=11, value=mla.mla)
            ws.cell(row=row, column=12, value=pvp_lleno)
            ws.cell(row=row, column=13, value=round(pvp_seller, 2))
            row += 1
    
    # Guardar en memoria
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=rebate_export_{hoy.strftime('%Y%m%d')}.xlsx"}
    )

@router.patch("/productos/{item_id}/web-transferencia")
async def actualizar_web_transferencia(
    item_id: int,
    participa: bool,
    porcentaje_markup: float = 6.0,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Activa/desactiva web transferencia y calcula precio"""
    from app.services.pricing_calculator import (
        calcular_precio_web_transferencia,
        obtener_tipo_cambio_actual,
        convertir_a_pesos
    )
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto_erp:
        raise HTTPException(404, "Producto no encontrado")

    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    # Guardar valores anteriores
    valores_anteriores = {
        "participa_web_transferencia": pricing.participa_web_transferencia if pricing else False,
        "porcentaje_markup_web": float(pricing.porcentaje_markup_web) if pricing and pricing.porcentaje_markup_web else None,
        "precio_web_transferencia": float(pricing.precio_web_transferencia) if pricing and pricing.precio_web_transferencia else None
    }

    if not pricing:
        pricing = ProductoPricing(
            item_id=item_id,
            participa_web_transferencia=participa,
            porcentaje_markup_web=porcentaje_markup,
            usuario_id=current_user.id
        )
        db.add(pricing)
    else:
        pricing.participa_web_transferencia = participa
        pricing.porcentaje_markup_web = porcentaje_markup
        pricing.fecha_modificacion = datetime.now()

    precio_web = None
    markup_web_real = None

    if participa:
        tipo_cambio = None
        if producto_erp.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

        costo_ars = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)

        if pricing.markup_calculado is not None and pricing.precio_lista_ml is not None:
            markup_clasica = pricing.markup_calculado / 100
        else:
            markup_clasica = 0

        markup_objetivo = markup_clasica + (porcentaje_markup / 100)

        resultado = calcular_precio_web_transferencia(
            costo_ars=costo_ars,
            iva=producto_erp.iva,
            markup_objetivo=markup_objetivo
        )

        precio_web = resultado["precio"]
        markup_web_real = resultado["markup_real"]
        pricing.precio_web_transferencia = precio_web
        pricing.markup_web_real = markup_web_real
    else:
        pricing.precio_web_transferencia = None
        pricing.markup_web_real = None

    db.commit()
    db.refresh(pricing)

    # Determinar tipo de acción
    if participa and not valores_anteriores["participa_web_transferencia"]:
        tipo_accion = TipoAccion.ACTIVAR_WEB_TRANSFERENCIA
    elif not participa and valores_anteriores["participa_web_transferencia"]:
        tipo_accion = TipoAccion.DESACTIVAR_WEB_TRANSFERENCIA
    else:
        tipo_accion = TipoAccion.MODIFICAR_PRECIO_WEB

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=tipo_accion,
        item_id=item_id,
        valores_anteriores=valores_anteriores,
        valores_nuevos={
            "participa_web_transferencia": participa,
            "porcentaje_markup_web": porcentaje_markup,
            "precio_web_transferencia": precio_web,
            "markup_web_real": markup_web_real
        }
    )

    return {
        "item_id": item_id,
        "participa_web_transferencia": participa,
        "porcentaje_markup_web": porcentaje_markup,
        "precio_web_transferencia": precio_web,
        "markup_web_real": markup_web_real if precio_web else None
    }
    
class CalculoWebMasivoRequest(BaseModel):
        porcentaje_con_precio: float
        porcentaje_sin_precio: float
        filtros: dict = None  # ← AGREGAR
    
@router.post("/productos/calcular-web-masivo")
async def calcular_web_masivo(
    request: CalculoWebMasivoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Calcula precio web transferencia masivamente"""
    from app.services.pricing_calculator import (
        calcular_precio_web_transferencia,
        obtener_tipo_cambio_actual,
        convertir_a_pesos
    )

    # Obtener productos base
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )
    
    # Aplicar filtros si existen
    if request.filtros:
        if request.filtros.get('search'):
            search_term = f"%{request.filtros['search']}%"
            query = query.filter(
                (ProductoERP.descripcion.ilike(search_term)) |
                (ProductoERP.codigo.ilike(search_term))
            )
        
        if request.filtros.get('con_stock'):
            query = query.filter(ProductoERP.stock > 0)
        
        if request.filtros.get('con_precio'):
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        
        if request.filtros.get('marcas'):
            marcas_list = request.filtros['marcas'].split(',')
            query = query.filter(ProductoERP.marca.in_(marcas_list))
        
        if request.filtros.get('subcategorias'):
            subcats_list = [int(s) for s in request.filtros['subcategorias'].split(',')]
            query = query.filter(ProductoERP.subcategoria_id.in_(subcats_list))
    
    productos = query.all()

    procesados = 0

    for producto_erp, producto_pricing in productos:
        # Determinar markup a usar
        if producto_pricing and producto_pricing.precio_lista_ml:
            # Tiene precio: sumar porcentaje
            markup_base = (producto_pricing.markup_calculado or 0) / 100
            porcentaje_adicional = request.porcentaje_con_precio
        else:
            # No tiene precio: usar porcentaje base
            markup_base = 0
            porcentaje_adicional = request.porcentaje_sin_precio

        markup_objetivo = markup_base + (porcentaje_adicional / 100)

        # Calcular precio
        tipo_cambio = None
        if producto_erp.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

        costo_ars = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)

        resultado = calcular_precio_web_transferencia(
            costo_ars=costo_ars,
            iva=producto_erp.iva,
            markup_objetivo=markup_objetivo
        )

        # Crear o actualizar pricing
        if not producto_pricing:
            producto_pricing = ProductoPricing(
                item_id=producto_erp.item_id,
                usuario_id=current_user.id
            )
            db.add(producto_pricing)

        producto_pricing.participa_web_transferencia = True
        producto_pricing.porcentaje_markup_web = porcentaje_adicional
        producto_pricing.precio_web_transferencia = resultado["precio"]
        producto_pricing.markup_web_real = resultado["markup_real"]
        producto_pricing.fecha_modificacion = datetime.now()

        procesados += 1

    db.commit()
    
    # Registrar auditoría masiva
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion
    
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=procesados,
        valores_nuevos={
            "accion": "calcular_web_masivo",
            "porcentaje_con_precio": request.porcentaje_con_precio,
            "porcentaje_sin_precio": request.porcentaje_sin_precio,
            "filtros": request.filtros
        },
        comentario="Cálculo masivo de precios web transferencia"
    )

    return {
        "procesados": procesados,
        "porcentaje_con_precio": request.porcentaje_con_precio,
        "porcentaje_sin_precio": request.porcentaje_sin_precio
    }


@router.post("/productos/limpiar-rebate")
async def limpiar_rebate(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Desactiva rebate en todos los productos"""
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion
    
    count = db.query(ProductoPricing).filter(
        ProductoPricing.participa_rebate == True
    ).count()
    
    db.query(ProductoPricing).update({
        ProductoPricing.participa_rebate: False
    })
    db.commit()

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=count,
        valores_nuevos={"accion": "limpiar_rebate"},
        comentario="Limpieza masiva de rebate"
    )

    return {
        "mensaje": "Rebate desactivado en todos los productos",
        "productos_actualizados": count
    }

@router.post("/productos/limpiar-web-transferencia")
async def limpiar_web_transferencia(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Desactiva web transferencia en todos los productos"""
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion
    
    count = db.query(ProductoPricing).filter(
        ProductoPricing.participa_web_transferencia == True
    ).count()
    
    db.query(ProductoPricing).update({
        ProductoPricing.participa_web_transferencia: False,
        ProductoPricing.precio_web_transferencia: None,
        ProductoPricing.markup_web_real: None
    })
    db.commit()

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=count,
        valores_nuevos={"accion": "limpiar_web_transferencia"},
        comentario="Limpieza masiva de web transferencia"
    )

    return {
        "mensaje": "Web transferencia desactivada en todos los productos",
        "productos_actualizados": count
    }

@router.get("/subcategorias")
async def listar_subcategorias(db: Session = Depends(get_db)):
    """Lista todas las subcategorías agrupadas por categoría"""
    from app.models.comision_config import SubcategoriaGrupo
    from collections import defaultdict
    
    subcats = db.query(SubcategoriaGrupo).order_by(
        SubcategoriaGrupo.nombre_categoria,
        SubcategoriaGrupo.nombre_subcategoria
    ).all()
    
    # Agrupar por categoría
    agrupadas = defaultdict(list)
    for s in subcats:
        if s.nombre_subcategoria and s.nombre_categoria:
            agrupadas[s.nombre_categoria].append({
                "id": s.subcat_id,
                "nombre": s.nombre_subcategoria,
                "grupo_id": s.grupo_id
            })
    
    return {
        "categorias": [
            {
                "nombre": cat,
                "subcategorias": subs
            }
            for cat, subs in sorted(agrupadas.items())
        ]
    }
    
@router.post("/sincronizar-subcategorias")
async def sincronizar_subcategorias_endpoint():
    """Sincroniza subcategorías desde el worker"""
    from app.scripts.sync_subcategorias import sincronizar_subcategorias
    sincronizar_subcategorias()
    return {"mensaje": "Subcategorías sincronizadas"}


@router.get("/exportar-web-transferencia")
async def exportar_web_transferencia(
    porcentaje_adicional: float = Query(0, description="Porcentaje adicional a sumar"),
    search: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Exporta precios de Web Transferencia en formato Excel con filtros opcionales"""
    from io import BytesIO
    from openpyxl import Workbook
    
    # Obtener productos con precio web transferencia
    query = db.query(
        ProductoERP.codigo,
        ProductoPricing.precio_web_transferencia
    ).join(
        ProductoPricing,
        ProductoERP.item_id == ProductoPricing.item_id
    ).filter(
        ProductoPricing.participa_web_transferencia == True,
        ProductoPricing.precio_web_transferencia.isnot(None)
    )
    
    # Aplicar filtros
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (ProductoERP.descripcion.ilike(search_term)) |
            (ProductoERP.codigo.ilike(search_term))
        )
    
    if con_stock:
        query = query.filter(ProductoERP.stock > 0)
    
    if con_precio:
        query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
    
    if marcas:
        marcas_list = marcas.split(',')
        query = query.filter(ProductoERP.marca.in_(marcas_list))
    
    if subcategorias:
        subcats_list = [int(s) for s in subcategorias.split(',')]
        query = query.filter(ProductoERP.subcategoria_id.in_(subcats_list))
    
    productos = query.all()
    
    # Crear Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Web Transferencia"
    
    # Header
    ws.append(['Código/EAN', 'Precio', 'ID Moneda'])
    
    # Datos - todo como texto
    for codigo, precio_base in productos:
        # Aplicar porcentaje adicional
        precio_final = float(precio_base) * (1 + porcentaje_adicional / 100)
        
        # Redondear a múltiplo de 10
        precio_final = round(precio_final / 10) * 10
        
        ws.append([
            str(codigo),
            str(int(precio_final)),
            '1'
        ])
    
    # Guardar en memoria
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=web_transferencia.xlsx"
        }
    )

@router.get("/exportar-clasica")
async def exportar_clasica(
    porcentaje_adicional: float = Query(0, description="Porcentaje adicional sobre rebate"),
    search: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Exporta precios de Clásica. Si tiene rebate activo, aplica % sobre precio rebate."""
    from io import BytesIO
    from openpyxl import Workbook
    
    # Obtener productos con precio clásica
    query = db.query(
        ProductoERP.codigo,
        ProductoPricing.precio_lista_ml,
        ProductoPricing.participa_rebate,
        ProductoPricing.porcentaje_rebate
    ).join(
        ProductoPricing,
        ProductoERP.item_id == ProductoPricing.item_id
    ).filter(
        ProductoPricing.precio_lista_ml.isnot(None)
    )
    
    # Aplicar filtros
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (ProductoERP.descripcion.ilike(search_term)) |
            (ProductoERP.codigo.ilike(search_term))
        )
    
    if con_stock:
        query = query.filter(ProductoERP.stock > 0)
    
    if con_precio:
        query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
    
    if marcas:
        marcas_list = marcas.split(',')
        query = query.filter(ProductoERP.marca.in_(marcas_list))
    
    if subcategorias:
        subcats_list = [int(s) for s in subcategorias.split(',')]
        query = query.filter(ProductoERP.subcategoria_id.in_(subcats_list))
    
    productos = query.all()
    
    # Crear Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Clasica"
    
    # Header
    ws.append(['Código/EAN', 'Precio', 'ID Moneda'])
    
    # Datos
    for codigo, precio_clasica, participa_rebate, porcentaje_rebate in productos:
        # Si tiene rebate activo, calcular precio rebate y aplicar % adicional
        if participa_rebate and porcentaje_rebate:
            precio_rebate = precio_clasica * (1 + float(porcentaje_rebate) / 100)
            precio_final = precio_rebate * (1 + porcentaje_adicional / 100)
            # Redondear a múltiplo de 10
            precio_final = round(precio_final / 10) * 10
        else:
            # Si no tiene rebate, usar precio clásica sin modificar
            precio_final = round(precio_clasica / 10) * 10
        
        ws.append([
            str(codigo),
            str(int(precio_final)),
            '1'
        ])
    
    # Guardar en memoria
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=clasica.xlsx"
        }
    )

@router.patch("/productos/{item_id}/out-of-cards")
async def actualizar_out_of_cards(
    item_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el estado de out_of_cards de un producto"""
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion
    
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    
    if not pricing:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    # Guardar valor anterior
    valor_anterior = pricing.out_of_cards
    valor_nuevo = data.get("out_of_cards", False)
    
    pricing.out_of_cards = valor_nuevo
    db.commit()
    
    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MARCAR_OUT_OF_CARDS if valor_nuevo else TipoAccion.DESMARCAR_OUT_OF_CARDS,
        item_id=item_id,
        valores_anteriores={"out_of_cards": valor_anterior},
        valores_nuevos={"out_of_cards": valor_nuevo}
    )
    
    return {"status": "success", "out_of_cards": pricing.out_of_cards}
