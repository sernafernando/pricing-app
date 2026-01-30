#!/usr/bin/env python3
"""
Script para corregir df_id y sd_id NULL en tb_commercial_transactions

Problema: GAUSSONLINE sincroniza transacciones con df_id/sd_id NULL desde enero 2025,
impidiendo el cálculo de métricas de rentabilidad.

Solución: Mapea ct_kindof + ct_pointofsale a df_id/sd_id correcto basándose en 
patrones históricos de uso.

Ejecutar:
    python scripts/fix_df_sd_null_daily.py
    
Cron (diario a las 3:20 AM):
    20 3 * * * cd /var/www/html/pricing-app/backend && venv/bin/python scripts/fix_df_sd_null_daily.py >> /var/log/pricing-app/fix_df_sd_null.log 2>&1
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

from datetime import datetime
from sqlalchemy import text
from app.core.database import SessionLocal


# Mapeo ct_kindof + ct_pointofsale -> df_id
DF_ID_MAPPING = [
    ('B', 5, 2),    # 01.Fc B 0005
    ('A', 5, 1),    # 01.Fc A 0005
    ('A', 3, 129),  # 21.Fc A 00003 Grupo Gauss mercadolibre
    ('B', 3, 130),  # 21.Fc B 00003 Grupo Gauss Mercadolibre
    ('X', 5, 8),    # 01.Rc X 0005
    ('X', 3, 112),  # 21.Rc X 0003
    ('X', 2, 75),   # 02.Rc X 0002 S.Nueva
    ('R', 5, 7),    # 01.Rm R 0005
    ('R', 10, 107), # 21-Rm R 0010
    ('A', 2, 65),   # 02Fc A 0002 S.Nueva
    ('B', 2, 69),   # 02.Fc B 0001 S.Nueva
]

# Mapeo df_id -> sd_id
SD_ID_MAPPING = [
    # Facturas A/B -> sd_id = 1 (venta)
    ([1, 2, 65, 69, 129, 130], 1),
    # Recibos X -> sd_id = 1 (venta)
    ([8, 75, 112], 1),
    # Notas de crédito -> sd_id = 3 (devolución)
    ([5, 6, 73, 115, 116], 3),
    # Remitos R -> sd_id = 1 (entrega)
    ([7, 60, 64, 78, 107, 110], 1),
]


def fix_df_id_null(db):
    """Corrige df_id NULL basándose en ct_kindof + ct_pointofsale"""
    total = 0
    
    for ct_kindof, ct_pointofsale, df_id in DF_ID_MAPPING:
        query = text("""
            UPDATE tb_commercial_transactions
            SET df_id = :df_id
            WHERE df_id IS NULL
              AND ct_kindof = :ct_kindof
              AND ct_pointofsale = :ct_pointofsale
              AND ct_date >= CURRENT_DATE - INTERVAL '7 days'
        """)
        
        result = db.execute(query, {
            'df_id': df_id,
            'ct_kindof': ct_kindof,
            'ct_pointofsale': ct_pointofsale
        })
        
        count = result.rowcount
        if count > 0:
            print(f"  ✓ ct_kindof={ct_kindof} punto={ct_pointofsale} → df_id={df_id}: {count} registros")
            total += count
    
    return total


def fix_sd_id_null(db):
    """Corrige sd_id NULL basándose en df_id"""
    total = 0
    
    for df_ids, sd_id in SD_ID_MAPPING:
        df_ids_str = ','.join(map(str, df_ids))
        
        query = text(f"""
            UPDATE tb_commercial_transactions
            SET sd_id = :sd_id
            WHERE sd_id IS NULL
              AND df_id IN ({df_ids_str})
              AND ct_date >= CURRENT_DATE - INTERVAL '7 days'
        """)
        
        result = db.execute(query, {'sd_id': sd_id})
        
        count = result.rowcount
        if count > 0:
            print(f"  ✓ df_id IN ({df_ids_str}) → sd_id={sd_id}: {count} registros")
            total += count
    
    return total


def get_stats(db):
    """Obtiene estadísticas de registros NULL recientes"""
    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE df_id IS NULL) as df_id_null,
            COUNT(*) FILTER (WHERE sd_id IS NULL) as sd_id_null
        FROM tb_commercial_transactions
        WHERE ct_date >= CURRENT_DATE - INTERVAL '7 days'
    """)
    
    result = db.execute(query).fetchone()
    return result.df_id_null, result.sd_id_null


def main():
    print("=" * 70)
    print("FIX df_id/sd_id NULL - Últimos 7 días")
    print("=" * 70)
    print(f"Ejecutado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    db = SessionLocal()
    
    try:
        # Estadísticas ANTES
        df_null_before, sd_null_before = get_stats(db)
        print(f"\n📊 ANTES:")
        print(f"  df_id NULL: {df_null_before}")
        print(f"  sd_id NULL: {sd_null_before}")
        
        if df_null_before == 0 and sd_null_before == 0:
            print("\n✅ No hay registros con NULL. Todo OK!")
            return
        
        # Corregir df_id
        print(f"\n🔧 Corrigiendo df_id NULL...")
        df_fixed = fix_df_id_null(db)
        db.commit()
        
        # Corregir sd_id
        print(f"\n🔧 Corrigiendo sd_id NULL...")
        sd_fixed = fix_sd_id_null(db)
        db.commit()
        
        # Estadísticas DESPUÉS
        df_null_after, sd_null_after = get_stats(db)
        print(f"\n📊 DESPUÉS:")
        print(f"  df_id NULL: {df_null_after} (corregidos: {df_fixed})")
        print(f"  sd_id NULL: {sd_null_after} (corregidos: {sd_fixed})")
        
        print("\n" + "=" * 70)
        print("✅ COMPLETADO")
        print("=" * 70)
        print(f"Total corregidos: {df_fixed + sd_fixed}")
        print()
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
