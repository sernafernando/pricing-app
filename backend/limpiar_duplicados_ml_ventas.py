"""
Limpia registros duplicados en ml_ventas_metricas
Deja solo el registro más reciente por cada id_operacion
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

print("=" * 80)
print("LIMPIEZA DE REGISTROS DUPLICADOS EN ml_ventas_metricas")
print("=" * 80)

# Contar duplicados
result = db.execute(text("""
    SELECT COUNT(*) as total,
           COUNT(DISTINCT id_operacion) as unicos
    FROM ml_ventas_metricas
"""))

row = result.fetchone()
print(f"\nRegistros totales: {row.total}")
print(f"Operaciones únicas: {row.unicos}")
print(f"Duplicados: {row.total - row.unicos}")

if row.total == row.unicos:
    print("\n✅ No hay duplicados")
    db.close()
    exit(0)

# Eliminar duplicados, dejando solo el más reciente
print("\n🗑️  Eliminando registros duplicados...")

result = db.execute(text("""
    DELETE FROM ml_ventas_metricas
    WHERE id NOT IN (
        SELECT DISTINCT ON (id_operacion) id
        FROM ml_ventas_metricas
        ORDER BY id_operacion, fecha_calculo DESC
    )
"""))

db.commit()

eliminados = result.rowcount
print(f"  ✓ Eliminados {eliminados} registros duplicados")

# Verificar resultado
result = db.execute(text("""
    SELECT COUNT(*) as total,
           COUNT(DISTINCT id_operacion) as unicos
    FROM ml_ventas_metricas
"""))

row = result.fetchone()
print(f"\nResultado final:")
print(f"  Registros totales: {row.total}")
print(f"  Operaciones únicas: {row.unicos}")

print("\n✅ Limpieza completada")

db.close()
