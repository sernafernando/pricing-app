from typing import Dict, Optional, Tuple
from app.models.tipo_cambio import TipoCambio
from app.models.comision_config import SubcategoriaGrupo, ComisionListaGrupo
from sqlalchemy.orm import Session
from datetime import date
import math

# Constantes de tiers de ML
MONTOT1 = 15000
MONTOT2 = 24000
MONTOT3 = 33000
TIER1 = 1095
TIER2 = 2190
TIER3 = 2628
VARIOS_DEFAULT = 6.5
GRUPO_DEFAULT = 1  # Grupo por defecto si la subcategoría no está asignada

def obtener_tipo_cambio_actual(db: Session, moneda: str = "USD") -> Optional[float]:
    """Obtiene el tipo de cambio de venta actual"""
    tc = db.query(TipoCambio).filter(
        TipoCambio.moneda == moneda,
        TipoCambio.fecha == date.today()
    ).first()
    
    if tc:
        return tc.venta
    
    tc = db.query(TipoCambio).filter(
        TipoCambio.moneda == moneda
    ).order_by(TipoCambio.fecha.desc()).first()
    
    return tc.venta if tc else None

def convertir_a_pesos(costo: float, moneda: str, tipo_cambio: Optional[float]) -> float:
    """Convierte costo a pesos argentinos"""
    if moneda == "ARS":
        return costo
    if tipo_cambio:
        return costo * tipo_cambio
    return costo

def obtener_grupo_subcategoria(db: Session, subcategoria_id: int) -> int:
    """Obtiene el grupo al que pertenece una subcategoría. Si no existe, retorna grupo 1"""
    mapping = db.query(SubcategoriaGrupo).filter(
        SubcategoriaGrupo.subcat_id == subcategoria_id
    ).first()
    return mapping.grupo_id if mapping else GRUPO_DEFAULT

def obtener_comision_base(db: Session, pricelist_id: int, grupo_id: int) -> Optional[float]:
    """Obtiene la comisión base para una lista y grupo específicos"""
    comision = db.query(ComisionListaGrupo).filter(
        ComisionListaGrupo.pricelist_id == pricelist_id,
        ComisionListaGrupo.grupo_id == grupo_id
    ).first()
    return comision.comision_porcentaje if comision else None

def calcular_comision_ml_total(
    precio: float,
    comision_base_pct: float,
    iva: float,
    varios_pct: float = VARIOS_DEFAULT
) -> Dict[str, float]:
    """Calcula comisión ML + tiers + varios"""
    
    comision_base = precio * (comision_base_pct / 100) / 1.21
    
    tier = 0
    if precio < MONTOT1:
        tier = TIER1 / 1.21
    elif precio < MONTOT2:
        tier = TIER2 / 1.21
    elif precio < MONTOT3:
        tier = TIER3 / 1.21
    
    comision_con_tier = comision_base if precio >= MONTOT3 else comision_base + tier
    comision_varios = (precio / (1 + iva / 100)) * (varios_pct / 100)
    comision_total = comision_con_tier + comision_varios
    
    return {
        "comision_base": comision_base,
        "tier": tier,
        "comision_varios": comision_varios,
        "comision_total": comision_total
    }

def calcular_limpio(precio: float, iva: float, costo_envio: float, comision_total: float) -> float:
    """Calcula limpio"""
    precio_sin_iva = precio / (1 + iva / 100)
    envio_sin_iva = (costo_envio / 1.21) if precio >= MONTOT3 else 0
    return precio_sin_iva - envio_sin_iva - comision_total

def calcular_markup(limpio: float, costo: float) -> float:
    """Calcula markup"""
    if costo == 0:
        return 0
    return (limpio / costo) - 1

def precio_por_markup_goalseek(
    costo: float,
    markup_objetivo: float,
    iva: float,
    comision_ml: float,
    varios: float,
    costo_envio: float
) -> float:
    """Goal seek: dado un markup objetivo, encuentra el precio necesario"""
    
    if costo <= 0 or markup_objetivo <= 0:
        return 0
    
    markup_objetivo_decimal = markup_objetivo / 100
    
    precio_min = costo
    precio_max = costo * 10
    precio = (precio_min + precio_max) / 2
    
    for iteracion in range(50):
        comisiones = calcular_comision_ml_total(precio, comision_ml, iva, varios)
        limpio = calcular_limpio(precio, iva, costo_envio, comisiones["comision_total"])
        markup_actual = calcular_markup(limpio, costo)
        
        diferencia = markup_objetivo_decimal - markup_actual
        
        if abs(diferencia) < 0.001:
            return round(precio)
        
        if markup_actual < markup_objetivo_decimal:
            precio_min = precio
        else:
            precio_max = precio
        
        precio = (precio_min + precio_max) / 2
        
        if precio_max - precio_min < 1:
            return round(precio)
    
    return round(precio)

