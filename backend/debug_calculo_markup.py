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
from app.models.pricing_constants import PricingConstants

db = SessionLocal()

# Ver qué constantes está usando
constants = db.query(PricingConstants).filter(
    PricingConstants.fecha_desde <= datetime.now().date()
).order_by(PricingConstants.fecha_desde.desc()).first()

print(f"\nConstantes de BD:")
print(f"  monto_tier1: {constants.monto_tier1}")
print(f"  monto_tier2: {constants.monto_tier2}")
print(f"  monto_tier3: {constants.monto_tier3}")
print(f"  comision_tier1: {constants.comision_tier1}")
print(f"  comision_tier2: {constants.comision_tier2}")
print(f"  comision_tier3: {constants.comision_tier3}")
print(f"  varios_porcentaje: {constants.varios_porcentaje}")

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

# Debug: Ver paso a paso qué hace el helper
print("\n" + "=" * 80)
print("DEBUG DETALLADO DEL HELPER")
print("=" * 80)

# Simular lo que hace el helper internamente
monto_total = precio_unitario * cantidad
total_sin_iva_helper = monto_total / (1 + iva / 100)
print(f"total_sin_iva (helper): {total_sin_iva_helper:,.2f}")

# Comisión base
comision_base_sin_iva = (comision_base_pct / 100) / 1.21
print(f"comision_base_sin_iva (factor): {comision_base_sin_iva:.6f}")

# Tier
if precio_unitario >= monto_tier3:
    tier_fijo = 0
else:
    tier_fijo = 2810 / 1.21  # Usar valor de BD
print(f"tier_fijo_sin_iva: {tier_fijo:,.2f}")

# Varios
varios_helper = total_sin_iva_helper * (7.0 / 100)  # Usar 7% de BD
print(f"varios_sin_iva: {varios_helper:,.2f}")

# Comisión total (como lo hace ml_commission_calculator.py línea 109)
comision_total_helper = (precio_unitario * comision_base_sin_iva + tier_fijo) * cantidad + varios_helper
print(f"comision_total (helper formula): {comision_total_helper:,.2f}")

# Envío
envio_unitario_helper = costo_envio / 1.21 if precio_unitario >= monto_tier3 else 0
costo_envio_helper = envio_unitario_helper * cantidad
print(f"envio_unitario_sin_iva: {envio_unitario_helper:,.2f}")
print(f"costo_envio_total: {costo_envio_helper:,.2f}")

# Limpio (como lo hace ml_metrics_calculator.py líneas 83-86)
unitario_sin_iva_helper = precio_unitario / (1 + iva / 100)
comision_unitaria_helper = comision_total_helper / cantidad
limpio_unitario_helper = unitario_sin_iva_helper - envio_unitario_helper - comision_unitaria_helper
monto_limpio_helper = limpio_unitario_helper * cantidad
print(f"unitario_sin_iva: {unitario_sin_iva_helper:,.2f}")
print(f"comision_unitaria: {comision_unitaria_helper:,.2f}")
print(f"limpio_unitario: {limpio_unitario_helper:,.2f}")
print(f"monto_limpio: {monto_limpio_helper:,.2f}")

# Markup
costo_total_sin_iva_helper = costo_sin_iva * cantidad
markup_helper = ((monto_limpio_helper / costo_total_sin_iva_helper) - 1) * 100
print(f"costo_total: {costo_total_sin_iva_helper:,.2f}")
print(f"markup: {markup_helper:.2f}%")

db.close()

print("\n" + "=" * 80)
print("DIFERENCIAS")
print("=" * 80)
print(f"Comisión esperada: ${comision_total:,.2f} vs Helper: ${comision_helper:,.2f} -> Diff: ${comision_helper - comision_total:,.2f}")
print(f"Limpio esperado: ${limpio:,.2f} vs Helper: ${metricas['monto_limpio']:,.2f} -> Diff: ${metricas['monto_limpio'] - limpio:,.2f}")
print(f"Markup esperado: {markup:.2f}% vs Helper: {metricas['markup_porcentaje']:.2f}% -> Diff: {metricas['markup_porcentaje'] - markup:.2f}%")
