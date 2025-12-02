"""
Script para diagnosticar la query de rentabilidad
"""
from datetime import date, datetime, timedelta
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica

db = SessionLocal()

hoy = date.today()
print(f"\n=== Diagnóstico de query rentabilidad ===")
print(f"Fecha de hoy: {hoy}")

# Método 1: Comparando date con date
count1 = db.query(func.count(MLVentaMetrica.id)).filter(
    MLVentaMetrica.fecha_venta >= hoy,
    MLVentaMetrica.fecha_venta < hoy + timedelta(days=1)
).scalar()
print(f"\n1. Comparando con date >= {hoy} y < {hoy + timedelta(days=1)}: {count1}")

# Método 2: Comparando datetime con datetime (lo que hace ahora el código)
fecha_desde_dt = datetime.combine(hoy, datetime.min.time())
fecha_hasta_dt = datetime.combine(hoy + timedelta(days=1), datetime.min.time())
count2 = db.query(func.count(MLVentaMetrica.id)).filter(
    MLVentaMetrica.fecha_venta >= fecha_desde_dt,
    MLVentaMetrica.fecha_venta < fecha_hasta_dt
).scalar()
print(f"2. Comparando con datetime >= {fecha_desde_dt} y < {fecha_hasta_dt}: {count2}")

# Método 3: Ver las fechas reales almacenadas
print(f"\nEjemplos de fecha_venta almacenada:")
ejemplos = db.query(
    MLVentaMetrica.fecha_venta,
    MLVentaMetrica.codigo
).order_by(MLVentaMetrica.fecha_venta.desc()).limit(10).all()

for ej in ejemplos:
    print(f"  {ej.fecha_venta} - {ej.codigo}")

# Método 4: Contar por fecha_calculo
print(f"\nConteo por fecha_calculo = {hoy}:")
count_calculo = db.query(func.count(MLVentaMetrica.id)).filter(
    MLVentaMetrica.fecha_calculo == hoy
).scalar()
print(f"  Total: {count_calculo}")

# Ver el SQL generado
from sqlalchemy.dialects import postgresql
query = db.query(func.count(MLVentaMetrica.id)).filter(
    MLVentaMetrica.fecha_venta >= fecha_desde_dt,
    MLVentaMetrica.fecha_venta < fecha_hasta_dt
)
print(f"\nSQL generado:")
print(query.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

db.close()