def calcular_precio_producto(
    db: Session,
    costo: float,
    moneda_costo: str,
    iva: float,
    envio: float,
    subcategoria_id: int,
    pricelist_id: int,
    markup_objetivo: float,
    tipo_cambio: Optional[float] = None,
    adicional_markup: float = 4.0
) -> Dict:
    """Calcula precio usando comisiones de la base de datos"""
    
    costo_ars = convertir_a_pesos(costo, moneda_costo, tipo_cambio)
    
    # Obtener grupo (usa grupo 1 si no está asignado)
    grupo_id = obtener_grupo_subcategoria(db, subcategoria_id)
    
    # Obtener comisión base
    comision_base = obtener_comision_base(db, pricelist_id, grupo_id)
    if comision_base is None:
        return {
            "error": f"No hay comisión configurada para lista {pricelist_id} y grupo {grupo_id}",
            "costo_ars": round(costo_ars, 2),
            "grupo_id": grupo_id
        }
    
    markup_total = markup_objetivo + adicional_markup



    precio = precio_por_markup_goalseek(
        costo=costo_ars,
        markup_objetivo=markup_total,
        iva=iva,
        comision_ml=comision_base,
        varios=VARIOS_DEFAULT,
        costo_envio=envio
    )

    comisiones = calcular_comision_ml_total(precio, comision_base, iva, VARIOS_DEFAULT)
    limpio = calcular_limpio(precio, iva, envio, comisiones["comision_total"])
    markup_real = calcular_markup(limpio, costo_ars)

    return {
        "precio": precio,
        "costo_ars": round(costo_ars, 2),
        "tipo_cambio": tipo_cambio,
        "grupo_id": grupo_id,
        "pricelist_id": pricelist_id,
        "comision_base_pct": comision_base,
        "comision_total": round(comisiones["comision_total"], 2),
        "tier": round(comisiones["tier"], 2),
        "comision_varios": round(comisiones["comision_varios"], 2),
        "limpio": round(limpio, 2),
        "markup_objetivo": markup_objetivo,
        "markup_real": round(markup_real * 100, 2),
        "adicional_markup": adicional_markup
    }



def calcular_precio_web_transferencia(costo_ars: float, iva: float, markup_objetivo: float, max_iter: int = 100) -> dict:
    COMISION_WEB = 0.0073
    IIBB = 0.05
    TOLERANCIA = 0.0001
    
    # Convertir IVA de porcentaje a decimal si viene como 10.5, 21, etc
    iva_decimal = iva / 100 if iva > 1 else iva
    
    # Precio inicial
    precio = costo_ars * (1 + iva_decimal) * (1 + markup_objetivo) * 1.1
    
    for i in range(max_iter):
        # 1. Comisión sobre precio con IVA
        comision = precio * COMISION_WEB
        
        # 2. Precio sin IVA
        precio_sin_iva = precio / (1 + iva_decimal)
        
        # 3. IIBB sobre precio sin IVA
        iibb = precio_sin_iva * IIBB
        
        # 4. Limpio con IVA
        limpio_con_iva = precio - comision - iibb
        
        # 5. Limpio sin IVA
        limpio_sin_iva = limpio_con_iva / (1 + iva_decimal)
        
        # 6. Markup real
        markup_real = (limpio_sin_iva - costo_ars) / costo_ars if costo_ars > 0 else 0
        
        # Verificar convergencia
        if abs(markup_real - markup_objetivo) < TOLERANCIA:
                # Redondear a múltiplo de 10
                precio_redondeado = round(precio / 10) * 10
                
                # Recalcular markup real con el precio redondeado
                comision_final = precio_redondeado * COMISION_WEB
                precio_sin_iva_final = precio_redondeado / (1 + iva_decimal)
                iibb_final = precio_sin_iva_final * IIBB
                limpio_con_iva_final = precio_redondeado - comision_final - iibb_final
                limpio_sin_iva_final = limpio_con_iva_final / (1 + iva_decimal)
                markup_real_final = (limpio_sin_iva_final - costo_ars) / costo_ars if costo_ars > 0 else 0
                
                return {
                    "precio": precio_redondeado,
                    "markup_real": round(markup_real_final * 100, 2),
                    "iteraciones": i + 1,
                    "convergio": True
                }

        # Ajustar
        factor = (1 + markup_objetivo) / (1 + markup_real) if markup_real > 0 else 1.1
        precio = precio * factor
    
    # Si no converge, también redondear
    precio_redondeado = round(precio / 10) * 10
    
    # Recalcular markup real con el precio redondeado
    comision_final = precio_redondeado * COMISION_WEB
    precio_sin_iva_final = precio_redondeado / (1 + iva_decimal)
    iibb_final = precio_sin_iva_final * IIBB
    limpio_con_iva_final = precio_redondeado - comision_final - iibb_final
    limpio_sin_iva_final = limpio_con_iva_final / (1 + iva_decimal)
    markup_real_final = (limpio_sin_iva_final - costo_ars) / costo_ars if costo_ars > 0 else 0
    
    return {
        "precio": round(precio_redondeado, 0),
        "markup_real": round(markup_real_final * 100, 2),
        "iteraciones": max_iter,
        "convergio": False
    }
