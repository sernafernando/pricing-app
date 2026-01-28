#!/usr/bin/env python3
"""
Script para sincronizar tb_tiendanube_orders con rango de fechas específico.
Uso: python sync_tn_orders_range.py 2025-08-01 2026-01-28
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

import httpx
from datetime import datetime
from sqlalchemy import text
from app.core.database import SessionLocal

GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def sync_tiendanube_orders(from_date_str: str, to_date_str: str):
    """
    Sincroniza órdenes de TiendaNube desde el ERP.
    
    Args:
        from_date_str: Fecha desde (YYYY-MM-DD)
        to_date_str: Fecha hasta (YYYY-MM-DD)
    """
    print(f"{'='*80}")
    print(f"🔄 SINCRONIZAR tb_tiendanube_orders")
    print(f"{'='*80}")
    print(f"Rango: {from_date_str} → {to_date_str}")
    print()
    
    db = SessionLocal()
    
    try:
        # 1. Estado ANTES
        result = db.execute(text("""
            SELECT 
                COUNT(*) as total,
                MIN(tno_cd)::date as mas_viejo,
                MAX(tno_cd)::date as mas_nuevo
            FROM tb_tiendanube_orders
        """))
        row = result.fetchone()
        print(f"📊 Estado ANTES:")
        print(f"   - Total registros: {row[0]}")
        print(f"   - Registro más viejo: {row[1]}")
        print(f"   - Registro más nuevo: {row[2]}")
        print()
        
        # 2. Llamar al ERP
        print(f"🌐 Consultando ERP (scriptTiendaNubeOrders)...")
        print(f"   URL: {GBP_PARSER_URL}")
        print(f"   Rango: {from_date_str} a {to_date_str}")
        print()
        
        response = httpx.post(
            GBP_PARSER_URL,
            json={
                "strScriptLabel": "scriptTiendaNubeOrders",
                "fromDate": from_date_str,
                "toDate": to_date_str
            },
            timeout=180.0  # 3 minutos para rangos grandes
        )
        
        if response.status_code != 200:
            print(f"❌ Error HTTP {response.status_code}: {response.text}")
            return False
        
        data = response.json()
        
        if not data or not isinstance(data, list):
            print("❌ No se obtuvieron datos del ERP")
            return False
        
        print(f"✅ Obtenidos {len(data)} registros del ERP")
        print()
        
        # 3. Insertar/actualizar en DB (batch)
        print(f"💾 Actualizando base de datos...")
        
        nuevos = 0
        actualizados = 0
        errores = 0
        
        for i, record in enumerate(data):
            try:
                comp_id = record.get('comp_id')
                tno_id = record.get('tno_id')
                
                if not comp_id or not tno_id:
                    errores += 1
                    continue
                
                # Verificar si existe
                exists = db.execute(text("""
                    SELECT 1 FROM tb_tiendanube_orders 
                    WHERE comp_id = :comp_id AND tno_id = :tno_id
                """), {"comp_id": comp_id, "tno_id": tno_id}).fetchone()
                
                if exists:
                    # Actualizar
                    db.execute(text("""
                        UPDATE tb_tiendanube_orders SET
                            tno_cd = :tno_cd,
                            tn_id = :tn_id,
                            tno_orderID = :tno_orderID,
                            "tno_JSon" = :tno_json,
                            bra_id = :bra_id,
                            soh_id = :soh_id,
                            cust_id = :cust_id,
                            tno_isCancelled = :tno_isCancelled
                        WHERE comp_id = :comp_id AND tno_id = :tno_id
                    """), {
                        "comp_id": comp_id,
                        "tno_id": tno_id,
                        "tno_cd": record.get('tno_cd'),
                        "tn_id": record.get('tn_id'),
                        "tno_orderID": record.get('tno_orderID'),
                        "tno_json": record.get('tno_JSon'),
                        "bra_id": record.get('bra_id'),
                        "soh_id": record.get('soh_id'),
                        "cust_id": record.get('cust_id'),
                        "tno_isCancelled": record.get('tno_isCancelled', False)
                    })
                    actualizados += 1
                else:
                    # Insertar nuevo
                    db.execute(text("""
                        INSERT INTO tb_tiendanube_orders (
                            comp_id, tno_id, tno_cd, tn_id, tno_orderID, 
                            "tno_JSon", bra_id, soh_id, cust_id, tno_isCancelled
                        ) VALUES (
                            :comp_id, :tno_id, :tno_cd, :tn_id, :tno_orderID,
                            :tno_json, :bra_id, :soh_id, :cust_id, :tno_isCancelled
                        )
                    """), {
                        "comp_id": comp_id,
                        "tno_id": tno_id,
                        "tno_cd": record.get('tno_cd'),
                        "tn_id": record.get('tn_id'),
                        "tno_orderID": record.get('tno_orderID'),
                        "tno_json": record.get('tno_JSon'),
                        "bra_id": record.get('bra_id'),
                        "soh_id": record.get('soh_id'),
                        "cust_id": record.get('cust_id'),
                        "tno_isCancelled": record.get('tno_isCancelled', False)
                    })
                    nuevos += 1
                
                # Commit cada 100 registros
                if (i + 1) % 100 == 0:
                    db.commit()
                    print(f"   Procesados: {i + 1}/{len(data)} ({nuevos} nuevos, {actualizados} actualizados)")
            
            except Exception as e:
                print(f"   ⚠️  Error en registro {i}: {e}")
                errores += 1
                continue
        
        db.commit()
        
        print()
        print(f"✅ Sincronización completada:")
        print(f"   - Nuevos: {nuevos}")
        print(f"   - Actualizados: {actualizados}")
        print(f"   - Errores: {errores}")
        print()
        
        # 4. Estado DESPUÉS
        result = db.execute(text("""
            SELECT 
                COUNT(*) as total,
                MIN(tno_cd)::date as mas_viejo,
                MAX(tno_cd)::date as mas_nuevo,
                COUNT(*) FILTER (WHERE tno_isCancelled = true) as cancelados
            FROM tb_tiendanube_orders
        """))
        row = result.fetchone()
        print(f"📊 Estado DESPUÉS:")
        print(f"   - Total registros: {row[0]}")
        print(f"   - Registro más viejo: {row[1]}")
        print(f"   - Registro más nuevo: {row[2]}")
        print(f"   - Cancelados: {row[3]}")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    if len(sys.argv) != 3:
        print("❌ Uso: python sync_tn_orders_range.py FECHA_DESDE FECHA_HASTA")
        print("   Ejemplo: python sync_tn_orders_range.py 2025-08-01 2026-01-28")
        sys.exit(1)
    
    from_date = sys.argv[1]
    to_date = sys.argv[2]
    
    # Validar formato de fechas
    try:
        datetime.strptime(from_date, '%Y-%m-%d')
        datetime.strptime(to_date, '%Y-%m-%d')
    except ValueError:
        print("❌ Formato de fecha inválido. Usar: YYYY-MM-DD")
        sys.exit(1)
    
    print(f"\n{'='*80}")
    print(f"🚀 SINCRONIZAR TIENDANUBE ORDERS")
    print(f"{'='*80}\n")
    
    success = sync_tiendanube_orders(from_date, to_date)
    
    if success:
        print(f"{'='*80}")
        print(f"✅ SINCRONIZACIÓN COMPLETADA")
        print(f"{'='*80}\n")
        print("💡 Próximos pasos:")
        print("   1. Ejecutá el script para archivar pedidos cancelados")
        print("   2. Refrescá el frontend y verificá que se hayan limpiado los pedidos viejos")
        print()
    else:
        print(f"\n❌ SINCRONIZACIÓN FALLIDA")


if __name__ == "__main__":
    main()
