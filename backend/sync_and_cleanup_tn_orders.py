#!/usr/bin/env python3
"""
Script para:
1. Sincronizar tb_tiendanube_orders desde el ERP (últimos 60 días)
2. Archivar pedidos cancelados en TiendaNube
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

import httpx
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app.core.database import SessionLocal

GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def sync_tiendanube_orders(days_back: int = 60):
    """
    Sincroniza órdenes de TiendaNube desde el ERP.
    """
    from_date = date.today() - timedelta(days=days_back)
    to_date = date.today()
    
    print(f"{'='*80}")
    print(f"🔄 PASO 1: SINCRONIZAR tb_tiendanube_orders")
    print(f"{'='*80}")
    print(f"Rango: {from_date} → {to_date} ({days_back} días)")
    print()
    
    db = SessionLocal()
    
    try:
        # 1. Estado ANTES
        result = db.execute(text("""
            SELECT 
                COUNT(*) as total,
                MAX(tno_cd)::date as ultima_actualizacion
            FROM tb_tiendanube_orders
        """))
        row = result.fetchone()
        print(f"📊 Estado ANTES:")
        print(f"   - Total registros: {row[0]}")
        print(f"   - Última actualización: {row[1]}")
        print()
        
        # 2. Llamar al ERP
        print(f"🌐 Consultando ERP (scriptTiendaNubeOrders)...")
        
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
            return False
        
        data = response.json()
        
        if not data or not isinstance(data, list):
            print("❌ No se obtuvieron datos del ERP")
            return False
        
        print(f"✅ Obtenidos {len(data)} registros del ERP")
        print()
        
        # 3. Insertar/actualizar en DB
        print(f"💾 Actualizando base de datos...")
        
        nuevos = 0
        actualizados = 0
        
        for record in data:
            comp_id = record.get('comp_id')
            tno_id = record.get('tno_id')
            
            if not comp_id or not tno_id:
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
            
            if (nuevos + actualizados) % 100 == 0:
                db.commit()
        
        db.commit()
        
        print(f"✅ Sincronización completada:")
        print(f"   - Nuevos: {nuevos}")
        print(f"   - Actualizados: {actualizados}")
        print()
        
        # 4. Estado DESPUÉS
        result = db.execute(text("""
            SELECT 
                COUNT(*) as total,
                MAX(tno_cd)::date as ultima_actualizacion,
                COUNT(*) FILTER (WHERE tno_isCancelled = true) as cancelados
            FROM tb_tiendanube_orders
        """))
        row = result.fetchone()
        print(f"📊 Estado DESPUÉS:")
        print(f"   - Total registros: {row[0]}")
        print(f"   - Última actualización: {row[1]}")
        print(f"   - Cancelados: {row[2]}")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def archive_cancelled_orders():
    """
    Marca como inactivos (export_activo=false) los pedidos TN que están cancelados.
    """
    print(f"{'='*80}")
    print(f"🗂️  PASO 2: ARCHIVAR PEDIDOS CANCELADOS")
    print(f"{'='*80}")
    print()
    
    db = SessionLocal()
    
    try:
        # 1. Cuántos pedidos TN activos hay
        result = db.execute(text("""
            SELECT COUNT(*) 
            FROM tb_sale_order_header 
            WHERE export_id = 80 
              AND export_activo = true 
              AND user_id = 50021
        """))
        total_tn_activos = result.fetchone()[0]
        print(f"📊 Pedidos TN activos actuales: {total_tn_activos}")
        
        # 2. Cuántos están cancelados en tb_tiendanube_orders
        result = db.execute(text("""
            SELECT COUNT(DISTINCT tsoh.soh_id)
            FROM tb_sale_order_header tsoh
            INNER JOIN tb_tiendanube_orders tno ON tsoh.soh_id = tno.soh_id AND tsoh.bra_id = tno.bra_id
            WHERE tsoh.export_id = 80 
              AND tsoh.export_activo = true 
              AND tsoh.user_id = 50021
              AND tno.tno_isCancelled = true
        """))
        total_a_archivar = result.fetchone()[0]
        print(f"⚠️  Pedidos TN cancelados (a archivar): {total_a_archivar}")
        print()
        
        if total_a_archivar == 0:
            print("✅ No hay pedidos TN cancelados para archivar")
            return
        
        # 3. Archivar
        print(f"🗂️  Archivando {total_a_archivar} pedidos cancelados...")
        
        result = db.execute(text("""
            UPDATE tb_sale_order_header tsoh
            SET export_activo = false
            FROM tb_tiendanube_orders tno
            WHERE tsoh.soh_id = tno.soh_id 
              AND tsoh.bra_id = tno.bra_id
              AND tsoh.export_id = 80 
              AND tsoh.export_activo = true 
              AND tsoh.user_id = 50021
              AND tno.tno_isCancelled = true
        """))
        
        archivados = result.rowcount
        db.commit()
        
        print(f"✅ Archivados: {archivados} pedidos")
        print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def main():
    print(f"\n{'='*80}")
    print(f"🚀 SINCRONIZAR Y LIMPIAR PEDIDOS TIENDANUBE")
    print(f"{'='*80}\n")
    
    # Paso 1: Sincronizar tb_tiendanube_orders
    success = sync_tiendanube_orders(days_back=60)
    
    if not success:
        print("\n❌ Falló la sincronización. No se puede continuar.")
        return
    
    # Paso 2: Archivar pedidos cancelados
    archive_cancelled_orders()
    
    print(f"{'='*80}")
    print(f"✅ PROCESO COMPLETADO")
    print(f"{'='*80}\n")
    print("💡 Próximos pasos:")
    print("   1. Refrescá el frontend y verificá que no haya pedidos cancelados")
    print("   2. Si todavía hay pedidos viejos, ejecutá la sincronización del Export 87")
    print("   3. Considerá programar este script como cron job diario")
    print()


if __name__ == "__main__":
    main()
