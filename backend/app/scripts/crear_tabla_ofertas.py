import sys
sys.path.append('/var/www/html/pricing-app/backend')

from app.core.database import engine, Base
from app.models.publicacion_ml import PublicacionML  # Importar primero
from app.models.oferta_ml import OfertaML

def crear_tabla():
    Base.metadata.create_all(bind=engine, tables=[OfertaML.__table__])
    print("✅ Tabla ofertas_ml creada")

if __name__ == "__main__":
    crear_tabla()
