#!/usr/bin/env python3
"""
Script CORREGIDO para arreglar df_id y sd_id NULL en tb_commercial_transactions

DIFERENCIA CON LA VERSIÓN ANTERIOR:
- Ahora usa ct_docnumber para diferenciar Facturas de Notas de Crédito
- No pisa registros que ya tienen df_id correcto

Problema: GAUSSONLINE sincroniza transacciones con df_id/sd_id NULL desde enero 2025.

Solución: Mapea bra_id + ct_kindof + ct_pointofsale + rango ct_docnumber → df_id correcto

Ejecutar:
    python scripts/fix_df_sd_null_daily_v2.py
    
Cron (diario a las 3:20 AM):
    20 3 * * * cd /var/www/html/pricing-app/backend && venv/bin/python scripts/fix_df_sd_null_daily_v2.py >> /var/log/pricing-app/fix_df_sd_null.log 2>&1
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


# ============================================================================
# MAPEO CORREGIDO: Incluye bra_id y rangos de ct_docnumber
# ============================================================================
# Formato: (bra_id, ct_kindof, ct_pointofsale, docnumber_min, docnumber_max, df_id, sd_id, descripcion)

DF_ID_MAPPING = [
    # PUNTO 5 - bra_id=1
    # Facturas A punto 5
    (1, 'A', 5, 0, 1564, 1, 1, '01.Fc A 0005'),
    (1, 'A', 5, 1584, 999999, 1, 1, '01.Fc A 0005'),
    # NC A punto 5
    (1, 'A', 5, 1565, 1583, 5, 3, '01.Nc A 0005'),
    
    # Facturas B punto 5
    (1, 'B', 5, 0, 4644, 2, 1, '01.Fc B 0005'),
    (1, 'B', 5, 4657, 999999, 2, 1, '01.Fc B 0005'),
    # NC B punto 5
    (1, 'B', 5, 4645, 4656, 6, 3, '01.Nc B 0005'),
    
    # Recibos X punto 5
    (1, 'X', 5, 0, 999999, 8, 1, '01.Rc X 0005'),
    
    # Remitos R punto 5
    (1, 'R', 5, 0, 999999, 7, 1, '01.Rm R 0005'),
    
    # PUNTO 3 - bra_id=45
    # Facturas A punto 3
    (45, 'A', 3, 0, 101, 129, 1, '21.Fc A 00003 Grupo Gauss ML'),
    (45, 'A', 3, 209, 999999, 129, 1, '21.Fc A 00003 Grupo Gauss ML'),
    # NC A punto 3
    (45, 'A', 3, 102, 208, 115, 3, '21.Nc A 00003 Grupo Gauss ML'),
    
    # Facturas B punto 3
    (45, 'B', 3, 0, 354, 130, 1, '21.Fc B 00003 Grupo Gauss ML'),
    (45, 'B', 3, 807, 999999, 130, 1, '21.Fc B 00003 Grupo Gauss ML'),
    # NC B punto 3
    (45, 'B', 3, 355, 806, 116, 3, '21.Nc B 00003 Grupo Gauss ML'),
    
    # Recibos X punto 3
    (45, 'X', 3, 0, 999999, 112, 1, '21.Rc X 0003'),
    
    # PUNTO 2 - Sucursal Nueva (solo Facturas/Recibos - no tenemos NCs aquí por ahora)
    (None, 'A', 2, 0, 999999, 65, 1, '02.Fc A 0002 S.Nueva'),
    (None, 'B', 2, 0, 999999, 69, 1, '02.Fc B 0002 S.Nueva'),
    (None, 'X', 2, 0, 999999, 75, 1, '02.Rc X 0002 S.Nueva'),
    (None, 'R', 2, 0, 999999, 78, 1, '02.Rm R 0002 S.Nueva'),
    
    # PUNTO 10 - Remitos
    (None, 'R', 10, 0, 999999, 107, 1, '21.Rm R 0010'),
]


def fix_df_id_null(db):
    """Corrige df_id NULL basándose en bra_id + ct_kindof + ct_pointofsale + ct_docnumber"""
    total = 0
    
    for bra_id, ct_kindof, ct_pointofsale, doc_min, doc_max, df_id, sd_id, descripcion in DF_ID_MAPPING:
        # Construir filtro de bra_id (si aplica)
        bra_filter = "AND bra_id = :bra_id" if bra_id is not None else ""
        
        query = text(f"""
            UPDATE tb_commercial_transactions
            SET df_id = :df_id, sd_id = :sd_id
            WHERE df_id IS NULL
              AND ct_kindof = :ct_kindof
              AND ct_pointofsale = :ct_pointofsale
              {bra_filter}
              AND ct_docnumber ~ '^[0-9]+$'
              AND ct_docnumber::int >= :doc_min
              AND ct_docnumber::int <= :doc_max
              AND ct_date >= CURRENT_DATE - INTERVAL '7 days'
        """)
        
        params = {
            'df_id': df_id,
            'sd_id': sd_id,
            'ct_kindof': ct_kindof,
            'ct_pointofsale': ct_pointofsale,
            'doc_min': doc_min,
            'doc_max': doc_max
        }
        
        if bra_id is not None:
            params['bra_id'] = bra_id
        
        result = db.execute(query, params)
        count = result.rowcount
        
        if count > 0:
            print(f"  ✓ {descripcion} (docnumber {doc_min}-{doc_max}) → df_id={df_id}, sd_id={sd_id}: {count} registros")
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
    print("=" * 80)
    print("FIX df_id/sd_id NULL - VERSIÓN CORREGIDA (usa ct_docnumber)")
    print("=" * 80)
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
        
        # Corregir df_id y sd_id en un solo paso
        print(f"\n🔧 Corrigiendo df_id y sd_id NULL usando ct_docnumber...")
        total_fixed = fix_df_id_null(db)
        db.commit()
        
        # Estadísticas DESPUÉS
        df_null_after, sd_null_after = get_stats(db)
        print(f"\n📊 DESPUÉS:")
        print(f"  df_id NULL: {df_null_after}")
        print(f"  sd_id NULL: {sd_null_after}")
        print(f"  Corregidos: {total_fixed}")
        
        if df_null_after > 0 or sd_null_after > 0:
            print(f"\n⚠️  ADVERTENCIA: Aún quedan {df_null_after + sd_null_after} registros con NULL")
            print("   Revisar si hay nuevos patrones de ct_docnumber que agregar al mapeo.")
        
        print("\n" + "=" * 80)
        print("✅ COMPLETADO")
        print("=" * 80)
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
