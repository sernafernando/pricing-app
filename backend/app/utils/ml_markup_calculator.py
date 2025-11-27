"""
Helper centralizado para calcular markup de MercadoLibre
Replica la lógica exacta de st_app.py para garantizar consistencia

Uso:
    from app.utils.ml_markup_calculator import calcular_markup_ml, calcular_limpio_ml
"""
from typing import Optional


def calcular_limpio_ml(
    monto_unitario: float,
    cantidad: float,
    iva_porcentaje: float,
    comision_pesos: float,
    costo_envio_total: Optional[float] = None,
    count_per_pack: int = 1,
    min_free: float = 0,
    ml_logistic_type: Optional[str] = None,
    gasto_envio_flex: float = 0,
    ganancia_flex: float = 0,
    usar_flex: bool = False
) -> float:
    """
    Calcula el monto limpio según la lógica del dashboard (st_app.py líneas 625-642)

    Args:
        monto_unitario: Precio de venta unitario (con IVA)
        cantidad: Cantidad vendida
        iva_porcentaje: Porcentaje de IVA (ej: 10.5 para 10.5%)
        comision_pesos: Comisión ML en pesos (ya sin IVA)
        costo_envio_total: Costo total del envío (con IVA), None si no hay envío
        count_per_pack: Cantidad de items en el pack
        min_free: Monto mínimo para envío gratis
        ml_logistic_type: Tipo de logística ML ('self_service', 'cross_docking', 'fulfillment', None)
        gasto_envio_flex: Gasto de envío Flex
        ganancia_flex: Ganancia de envío Flex
        usar_flex: Si se deben aplicar cálculos Flex

    Returns:
        Monto limpio (monto después de restar comisión y costos de envío)
    """
    # Monto sin IVA
    monto_sin_iva = (monto_unitario / (1 + iva_porcentaje / 100)) * cantidad

    # Si no hay envío, retornar directo
    if costo_envio_total is None or count_per_pack == 0:
        return monto_sin_iva - comision_pesos

    # Calcular costo de envío prorrateado
    # Fórmula st_app.py:634: (((Costo envío / 1.21) * Cantidad) / contar_si)
    costo_envio_sin_iva = costo_envio_total / 1.21
    costo_envio_prorrateado = (costo_envio_sin_iva * cantidad) / count_per_pack

    # Aplicar lógica de envío según tipo
    if monto_unitario >= min_free:
        if ml_logistic_type == 'self_service' and usar_flex:
            # Flex con envío gratis
            return monto_sin_iva - gasto_envio_flex / count_per_pack - comision_pesos
        else:
            # Envío gratis normal
            return monto_sin_iva - costo_envio_prorrateado - comision_pesos
    else:
        if ml_logistic_type == 'self_service' and usar_flex:
            # Flex sin envío gratis
            return monto_sin_iva + ganancia_flex / count_per_pack - comision_pesos
        else:
            # Sin envío gratis normal
            return monto_sin_iva - comision_pesos


def calcular_markup_ml(
    monto_limpio: float,
    costo_total_sin_iva: float
) -> Optional[float]:
    """
    Calcula el markup según la lógica del dashboard (st_app.py líneas 655-659)

    Args:
        monto_limpio: Monto limpio calculado con calcular_limpio_ml()
        costo_total_sin_iva: Costo total del producto sin IVA (costo unitario * cantidad)

    Returns:
        Markup porcentual, o None si el costo es 0
    """
    # Fórmula st_app.py:659: ((Limpio / costo_total) - 1) * 100
    if costo_total_sin_iva == 0:
        return None

    return ((monto_limpio / costo_total_sin_iva) - 1) * 100


def calcular_metricas_ml_completas(
    monto_unitario: float,
    cantidad: float,
    iva_porcentaje: float,
    costo_unitario_sin_iva: float,
    comision_pesos: float,
    costo_envio_total: Optional[float] = None,
    count_per_pack: int = 1,
    **kwargs
) -> dict:
    """
    Calcula todas las métricas ML de una vez

    Args:
        monto_unitario: Precio de venta unitario (con IVA)
        cantidad: Cantidad vendida
        iva_porcentaje: Porcentaje de IVA
        costo_unitario_sin_iva: Costo unitario sin IVA
        comision_pesos: Comisión ML en pesos (sin IVA)
        costo_envio_total: Costo total del envío (con IVA)
        count_per_pack: Cantidad de items en el pack
        **kwargs: Argumentos adicionales para calcular_limpio_ml (min_free, ml_logistic_type, etc.)

    Returns:
        Dict con todas las métricas: monto_limpio, costo_total, ganancia, markup_porcentaje
    """
    costo_total_sin_iva = costo_unitario_sin_iva * cantidad

    monto_limpio = calcular_limpio_ml(
        monto_unitario=monto_unitario,
        cantidad=cantidad,
        iva_porcentaje=iva_porcentaje,
        comision_pesos=comision_pesos,
        costo_envio_total=costo_envio_total,
        count_per_pack=count_per_pack,
        **kwargs
    )

    ganancia = monto_limpio - costo_total_sin_iva
    markup_porcentaje = calcular_markup_ml(monto_limpio, costo_total_sin_iva)

    return {
        'monto_limpio': monto_limpio,
        'costo_total_sin_iva': costo_total_sin_iva,
        'ganancia': ganancia,
        'markup_porcentaje': markup_porcentaje
    }
