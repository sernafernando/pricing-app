#!/usr/bin/env python3
"""
Script SIMPLE para sincronizar pedidos del Export 87.
Sin complicaciones - guarda TAL CUAL en tb_pedidos_export.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.pedido_export import PedidoExport

GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def sync_pedidos_export():
    """
    Sincroniza pedidos desde Export 87 del ERP.
    Guarda TODO tal cual viene en tb_pedidos_export.
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 Sincronizando pedidos Export 87...")
    
    db = SessionLocal()
    
    try:
        # 1. Obtener datos del ERP Export 87
        print(f"📡 Consultando ERP Export 87...")
        
        response = httpx.post(
            GBP_PARSER_URL,
            json={"intExpgr_id": 87},
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
        
        # 2. Extraer IDs de pedidos actuales
        pedidos_actuales = set()
        for record in data:
            id_pedido = record.get('IDPedido')
            if id_pedido:
                pedidos_actuales.add(id_pedido)
        
        print(f"✓ {len(pedidos_actuales)} pedidos únicos")
        
        # 3. Marcar pedidos viejos como inactivos
        archivados = db.query(PedidoExport).filter(
            and_(
                PedidoExport.activo == True,
                PedidoExport.id_pedido.notin_(pedidos_actuales)
            )
        ).update(
            {"activo": False},
            synchronize_session=False
        )
        
        print(f"📦 Archivados: {archivados} pedidos")
        
        # 4. Deduplicar registros (por si el ERP trae duplicados)
        # Usar un dict con (id_pedido, item_id) como key
        registros_unicos = {}
        for record in data:
            id_pedido = record.get('IDPedido')
            item_id = record.get('item_id')
            if id_pedido and item_id:
                key = (id_pedido, item_id)
                # Guardar el último (más reciente) si hay duplicados
                registros_unicos[key] = record
        
        print(f"✓ {len(registros_unicos)} registros únicos (de {len(data)} totales)")
        
        # 5. Procesar registros únicos
        nuevos = 0
        actualizados = 0
        errores = 0
        
        for record in registros_unicos.values():
            try:
                id_pedido = record.get('IDPedido')
                item_id = record.get('item_id')
                
                if not id_pedido or not item_id:
                    errores += 1
                    continue
                
                # Buscar si existe
                pedido = db.query(PedidoExport).filter(
                    and_(
                        PedidoExport.id_pedido == id_pedido,
                        PedidoExport.item_id == item_id
                    )
                ).first()
                
                # Preparar datos TAL CUAL vienen del ERP
                user_id_raw = record.get('userID')
                user_id = int(user_id_raw) if user_id_raw else None
                
                pedido_data = {
                    'id_pedido': id_pedido,
                    'item_id': item_id,
                    'id_cliente': record.get('IDCliente'),
                    'nombre_cliente': record.get('NombreCliente'),
                    'user_id': user_id,  # 50021=TN, 50006=ML
                    'cantidad': record.get('Cantidad'),
                    'item_code': record.get('EAN'),
                    'item_desc': record.get('Descripción'),
                    'tipo_envio': record.get('Tipo de Envío'),
                    'direccion_envio': record.get('Dirección de Envío'),
                    'fecha_envio': record.get('Fecha de envío'),
                    'observaciones': record.get('Observaciones'),
                    'orden_tn': record.get('Orden TN'),
                    'order_id_tn': str(record.get('orderID')) if record.get('orderID') else None,
                    'activo': True,
                    'fecha_sync': datetime.now()
                }
                
                if pedido:
                    # Actualizar
                    for key, value in pedido_data.items():
                        if key not in ['id_pedido', 'item_id']:  # No actualizar PK
                            setattr(pedido, key, value)
                    actualizados += 1
                else:
                    # Crear nuevo
                    pedido = PedidoExport(**pedido_data)
                    db.add(pedido)
                    nuevos += 1
                
                # Commit cada 100 registros
                if (nuevos + actualizados) % 100 == 0:
                    try:
                        db.commit()
                        print(f"  ⚙️  Procesados: {nuevos + actualizados}...")
                    except Exception as commit_error:
                        print(f"⚠️  Error en commit batch: {commit_error}")
                        db.rollback()
                        # Continuar con el siguiente batch
                    
            except Exception as e:
                print(f"❌ Error procesando registro IDPedido={record.get('IDPedido')}, item_id={record.get('item_id')}: {e}")
                errores += 1
        
        # Commit final
        try:
            db.commit()
        except Exception as final_commit_error:
            print(f"⚠️  Error en commit final: {final_commit_error}")
            db.rollback()
        
        print(f"\n✅ Sincronización completada:")
        print(f"   - Nuevos: {nuevos}")
        print(f"   - Actualizados: {actualizados}")
        print(f"   - Archivados: {archivados}")
        print(f"   - Errores: {errores}")
        print(f"   - Total activos: {db.query(PedidoExport).filter(PedidoExport.activo == True).count()}")
        
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
    sync_pedidos_export()
