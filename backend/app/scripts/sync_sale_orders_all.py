"""
Script para sincronizar ÓRDENES DE VENTA del ERP (Sale Orders).
Diseñado para ejecutarse cada 5-10 minutos para datos casi en tiempo real.

Tablas sincronizadas:
- tbSaleOrderHeader (cabecera de órdenes)
- tbSaleOrderDetail (detalle de órdenes)
- tbSaleOrderHeaderHistory (historial de cabecera)
- tbSaleOrderDetailHistory (historial de detalle)

Ejecutar:
    python -m app.scripts.sync_sale_orders_all
    python -m app.scripts.sync_sale_orders_all --days 7
    python -m app.scripts.sync_sale_orders_all --days 1  # Solo hoy
"""
import sys
import os
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Cargar variables de entorno desde .env
    from dotenv import load_dotenv
    env_path = Path(backend_path) / '.env'
    load_dotenv(dotenv_path=env_path)

import argparse
import httpx
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from app.models.sale_order_header_history import SaleOrderHeaderHistory
from app.models.sale_order_detail_history import SaleOrderDetailHistory

# URL del endpoint gbp-parser
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


async def sync_sale_order_header(db: Session, days: int = 7):
    """
    Sincroniza cabecera de órdenes de venta.
    
    Args:
        db: Sesión de base de datos
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)
    
    Returns:
        tuple: (nuevos, actualizados, errores)
    """
    print(f"  📋 Sale Order Header (últimos {days} días)...", end=" ", flush=True)
    
    try:
        from_date = (date.today() - timedelta(days=days)).isoformat()
        to_date = date.today().isoformat()
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptSaleOrderHeader",
                "fromDate": from_date,
                "toDate": to_date
            })
            response.raise_for_status()
            data = response.json()
        
        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return (0, 0, 0)
        
        nuevos = 0
        actualizados = 0
        errores = 0
        
        for record in data:
            try:
                comp_id = record.get('comp_id')
                bra_id = record.get('bra_id')
                soh_id = record.get('soh_id')
                
                if not all([comp_id, bra_id, soh_id]):
                    errores += 1
                    continue
                
                # Buscar existente
                existente = db.query(SaleOrderHeader).filter(
                    and_(
                        SaleOrderHeader.comp_id == comp_id,
                        SaleOrderHeader.bra_id == bra_id,
                        SaleOrderHeader.soh_id == soh_id
                    )
                ).first()
                
                # Helper para fechas
                def parse_dt(val):
                    if not val:
                        return None
                    try:
                        return datetime.fromisoformat(val.replace('T', ' ').replace('Z', ''))
                    except:
                        return None
                
                # Datos básicos (no mapeo todas las 70+ columnas, solo las principales)
                datos = {
                    'comp_id': comp_id,
                    'bra_id': bra_id,
                    'soh_id': soh_id,
                    'soh_cd': parse_dt(record.get('soh_cd')),
                    'soh_deliverydate': parse_dt(record.get('soh_deliveryDate')),
                    'cust_id': record.get('cust_id'),
                    'sm_id': record.get('sm_id'),
                    'st_id': record.get('st_id'),
                    'soh_total': record.get('soh_total'),
                    'soh_quotation': record.get('soh_quotation'),
                    'soh_observation1': record.get('soh_observation1'),
                    'soh_observation2': record.get('soh_observation2'),
                    'soh_lastupdate': parse_dt(record.get('soh_lastUpdate')),
                    'mlo_id': record.get('mlo_id'),
                    'soh_mlid': record.get('soh_MLId'),
                    'prli_id': record.get('prli_id'),
                    'ssos_id': record.get('ssos_id'),
                    'df_id': record.get('df_id'),
                    'user_id': record.get('user_id'),
                }
                
                if existente:
                    for key, value in datos.items():
                        setattr(existente, key, value)
                    actualizados += 1
                else:
                    nuevo = SaleOrderHeader(**datos)
                    db.add(nuevo)
                    nuevos += 1
                
                # Commit cada 500
                if (nuevos + actualizados) % 500 == 0:
                    db.commit()
            
            except Exception as e:
                errores += 1
                if errores <= 5:
                    print(f"\n  ⚠️  Error en registro: {str(e)}")
                continue
        
        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados, {errores} errores)")
        return (nuevos, actualizados, errores)
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return (0, 0, 0)


