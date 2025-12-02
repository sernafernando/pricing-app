"""
Script para diagnosticar el problema de fechas en rentabilidad
"""
from datetime import date, timedelta
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica

db = SessionLocal()

# Fecha de hoy
hoy = date.today()
manana = hoy + timedelta(days=1)

print(f"\n=== Diagnóstico de fechas ===")
print(f"Fecha de hoy: {hoy}")
print(f"Fecha mañana (ajustada): {manana}")

# Contar con el patrón nuevo (>= hoy y < mañana)
count_nuevo = db.query(func.count(MLVentaMetrica.id)).filter(
    MLVentaMetrica.fecha_venta >= hoy,
    MLVentaMetrica.fecha_venta < manana
).scalar()

print(f"\nConteo con patrón nuevo (>= {hoy} y < {manana}): {count_nuevo}")

# Ver algunas fechas de ejemplo
print(f"\nEjemplos de fecha_venta de hoy:")
ejemplos = db.query(
    MLVentaMetrica.fecha_venta,
    MLVentaMetrica.codigo
).filter(
    MLVentaMetrica.fecha_venta >= hoy,
    MLVentaMetrica.fecha_venta < manana
).limit(5).all()

for ej in ejemplos:
    print(f"  {ej.fecha_venta} - {ej.codigo}")

# Ver el rango de fechas que hay
print(f"\nRango de fechas en la tabla:")
min_fecha = db.query(func.min(MLVentaMetrica.fecha_venta)).scalar()
max_fecha = db.query(func.max(MLVentaMetrica.fecha_venta)).scalar()
print(f"  Min: {min_fecha}")
print(f"  Max: {max_fecha}")

db.close()
