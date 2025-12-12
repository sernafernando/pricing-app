"""
Verificar valores guardados para 6935364070854
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()

result = db.execute(text("""
    SELECT
        codigo,
        fecha_venta,
        monto_total,
        costo_envio_ml,
        comision_ml,
        monto_limpio,
        markup_porcentaje,
        fecha_calculo
    FROM ml_ventas_metricas
    WHERE codigo = '6935364070854'
      AND fecha_venta >= '2025-11-26'
    ORDER BY fecha_calculo DESC, fecha_venta
    LIMIT 10
"""))

print("=" * 120)
print("VALORES GUARDADOS PARA PRODUCTO 6935364070854")
print("=" * 120)
print(f"{'Fecha Venta':<20} | {'Monto Total':>12} | {'Costo Envío':>12} | {'Comisión':>12} | {'Limpio':>12} | {'Markup':>8} | Fecha Cálculo")
print("-" * 120)

for row in result.fetchall():
    print(f"{str(row.fecha_venta)[:19]:<20} | ${row.monto_total:>11,.2f} | ${row.costo_envio_ml:>11,.2f} | ${row.comision_ml:>11,.2f} | ${row.monto_limpio:>11,.2f} | {row.markup_porcentaje:>7.2f}% | {row.fecha_calculo}")

print("\n" + "=" * 120)
print("VALORES ESPERADOS DEL DASHBOARD")
print("=" * 120)
print("Ventas de $30k-$31k: Costo Envío = $0.00, Markup entre -2.57% y 1.98%")

db.close()
