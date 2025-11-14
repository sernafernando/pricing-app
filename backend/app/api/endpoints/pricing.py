from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing, HistorialPrecio
from app.models.auditoria_precio import AuditoriaPrecio
from app.models.usuario import Usuario
from app.models.configuracion import Configuracion
from app.services.pricing_calculator import (
    calcular_precio_producto,
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    convertir_a_pesos,
    obtener_tipo_cambio_actual,
    obtener_grupo_subcategoria,
    obtener_comision_base,
    precio_por_markup_goalseek
)


router = APIRouter()

def calcular_markup_rebate(db: Session, producto: ProductoERP, pricing: ProductoPricing, tipo_cambio=None) -> Optional[float]:
    """Calcula el markup de rebate para un producto"""
    if not pricing or not pricing.participa_rebate or not pricing.precio_lista_ml or not producto.costo:
        return None

    try:
        porcentaje_rebate_val = float(pricing.porcentaje_rebate if pricing.porcentaje_rebate is not None else 3.8)
        precio_rebate = float(pricing.precio_lista_ml) / (1 - porcentaje_rebate_val / 100)

        costo_rebate = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
        grupo_id_rebate = obtener_grupo_subcategoria(db, producto.subcategoria_id)
        comision_base_rebate = obtener_comision_base(db, 4, grupo_id_rebate)

        if comision_base_rebate and precio_rebate > 0:
            comisiones_rebate = calcular_comision_ml_total(
                precio_rebate,
                comision_base_rebate,
                producto.iva,
                db=db
            )
            limpio_rebate = calcular_limpio(
                precio_rebate,
                producto.iva,
                producto.envio or 0,
                comisiones_rebate["comision_total"],
                db=db,
                grupo_id=grupo_id_rebate
            )
            markup_rebate_val = calcular_markup(limpio_rebate, costo_rebate) * 100
            return markup_rebate_val
    except:
        pass

    return None


def calcular_markup_oferta(db: Session, producto: ProductoERP, tipo_cambio=None) -> Optional[float]:
    """Calcula el markup de oferta vigente para un producto"""
    if not producto.costo:
        return None

    try:
        from app.models.publicacion_ml import PublicacionML
        from app.models.oferta_ml import OfertaML
        from datetime import date

        hoy = date.today()

        # Buscar publicación del producto
        pubs = db.query(PublicacionML).filter(PublicacionML.item_id == producto.item_id).all()

        mejor_oferta = None
        mejor_pub = None

        for pub in pubs:
            oferta = db.query(OfertaML).filter(
                OfertaML.mla == pub.mla,
                OfertaML.fecha_desde <= hoy,
                OfertaML.fecha_hasta >= hoy,
                OfertaML.pvp_seller.isnot(None)
            ).order_by(OfertaML.fecha_desde.desc()).first()

            if oferta:
                if not mejor_oferta:
                    mejor_oferta = oferta
                    mejor_pub = pub

        if mejor_oferta and mejor_pub:
            mejor_oferta_pvp = float(mejor_oferta.pvp_seller) if mejor_oferta.pvp_seller else None

            if mejor_oferta_pvp and mejor_oferta_pvp > 0:
                costo_oferta = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
                grupo_id_oferta = obtener_grupo_subcategoria(db, producto.subcategoria_id)
                comision_base_oferta = obtener_comision_base(db, mejor_pub.pricelist_id, grupo_id_oferta)

                if comision_base_oferta:
                    comisiones_oferta = calcular_comision_ml_total(
                        mejor_oferta_pvp,
                        comision_base_oferta,
                        producto.iva,
                        db=db
                    )
                    limpio_oferta = calcular_limpio(
                        mejor_oferta_pvp,
                        producto.iva,
                        producto.envio or 0,
                        comisiones_oferta["comision_total"],
                        db=db,
                        grupo_id=grupo_id_oferta
                    )
                    markup_oferta_val = calcular_markup(limpio_oferta, costo_oferta) * 100
                    return markup_oferta_val
    except:
        pass

    return None


