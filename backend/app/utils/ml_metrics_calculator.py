"""
Helper centralizado para calcular métricas ML
Usa la fórmula EXACTA de pricing de productos

Uso:
    from app.utils.ml_metrics_calculator import calcular_metricas_ml
"""

from typing import Optional
from datetime import datetime
from app.utils.ml_commission_calculator import calcular_comision_ml


def calcular_metricas_ml(
    monto_unitario: float,
    cantidad: float,
    iva_porcentaje: float,
    costo_unitario_sin_iva: float,
    comision_ml: Optional[float] = None,
    costo_envio_ml: Optional[float] = None,
    count_per_pack: int = 1,
    # Parámetros opcionales para calcular comisión dinámicamente
    subcat_id: Optional[int] = None,
    pricelist_id: Optional[int] = None,
    fecha_venta: Optional[datetime] = None,
    comision_base_porcentaje: Optional[float] = None,
    db_session=None,  # Sesión de DB para pricing_constants
    # Parámetros para offset Flex
    ml_logistic_type: Optional[str] = None,
) -> dict:
    """
    Calcula métricas ML usando la fórmula EXACTA de pricing de productos

    Args:
        monto_unitario: Precio de venta unitario (con IVA)
        cantidad: Cantidad vendida
        iva_porcentaje: Porcentaje de IVA (ej: 10.5)
        costo_unitario_sin_iva: Costo unitario sin IVA
        comision_ml: Comisión ML en pesos (sin IVA) - OPCIONAL si se pasan subcat_id y pricelist_id
        costo_envio_ml: Costo de envío del producto (con IVA), None si no aplica
        count_per_pack: Items en el pack (DEPRECADO - no se usa)
        subcat_id: ID de subcategoría (para calcular comisión dinámicamente)
        pricelist_id: ID de pricelist (para calcular comisión dinámicamente)
        fecha_venta: Fecha de la venta (para calcular comisión dinámicamente)
        comision_base_porcentaje: Porcentaje base de comisión (para calcular comisión dinámicamente)
        ml_logistic_type: Tipo de logística ML ('self_service' = Flex, 'fulfillment' = Full, etc.)

    Returns:
        Dict con: monto_limpio, costo_total, ganancia, markup_porcentaje, costo_envio, comision_ml, offset_flex
    """
    # Si no se pasó comisión pero sí los datos para calcularla
    if comision_ml is None and all([fecha_venta, comision_base_porcentaje is not None]):
        comision_ml = calcular_comision_ml(
            monto_unitario=monto_unitario,
            cantidad=cantidad,
            iva_porcentaje=iva_porcentaje,
            fecha_venta=fecha_venta,
            comision_base_porcentaje=comision_base_porcentaje,
            db_session=db_session,
        )
    elif comision_ml is None:
        raise ValueError("Debe proporcionar comision_ml O (fecha_venta + comision_base_porcentaje)")

    # Costo total sin IVA (costo × cantidad)
    costo_total_sin_iva = costo_unitario_sin_iva * cantidad

    # Obtener monto_tier3 y offset_flex desde pricing_constants
    monto_tier3 = 33000  # Default
    offset_flex_valor = None  # Monto fijo offset Flex (configurable en panel Constantes Pricing)
    if db_session:
        from app.models.pricing_constants import PricingConstants

        constants = (
            db_session.query(PricingConstants)
            .filter(PricingConstants.fecha_desde <= fecha_venta.date())
            .order_by(PricingConstants.fecha_desde.desc())
            .first()
        )
        if constants:
            monto_tier3 = float(constants.monto_tier3)
            if constants.offset_flex is not None:
                offset_flex_valor = float(constants.offset_flex)

    # Costo de envío sin IVA - SOLO si precio >= monto_tier3 (envío gratis)
    # El pricing calcula por unidad, pero en ventas se multiplica por cantidad
    envio_unitario_sin_iva = 0
    if monto_unitario >= monto_tier3 and costo_envio_ml:
        envio_unitario_sin_iva = costo_envio_ml / 1.21

    costo_envio_sin_iva = envio_unitario_sin_iva * cantidad

    # FÓRMULA DE LIMPIO (exactamente como pricing de productos):
    # (precio_sin_iva - envio_sin_iva - comision_unitaria) * cantidad
    unitario_sin_iva = monto_unitario / (1 + iva_porcentaje / 100)
    comision_unitaria = comision_ml / cantidad
    limpio_unitario = unitario_sin_iva - envio_unitario_sin_iva - comision_unitaria
    monto_limpio = limpio_unitario * cantidad

    # Ganancia
    ganancia = monto_limpio - costo_total_sin_iva

    # Offset Flex: se aplica a ventas con logística self_service (Flex)
    # cuando el precio unitario con IVA es MENOR que monto_tier3 (envío gratis).
    # El offset es un monto fijo POR ENVÍO (no por unidad), ya que Flex cobra
    # un único costo de envío independientemente de la cantidad de unidades.
    offset_flex_total = 0
    if offset_flex_valor is not None and ml_logistic_type == "self_service" and monto_unitario < monto_tier3:
        offset_flex_total = offset_flex_valor

    # Markup % - Fórmula: (limpio / costo) - 1
    markup_porcentaje = None
    if costo_total_sin_iva > 0:
        markup_porcentaje = ((monto_limpio / costo_total_sin_iva) - 1) * 100

        # Limitar a rango válido para NUMERIC(10,2)
        if markup_porcentaje > 99999999.99:
            markup_porcentaje = 99999999.99
        elif markup_porcentaje < -99999999.99:
            markup_porcentaje = -99999999.99

    return {
        "monto_limpio": monto_limpio,
        "costo_total_sin_iva": costo_total_sin_iva,
        "ganancia": ganancia,
        "markup_porcentaje": markup_porcentaje or 0,
        "costo_envio": costo_envio_sin_iva,
        "comision_ml": comision_ml,
        "offset_flex": offset_flex_total,
    }
