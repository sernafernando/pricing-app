from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing, HistorialPrecio
from app.services.pricing_calculator import (
    calcular_precio_producto,
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    convertir_a_pesos,
    obtener_tipo_cambio_actual,
    obtener_grupo_subcategoria,
    obtener_comision_base,
    VARIOS_DEFAULT
)

router = APIRouter()

class CalcularPorMarkupRequest(BaseModel):
    item_id: int
    pricelist_id: int
    markup_objetivo: float
    adicional_markup: Optional[float] = 4.0

class CalcularPorPrecioRequest(BaseModel):
    item_id: int
    pricelist_id: int
    precio_manual: float

@router.post("/precios/calcular-por-markup")
async def calcular_por_markup(
    request: CalcularPorMarkupRequest,
    db: Session = Depends(get_db)
):
    """Dado un markup objetivo, calcula el precio necesario"""
    
    producto = db.query(ProductoERP).filter(
        ProductoERP.item_id == request.item_id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
        if not tipo_cambio:
            raise HTTPException(400, "No hay tipo de cambio disponible")
    
    resultado = calcular_precio_producto(
        db=db,
        costo=producto.costo,
        moneda_costo=producto.moneda_costo,
        iva=producto.iva,
        envio=producto.envio or 0,
        subcategoria_id=producto.subcategoria_id,
        pricelist_id=request.pricelist_id,
        markup_objetivo=request.markup_objetivo,
        tipo_cambio=tipo_cambio,
        adicional_markup=request.adicional_markup
    )
    
    if "error" in resultado:
        raise HTTPException(400, resultado["error"])
    
    return {
        "modo": "por_markup",
        "item_id": request.item_id,
        "producto": {
            "descripcion": producto.descripcion,
            "marca": producto.marca,
            "categoria": producto.categoria
        },
        **resultado
    }

@router.post("/precios/calcular-por-precio")
async def calcular_por_precio(
    request: CalcularPorPrecioRequest,
    db: Session = Depends(get_db)
):
    """Dado un precio manual, calcula qué markup resulta"""
    
    producto = db.query(ProductoERP).filter(
        ProductoERP.item_id == request.item_id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    # Obtener TC si es necesario
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
        if not tipo_cambio:
            raise HTTPException(400, "No hay tipo de cambio disponible")
    
    # Convertir costo a pesos
    costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
    
    # Obtener grupo y comisión
    grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
    comision_base = obtener_comision_base(db, request.pricelist_id, grupo_id)
    
    if comision_base is None:
        raise HTTPException(400, f"No hay comisión configurada para lista {request.pricelist_id} y grupo {grupo_id}")
    
    # Calcular comisiones y markup con el precio dado
    comisiones = calcular_comision_ml_total(
        request.precio_manual,
        comision_base,
        producto.iva,
        VARIOS_DEFAULT
    )
    
    limpio = calcular_limpio(
        request.precio_manual,
        producto.iva,
        producto.envio or 0,
        comisiones["comision_total"]
    )
    
    markup_resultante = calcular_markup(limpio, costo_ars)
    
    return {
        "modo": "por_precio",
        "item_id": request.item_id,
        "producto": {
            "descripcion": producto.descripcion,
            "marca": producto.marca,
            "categoria": producto.categoria
        },
        "precio_manual": request.precio_manual,
        "costo_ars": round(costo_ars, 2),
        "tipo_cambio": tipo_cambio,
        "grupo_id": grupo_id,
        "pricelist_id": request.pricelist_id,
        "comision_base_pct": comision_base,
        "comision_total": round(comisiones["comision_total"], 2),
        "tier": round(comisiones["tier"], 2),
        "comision_varios": round(comisiones["comision_varios"], 2),
        "limpio": round(limpio, 2),
        "markup_resultante": round(markup_resultante * 100, 2)
    }

class SetPrecioRequest(BaseModel):
    item_id: int
    precio_lista_ml: float
    motivo: Optional[str] = None
    usuario_id: Optional[int] = 1

@router.post("/precios/set")
async def setear_precio(
    request: SetPrecioRequest,
    db: Session = Depends(get_db)
):
    """Setea el precio de lista ML para un producto"""

    producto = db.query(ProductoERP).filter(
        ProductoERP.item_id == request.item_id
    ).first()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    pricing = db.query(ProductoPricing).filter(
        ProductoPricing.item_id == request.item_id
    ).first()

    # Calcular markup
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
    
    costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
    grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
    comision_base = obtener_comision_base(db, 4, grupo_id)
    
    markup_calculado = None
    if comision_base:
        comisiones = calcular_comision_ml_total(request.precio_lista_ml, comision_base, producto.iva, VARIOS_DEFAULT)
        limpio = calcular_limpio(request.precio_lista_ml, producto.iva, producto.envio or 0, comisiones["comision_total"])
        markup = calcular_markup(limpio, costo_ars)
        markup_calculado = round(markup * 100, 2)

    if pricing:
        historial = HistorialPrecio(
            producto_pricing_id=pricing.id,
            precio_anterior=pricing.precio_lista_ml,
            precio_nuevo=request.precio_lista_ml,
            usuario_id=request.usuario_id,
            motivo=request.motivo
        )
        db.add(historial)

        pricing.precio_lista_ml = request.precio_lista_ml
        pricing.markup_calculado = markup_calculado
        pricing.usuario_id = request.usuario_id
        pricing.motivo_cambio = request.motivo
        pricing.fecha_modificacion = datetime.now()
    else:
        pricing = ProductoPricing(
            item_id=request.item_id,
            precio_lista_ml=request.precio_lista_ml,
            markup_calculado=markup_calculado,
            usuario_id=request.usuario_id,
            motivo_cambio=request.motivo
        )
        db.add(pricing)

    db.commit()
    db.refresh(pricing)

    return {
        "item_id": request.item_id,
        "precio_lista_ml": request.precio_lista_ml,
        "markup": markup_calculado,
        "actualizado": pricing.fecha_modificacion
    }

@router.get("/precios/historial/{item_id}")
async def obtener_historial(
    item_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene el histórico de cambios de precio"""
    
    pricing = db.query(ProductoPricing).filter(
        ProductoPricing.item_id == item_id
    ).first()
    
    if not pricing:
        return {"historial": []}
    
    historial = db.query(HistorialPrecio).filter(
        HistorialPrecio.producto_pricing_id == pricing.id
    ).order_by(HistorialPrecio.timestamp.desc()).all()
    
    return {
        "item_id": item_id,
        "precio_actual": pricing.precio_lista_ml,
        "historial": [
            {
                "precio_anterior": h.precio_anterior,
                "precio_nuevo": h.precio_nuevo,
                "timestamp": h.timestamp,
                "motivo": h.motivo
            }
            for h in historial
        ]
    }

class CalcularPreciosCompletosRequest(BaseModel):
    item_id: int
    markup_objetivo: float
    adicional_cuotas: Optional[float] = 4.0
    # Mapeo de cuotas a pricelist_id
    pricelist_clasica: int = 4      # Lista para clásica
    pricelist_3_cuotas: int = 17    # Lista ML PREMIUM 3C
    pricelist_6_cuotas: int = 14    # Lista ML PREMIUM 6C
    pricelist_9_cuotas: int = 13    # Lista ML PREMIUM 9C
    pricelist_12_cuotas: int = 23   # Lista ML PREMIUM 12C

@router.post("/precios/calcular-completo")
async def calcular_precios_completos(
    request: CalcularPreciosCompletosRequest,
    db: Session = Depends(get_db)
):
    """
    Calcula precio clásica + todos los precios en cuotas
    Clásica usa markup objetivo directo
    Cuotas usan markup objetivo + adicional
    """
    
    producto = db.query(ProductoERP).filter(
        ProductoERP.item_id == request.item_id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
        if not tipo_cambio:
            raise HTTPException(400, "No hay tipo de cambio disponible")
    
    resultado = {
        "item_id": request.item_id,
        "producto": {
            "descripcion": producto.descripcion,
            "marca": producto.marca,
            "categoria": producto.categoria,
            "costo": producto.costo,
            "moneda_costo": producto.moneda_costo
        },
        "markup_objetivo": request.markup_objetivo,
        "adicional_cuotas": request.adicional_cuotas,
    }
    
    # CLÁSICA - sin adicional
    clasica = calcular_precio_producto(
        db=db,
        costo=producto.costo,
        moneda_costo=producto.moneda_costo,
        iva=producto.iva,
        envio=producto.envio or 0,
        subcategoria_id=producto.subcategoria_id,
        pricelist_id=request.pricelist_clasica,
        markup_objetivo=request.markup_objetivo,
        tipo_cambio=tipo_cambio,
        adicional_markup=0  # SIN adicional para clásica
    )
    
    if "error" in clasica:
        raise HTTPException(400, clasica["error"])
    
    resultado["clasica"] = clasica
    
    # CUOTAS - con adicional
    cuotas_config = {
        "3_cuotas": request.pricelist_3_cuotas,
        "6_cuotas": request.pricelist_6_cuotas,
        "9_cuotas": request.pricelist_9_cuotas,
        "12_cuotas": request.pricelist_12_cuotas
    }
    
    resultado["cuotas"] = {}
    
    for nombre_cuota, pricelist_id in cuotas_config.items():
        calculo = calcular_precio_producto(
            db=db,
            costo=producto.costo,
            moneda_costo=producto.moneda_costo,
            iva=producto.iva,
            envio=producto.envio or 0,
            subcategoria_id=producto.subcategoria_id,
            pricelist_id=pricelist_id,
            markup_objetivo=request.markup_objetivo,
            tipo_cambio=tipo_cambio,
            adicional_markup=request.adicional_cuotas  # CON adicional para cuotas
        )
        
        if "error" not in calculo:
            resultado["cuotas"][nombre_cuota] = calculo
    
    return resultado

@router.post("/precios/set-rapido")
async def setear_precio_rapido(
    item_id: int,
    precio: float,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Setea precio clásica y calcula markup al instante"""
    
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")
    
    # Obtener TC si es USD
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
    
    # Calcular markup del precio ingresado
    from app.services.pricing_calculator import (
        convertir_a_pesos,
        obtener_grupo_subcategoria,
        obtener_comision_base,
        calcular_comision_ml_total,
        calcular_limpio,
        calcular_markup,
        VARIOS_DEFAULT
    )
    
    costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
    grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
    comision_base = obtener_comision_base(db, 4, grupo_id)  # Lista clásica
    
    if not comision_base:
        raise HTTPException(400, "No hay comisión configurada")
    
    comisiones = calcular_comision_ml_total(precio, comision_base, producto.iva, VARIOS_DEFAULT)
    limpio = calcular_limpio(precio, producto.iva, producto.envio or 0, comisiones["comision_total"])
    markup = calcular_markup(limpio, costo_ars)
    
    # Guardar precio
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    
    if pricing:
        historial = HistorialPrecio(
            producto_pricing_id=pricing.id,
            precio_anterior=pricing.precio_lista_ml,
            precio_nuevo=precio,
            usuario_id=current_user.id,
            motivo="Edición rápida"
        )
        db.add(historial)
        pricing.precio_lista_ml = precio
        pricing.markup_calculado = round(markup * 100, 2)
        pricing.usuario_id = current_user.id
        pricing.fecha_modificacion = datetime.now()
    else:
        pricing = ProductoPricing(
            item_id=item_id,
            precio_lista_ml=precio,
            usuario_id=current_user.id,
            motivo_cambio="Edición rápida"
        )
        db.add(pricing)
    
    db.commit()
    
    return {
        "item_id": item_id,
        "precio": precio,
        "markup": round(markup * 100, 2),
        "limpio": round(limpio, 2),
        "costo_ars": round(costo_ars, 2)
    }
