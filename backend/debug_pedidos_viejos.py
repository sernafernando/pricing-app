#!/usr/bin/env python3
"""
Script para verificar pedidos viejos en la DB
"""
import sys
import os
from pathlib import Path

# Agregar el directorio app al path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from app.core.config import settings
from datetime import datetime

def main():
    print("🔍 VERIFICANDO PEDIDOS VIEJOS EN LA DB\n")
    
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        # 1. Total de pedidos activos y rango de fechas
        print("=" * 80)
        print("📊 PEDIDOS ACTIVOS (export_id=80, export_activo=true)")
        print("=" * 80)
        
        result = conn.execute(text("""
            SELECT 
                COUNT(*) as total_activos,
                MIN(soh_cd) as mas_viejo,
                MAX(soh_cd) as mas_nuevo
            FROM tb_sale_order_header 
            WHERE export_id = 80 AND export_activo = true
        """))
        
        row = result.fetchone()
        print(f"Total de pedidos activos: {row[0]}")
        print(f"Pedido más viejo: {row[1]}")
        print(f"Pedido más nuevo: {row[2]}")
        print()
        
        # 2. Los 10 pedidos más viejos
        print("=" * 80)
        print("👴 LOS 10 PEDIDOS ACTIVOS MÁS VIEJOS")
        print("=" * 80)
        
        result = conn.execute(text("""
            SELECT soh_id, soh_cd, bra_id, cust_id, user_id
            FROM tb_sale_order_header 
            WHERE export_id = 80 AND export_activo = true 
            ORDER BY soh_cd ASC 
            LIMIT 10
        """))
        
        print(f"{'SOH_ID':<10} {'FECHA':<20} {'BRA_ID':<8} {'CUST_ID':<10} {'USER_ID':<10}")
        print("-" * 80)
        for row in result:
            fecha_str = row[1].strftime('%Y-%m-%d %H:%M:%S') if row[1] else 'N/A'
            print(f"{row[0]:<10} {fecha_str:<20} {row[2]:<8} {row[3] or 'N/A':<10} {row[4] or 'N/A':<10}")
        print()
        
        # 3. Pedidos por rango de fechas
        print("=" * 80)
        print("📅 PEDIDOS ACTIVOS POR RANGO DE FECHAS")
        print("=" * 80)
        
        result = conn.execute(text("""
            SELECT 
                DATE_TRUNC('month', soh_cd) as mes,
                COUNT(*) as cantidad
            FROM tb_sale_order_header 
            WHERE export_id = 80 AND export_activo = true AND soh_cd IS NOT NULL
            GROUP BY DATE_TRUNC('month', soh_cd)
            ORDER BY mes DESC
            LIMIT 12
        """))
        
        print(f"{'MES':<15} {'CANTIDAD':<10}")
        print("-" * 80)
        for row in result:
            mes_str = row[0].strftime('%Y-%m') if row[0] else 'N/A'
            print(f"{mes_str:<15} {row[1]:<10}")
        print()
        
        # 4. Última sincronización
        print("=" * 80)
        print("🔄 ÚLTIMAS SINCRONIZACIONES (tb_export_87_snapshot)")
        print("=" * 80)
        
        result = conn.execute(text("""
            SELECT snapshot_date, COUNT(*) as registros 
            FROM tb_export_87_snapshot 
            GROUP BY snapshot_date 
            ORDER BY snapshot_date DESC 
            LIMIT 5
        """))
        
        rows = result.fetchall()
        if rows:
            print(f"{'FECHA':<30} {'REGISTROS':<10}")
            print("-" * 80)
            for row in rows:
                fecha_str = row[0].strftime('%Y-%m-%d %H:%M:%S') if row[0] else 'N/A'
                print(f"{fecha_str:<30} {row[1]:<10}")
        else:
            print("⚠️  No hay snapshots en la tabla tb_export_87_snapshot")
        print()
        
        # 5. Pedidos de enero 2026
        print("=" * 80)
        print("🆕 PEDIDOS DE ENERO 2026")
        print("=" * 80)
        
        result = conn.execute(text("""
            SELECT COUNT(*) as total
            FROM tb_sale_order_header 
            WHERE export_id = 80 
              AND export_activo = true 
              AND soh_cd >= '2026-01-01'
        """))
        
        row = result.fetchone()
        print(f"Total de pedidos activos de enero 2026: {row[0]}")
        print()
        
        # 6. Pedidos de octubre 2025 (los viejos que mencionaste)
        print("=" * 80)
        print("👻 PEDIDOS DE OCTUBRE 2025 (VIEJOS)")
        print("=" * 80)
        
        result = conn.execute(text("""
            SELECT COUNT(*) as total
            FROM tb_sale_order_header 
            WHERE export_id = 80 
              AND export_activo = true 
              AND soh_cd >= '2025-10-01'
              AND soh_cd < '2025-11-01'
        """))
        
        row = result.fetchone()
        print(f"Total de pedidos activos de octubre 2025: {row[0]}")
        
        if row[0] > 0:
            print("\n⚠️  PROBLEMA DETECTADO: Hay pedidos de octubre 2025 marcados como activos!")
            print("   Esto significa que:")
            print("   1. El Export 87 del ERP está devolviendo pedidos viejos, O")
            print("   2. La última sincronización no se ejecutó correctamente desde octubre")
        print()

if __name__ == "__main__":
    main()
