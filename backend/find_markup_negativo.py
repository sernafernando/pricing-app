"""
Buscar el registro con markup -12.34%
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

# Buscar registros con markup cercano a -12.34%
result = db.execute(text("""
    SELECT
        codigo,
        fecha_venta,
        monto_unitario,
        cantidad,
        costo_total_sin_iva,
        comision_ml,
        costo_envio_ml,
        monto_limpio,
        ganancia,
        markup_porcentaje
    FROM ml_ventas_metricas
    WHERE codigo = '6935364080433'
      AND markup_porcentaje BETWEEN -13 AND -12
    ORDER BY fecha_venta DESC
    LIMIT 3
"""))

rows = result.fetchall()

print("=" * 80)
print("REGISTROS CON MARKUP -12.34%")
print("=" * 80)

for row in rows:
    print(f"\nCódigo: {row.codigo}")
    print(f"Fecha: {row.fecha_venta}")
    print(f"Monto unitario: ${row.monto_unitario:,.2f}")
    print(f"Cantidad: {row.cantidad}")
    print(f"Costo total: ${row.costo_total_sin_iva:,.2f}")
    print(f"Comisión ML: ${row.comision_ml:,.2f}")
    print(f"Costo envío: ${row.costo_envio_ml:,.2f}")
    print(f"Monto limpio: ${row.monto_limpio:,.2f}")
    print(f"Ganancia: ${row.ganancia:,.2f}")
    print(f"Markup: {row.markup_porcentaje:.2f}%")
    print("-" * 80)

    # Recalcular manualmente para verificar
    monto_sin_iva = row.monto_unitario * row.cantidad / 1.105
    print(f"Monto sin IVA (verificación): ${monto_sin_iva:,.2f}")

    envio_prorrateado = row.costo_envio_ml
    print(f"Envío prorrateado: ${envio_prorrateado:,.2f}")

    limpio_verificado = monto_sin_iva - row.comision_ml - envio_prorrateado
    print(f"Limpio (verificación): ${limpio_verificado:,.2f}")

    ganancia_verificada = limpio_verificado - row.costo_total_sin_iva
    print(f"Ganancia (verificación): ${ganancia_verificada:,.2f}")

    markup_verificado = ((limpio_verificado / row.costo_total_sin_iva) - 1) * 100 if row.costo_total_sin_iva > 0 else 0
    print(f"Markup (verificación): {markup_verificado:.2f}%")

db.close()