async def sync_sale_order_detail(db: Session, days: int = 7):
    """
    Sincroniza detalle de órdenes de venta.
    
    Args:
        db: Sesión de base de datos
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)
    """
    print(f"  📋 Sale Order Detail (últimos {days} días)...", end=" ", flush=True)
    
    try:
        from_date = (date.today() - timedelta(days=days)).isoformat()
        to_date = date.today().isoformat()
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptSaleOrderDetail",
                "fromDate": from_date,
                "toDate": to_date
            })
            response.raise_for_status()
            data = response.json()
        
        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return (0, 0, 0)
        
        nuevos = 0
        actualizados = 0
        errores = 0
        errores_por_tipo = {}
        
        for record in data:
            try:
                comp_id = record.get('comp_id')
                bra_id = record.get('bra_id')
                soh_id = record.get('soh_id')
                sod_id = record.get('sod_id')
                
                if not all([comp_id, bra_id, soh_id, sod_id]):
                    errores += 1
                    error_key = "campos_null"
                    errores_por_tipo[error_key] = errores_por_tipo.get(error_key, 0) + 1
                    if errores <= 3:
                        print(f"\n  ⚠️  PKs nulas: comp_id={comp_id}, bra_id={bra_id}, soh_id={soh_id}, sod_id={sod_id}")
                    continue
                
                existente = db.query(SaleOrderDetail).filter(
                    and_(
                        SaleOrderDetail.comp_id == comp_id,
                        SaleOrderDetail.bra_id == bra_id,
                        SaleOrderDetail.soh_id == soh_id,
                        SaleOrderDetail.sod_id == sod_id
                    )
                ).first()
                
                datos = {
                    'comp_id': comp_id,
                    'bra_id': bra_id,
                    'soh_id': soh_id,
                    'sod_id': sod_id,
                    'item_id': record.get('item_id'),
                    'sod_qty': record.get('sod_qty'),
                    'sod_price': record.get('sod_price'),
                    'sod_subtotal': record.get('sod_subtotal'),
                    'sod_discountpercentage': record.get('sod_discountPercentage'),
                    'sod_total': record.get('sod_total'),
                    'sod_delivered': record.get('sod_delivered'),
                    'sod_fordelivery': record.get('sod_forDelivery'),
                    'um_id': record.get('um_id'),
                    'prli_id': record.get('prli_id'),
                }
                
                if existente:
                    for key, value in datos.items():
                        setattr(existente, key, value)
                    actualizados += 1
                else:
                    nuevo = SaleOrderDetail(**datos)
                    db.add(nuevo)
                    nuevos += 1
                
                # Commit cada 100 para detectar errores más rápido
                if (nuevos + actualizados) % 100 == 0:
                    try:
                        db.commit()
                    except Exception as commit_err:
                        db.rollback()
                        errores += 1
                        error_key = type(commit_err).__name__
                        errores_por_tipo[error_key] = errores_por_tipo.get(error_key, 0) + 1
                        if errores <= 3:
                            print(f"\n  ⚠️  Error en commit: {str(commit_err)[:100]}")
            
            except Exception as e:
                errores += 1
                error_key = type(e).__name__
                errores_por_tipo[error_key] = errores_por_tipo.get(error_key, 0) + 1
                if errores <= 3:
                    print(f"\n  ⚠️  Error: {str(e)[:100]}")
                continue
        
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            if errores_por_tipo:
                print(f"\n  📊 Errores por tipo: {errores_por_tipo}")
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados, {errores} errores)")
        return (nuevos, actualizados, errores)
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return (0, 0, 0)


async def sync_sale_order_header_history(db: Session, days: int = 7):
    """
    Sincroniza historial de cabecera de órdenes.
    
    Args:
        db: Sesión de base de datos
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)
    """
    print(f"  📜 Sale Order Header History (últimos {days} días)...", end=" ", flush=True)
    
    try:
        from_date = (date.today() - timedelta(days=days)).isoformat()
        to_date = date.today().isoformat()
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptSaleOrderHeaderHistory",
                "fromDate": from_date,
                "toDate": to_date
            })
            response.raise_for_status()
            data = response.json()
        
        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return (0, 0, 0)
        
        nuevos = 0
        actualizados = 0
        
        for record in data:
            try:
                sohhID = record.get('sohhID') or record.get('sohh_id')
                if not sohhID:
                    continue
                
                existente = db.query(SaleOrderHeaderHistory).filter(
                    SaleOrderHeaderHistory.sohh_id == sohhID
                ).first()
                
                def parse_dt(val):
                    if not val:
                        return None
                    try:
                        return datetime.fromisoformat(val.replace('T', ' ').replace('Z', ''))
                    except:
                        return None
                
                datos = {
                    'sohh_id': sohhID,
                    'comp_id': record.get('comp_id'),
                    'bra_id': record.get('bra_id'),
                    'soh_id': record.get('soh_id'),
                    'sohh_cd': parse_dt(record.get('sohh_cd')),
                    'sohh_action': record.get('sohh_action'),
                    'user_id': record.get('user_id'),
                    'sohh_previousvalue': record.get('sohh_previousValue'),
                    'sohh_newvalue': record.get('sohh_newValue'),
                }
                
                if existente:
                    for key, value in datos.items():
                        setattr(existente, key, value)
                    actualizados += 1
                else:
                    nuevo = SaleOrderHeaderHistory(**datos)
                    db.add(nuevo)
                    nuevos += 1
                
                if (nuevos + actualizados) % 500 == 0:
                    db.commit()
            
            except Exception:
                continue
        
        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return (nuevos, actualizados, 0)
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return (0, 0, 0)


