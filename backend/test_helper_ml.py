"""
Script de prueba para el helper de métricas ML
Usa los valores del dashboard para verificar que el cálculo sea correcto
"""
import sys
from pathlib import Path
from datetime import datetime

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

from app.utils.ml_metrics_calculator import calcular_metricas_ml
from app.core.database import SessionLocal

# Datos de la venta del dashboard (código 6935364080433)
# Dashboard muestra:
# - Comisión: 7,638.60 pesos
# - Markup: 0.46%

print("=" * 80)
print("PRUEBA HELPER ML - Valores del Dashboard")
print("=" * 80)

# Valores de la operación (del dashboard)
monto_unitario = 40865.0  # Precio de venta con IVA
cantidad = 1
iva_porcentaje = 10.5
costo_unitario_sin_iva = 24780.0  # Costo sin IVA
costo_envio_ml = 5383.0  # Costo de envío CON IVA
count_per_pack = 1

# Datos para calcular comisión dinámicamente
fecha_venta = datetime(2025, 11, 26)
comision_base_porcentaje = 15.5

print(f"\nDatos de entrada:")
print(f"  Monto unitario (con IVA): ${monto_unitario:,.2f}")
print(f"  Cantidad: {cantidad}")
print(f"  IVA: {iva_porcentaje}%")
print(f"  Costo unitario sin IVA: ${costo_unitario_sin_iva:,.2f}")
print(f"  Fecha venta: {fecha_venta.date()}")
print(f"  Comisión base %: {comision_base_porcentaje}%")

# Calcular métricas con sesión de DB
db = SessionLocal()
try:
    metricas = calcular_metricas_ml(
        monto_unitario=monto_unitario,
        cantidad=cantidad,
        iva_porcentaje=iva_porcentaje,
        costo_unitario_sin_iva=costo_unitario_sin_iva,
        costo_envio_ml=costo_envio_ml,
        count_per_pack=count_per_pack,
        fecha_venta=fecha_venta,
        comision_base_porcentaje=comision_base_porcentaje,
        db_session=db
    )
finally:
    db.close()

print(f"\n{'=' * 80}")
print("RESULTADOS:")
print(f"{'=' * 80}")
print(f"  Comisión ML calculada: ${metricas['comision_ml']:,.2f}")
print(f"  Monto limpio: ${metricas['monto_limpio']:,.2f}")
print(f"  Costo total: ${metricas['costo_total_sin_iva']:,.2f}")
print(f"  Ganancia: ${metricas['ganancia']:,.2f}")
print(f"  Markup: {metricas['markup_porcentaje']:.2f}%")

print(f"\n{'=' * 80}")
print("COMPARACIÓN CON DASHBOARD:")
print(f"{'=' * 80}")
comision_dashboard = 7638.60
markup_dashboard = 0.46

diff_comision = metricas['comision_ml'] - comision_dashboard
diff_markup = metricas['markup_porcentaje'] - markup_dashboard

print(f"  Comisión Dashboard: ${comision_dashboard:,.2f}")
print(f"  Diferencia comisión: ${diff_comision:,.2f} ({abs(diff_comision/comision_dashboard*100):.2f}%)")
print(f"\n  Markup Dashboard: {markup_dashboard:.2f}%")
print(f"  Diferencia markup: {diff_markup:.2f}% puntos")

# Verificar si está dentro del margen aceptable (0.2%)
if abs(diff_markup) <= 0.2:
    print(f"\n  ✅ DENTRO DEL MARGEN ACEPTABLE (≤0.2%)")
else:
    print(f"\n  ❌ FUERA DEL MARGEN ACEPTABLE (>{0.2}%)")

print()
