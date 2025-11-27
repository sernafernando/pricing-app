"""
Helper centralizado para calcular comisiones de MercadoLibre
Replica EXACTAMENTE la lógica de st_app.py (líneas 464-591)

Uso:
    from app.utils.ml_commission_calculator import calcular_comision_ml
"""
from datetime import datetime
from typing import Optional


def calcular_comision_ml(
    monto_unitario: float,
    cantidad: float,
    iva_porcentaje: float,
    fecha_venta: datetime,
    comision_base_porcentaje: float,
    varios_porcentaje: float = 6.5,
    # Parámetros de configuración (vienen de pricing_constants o secrets)
    min_fijo: float = 18000,
    max_fijo: float = 28000,
    min_free: float = 39000,
    valor_fijo: float = 1490,
    valor_max_fijo: float = 2480,
    valor_free: float = 1490,
) -> float:
    """
    Calcula la comisión ML EXACTAMENTE como st_app.py

    La fórmula es: ((monto * base_pct_sin_iva + fijo_val) * qty) + varios

    Args:
        monto_unitario: Precio de venta unitario (CON IVA)
        cantidad: Cantidad vendida
        iva_porcentaje: Porcentaje de IVA (ej: 10.5)
        fecha_venta: Fecha de la venta (para determinar período)
        comision_base_porcentaje: Porcentaje de comisión base (ej: 15.5 para 15.5%)
        varios_porcentaje: Porcentaje de "varios" (default 6.5%)
        min_fijo: Umbral mínimo para tarifa fija
        max_fijo: Umbral máximo para tarifa fija
        min_free: Umbral para envío gratis/sin tarifa fija
        valor_fijo: Valor fijo para montos < min_fijo
        valor_max_fijo: Valor fijo para montos entre min_fijo y max_fijo
        valor_free: Valor fijo para montos >= max_fijo y < min_free

    Returns:
        Comisión total en pesos (SIN IVA)
    """
    # Calcular monto total sin IVA
    total_sin_iva = (monto_unitario * cantidad) / (1 + iva_porcentaje / 100)

    # Comisión base sin IVA
    comision_base_sin_iva = (comision_base_porcentaje / 100) / 1.21

    # Varios sin IVA
    varios_sin_iva = total_sin_iva * (varios_porcentaje / 100)

    # Valores fijos sin IVA
    valor_fijo_sin_iva = valor_fijo / 1.21
    valor_max_fijo_sin_iva = valor_max_fijo / 1.21
    valor_free_sin_iva = valor_free / 1.21

    # Determinar período según fecha (lógica de st_app.py líneas 499-505)
    # Para simplificar, usamos el período actual (desde oct 2025)
    # Si necesitas períodos históricos, agregar lógica de fechas aquí

    if fecha_venta >= datetime(2025, 10, 6):
        # Período actual (desde oct 2025) - st_app.py líneas 577-586
        varios_actual = varios_sin_iva
    elif fecha_venta >= datetime(2025, 9, 3):
        # Septiembre 2025 - st_app.py líneas 565-575
        varios_actual = varios_sin_iva
        # Valores diferentes para Q3
        valor_fijo_sin_iva = 2628 / 1.21
        valor_max_fijo_sin_iva = 2190 / 1.21
        valor_free_sin_iva = 2628 / 1.21
        min_fijo = 15000
        max_fijo = 24000
        min_free = 33000
    elif fecha_venta >= datetime(2025, 8, 4):
        # Agosto 2025 - st_app.py líneas 553-563
        varios_actual = varios_sin_iva
        valor_fijo_sin_iva = 2628 / 1.21
        valor_max_fijo_sin_iva = 2190 / 1.21
        valor_free_sin_iva = 2628 / 1.21
        min_fijo = 15000
        max_fijo = 24000
        min_free = 33000
    elif fecha_venta >= datetime(2025, 3, 11):
        # Q1 2025 - st_app.py líneas 541-551
        varios_actual = total_sin_iva * 0.055  # 5.5%
        valor_fijo_sin_iva = 1000 / 1.21
        valor_max_fijo_sin_iva = 2000 / 1.21
        valor_free_sin_iva = 1000 / 1.21
        min_fijo = 15000
        max_fijo = 24000
        min_free = 33000
    elif fecha_venta >= datetime(2025, 2, 26):
        # Feb 26 - Mar 10, 2025 - st_app.py líneas 529-539
        varios_actual = varios_sin_iva
        valor_fijo_sin_iva = 900 / 1.21
        valor_max_fijo_sin_iva = 1800 / 1.21
        valor_free_sin_iva = 0.0
        min_fijo = 12000
        max_fijo = 30000
        min_free = float('inf')  # nunca se cumple
    else:
        # Antes de feb 26, 2025 - st_app.py líneas 517-527
        varios_actual = varios_sin_iva
        valor_fijo_sin_iva = 900 / 1.21
        valor_max_fijo_sin_iva = 1800 / 1.21
        valor_free_sin_iva = 0.0
        min_fijo = 12000
        max_fijo = 30000
        min_free = float('inf')

    # Determinar valor fijo según umbral (st_app.py líneas 509-514)
    if monto_unitario >= min_free:
        # Envío gratis / sin cargo fijo
        fijo_val = 0.0
    elif monto_unitario < min_fijo:
        # Monto bajo
        fijo_val = valor_fijo_sin_iva
    elif monto_unitario < max_fijo:
        # Monto medio
        fijo_val = valor_max_fijo_sin_iva
    else:
        # Monto alto pero < min_free
        fijo_val = valor_free_sin_iva

    # Fórmula final (st_app.py línea 515)
    comision_total = ((monto_unitario * comision_base_sin_iva + fijo_val) * cantidad) + varios_actual

    return comision_total