async def sync_sale_order_detail_history(db: Session, days: int = 7):
    """
    Sincroniza historial de detalle de órdenes.
    
    Args:
        db: Sesión de base de datos
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)
    """
    print(f"  📜 Sale Order Detail History (últimos {days} días)...", end=" ", flush=True)
    
    try:
        from_date = (date.today() - timedelta(days=days)).isoformat()
        to_date = date.today().isoformat()
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptSaleOrderDetailHistory",
                "fromDate": from_date,
                "toDate": to_date
            })
            response.raise_for_status()
            data = response.json()
        
        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return (0, 0, 0)
        
        nuevos = 0
        actualizados = 0
        
        for record in data:
            try:
                sodhID = record.get('sodhID') or record.get('sodh_id')
                if not sodhID:
                    continue
                
                existente = db.query(SaleOrderDetailHistory).filter(
                    SaleOrderDetailHistory.sodh_id == sodhID
                ).first()
                
                def parse_dt(val):
                    if not val:
                        return None
                    try:
                        return datetime.fromisoformat(val.replace('T', ' ').replace('Z', ''))
                    except:
                        return None
                
                datos = {
                    'sodh_id': sodhID,
                    'comp_id': record.get('comp_id'),
                    'bra_id': record.get('bra_id'),
                    'soh_id': record.get('soh_id'),
                    'sod_id': record.get('sod_id'),
                    'sodh_cd': parse_dt(record.get('sodh_cd')),
                    'sodh_action': record.get('sodh_action'),
                    'user_id': record.get('user_id'),
                    'sodh_previousvalue': record.get('sodh_previousValue'),
                    'sodh_newvalue': record.get('sodh_newValue'),
                }
                
                if existente:
                    for key, value in datos.items():
                        setattr(existente, key, value)
                    actualizados += 1
                else:
                    nuevo = SaleOrderDetailHistory(**datos)
                    db.add(nuevo)
                    nuevos += 1
                
                if (nuevos + actualizados) % 500 == 0:
                    db.commit()
            
            except Exception:
                continue
        
        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return (nuevos, actualizados, 0)
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return (0, 0, 0)


async def main_async(days: int = 7):
    """
    Función principal async.
    
    Args:
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"SYNC SALE ORDERS (últimos {days} días) - {timestamp}")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        # Sincronizar las 4 tablas
        result_header = await sync_sale_order_header(db, days)
        result_detail = await sync_sale_order_detail(db, days)
        result_header_hist = await sync_sale_order_header_history(db, days)
        result_detail_hist = await sync_sale_order_detail_history(db, days)
        
        print("\n" + "=" * 60)
        print("✅ SINCRONIZACIÓN COMPLETADA")
        print("=" * 60)
        print(f"Sale Order Header: {result_header[0]} nuevos, {result_header[1]} actualizados")
        print(f"Sale Order Detail: {result_detail[0]} nuevos, {result_detail[1]} actualizados")
        print(f"Header History: {result_header_hist[0]} nuevos, {result_header_hist[1]} actualizados")
        print(f"Detail History: {result_detail_hist[0]} nuevos, {result_detail_hist[1]} actualizados")
        
    except Exception as e:
        print(f"\n❌ Error durante la sincronización: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Sync Sale Orders desde ERP')
    parser.add_argument('--days', type=int, default=7,
                        help='Días hacia atrás para sincronizar (default: 7 para ejecuciones cada 5-10 min)')
    args = parser.parse_args()
    
    import asyncio
    asyncio.run(main_async(args.days))


if __name__ == "__main__":
    main()
