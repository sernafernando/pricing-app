"""
Script para backfill de prli_id en órdenes históricas de MercadoLibre.

Este script intenta rellenar el prli_id de órdenes viejas usando:
1. tb_ml_publication_snapshots: snapshot más cercano a la fecha de venta
2. tb_mercadolibre_items_publicados: pricelist actual (último recurso, puede ser incorrecto)

IMPORTANTE: Este backfill es "best effort" y puede no ser 100% preciso para órdenes antiguas.
Las nuevas órdenes sincronizadas SÍ tendrán el prli_id correcto del ERP.

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.backfill_ml_orders_prli_id
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

from sqlalchemy.orm import Session
from sqlalchemy import text, func
from app.core.database import SessionLocal
import app.models  # noqa


def backfill_prli_id_from_snapshots(db: Session, limit: int = 1000):
    """
    Backfill prli_id usando snapshots de publicaciones.
    """
    
    print("📊 Buscando órdenes sin prli_id...")
    
    # Contar órdenes sin prli_id
    count_query = text("""
        SELECT COUNT(*) 
        FROM tb_mercadolibre_orders_header 
        WHERE prli_id IS NULL
    """)
    
    total_sin_prli = db.execute(count_query).scalar()
    print(f"   Encontradas {total_sin_prli} órdenes sin prli_id\n")
    
    if total_sin_prli == 0:
        print("✅ Todas las órdenes ya tienen prli_id")
        return 0
    
    # Query para actualizar usando snapshots
    update_query = text("""
        WITH snapshot_lookup AS (
            SELECT DISTINCT ON (tmloh.mlo_id)
                tmloh.mlo_id,
                CASE 
                    WHEN tmloh.mlo_ismshops = TRUE THEN tmps.prli_id4mercadoshop 
                    ELSE tmps.prli_id 
                END as snapshot_prli_id,
                ABS(EXTRACT(EPOCH FROM (tmps.snapshot_date - tmloh.ml_date_created))) as time_diff
            FROM tb_mercadolibre_orders_header tmloh
            INNER JOIN tb_mercadolibre_orders_detail tmlod 
                ON tmlod.comp_id = tmloh.comp_id 
                AND tmlod.mlo_id = tmloh.mlo_id
            INNER JOIN tb_ml_publication_snapshots tmps
                ON tmps.ml_id = tmlod.ml_id
            WHERE tmloh.prli_id IS NULL
                AND tmps.prli_id IS NOT NULL
            ORDER BY tmloh.mlo_id, time_diff ASC
        ),
        current_pricelist_lookup AS (
            SELECT DISTINCT ON (tmloh.mlo_id)
                tmloh.mlo_id,
                CASE 
                    WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop 
                    ELSE tmlip.prli_id 
                END as current_prli_id
            FROM tb_mercadolibre_orders_header tmloh
            INNER JOIN tb_mercadolibre_orders_detail tmlod 
                ON tmlod.comp_id = tmloh.comp_id 
                AND tmlod.mlo_id = tmloh.mlo_id
            INNER JOIN tb_mercadolibre_items_publicados tmlip
                ON tmlip.ml_id = tmlod.ml_id
            WHERE tmloh.prli_id IS NULL
        )
        UPDATE tb_mercadolibre_orders_header AS tmloh
        SET prli_id = COALESCE(sl.snapshot_prli_id, cpl.current_prli_id)
        FROM snapshot_lookup sl
        FULL OUTER JOIN current_pricelist_lookup cpl ON cpl.mlo_id = sl.mlo_id
        WHERE tmloh.mlo_id = COALESCE(sl.mlo_id, cpl.mlo_id)
            AND tmloh.prli_id IS NULL
            AND (sl.snapshot_prli_id IS NOT NULL OR cpl.current_prli_id IS NOT NULL)
    """)
    
    try:
        print("🔄 Ejecutando backfill...")
        result = db.execute(update_query)
        db.commit()
        
        rows_updated = result.rowcount
        print("✅ Backfill completado!")
        print(f"   Órdenes actualizadas: {rows_updated}")
        print(f"   Órdenes pendientes: {total_sin_prli - rows_updated}")
        
        if total_sin_prli - rows_updated > 0:
            print("\n⚠️  Algunas órdenes no pudieron ser actualizadas:")
            print("   - No tienen snapshots cercanos")
            print("   - No tienen publicación en items_publicados")
            print("   Estas órdenes quedarán con prli_id = NULL")
        
        return rows_updated
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error en backfill: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    """
    Backfill de prli_id en órdenes históricas
    """
    print("🚀 Backfill de prli_id en órdenes MercadoLibre")
    print("=" * 60)
    print("⚠️  ADVERTENCIA: Este proceso actualiza datos históricos")
    print("   usando el snapshot más cercano a la fecha de venta.")
    print("   Puede no ser 100% preciso para órdenes antiguas.")
    print("=" * 60)
    print()
    
    respuesta = input("¿Continuar? (s/N): ")
    if respuesta.lower() not in ['s', 'si', 'yes', 'y']:
        print("❌ Operación cancelada")
        return
    
    db = SessionLocal()
    
    try:
        rows_updated = backfill_prli_id_from_snapshots(db)
        print("=" * 60)
        
        if rows_updated > 0:
            print("\n💡 Próximo paso:")
            print("   Regenerar métricas ML para que usen el prli_id actualizado:")
            print("   python -m app.scripts.agregar_metricas_ml_local --from-date 2025-01-01")
        
    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
