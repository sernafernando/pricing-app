import requests
from sqlalchemy.orm import Session
from app.models.precio_ml import PrecioML
from datetime import datetime

PRICELISTS = {
    4: "Clásica",
    17: "ML PREMIUM 3C",
    14: "ML PREMIUM 6C", 
    13: "ML PREMIUM 9C",
    23: "ML PREMIUM 12C"
}

def sincronizar_precios_ml(db: Session, pricelist_id: int = None):
    """Sincroniza precios de ML - Simple y directo"""
    
    listas = {pricelist_id: PRICELISTS[pricelist_id]} if pricelist_id else PRICELISTS
    
    resultados = {
        "exitosos": 0,
        "errores": 0,
        "listas_procesadas": []
    }
    
    for pl_id, nombre in listas.items():
        try:
            print(f"Sincronizando lista {pl_id} - {nombre}...")
            
            url = f"https://parser-worker-js.gaussonline.workers.dev/consulta?opName=PriceListItems_funGetXMLData&pPriceList={pl_id}&pItem=-1"
            response = requests.get(url, timeout=60)
            
            if response.status_code != 200:
                print(f"Error HTTP {response.status_code}")
                resultados["errores"] += 1
                continue
            
            datos = response.json()
            items_procesados = 0
            
            for item in datos:
                item_id = int(item.get('item_id', 0))
                precio = float(item.get('prli_price_Final_Pesos', 0))
                cotizacion_dolar = float(item.get('Cotizacion_Dolar', 0))
                
                if not item_id or not precio:
                    continue
                
                # Buscar o crear
                precio_ml = db.query(PrecioML).filter(
                    PrecioML.item_id == item_id,
                    PrecioML.pricelist_id == pl_id
                ).first()
                
                if precio_ml:
                    precio_ml.precio = precio
                    precio_ml.cotizacion_dolar = cotizacion_dolar
                    precio_ml.fecha_actualizacion = datetime.now()
                else:
                    db.add(PrecioML(
                        item_id=item_id,
                        pricelist_id=pl_id,
                        precio=precio,
                        cotizacion_dolar=cotizacion_dolar
                    ))
                
                items_procesados += 1
                
                if items_procesados % 100 == 0:
                    db.commit()
            
            db.commit()
            
            resultados["exitosos"] += items_procesados
            resultados["listas_procesadas"].append({
                "pricelist_id": pl_id,
                "nombre": nombre,
                "items": items_procesados
            })
            
            print(f"✓ Lista {pl_id}: {items_procesados} precios")
            
        except Exception as e:
                print(f"✗ Error en lista {pl_id}: {e}")
                resultados["errores"] += 1
                db.rollback()
        
    return resultados
