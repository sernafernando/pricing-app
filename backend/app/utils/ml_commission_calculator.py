"""
Helper centralizado para calcular comisiones de MercadoLibre
Replica EXACTAMENTE la lógica de st_app.py (líneas 464-591)
Obtiene valores de pricing_constants automáticamente

Uso:
    from app.utils.ml_commission_calculator import calcular_comision_ml
"""

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session


def calcular_comision_ml(
    monto_unitario: float,
    cantidad: float,
    iva_porcentaje: float,
    fecha_venta: datetime,
    comision_base_porcentaje: float,
    db_session: Optional[Session] = None,
) -> float:
    """
    Calcula la comisión ML EXACTAMENTE como st_app.py

    Fórmula: (monto * base% + tier_fijo) * qty + varios

    Componentes:
    1. Base: comision_base_porcentaje / 100 / 1.21
    2. Tier: valor fijo según rango (monto_tier1, monto_tier2, monto_tier3)
    3. Varios: varios_porcentaje% del total sin IVA

    Args:
        monto_unitario: Precio de venta unitario (CON IVA)
        cantidad: Cantidad vendida
        iva_porcentaje: Porcentaje de IVA (ej: 10.5 para 10.5%)
        fecha_venta: Fecha de la venta
        comision_base_porcentaje: Porcentaje de comisión base (ej: 15.5 para 15.5%)
        db_session: Sesión de DB (opcional, para obtener pricing_constants)

    Returns:
        Comisión total en pesos (SIN IVA)
    """
    # Obtener constantes de pricing
    if db_session:
        from app.models.pricing_constants import PricingConstants

        constants = (
            db_session.query(PricingConstants)
            .filter(PricingConstants.fecha_desde <= fecha_venta.date())
            .order_by(PricingConstants.fecha_desde.desc())
            .first()
        )

        if constants:
            monto_tier1 = float(constants.monto_tier1)
            monto_tier2 = float(constants.monto_tier2)
            monto_tier3 = float(constants.monto_tier3)
            comision_tier1 = float(constants.comision_tier1)
            comision_tier2 = float(constants.comision_tier2)
            comision_tier3 = float(constants.comision_tier3)
            varios_porcentaje = float(constants.varios_porcentaje)
        else:
            # Fallback a valores por defecto
            monto_tier1 = 15000
            monto_tier2 = 24000
            monto_tier3 = 33000
            comision_tier1 = 1095
            comision_tier2 = 2190
            comision_tier3 = 2628
            varios_porcentaje = 6.5
    else:
        # Sin sesión DB, usar valores por defecto
        monto_tier1 = 15000
        monto_tier2 = 24000
        monto_tier3 = 33000
        comision_tier1 = 1095
        comision_tier2 = 2190
        comision_tier3 = 2628
        varios_porcentaje = 6.5

    # Calcular monto total
    monto_total = monto_unitario * cantidad

    # Monto sin IVA
    total_sin_iva = monto_total / (1 + iva_porcentaje / 100)

    # 1. Comisión base (porcentaje sobre precio / 1.21)
    comision_base_sin_iva = (comision_base_porcentaje / 100) / 1.21

    # 2. Tier (cargo fijo según rango de precio UNITARIO)
    # Los valores de tier vienen CON IVA, hay que dividir por 1.21
    # IMPORTANTE: El tier se calcula por precio unitario, NO por total
    if monto_unitario >= monto_tier3:
        # Por encima de tier3 = sin cargo fijo
        tier_fijo_sin_iva = 0
    elif monto_unitario < monto_tier1:
        # Menor a tier1
        tier_fijo_sin_iva = comision_tier1 / 1.21
    elif monto_unitario < monto_tier2:
        # Entre tier1 y tier2
        tier_fijo_sin_iva = comision_tier2 / 1.21
    elif monto_unitario < monto_tier3:
        # Entre tier2 y tier3
        tier_fijo_sin_iva = comision_tier3 / 1.21
    else:
        tier_fijo_sin_iva = 0

    # 3. Varios (porcentaje del total sin IVA)
    varios_sin_iva = total_sin_iva * (varios_porcentaje / 100)

    # Fórmula final: ((monto * base% + tier) * qty) + varios
    # Como monto_unitario ya incluye la cantidad en monto_total, simplificamos:
    comision_total = (monto_unitario * comision_base_sin_iva + tier_fijo_sin_iva) * cantidad + varios_sin_iva

    return comision_total
