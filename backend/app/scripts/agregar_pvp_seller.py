import sys
sys.path.append('/var/www/html/pricing-app/backend')

from app.core.database import engine

def agregar_columna():
    with engine.connect() as conn:
        conn.execute("ALTER TABLE ofertas_ml ADD COLUMN IF NOT EXISTS pvp_seller FLOAT;")
        conn.commit()
    print("✅ Columna pvp_seller agregada")

if __name__ == "__main__":
    agregar_columna()
