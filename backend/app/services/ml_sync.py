import httpx
from sqlalchemy.orm import Session
from app.models.publicacion_ml import PublicacionML
from app.models.producto import ProductoERP
from typing import Dict, List

ENDPOINT_ML = "http://localhost:8002/api/gbp-parser?intExpgr_id=77"

async def sincronizar_publicaciones_ml(db: Session) -> Dict:
    """Sincroniza publicaciones de ML desde el endpoint externo"""
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ENDPOINT_ML)
            response.raise_for_status()
            data = response.json()
        
        if not isinstance(data, list):
            return {"error": "Formato de respuesta inválido"}
        
        nuevas = 0
        actualizadas = 0
        ignoradas = 0
        errores = []
        
        for row in data:
            try:
                mla = row.get('publicationID')
                item_id = row.get('item_id')
                
                if not mla or not item_id:
                    continue
                
                # Verificar que el producto existe
                producto_existe = db.query(ProductoERP).filter(
                    ProductoERP.item_id == int(item_id)
                ).first()
                
                if not producto_existe:
                    ignoradas += 1
                    continue
                
                # Buscar si existe la publicación
                pub = db.query(PublicacionML).filter(
                    PublicacionML.mla == mla
                ).first()
                
                if pub:
                    # Actualizar
                    pub.item_id = int(item_id)
                    pub.codigo = row.get('Código')
                    pub.item_title = row.get('itemTitle')
                    pub.pricelist_id = int(row.get('IDLista')) if row.get('IDLista') else None
                    pub.lista_nombre = row.get('Lista')
                    actualizadas += 1
                else:
                    # Crear nuevo
                    pub = PublicacionML(
                        mla=mla,
                        item_id=int(item_id),
                        codigo=row.get('Código'),
                        item_title=row.get('itemTitle'),
                        pricelist_id=int(row.get('IDLista')) if row.get('IDLista') else None,
                        lista_nombre=row.get('Lista')
                    )
                    db.add(pub)
                    nuevas += 1
                    
            except Exception as e:
                errores.append(f"Error en {row.get('publicationID')}: {str(e)}")
        
        db.commit()
        
        return {
            "status": "success",
            "nuevas": nuevas,
            "actualizadas": actualizadas,
            "ignoradas": ignoradas,
            "total": nuevas + actualizadas,
            "errores": errores[:10] if errores else []
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": str(e)
        }

def obtener_publicaciones_por_item(db: Session, item_id: int) -> List[PublicacionML]:
    """Obtiene todas las publicaciones ML de un producto"""
    return db.query(PublicacionML).filter(
        PublicacionML.item_id == item_id
    ).all()

def obtener_publicacion_por_mla(db: Session, mla: str) -> PublicacionML:
    """Obtiene una publicación por su MLA"""
    return db.query(PublicacionML).filter(
        PublicacionML.mla == mla
    ).first()
