from typing import Dict, Optional, Tuple
from app.models.tipo_cambio import TipoCambio
from app.models.comision_config import SubcategoriaGrupo, ComisionListaGrupo
from app.models.comision_versionada import ComisionVersion, ComisionBase, ComisionAdicionalCuota
from app.models.pricing_constants import PricingConstants
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import date
import math

# Constantes de tiers de ML (valores por defecto si no hay en BD)
MONTOT1 = 15000
MONTOT2 = 24000
MONTOT3 = 33000
TIER1 = 1095
TIER2 = 2190
TIER3 = 2628
VARIOS_DEFAULT = 6.5
GRUPO_DEFAULT = 1  # Grupo por defecto si la subcategoría no está asignada

def obtener_constantes_pricing(db: Session) -> Dict[str, float]:
    """Obtiene las constantes de pricing vigentes desde la base de datos"""
    # Ordenar por fecha_desde DESC para tomar la versión más reciente si hay múltiples vigentes
    constants = db.query(PricingConstants).filter(
        and_(
            PricingConstants.fecha_desde <= date.today(),
            or_(
                PricingConstants.fecha_hasta.is_(None),
                PricingConstants.fecha_hasta >= date.today()
            )
        )
    ).order_by(PricingConstants.fecha_desde.desc()).first()

    if constants:
        return {
            "monto_tier1": float(constants.monto_tier1),
            "monto_tier2": float(constants.monto_tier2),
            "monto_tier3": float(constants.monto_tier3),
            "tier1": float(constants.comision_tier1),
            "tier2": float(constants.comision_tier2),
            "tier3": float(constants.comision_tier3),
            "varios": float(constants.varios_porcentaje),
            "grupo_default": constants.grupo_comision_default,
            "markup_adicional_cuotas": float(constants.markup_adicional_cuotas)
        }

    # Valores por defecto si no hay constantes en BD
    return {
        "monto_tier1": MONTOT1,
        "monto_tier2": MONTOT2,
        "monto_tier3": MONTOT3,
        "tier1": TIER1,
        "tier2": TIER2,
        "tier3": TIER3,
        "varios": VARIOS_DEFAULT,
        "grupo_default": GRUPO_DEFAULT,
        "markup_adicional_cuotas": 4.0
    }

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

def obtener_envio_promedio_grupo(db: Session, grupo_id: int) -> float:
    """Obtiene el costo de envío promedio para productos activos de un grupo

    Args:
        db: Sesión de base de datos
        grupo_id: ID del grupo de comisión

    Returns:
        Costo de envío promedio del grupo, o 0 si no hay datos
    """
    from app.models.producto import ProductoERP
    from sqlalchemy import func

    # Obtener subcategorías del grupo
    subcategorias = db.query(SubcategoriaGrupo.subcat_id).filter(
        SubcategoriaGrupo.grupo_id == grupo_id
    ).all()

    if not subcategorias:
        return 0.0

    subcat_ids = [s[0] for s in subcategorias]

    # Calcular promedio de envío para productos activos con envío > 0
    resultado = db.query(func.avg(ProductoERP.envio)).filter(
        ProductoERP.subcategoria_id.in_(subcat_ids),
        ProductoERP.activo == True,
        ProductoERP.envio > 0
    ).scalar()

    return float(resultado) if resultado else 0.0

def obtener_comision_versionada(db: Session, grupo_id: int, pricelist_id: int, fecha: Optional[date] = None) -> Optional[float]:
    """
    Obtiene la comisión para un grupo y pricelist en una fecha específica.
    Usa el sistema versionado de comisiones.

    Args:
        db: Sesión de base de datos
        grupo_id: ID del grupo de comisión
        pricelist_id: ID de la lista de precios (4=clasica, 17=3c, 14=6c, 13=9c, 23=12c)
        fecha: Fecha para la cual obtener comisión (por defecto hoy)

    Returns:
        Comisión en porcentaje (ej: 15.5 para 15.5%) o None si no se encuentra
    """
    if fecha is None:
        fecha = date.today()

    # Obtener versión vigente para la fecha
    version = db.query(ComisionVersion).filter(
        and_(
            ComisionVersion.fecha_desde <= fecha,
            or_(
                ComisionVersion.fecha_hasta.is_(None),
                ComisionVersion.fecha_hasta >= fecha
            ),
            ComisionVersion.activo == True
        )
    ).first()

    if not version:
        # Fallback al sistema antiguo si no hay versión
        return obtener_comision_base_legacy(db, pricelist_id, grupo_id)

    # Obtener comisión base para este grupo
    comision_base_obj = db.query(ComisionBase).filter(
        and_(
            ComisionBase.version_id == version.id,
            ComisionBase.grupo_id == grupo_id
        )
    ).first()

    if not comision_base_obj:
        return None

    comision_base = float(comision_base_obj.comision_base)

    # Si es lista 4 (clásica), retornar solo la base
    if pricelist_id == 4:
        return comision_base

    # Mapeo de pricelist_id a cantidad de cuotas
    pricelist_to_cuotas = {
        17: 3,   # ML PREMIUM 3C
        14: 6,   # ML PREMIUM 6C
        13: 9,   # ML PREMIUM 9C
        23: 12   # ML PREMIUM 12C
    }

    cuotas = pricelist_to_cuotas.get(pricelist_id)
    if cuotas is None:
        # Si no es una lista de cuotas conocida, retornar la base
        return comision_base

    # Obtener adicional para estas cuotas
    adicional_obj = db.query(ComisionAdicionalCuota).filter(
        and_(
            ComisionAdicionalCuota.version_id == version.id,
            ComisionAdicionalCuota.cuotas == cuotas
        )
    ).first()

    if not adicional_obj:
        return comision_base

    adicional = float(adicional_obj.adicional)
    return comision_base + adicional

