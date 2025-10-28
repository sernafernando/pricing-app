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
    participa_rebate: Optional[bool] = False
    porcentaje_rebate: Optional[float] = 3.8
    precio_rebate: Optional[float] = None
    participa_web_transferencia: Optional[bool] = False
    porcentaje_markup_web: Optional[float] = 6.0
    precio_web_transferencia: Optional[float] = None
    markup_web_real: Optional[float] = None

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
    porcentaje_rebate: float

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
    db: Session = Depends(get_db)
):
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

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
    
    # Ordenamiento
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
            elif campo == 'markup':
                col = ProductoPricing.markup_calculado
            else:
                continue
            
            if direccion == 'asc':
                query = query.order_by(col.asc().nullslast())
            else:
                query = query.order_by(col.desc().nullslast())

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
            necesita_revision=False,
            participa_rebate=producto_pricing.participa_rebate if producto_pricing else False,
            porcentaje_rebate=float(producto_pricing.porcentaje_rebate) if producto_pricing and producto_pricing.porcentaje_rebate else 3.8,
            precio_rebate=float(producto_pricing.precio_lista_ml) / (1 - float(producto_pricing.porcentaje_rebate or 3.8) / 100) if producto_pricing and producto_pricing.precio_lista_ml and producto_pricing.participa_rebate else None,
            participa_web_transferencia=producto_pricing.participa_web_transferencia if producto_pricing else False,
            porcentaje_markup_web=float(producto_pricing.porcentaje_markup_web) if producto_pricing and producto_pricing.porcentaje_markup_web else 6.0,
            precio_web_transferencia=float(producto_pricing.precio_web_transferencia) if producto_pricing and producto_pricing.precio_web_transferencia else None,
            markup_web_real=float(producto_pricing.markup_web_real) if producto_pricing and producto_pricing.markup_web_real else None,
        ))

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
    datos: RebateUpdate,  # ← CAMBIAR ESTO
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Actualiza configuración de rebate de un producto"""
    
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    
    if not pricing:
        # Si no existe pricing, crear uno
        pricing = ProductoPricing(
            item_id=item_id,
            participa_rebate=datos.participa_rebate,  # ← CAMBIAR
            porcentaje_rebate=datos.porcentaje_rebate,  # ← CAMBIAR
            usuario_id=current_user.id
        )
        db.add(pricing)
    else:
        pricing.participa_rebate = datos.participa_rebate  # ← CAMBIAR
        pricing.porcentaje_rebate = datos.porcentaje_rebate  # ← CAMBIAR
        pricing.fecha_modificacion = datetime.now()
    
    db.commit()
    db.refresh(pricing)
    
    return {
        "item_id": item_id,
        "participa_rebate": datos.participa_rebate,  # ← CAMBIAR
        "porcentaje_rebate": datos.porcentaje_rebate  # ← CAMBIAR

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
        ProductoPricing.participa_rebate == True
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
            ws.cell(row=row, column=7, value=producto_erp.descripcion or "")
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
    
    # Obtener producto
    producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto_erp:
        raise HTTPException(404, "Producto no encontrado")
    
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    
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
    
    # Si participa, calcular precio
    precio_web = None
    if participa and pricing.markup_calculado is not None:
        tipo_cambio = None
        if producto_erp.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
        
        costo_ars = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)
        markup_clasica = pricing.markup_calculado / 100  # Convertir a decimal (1.94% → 0.0194)
        markup_objetivo = markup_clasica + (porcentaje_markup / 100)  # 0.0194 + 0.06 = 0.0794 (7.94%)
        
        resultado = calcular_precio_web_transferencia(
            costo_ars=costo_ars,
            iva=producto_erp.iva,
            markup_objetivo=markup_objetivo
        )
        
        precio_web = resultado["precio"]
        markup_web_real = resultado["markup_real"]
        pricing.precio_web_transferencia = precio_web
    else:
        pricing.precio_web_transferencia = None
    
    db.commit()
    db.refresh(pricing)
    
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

@router.post("/productos/calcular-web-masivo")
async def calcular_web_masivo(
    request: CalculoWebMasivoRequest,  # ← CAMBIAR
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Calcula precio web transferencia masivamente"""
    from app.services.pricing_calculator import (
        calcular_precio_web_transferencia,
        obtener_tipo_cambio_actual,
        convertir_a_pesos
    )
    
    # Obtener todos los productos
    productos = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    ).all()
    
    procesados = 0
    
    for producto_erp, producto_pricing in productos:
        # Determinar markup a usar
        if producto_pricing and producto_pricing.precio_lista_ml:
            # Tiene precio: sumar porcentaje
            markup_base = (producto_pricing.markup_calculado or 0) / 100
            porcentaje_adicional = request.porcentaje_con_precio  # ← CAMBIAR
        else:
            # No tiene precio: usar porcentaje base
            markup_base = 0
            porcentaje_adicional = request.porcentaje_sin_precio  # ← CAMBIAR
        
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
    
    return {
        "procesados": procesados,
        "porcentaje_con_precio": request.porcentaje_con_precio,  # ← CAMBIAR
        "porcentaje_sin_precio": request.porcentaje_sin_precio  # ← CAMBIAR
    }


@router.post("/productos/limpiar-rebate")
async def limpiar_rebate(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Desactiva rebate en todos los productos"""
    count = db.query(ProductoPricing).update({
        ProductoPricing.participa_rebate: False
        # ← ELIMINAR la línea de precio_rebate
    })
    db.commit()
    
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
    count = db.query(ProductoPricing).update({
        ProductoPricing.participa_web_transferencia: False,
        ProductoPricing.precio_web_transferencia: None,
        ProductoPricing.markup_web_real: None
    })
    db.commit()
    
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
