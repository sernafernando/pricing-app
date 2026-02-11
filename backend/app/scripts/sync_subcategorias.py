import requests
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.comision_config import SubcategoriaGrupo

def sincronizar_subcategorias():
    """Sincroniza subcategorías desde el worker con categorías"""
    url_subcats = "http://localhost:8002/api/gbp-parser?opName=SubCategory_funGetXMLData&pCategory=-1"
    url_cats = "http://localhost:8002/api/gbp-parser?opName=Category_funGetXMLData"
    
    try:
        # Obtener categorías
        resp_cats = requests.get(url_cats, timeout=30)
        resp_cats.raise_for_status()
        categorias = {c['cat_id']: c['cat_desc'] for c in resp_cats.json()}
        
        # Obtener subcategorías
        resp_subcats = requests.get(url_subcats, timeout=30)
        resp_subcats.raise_for_status()
        data = resp_subcats.json()
        
        db = SessionLocal()
        
        actualizadas = 0
        nuevas = 0
        
        for item in data:
            subcat_id = int(item.get('subcat_id'))
            nombre = item.get('subcat_desc')
            cat_id = item.get('cat_id')
            nombre_categoria = categorias.get(cat_id, '')
            
            # Buscar si existe
            existente = db.query(SubcategoriaGrupo).filter(
                SubcategoriaGrupo.subcat_id == subcat_id
            ).first()
            
            if existente:
                # Actualizar siempre cat_id y nombre_categoria
                existente.nombre_subcategoria = nombre
                existente.cat_id = cat_id
                existente.nombre_categoria = nombre_categoria
                actualizadas += 1
            else:
                # Crear nueva
                nueva = SubcategoriaGrupo(
                    subcat_id=subcat_id,
                    nombre_subcategoria=nombre,
                    cat_id=cat_id,
                    nombre_categoria=nombre_categoria,
                    grupo_id=None
                )
                db.add(nueva)
                nuevas += 1
        
        db.commit()
        print("✅ Sincronización completada:")
        print(f"   - {actualizadas} subcategorías actualizadas")
        print(f"   - {nuevas} subcategorías nuevas")
        
    except Exception as e:
        print(f"❌ Error sincronizando subcategorías: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    sincronizar_subcategorias()
