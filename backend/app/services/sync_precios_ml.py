import requests
from sqlalchemy.orm import Session
from app.models.precio_ml import PrecioML
from app.models.publicacion_ml import PublicacionML
from datetime import datetime

# Listas que vamos a sincronizar
PRICELISTS = {
    4: "Clásica",
    17: "ML PREMIUM 3C",
    14: "ML PREMIUM 6C", 
    13: "ML PREMIUM 9C",
    23: "ML PREMIUM 12C"
}

def sincronizar_precios_ml(db: Session, pricelist_id: int = None):
    """
    Sincroniza precios de MercadoLibre desde la API
    Si pricelist_id es None, sincroniza todas las listas
    """
    listas = {pricelist_id: PRICELISTS[pricelist_id]} if pricelist_id else PRICELISTS
    
    resultados = {
        "exitosos": 0,
        "errores": 0,
        "listas_procesadas": []
    }
    
    for pl_id, nombre in listas.items():
        try:
            print(f"Sincronizando lista {pl_id} - {nombre}...")
            
            # Llamar a la API
            url = f"https://parser-worker-js.gaussonline.workers.dev/consulta?opName=PriceListItems_funGetXMLData&pPriceList={pl_id}&pItem=-1"
            response = requests.get(url, timeout=60)
            
            if response.status_code != 200:
                print(f"Error HTTP {response.status_code} para lista {pl_id}")
                resultados["errores"] += 1
                continue
            
            # Parsear JSON
            precios = response.json()
            
            if not isinstance(precios, list):
                print(f"Respuesta no es una lista para {pl_id}")
                resultados["errores"] += 1
                continue
            
            items_procesados = 0
            items_sin_mla = 0
            
            for item in precios:
                try:
                    item_id = int(item.get('item_id', 0))
                    precio_text = item.get('prli_price_Final_Pesos')
                    
                    if not item_id or not precio_text:
                        continue
                    
                    precio = float(precio_text)
                    
                    # Buscar el MLA correspondiente al item_id
                    publicacion = db.query(PublicacionML).filter(
                        PublicacionML.item_id == item_id,
                        PublicacionML.pricelist_id == pl_id
                    ).first()
                    
                    if not publicacion or not publicacion.mla:
                        items_sin_mla += 1
                        continue
                    
                    mla = publicacion.mla
                    
                    # Buscar o crear el registro
                    precio_ml = db.query(PrecioML).filter(
                        PrecioML.mla == mla,
                        PrecioML.pricelist_id == pl_id
                    ).first()
                    
                    if precio_ml:
                        precio_ml.precio = precio
                        precio_ml.fecha_actualizacion = datetime.now()
                    else:
                        precio_ml = PrecioML(
                            mla=mla,
                            pricelist_id=pl_id,
                            precio=precio
                        )
                        db.add(precio_ml)
                    
                    items_procesados += 1
                    
                    # Commit cada 100 items
                    if items_procesados % 100 == 0:
                        db.commit()
                        
                except Exception as e:
                    print(f"Error procesando item {item.get('item_id')}: {e}")
                    continue
            
            db.commit()
            resultados["exitosos"] += items_procesados
            resultados["listas_procesadas"].append({
                "pricelist_id": pl_id,
                "nombre": nombre,
                "items": items_procesados,
                "sin_mla": items_sin_mla
            })
            
            print(f"Lista {pl_id} completada: {items_procesados} items, {items_sin_mla} sin MLA")
            
        except Exception as e:
            print(f"Error sincronizando lista {pl_id}: {e}")
            resultados["errores"] += 1
            db.rollback()
    
    return resultados