def obtener_comision_base_legacy(db: Session, pricelist_id: int, grupo_id: int) -> Optional[float]:
    """Función legacy para obtener comisiones del sistema antiguo (fallback)"""
    comision = db.query(ComisionListaGrupo).filter(
        ComisionListaGrupo.pricelist_id == pricelist_id,
        ComisionListaGrupo.grupo_id == grupo_id,
        ComisionListaGrupo.activo == True
    ).first()
    return float(comision.comision_porcentaje) if comision else None

def obtener_comision_base(db: Session, pricelist_id: int, grupo_id: int, fecha: Optional[date] = None) -> Optional[float]:
    """
    Obtiene la comisión base para una lista y grupo específicos.
    Ahora usa el sistema versionado con fallback al legacy.
    """
    return obtener_comision_versionada(db, grupo_id, pricelist_id, fecha)

def calcular_comision_ml_total(
    precio: float,
    comision_base_pct: float,
    iva: float,
    varios_pct: float = VARIOS_DEFAULT,
    db: Optional[Session] = None,
    constantes: Optional[Dict] = None
) -> Dict[str, float]:
    """Calcula comisión ML + tiers + varios"""

    # Obtener constantes de pricing (de BD si está disponible)
    if constantes is None and db is not None:
        constantes = obtener_constantes_pricing(db)

    # Usar valores de constantes o defaults
    if constantes:
        MONTOT1_val = constantes["monto_tier1"]
        MONTOT2_val = constantes["monto_tier2"]
        MONTOT3_val = constantes["monto_tier3"]
        TIER1_val = constantes["tier1"]
        TIER2_val = constantes["tier2"]
        TIER3_val = constantes["tier3"]
        varios_pct = constantes["varios"]
    else:
        MONTOT1_val = MONTOT1
        MONTOT2_val = MONTOT2
        MONTOT3_val = MONTOT3
        TIER1_val = TIER1
        TIER2_val = TIER2
        TIER3_val = TIER3

    comision_base = precio * (comision_base_pct / 100) / 1.21

    tier = 0
    if precio < MONTOT1_val:
        tier = TIER1_val / 1.21
    elif precio < MONTOT2_val:
        tier = TIER2_val / 1.21
    elif precio < MONTOT3_val:
        tier = TIER3_val / 1.21

    comision_con_tier = comision_base if precio >= MONTOT3_val else comision_base + tier
    comision_varios = (precio / (1 + iva / 100)) * (varios_pct / 100)
    comision_total = comision_con_tier + comision_varios

    return {
        "comision_base": comision_base,
        "tier": tier,
        "comision_varios": comision_varios,
        "comision_total": comision_total
    }

def calcular_limpio(
    precio: float,
    iva: float,
    costo_envio: float,
    comision_total: float,
    db: Optional[Session] = None,
    constantes: Optional[Dict] = None,
    grupo_id: Optional[int] = None
) -> float:
    """Calcula limpio

    Args:
        precio: Precio de venta
        iva: IVA en porcentaje (ej: 21)
        costo_envio: Costo de envío del producto
        comision_total: Comisión total calculada
        db: Sesión de base de datos (opcional)
        constantes: Constantes de pricing (opcional)
        grupo_id: ID del grupo para obtener envío promedio si costo_envio = 0 (opcional)

    Returns:
        Limpio (ganancia neta antes de markup)
    """
    # Obtener constantes de pricing (de BD si está disponible)
    if constantes is None and db is not None:
        constantes = obtener_constantes_pricing(db)

    MONTOT3_val = constantes["monto_tier3"] if constantes else MONTOT3

    precio_sin_iva = precio / (1 + iva / 100)

    # Si el precio >= MONTOT3 (envío gratis), restar el costo de envío
    if precio >= MONTOT3_val:
        # Si el producto no tiene costo de envío asignado pero tenemos grupo_id,
        # usar el envío promedio del grupo
        if costo_envio == 0 and grupo_id is not None and db is not None:
            costo_envio = obtener_envio_promedio_grupo(db, grupo_id)

        envio_sin_iva = costo_envio / 1.21
    else:
        envio_sin_iva = 0

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
    costo_envio: float,
    db: Optional[Session] = None,
    grupo_id: Optional[int] = None
) -> float:
    """Goal seek: dado un markup objetivo, encuentra el precio necesario

    Funciona con markups positivos y negativos.
    """

    if costo <= 0:
        return 0

    markup_objetivo_decimal = markup_objetivo / 100

    # Para markups negativos, permitir precios más altos
    # (porque con comisiones altas, incluso precios > costo pueden dar markup negativo)
    if markup_objetivo < 0:
        precio_min = costo * 0.5
        precio_max = costo * 5
    else:
        precio_min = costo
        precio_max = costo * 10

    precio = (precio_min + precio_max) / 2

    for iteracion in range(50):
        comisiones = calcular_comision_ml_total(precio, comision_ml, iva, varios, db=db)
        limpio = calcular_limpio(precio, iva, costo_envio, comisiones["comision_total"], db=db, grupo_id=grupo_id)
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

    # Obtener constantes de pricing de la BD
    constantes = obtener_constantes_pricing(db)
    varios = constantes["varios"]

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
        varios=varios,
        costo_envio=envio,
        db=db,
        grupo_id=grupo_id
    )

    comisiones = calcular_comision_ml_total(precio, comision_base, iva, db=db)
    limpio = calcular_limpio(precio, iva, envio, comisiones["comision_total"], db=db, grupo_id=grupo_id)
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