def obtener_markup_adicional_cuotas(db: Session) -> float:
    """Obtiene el valor de markup adicional para cuotas desde la configuración"""
    config = db.query(Configuracion).filter(
        Configuracion.clave == 'markup_adicional_cuotas'
    ).first()

    if config:
        try:
            return float(config.valor)
        except ValueError:
            return 4.0  # Valor por defecto
    return 4.0  # Valor por defecto si no existe la configuración

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
        db=db
    )

    limpio = calcular_limpio(
        request.precio_manual,
        producto.iva,
        producto.envio or 0,
        comisiones["comision_total"],
        db=db,
        grupo_id=grupo_id
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
    precio_lista_ml: float = Field(gt=0, le=999999999.99)
    motivo: Optional[str] = None
    participa_rebate: Optional[bool] = False
    porcentaje_rebate: Optional[float] = 3.8
    # Precios con cuotas
    precio_3_cuotas: Optional[float] = None
    precio_6_cuotas: Optional[float] = None
    precio_9_cuotas: Optional[float] = None
    precio_12_cuotas: Optional[float] = None

@router.post("/precios/set")
async def setear_precio(
    request: SetPrecioRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
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
        comisiones = calcular_comision_ml_total(request.precio_lista_ml, comision_base, producto.iva, db=db)
        limpio = calcular_limpio(request.precio_lista_ml, producto.iva, producto.envio or 0, comisiones["comision_total"], db=db, grupo_id=grupo_id)
        markup = calcular_markup(limpio, costo_ars)
        markup_calculado = round(markup * 100, 2)

    # Si no se proporcionaron precios de cuotas, calcularlos automáticamente
    precios_cuotas_calculados = {
        'precio_3_cuotas': request.precio_3_cuotas,
        'precio_6_cuotas': request.precio_6_cuotas,
        'precio_9_cuotas': request.precio_9_cuotas,
        'precio_12_cuotas': request.precio_12_cuotas
    }

    # Si al menos uno es None, calcular todos automáticamente
    if any(v is None for v in precios_cuotas_calculados.values()):
        if markup_calculado is not None:
            # Usar la misma función que usa el modal: calcular_precio_producto
            # markup_calculado ya está en porcentaje (ej: 35.5)

            # IDs de pricelists para cuotas
            cuotas_config = {
                'precio_3_cuotas': 17,   # Lista ML PREMIUM 3C
                'precio_6_cuotas': 14,   # Lista ML PREMIUM 6C
                'precio_9_cuotas': 13,   # Lista ML PREMIUM 9C
                'precio_12_cuotas': 23   # Lista ML PREMIUM 12C
            }

            # Obtener markup adicional desde configuración
            markup_adicional = obtener_markup_adicional_cuotas(db)

            for nombre_campo, pricelist_id in cuotas_config.items():
                try:
                    # Usar calcular_precio_producto con adicional_markup desde configuración
                    resultado = calcular_precio_producto(
                        db=db,
                        costo=producto.costo,
                        moneda_costo=producto.moneda_costo,
                        iva=producto.iva,
                        envio=producto.envio or 0,
                        subcategoria_id=producto.subcategoria_id,
                        pricelist_id=pricelist_id,
                        markup_objetivo=markup_calculado,
                        tipo_cambio=tipo_cambio,
                        adicional_markup=markup_adicional
                    )

                    if "error" not in resultado:
                        precio_calculado = round(resultado["precio"], 2)
                        # Solo guardar si el precio es válido (mayor a 0)
                        if precio_calculado > 0:
                            precios_cuotas_calculados[nombre_campo] = precio_calculado
                        else:
                            precios_cuotas_calculados[nombre_campo] = None
                except:
                    # Si falla el cálculo, dejar en None
                    precios_cuotas_calculados[nombre_campo] = None

    if pricing:
        if pricing.precio_lista_ml != request.precio_lista_ml:
                auditoria = AuditoriaPrecio(
                    producto_id=pricing.id,
                    usuario_id=current_user.id,
                    precio_anterior=pricing.precio_lista_ml,
                    precio_contado_anterior=None,  # Por ahora no usamos contado aquí
                    precio_nuevo=request.precio_lista_ml,
                    precio_contado_nuevo=None,
                    comentario=request.motivo
                )
                db.add(auditoria)
            
        historial = HistorialPrecio(
            producto_pricing_id=pricing.id,
            precio_anterior=pricing.precio_lista_ml,
            precio_nuevo=request.precio_lista_ml,
            usuario_id=current_user.id,
            motivo=request.motivo
        )
        db.add(historial)

        pricing.precio_lista_ml = request.precio_lista_ml
        pricing.markup_calculado = markup_calculado
        pricing.usuario_id = current_user.id
        pricing.motivo_cambio = request.motivo
        pricing.fecha_modificacion = datetime.now()
        pricing.participa_rebate = request.participa_rebate
        pricing.porcentaje_rebate = request.porcentaje_rebate
        # Actualizar precios con cuotas (usar los calculados si no se proporcionaron)
        pricing.precio_3_cuotas = precios_cuotas_calculados['precio_3_cuotas']
        pricing.precio_6_cuotas = precios_cuotas_calculados['precio_6_cuotas']
        pricing.precio_9_cuotas = precios_cuotas_calculados['precio_9_cuotas']
        pricing.precio_12_cuotas = precios_cuotas_calculados['precio_12_cuotas']

        # Calcular y actualizar markup_rebate y markup_oferta
        pricing.markup_rebate = calcular_markup_rebate(db, producto, pricing, tipo_cambio)
        pricing.markup_oferta = calcular_markup_oferta(db, producto, tipo_cambio)
    else:
        pricing = ProductoPricing(
            item_id=request.item_id,
            precio_lista_ml=request.precio_lista_ml,
            markup_calculado=markup_calculado,
            usuario_id=current_user.id,
            motivo_cambio=request.motivo,
            participa_rebate=request.participa_rebate,
            porcentaje_rebate=request.porcentaje_rebate,
            precio_3_cuotas=precios_cuotas_calculados['precio_3_cuotas'],
            precio_6_cuotas=precios_cuotas_calculados['precio_6_cuotas'],
            precio_9_cuotas=precios_cuotas_calculados['precio_9_cuotas'],
            precio_12_cuotas=precios_cuotas_calculados['precio_12_cuotas']
        )
        db.add(pricing)
        db.flush()  # Para obtener el ID antes de calcular markups

        # Calcular y actualizar markup_rebate y markup_oferta
        pricing.markup_rebate = calcular_markup_rebate(db, producto, pricing, tipo_cambio)
        pricing.markup_oferta = calcular_markup_oferta(db, producto, tipo_cambio)

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
    precio: float = Query(gt=0, le=999999999.99),
    recalcular_cuotas: bool = Query(True, description="Si True, recalcula precios de cuotas automáticamente"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Setea precio clásica y calcula markup al instante. Opcionalmente recalcula cuotas."""

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
        calcular_markup
    )
    
    costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
    grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
    comision_base = obtener_comision_base(db, 4, grupo_id)  # Lista clásica

    if not comision_base:
        raise HTTPException(400, "No hay comisión configurada")

    comisiones = calcular_comision_ml_total(precio, comision_base, producto.iva, db=db)
    limpio = calcular_limpio(precio, producto.iva, producto.envio or 0, comisiones["comision_total"], db=db, grupo_id=grupo_id)
    markup = calcular_markup(limpio, costo_ars)

    # Calcular precios de cuotas si recalcular_cuotas es True
    precios_cuotas = {'precio_3_cuotas': None, 'precio_6_cuotas': None, 'precio_9_cuotas': None, 'precio_12_cuotas': None}

    if recalcular_cuotas:
        # markup está en decimal (ej: 0.355 para 35.5%), convertir a porcentaje
        markup_porcentaje = round(markup * 100, 2)

        cuotas_config = {
            'precio_3_cuotas': 17,
            'precio_6_cuotas': 14,
            'precio_9_cuotas': 13,
            'precio_12_cuotas': 23
        }

        # Obtener markup adicional desde configuración
        markup_adicional = obtener_markup_adicional_cuotas(db)

        for nombre_campo, pricelist_id in cuotas_config.items():
            try:
                # Usar calcular_precio_producto con goalseek (funciona con markup positivo o negativo)
                resultado = calcular_precio_producto(
                    db=db,
                    costo=producto.costo,
                    moneda_costo=producto.moneda_costo,
                    iva=producto.iva,
                    envio=producto.envio or 0,
                    subcategoria_id=producto.subcategoria_id,
                    pricelist_id=pricelist_id,
                    markup_objetivo=markup_porcentaje,
                    tipo_cambio=tipo_cambio,
                    adicional_markup=markup_adicional
                )

                if "error" not in resultado:
                    precio_calculado = round(resultado["precio"], 2)
                    # Solo guardar si el precio es válido (mayor a 0), el markup puede ser negativo
                    if precio_calculado > 0:
                        precios_cuotas[nombre_campo] = precio_calculado
            except Exception as e:
                # Si falla el cálculo, continuar con el siguiente
                pass

    # Guardar precio
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    
    if pricing:
        if pricing.precio_lista_ml != precio:
                # Registro en tabla vieja
                auditoria = AuditoriaPrecio(
                    producto_id=pricing.id,
                    usuario_id=current_user.id,
                    precio_anterior=pricing.precio_lista_ml,
                    precio_contado_anterior=None,
                    precio_nuevo=precio,
                    precio_contado_nuevo=None,
                    comentario="Edición rápida"
                )
                db.add(auditoria)
                
                # Registro en tabla nueva para filtros
                from app.services.auditoria_service import registrar_auditoria
                from app.models.auditoria import TipoAccion
                
                registrar_auditoria(
                    db=db,
                    usuario_id=current_user.id,
                    tipo_accion=TipoAccion.MODIFICAR_PRECIO_CLASICA,
                    item_id=item_id,
                    valores_anteriores={
                        "precio_lista_ml": float(pricing.precio_lista_ml) if pricing.precio_lista_ml else None
                    },
                    valores_nuevos={
                        "precio_lista_ml": float(precio)
                    }
                )
                
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
        # Actualizar precios de cuotas si se recalcularon
        if recalcular_cuotas:
            pricing.precio_3_cuotas = precios_cuotas['precio_3_cuotas']
            pricing.precio_6_cuotas = precios_cuotas['precio_6_cuotas']
            pricing.precio_9_cuotas = precios_cuotas['precio_9_cuotas']
            pricing.precio_12_cuotas = precios_cuotas['precio_12_cuotas']

        # Calcular y actualizar markup_rebate y markup_oferta
        pricing.markup_rebate = calcular_markup_rebate(db, producto, pricing, tipo_cambio)
        pricing.markup_oferta = calcular_markup_oferta(db, producto, tipo_cambio)
    else:
        pricing = ProductoPricing(
            item_id=item_id,
            precio_lista_ml=precio,
            usuario_id=current_user.id,
            motivo_cambio="Edición rápida",
            precio_3_cuotas=precios_cuotas['precio_3_cuotas'] if recalcular_cuotas else None,
            precio_6_cuotas=precios_cuotas['precio_6_cuotas'] if recalcular_cuotas else None,
            precio_9_cuotas=precios_cuotas['precio_9_cuotas'] if recalcular_cuotas else None,
            precio_12_cuotas=precios_cuotas['precio_12_cuotas'] if recalcular_cuotas else None
        )
        db.add(pricing)
        db.flush()

        # Calcular y actualizar markup_rebate y markup_oferta
        pricing.markup_rebate = calcular_markup_rebate(db, producto, pricing, tipo_cambio)
        pricing.markup_oferta = calcular_markup_oferta(db, producto, tipo_cambio)

    # Recalcular web transferencia si está activo
    # NO hacer refresh aquí porque sobrescribe los valores asignados antes del commit

    if pricing.participa_web_transferencia and pricing.porcentaje_markup_web:
        from app.services.pricing_calculator import calcular_precio_web_transferencia
        markup_base = markup
        markup_objetivo = markup_base + (float(pricing.porcentaje_markup_web) / 100)
        resultado_web = calcular_precio_web_transferencia(
            costo_ars=costo_ars,
            iva=producto.iva,
            markup_objetivo=markup_objetivo
        )
        pricing.precio_web_transferencia = resultado_web["precio"]
        pricing.markup_web_real = resultado_web["markup_real"]

    db.commit()
    db.refresh(pricing)

    # Calcular precio rebate si está activo (solo para respuesta, no se guarda)
    precio_rebate = None
    if pricing.participa_rebate and pricing.porcentaje_rebate:
        precio_rebate = precio / (1 - float(pricing.porcentaje_rebate) / 100)

    response = {
        "item_id": item_id,
        "precio": precio,
        "markup": round(markup * 100, 2),
        "limpio": round(limpio, 2),
        "costo_ars": round(costo_ars, 2),
        "precio_rebate": round(precio_rebate, 2) if precio_rebate else None,
        "precio_web_transferencia": float(pricing.precio_web_transferencia) if pricing.precio_web_transferencia else None,
        "markup_web_real": float(pricing.markup_web_real) if pricing.markup_web_real else None
    }

    # Agregar precios de cuotas si se recalcularon
    if recalcular_cuotas:
        response["precio_3_cuotas"] = precios_cuotas['precio_3_cuotas']
        response["precio_6_cuotas"] = precios_cuotas['precio_6_cuotas']
        response["precio_9_cuotas"] = precios_cuotas['precio_9_cuotas']
        response["precio_12_cuotas"] = precios_cuotas['precio_12_cuotas']

        # Calcular markups de cuotas si los precios fueron calculados
        cuotas_pricelists = [
            (precios_cuotas['precio_3_cuotas'], 17, 'markup_3_cuotas'),
            (precios_cuotas['precio_6_cuotas'], 14, 'markup_6_cuotas'),
            (precios_cuotas['precio_9_cuotas'], 13, 'markup_9_cuotas'),
            (precios_cuotas['precio_12_cuotas'], 23, 'markup_12_cuotas')
        ]

        for precio_cuota, pricelist_id, nombre_markup in cuotas_pricelists:
            if precio_cuota and float(precio_cuota) > 0:
                try:
                    tipo_cambio_cuota = None
                    if producto.moneda_costo == "USD":
                        tipo_cambio_cuota = obtener_tipo_cambio_actual(db, "USD")

                    costo_cuota = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio_cuota)
                    grupo_id_cuota = obtener_grupo_subcategoria(db, producto.subcategoria_id)
                    comision_base_cuota = obtener_comision_base(db, pricelist_id, grupo_id_cuota)

                    if comision_base_cuota:
                        comisiones_cuota = calcular_comision_ml_total(
                            float(precio_cuota),
                            comision_base_cuota,
                            producto.iva,
                            db=db
                        )
                        limpio_cuota = calcular_limpio(
                            float(precio_cuota),
                            producto.iva,
                            producto.envio or 0,
                            comisiones_cuota["comision_total"],
                            db=db,
                            grupo_id=grupo_id_cuota
                        )
                        markup_calculado = calcular_markup(limpio_cuota, costo_cuota) * 100
                        response[nombre_markup] = round(markup_calculado, 2)
                except Exception:
                    response[nombre_markup] = None

    return response

@router.post("/precios/set-cuota")
async def setear_precio_cuota(
    item_id: int,
    tipo_cuota: str = Query(regex="^(3|6|9|12)$"),  # Solo acepta 3, 6, 9 o 12
    precio: float = Query(gt=0, le=999999999.99),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Setea el precio de un tipo de cuota específico y calcula su markup."""

    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")

    # Mapeo de tipo_cuota a campo en la base de datos
    campo_precio = f"precio_{tipo_cuota}_cuotas"
    campo_markup = f"markup_{tipo_cuota}_cuotas"

    # Mapeo de tipo_cuota a pricelist_id
    pricelist_map = {
        '3': 17,
        '6': 14,
        '9': 13,
        '12': 23
    }
    pricelist_id = pricelist_map[tipo_cuota]

    # Obtener TC si es USD
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

    # Calcular markup del precio ingresado
    costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
    grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
    comision_base = obtener_comision_base(db, pricelist_id, grupo_id)

    if not comision_base:
        raise HTTPException(400, "No hay comisión configurada")

    comisiones = calcular_comision_ml_total(precio, comision_base, producto.iva, db=db)
    limpio = calcular_limpio(precio, producto.iva, producto.envio or 0, comisiones["comision_total"], db=db, grupo_id=grupo_id)
    markup = calcular_markup(limpio, costo_ars)
    markup_porcentaje = round(markup * 100, 2)

    # Guardar en la base de datos
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    if pricing:
        # Actualizar el campo correspondiente
        setattr(pricing, campo_precio, precio)
        pricing.usuario_id = current_user.id
        pricing.fecha_modificacion = datetime.now()

        # Calcular y actualizar markup_rebate y markup_oferta
        pricing.markup_rebate = calcular_markup_rebate(db, producto, pricing, tipo_cambio)
        pricing.markup_oferta = calcular_markup_oferta(db, producto, tipo_cambio)
    else:
        # Crear nuevo registro
        pricing = ProductoPricing(
            item_id=item_id,
            usuario_id=current_user.id,
            motivo_cambio=f"Edición cuota {tipo_cuota}"
        )
        setattr(pricing, campo_precio, precio)
        db.add(pricing)
        db.flush()

        # Calcular y actualizar markup_rebate y markup_oferta
        pricing.markup_rebate = calcular_markup_rebate(db, producto, pricing, tipo_cambio)
        pricing.markup_oferta = calcular_markup_oferta(db, producto, tipo_cambio)

    db.commit()
    db.refresh(pricing)

    return {
        "item_id": item_id,
        "tipo_cuota": tipo_cuota,
        campo_precio: precio,
        campo_markup: markup_porcentaje,
        "limpio": round(limpio, 2),
        "costo_ars": round(costo_ars, 2)
    }
