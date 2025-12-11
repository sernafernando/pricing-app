"""
Debug: Calcular markup paso a paso con los valores del ejemplo
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

# Valores del ejemplo
precio_unitario = 33889  # con IVA
cantidad = 1
costo_sin_iva = 18766.65
iva = 10.5
comision_base_pct = 15.5
costo_envio = 5421.49  # con IVA

# Constantes (valores actuales)
monto_tier3 = 33000
varios_pct = 6.5

print("=" * 80)
print("CÁLCULO MANUAL (como debería ser)")
print("=" * 80)

# Paso 1: Precio sin IVA
precio_sin_iva = precio_unitario / (1 + iva / 100)
print(f"1. Precio sin IVA: {precio_unitario} / 1.{iva} = ${precio_sin_iva:,.2f}")

# Paso 2: Comisión base
comision_base = (precio_unitario * (comision_base_pct / 100)) / 1.21
print(f"2. Comisión base: ({precio_unitario} * {comision_base_pct}% / 1.21) = ${comision_base:,.2f}")

# Paso 3: Tier
tier = 0  # >= monto_tier3
print(f"3. Tier: $0 (precio {precio_unitario} >= tier3 {monto_tier3})")

# Paso 4: Varios
varios = precio_sin_iva * (varios_pct / 100)
print(f"4. Varios: {precio_sin_iva:,.2f} * {varios_pct}% = ${varios:,.2f}")

# Paso 5: Comisión total
comision_total = comision_base + tier + varios
print(f"5. Comisión total: {comision_base:,.2f} + {tier} + {varios:,.2f} = ${comision_total:,.2f}")

# Paso 6: Envío sin IVA (solo si >= tier3)
envio_sin_iva = costo_envio / 1.21 if precio_unitario >= monto_tier3 else 0
print(f"6. Envío sin IVA: {costo_envio} / 1.21 = ${envio_sin_iva:,.2f}")

# Paso 7: Limpio
limpio = precio_sin_iva - envio_sin_iva - comision_total
print(f"7. Limpio: {precio_sin_iva:,.2f} - {envio_sin_iva:,.2f} - {comision_total:,.2f} = ${limpio:,.2f}")

# Paso 8: Markup
markup = ((limpio / costo_sin_iva) - 1) * 100
print(f"8. Markup: ({limpio:,.2f} / {costo_sin_iva:,.2f} - 1) * 100 = {markup:.2f}%")

print("\n" + "=" * 80)
print("CÁLCULO CON HELPERS DEL BACKEND")
print("=" * 80)

from datetime import datetime
from app.core.database import SessionLocal
from app.utils.ml_commission_calculator import calcular_comision_ml
from app.utils.ml_metrics_calculator import calcular_metricas_ml

db = SessionLocal()

# Calcular comisión con el helper
comision_helper = calcular_comision_ml(
    monto_unitario=precio_unitario,
    cantidad=cantidad,
    iva_porcentaje=iva,
    fecha_venta=datetime.now(),
    comision_base_porcentaje=comision_base_pct,
    db_session=db
)
print(f"Comisión (helper): ${comision_helper:,.2f}")

# Calcular métricas con el helper
metricas = calcular_metricas_ml(
    monto_unitario=precio_unitario,
    cantidad=cantidad,
    iva_porcentaje=iva,
    costo_unitario_sin_iva=costo_sin_iva,
    costo_envio_ml=costo_envio,
    fecha_venta=datetime.now(),
    comision_base_porcentaje=comision_base_pct,
    db_session=db
)

print(f"Comisión ML: ${metricas['comision_ml']:,.2f}")
print(f"Costo envío: ${metricas['costo_envio']:,.2f}")
print(f"Monto limpio: ${metricas['monto_limpio']:,.2f}")
print(f"Markup: {metricas['markup_porcentaje']:.2f}%")

db.close()

print("\n" + "=" * 80)
print("DIFERENCIAS")
print("=" * 80)
print(f"Comisión esperada: ${comision_total:,.2f} vs Helper: ${comision_helper:,.2f} -> Diff: ${comision_helper - comision_total:,.2f}")
print(f"Limpio esperado: ${limpio:,.2f} vs Helper: ${metricas['monto_limpio']:,.2f} -> Diff: ${metricas['monto_limpio'] - limpio:,.2f}")
print(f"Markup esperado: {markup:.2f}% vs Helper: {metricas['markup_porcentaje']:.2f}% -> Diff: {metricas['markup_porcentaje'] - markup:.2f}%")
