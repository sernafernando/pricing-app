from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.erp_sync import sincronizar_erp
from app.services.ml_sync import sincronizar_publicaciones_ml
from app.services.google_sheets_sync import sincronizar_ofertas_sheets
from typing import Dict

router = APIRouter()

@router.post("/sync")
async def sync_erp(db: Session = Depends(get_db)):
    """Sincroniza productos desde el ERP y precios de ML"""
    try:
        # Sincronizar ERP
        print("=== Iniciando sincronización ERP ===")
        resultado_erp = await sincronizar_erp(db)
        
        # Sincronizar precios de MercadoLibre
        print("=== Iniciando sincronización de precios ML ===")
        from app.services.sync_precios_ml import sincronizar_precios_ml
        resultado_ml = sincronizar_precios_ml(db)
        
        return {
            "status": "success",
            "erp": resultado_erp,
            "precios_ml": resultado_ml
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
        
@router.post("/sync-ml")
async def sincronizar_ml(db: Session = Depends(get_db)):
    """Sincroniza publicaciones de Mercado Libre"""
    try:
        resultado = await sincronizar_publicaciones_ml(db)
        return resultado
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/sync-sheets")
async def sincronizar_sheets(db: Session = Depends(get_db)):
    """Sincroniza ofertas desde Google Sheets"""
    try:
        resultado = sincronizar_ofertas_sheets(db)
        return resultado
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/sync-tipo-cambio")
async def sincronizar_tipo_cambio(db: Session = Depends(get_db)):
    """Sincroniza tipo de cambio desde BNA"""
    try:
        from app.services.tipo_cambio_service import actualizar_tipo_cambio_bna
        resultado = actualizar_tipo_cambio_bna(db)
        return resultado
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/tipo-cambio/actual")
async def obtener_tipo_cambio_actual_endpoint(db: Session = Depends(get_db)):
    """Obtiene el tipo de cambio más reciente"""
    from app.models.tipo_cambio import TipoCambio
    
    tc = db.query(TipoCambio).filter(
        TipoCambio.moneda == "USD"
    ).order_by(TipoCambio.fecha.desc()).first()
    
    if not tc:
        return {"error": "No hay tipo de cambio disponible"}
    
    return {
        "moneda": tc.moneda,
        "compra": tc.compra,
        "venta": tc.venta,
        "fecha": tc.fecha.isoformat()
    }

@router.post("/recalcular-markups")
async def recalcular_markups_endpoint(db: Session = Depends(get_db)):
    """Recalcula markups de todos los productos con precio"""
    from app.models.producto import ProductoERP, ProductoPricing
    from app.services.pricing_calculator import (
        obtener_tipo_cambio_actual, convertir_a_pesos,
        obtener_grupo_subcategoria, obtener_comision_base,
        calcular_comision_ml_total, calcular_limpio,
        calcular_markup, VARIOS_DEFAULT
    )
    
    try:
        actualizados = 0
        errores = 0
        
        pricings = db.query(ProductoPricing).filter(
            ProductoPricing.precio_lista_ml.isnot(None)
        ).all()
        
        for pricing in pricings:
            try:
                producto = db.query(ProductoERP).filter(
                    ProductoERP.item_id == pricing.item_id
                ).first()
                
                if not producto:
                    continue
                
                tipo_cambio = None
                if producto.moneda_costo == "USD":
                    tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
                
                costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
                grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
                comision_base = obtener_comision_base(db, 4, grupo_id)
                
                if not comision_base:
                    continue
                
                comisiones = calcular_comision_ml_total(
                    pricing.precio_lista_ml, 
                    comision_base, 
                    producto.iva, 
                    VARIOS_DEFAULT
                )
                limpio = calcular_limpio(
                    pricing.precio_lista_ml, 
                    producto.iva, 
                    producto.envio or 0, 
                    comisiones["comision_total"]
                )
                markup = calcular_markup(limpio, costo_ars)
                
                pricing.markup_calculado = round(markup * 100, 2)
                actualizados += 1
                
            except Exception as e:
                errores += 1
                continue
        
        db.commit()
        return {"status": "success", "actualizados": actualizados, "errores": errores}
        
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
