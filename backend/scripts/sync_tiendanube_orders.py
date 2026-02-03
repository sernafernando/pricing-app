#!/usr/bin/env python3
"""
Script para sincronizar órdenes de TiendaNube desde el ERP.
Usa scriptTiendaNubeOrders via gbp-parser.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

import httpx
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.tienda_nube_order import TiendaNubeOrder

GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def sync_tiendanube_orders(from_date: date = None, to_date: date = None):
    """
    Sincroniza órdenes de TiendaNube desde el ERP.
    
    Args:
        from_date: Fecha desde (default: últimos 30 días)
        to_date: Fecha hasta (default: hoy)
    """
    # Por defecto, últimos 30 días
    if not from_date:
        from_date = date.today() - timedelta(days=30)
    if not to_date:
        # Agregar 1 día para incluir TODO el día de hoy (hasta las 23:59:59)
        to_date = date.today() + timedelta(days=1)
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sincronizando órdenes TiendaNube desde {from_date} hasta {to_date}...")
    
    db = SessionLocal()
    
    try:
        # 1. Obtener datos del ERP
        print(f"Consultando ERP scriptTiendaNubeOrders...")
        
        response = httpx.post(
            GBP_PARSER_URL,
            json={
                "strScriptLabel": "scriptTiendaNubeOrders",
                "fromDate": from_date.isoformat(),
                "toDate": to_date.isoformat()
            },
            timeout=120.0
        )
        
        if response.status_code != 200:
            print(f"❌ Error HTTP {response.status_code}: {response.text}")
            return
        
        data = response.json()
        
        if not data or not isinstance(data, list):
            print("❌ No se obtuvieron datos del ERP")
            return
        
        print(f"✓ Obtenidos {len(data)} registros del ERP")
        
        # 2. Procesar registros
        nuevos = 0
        actualizados = 0
        errores = 0
        
        for record in data:
            try:
                comp_id = record.get('comp_id')
                tno_id = record.get('tno_id')
                
                if not comp_id or not tno_id:
                    print(f"⚠️  Registro sin comp_id o tno_id: {record}")
                    errores += 1
                    continue
                
                # Buscar si existe
                orden = db.query(TiendaNubeOrder).filter(
                    and_(
                        TiendaNubeOrder.comp_id == comp_id,
                        TiendaNubeOrder.tno_id == tno_id
                    )
                ).first()
                
                # Preparar datos (nombres de campos en minúscula según el modelo)
                orden_data = {
                    'comp_id': comp_id,
                    'tno_id': tno_id,
                    'tno_cd': record.get('tno_cd'),
                    'tn_id': record.get('tn_id'),
                    'tno_orderid': record.get('tno_orderID'),  # Minúscula: tno_orderid
                    'tno_json': record.get('tno_JSon'),        # Minúscula: tno_json
                    'bra_id': record.get('bra_id'),
                    'soh_id': record.get('soh_id'),
                    'cust_id': record.get('cust_id'),
                    'tno_iscancelled': record.get('tno_isCancelled')  # Minúscula: tno_iscancelled
                }
                
                if orden:
                    # Actualizar
                    for key, value in orden_data.items():
                        if key not in ['comp_id', 'tno_id']:  # No actualizar PK
                            setattr(orden, key, value)
                    actualizados += 1
                else:
                    # Crear nuevo
                    orden = TiendaNubeOrder(**orden_data)
                    db.add(orden)
                    nuevos += 1
                
                # Commit cada 100 registros
                if (nuevos + actualizados) % 100 == 0:
                    db.commit()
                    print(f"  Procesados: {nuevos + actualizados}...")
                    
            except Exception as e:
                print(f"❌ Error procesando registro {record.get('tno_id')}: {e}")
                errores += 1
        
        # Commit final
        db.commit()
        
        print(f"✅ Sincronización completada:")
        print(f"   - Nuevos: {nuevos}")
        print(f"   - Actualizados: {actualizados}")
        print(f"   - Errores: {errores}")
        print(f"   - Total en DB: {db.query(TiendaNubeOrder).count()}")
        
    except httpx.HTTPError as e:
        print(f"❌ Error de conexión: {e}")
        db.rollback()
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    # Sincronizar últimos 30 días por defecto
    sync_tiendanube_orders()
