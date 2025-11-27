"""
Helper centralizado para calcular métricas ML
Basado en la fórmula que YA FUNCIONA en el sistema

Uso:
    from app.utils.ml_metrics_calculator import calcular_metricas_ml
"""
from typing import Optional


def calcular_metricas_ml(
    monto_unitario: float,
    cantidad: float,
    iva_porcentaje: float,
    costo_unitario_sin_iva: float,
    comision_ml: float,
    costo_envio_ml: Optional[float] = None,
    count_per_pack: int = 1
) -> dict:
    """
    Calcula métricas ML usando la fórmula que ya funciona

    Args:
        monto_unitario: Precio de venta unitario (con IVA)
        cantidad: Cantidad vendida
        iva_porcentaje: Porcentaje de IVA (ej: 10.5)
        costo_unitario_sin_iva: Costo unitario sin IVA
        comision_ml: Comisión ML en pesos (sin IVA)
        costo_envio_ml: Costo de envío (con IVA), None si no aplica
        count_per_pack: Items en el pack

    Returns:
        Dict con: monto_limpio, costo_total, ganancia, markup_porcentaje, costo_envio
    """
    # Costo total
    costo_total_sin_iva = costo_unitario_sin_iva * cantidad

    # Monto total
    monto_total = monto_unitario * cantidad

    # Monto sin IVA
    monto_sin_iva = monto_total / (1 + iva_porcentaje / 100)

    # Costo de envío prorrateado
    costo_envio_prorrateado = 0
    if costo_envio_ml and count_per_pack > 0:
        # Fórmula dashboard: (((Costo envío / 1.21) * Cantidad) / contar_si)
        costo_envio_prorrateado = ((costo_envio_ml / 1.21) * cantidad) / count_per_pack

    # Monto limpio = monto sin IVA - comisión - envío
    monto_limpio = monto_sin_iva - comision_ml - costo_envio_prorrateado

    # Ganancia
    ganancia = monto_limpio - costo_total_sin_iva

    # Markup % - Fórmula dashboard: ((Limpio / costo_total) - 1) * 100
    markup_porcentaje = None
    if costo_total_sin_iva > 0:
        markup_porcentaje = ((monto_limpio / costo_total_sin_iva) - 1) * 100

        # Limitar a rango válido para NUMERIC(10,2)
        if markup_porcentaje > 99999999.99:
            markup_porcentaje = 99999999.99
        elif markup_porcentaje < -99999999.99:
            markup_porcentaje = -99999999.99

    return {
        'monto_limpio': monto_limpio,
        'costo_total_sin_iva': costo_total_sin_iva,
        'ganancia': ganancia,
        'markup_porcentaje': markup_porcentaje or 0,
        'costo_envio': costo_envio_prorrateado
    }
