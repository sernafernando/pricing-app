"""
Verificar qué valores se guardaron para la venta 6935364080433
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

# Buscar la venta en ml_ventas_metricas
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
    ORDER BY fecha_venta DESC
    LIMIT 1
"""))

row = result.fetchone()

print("=" * 80)
print("VALORES GUARDADOS EN ml_ventas_metricas")
print("=" * 80)
if row:
    print(f"Código: {row.codigo}")
    print(f"Fecha: {row.fecha_venta}")
    print(f"Monto unitario: ${row.monto_unitario:,.2f}")
    print(f"Cantidad: {row.cantidad}")
    print(f"Costo total: ${row.costo_total_sin_iva:,.2f}")
    print(f"Comisión ML: ${row.comision_ml:,.2f}")
    print(f"Costo envío: ${row.costo_envio_ml:,.2f}")
    print(f"Monto limpio: ${row.monto_limpio:,.2f}")
    print(f"Ganancia: ${row.ganancia:,.2f}")
    print(f"Markup: {row.markup_porcentaje:.2f}%")

    # Calcular costo unitario
    costo_unitario = row.costo_total_sin_iva / row.cantidad if row.cantidad > 0 else 0
    print(f"\nCosto unitario (calculado): ${costo_unitario:,.2f}")
else:
    print("No se encontró el registro")

# Buscar el producto en productos_pricing para ver el markup_calculado
result2 = db.execute(text("""
    SELECT
        pp.markup_calculado,
        pe.costo,
        pe.moneda_costo
    FROM productos_pricing pp
    JOIN productos_erp pe ON pe.item_id = pp.item_id
    WHERE pe.codigo = '6935364080433'
    LIMIT 1
"""))

row2 = result2.fetchone()

print("\n" + "=" * 80)
print("DATOS DEL PRODUCTO")
print("=" * 80)
if row2:
    print(f"Markup calculado (esperado): {row2.markup_calculado:.2f}%")
    print(f"Costo en productos_erp: ${row2.costo:,.2f}")
    print(f"Moneda: {row2.moneda_costo}")
else:
    print("No se encontró el producto")

print("\n" + "=" * 80)
print("VALORES ESPERADOS (del dashboard)")
print("=" * 80)
print("Monto unitario: $40,865.00")
print("Costo sin IVA: $24,780.00")
print("Comisión: $7,638.60")
print("Costo envío: $5,383.00 (CON IVA)")
print("Markup: 0.46%")

db.close()
