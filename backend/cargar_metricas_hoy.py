"""
Script para cargar métricas del día de hoy completo
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

from datetime import datetime, date, timedelta
from app.core.database import SessionLocal
from app.scripts.agregar_metricas_ml_incremental import calcular_metricas_locales, process_and_insert

# Cargar todo el día de hoy
hoy = date.today()
from_datetime = datetime.combine(hoy, datetime.min.time())
to_datetime = datetime.combine(hoy, datetime.max.time())

print("=" * 60)
print(f"CARGANDO MÉTRICAS DEL DÍA: {hoy}")
print("=" * 60)
print(f"Desde: {from_datetime}")
print(f"Hasta: {to_datetime}")

db = SessionLocal()

try:
    rows = calcular_metricas_locales(db, from_datetime, to_datetime)
    insertados, actualizados, errores, notificaciones = process_and_insert(db, rows)

    print("\n" + "=" * 60)
    print("✅ COMPLETADO")
    print("=" * 60)
    print(f"Insertados: {insertados}")
    print(f"Actualizados: {actualizados}")
    print(f"Errores: {errores}")
    print(f"Notificaciones: {notificaciones}")
finally:
    db.close()
