"""
Debug: Ver qué valor de envío tiene el producto 097855088789
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

# Buscar el producto
query = text("""
SELECT
    pe.codigo,
    pe.descripcion,
    pe.envio,
    pe.costo,
    pe.precio_lista_ml
FROM productos_erp pe
WHERE pe.codigo = '097855088789'
""")

result = db.execute(query)
row = result.fetchone()

if row:
    print(f"Código: {row.codigo}")
    print(f"Descripción: {row.descripcion}")
    print(f"Envío (productos_erp.envio): ${row.envio:,.2f}" if row.envio else "Envío: None")
    print(f"Costo: ${row.costo:,.2f}" if row.costo else "Costo: None")
    print(f"Precio Lista ML: ${row.precio_lista_ml:,.2f}" if row.precio_lista_ml else "Precio: None")

    if row.envio:
        print(f"\nEnvío sin IVA (/ 1.21): ${row.envio / 1.21:,.2f}")
else:
    print("Producto no encontrado")

db.close()
