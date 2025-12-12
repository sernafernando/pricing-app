"""
Script para agregar métricas de ventas ML - DÍA COMPLETO
Procesa todas las ventas del día actual
Diseñado para ejecutarse cada 30 minutos como backup del incremental

Ejecutar:
    python app/scripts/agregar_metricas_ml_diario.py
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

from datetime import datetime, date, timedelta
from app.core.database import SessionLocal
from app.scripts.agregar_metricas_ml_incremental import calcular_metricas_locales, process_and_insert


def main():
    # Procesar todo el día de hoy
    hoy = date.today()
    from_datetime = datetime.combine(hoy, datetime.min.time())
    to_datetime = datetime.combine(hoy, datetime.max.time())

    now = datetime.now()
    print("=" * 60)
    print("MÉTRICAS ML DIARIO - Día completo")
    print("=" * 60)
    print(f"Ejecutado: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Procesando: {hoy}")
    print(f"Rango: {from_datetime} a {to_datetime}")

    db = SessionLocal()

    try:
        # Obtener datos de tablas locales
        rows = calcular_metricas_locales(db, from_datetime, to_datetime)

        # Procesar e insertar
        insertados, actualizados, errores, notificaciones = process_and_insert(db, rows)

        print("\n" + "=" * 60)
        print("✅ COMPLETADO")
        print("=" * 60)
        print(f"Insertados: {insertados}")
        print(f"Actualizados: {actualizados}")
        print(f"Errores: {errores}")
        print(f"🔔 Notificaciones creadas: {notificaciones}")
        print()

    except Exception as e:
        print(f"\n❌ Error crítico: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
