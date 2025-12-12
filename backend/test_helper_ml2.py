"""
Script de prueba para el helper de métricas ML - Operación 2
Código: 4895252500875
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

print("=" * 80)
print("PRUEBA HELPER ML - Operación 2")
print("=" * 80)

# Datos de la operación (de la tabla que pasaste)
codigo = "4895252500875"
monto_unitario = 70800.3  # Precio de venta con IVA
cantidad = 1
iva_porcentaje = 10.5
costo_unitario_sin_iva = 38291.0  # Costo sin IVA
costo_envio_ml = 0  # Parece que es 0 según la tabla
count_per_pack = 1

# Datos para calcular comisión dinámicamente
# Necesitamos averiguar estos valores... asumiendo defaults similares
fecha_venta = datetime.now()  # Asumiendo fecha actual
comision_base_porcentaje = 15.5  # Valor común

print(f"\nDatos de entrada:")
print(f"  Código: {codigo}")
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
        costo_envio_ml=costo_envio_ml if costo_envio_ml > 0 else None,
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
print("VALORES ESPERADOS (de la tabla):")
print(f"{'=' * 80}")
# Los valores en la tabla parecen estar corruptos/incorrectos
# Comisión y Limpio tienen números gigantes
print(f"  Markup esperado: 32.77%")
print(f"  Costo total esperado: ${38291:,.2f}")

print()
