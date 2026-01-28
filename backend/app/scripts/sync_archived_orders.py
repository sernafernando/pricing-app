"""
Script para limpiar pedidos que pasaron a history.

EN EL ERP:
- Cuando un header se archiva → se BORRA de tb_sale_order_header y se MUEVE a tb_sale_order_header_history
- Cuando un detail se archiva → se BORRA de tb_sale_order_detail y se MUEVE a tb_sale_order_detail_history
- Un registro NUNCA está en ambas tablas (normal + history) a la vez

EN NUESTRA DB LOCAL:
- Sincronizamos ambas tablas independientemente
- Resultado: registros quedan DUPLICADOS

SOLUCIÓN:
1. Si soh_id está en tb_sale_order_header_history → BORRAR de tb_sale_order_header
2. Si sod_id está en tb_sale_order_detail_history → BORRAR de tb_sale_order_detail

Ejecutar: python -m app.scripts.sync_archived_orders
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.core.database import SessionLocal
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sync_archived_headers():
    """
    Borra headers que están en tb_sale_order_header_history.
    """
    db = SessionLocal()
    
    try:
        logger.info("🔄 Limpiando headers archivados...")
        
        # Contar cuántos headers duplicados hay
        result = db.execute(text("""
            SELECT COUNT(DISTINCT soh.soh_id)
            FROM tb_sale_order_header soh
            INNER JOIN tb_sale_order_header_history h
                ON soh.soh_id = h.soh_id
                AND soh.bra_id = h.bra_id
                AND soh.comp_id = h.comp_id
        """))
        
        total_duplicados = result.scalar()
        logger.info(f"📊 Headers duplicados (están en header Y history): {total_duplicados}")
        
        if total_duplicados == 0:
            logger.info("✅ No hay headers duplicados")
            return {"headers_borrados": 0}
        
        # Mostrar ejemplos
        result = db.execute(text("""
            SELECT 
                soh.soh_id,
                soh.soh_cd,
                soh.ssos_id,
                COUNT(DISTINCT h.sohh_id) as registros_history
            FROM tb_sale_order_header soh
            INNER JOIN tb_sale_order_header_history h
                ON soh.soh_id = h.soh_id
                AND soh.bra_id = h.bra_id
                AND soh.comp_id = h.comp_id
            GROUP BY soh.soh_id, soh.soh_cd, soh.ssos_id
            ORDER BY soh.soh_cd ASC
            LIMIT 10
        """))
        
        logger.info("\n📋 Ejemplos de headers a borrar:")
        logger.info(f"{'SOH_ID':<10} {'FECHA':<12} {'ESTADO':<8} {'REGISTROS_HISTORY':<20}")
        logger.info("-" * 60)
        for row in result:
            logger.info(f"{row[0]:<10} {str(row[1])[:10]:<12} {row[2]:<8} {row[3]:<20}")
        
        # BORRAR headers que están en history
        logger.info("\n🗑️  Borrando headers duplicados...")
        result = db.execute(text("""
            DELETE FROM tb_sale_order_header soh
            USING tb_sale_order_header_history h
            WHERE soh.soh_id = h.soh_id
              AND soh.bra_id = h.bra_id
              AND soh.comp_id = h.comp_id
        """))
        
        headers_borrados = result.rowcount
        db.commit()
        
        logger.info(f"✅ Headers borrados: {headers_borrados}")
        
        return {"headers_borrados": headers_borrados}
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        db.rollback()
        return {"headers_borrados": 0, "error": str(e)}
    finally:
        db.close()


def sync_archived_details():
    """
    Borra details que están en tb_sale_order_detail_history.
    """
    db = SessionLocal()
    
    try:
        logger.info("\n🔄 Limpiando details archivados...")
        
        # Contar cuántos details duplicados hay
        result = db.execute(text("""
            SELECT COUNT(*)
            FROM tb_sale_order_detail sod
            INNER JOIN tb_sale_order_detail_history h
                ON sod.sod_id = h.sod_id
                AND sod.soh_id = h.soh_id
                AND sod.bra_id = h.bra_id
                AND sod.comp_id = h.comp_id
        """))
        
        total_duplicados = result.scalar()
        logger.info(f"📊 Details duplicados (están en detail Y history): {total_duplicados}")
        
        if total_duplicados == 0:
            logger.info("✅ No hay details duplicados")
            return {"details_borrados": 0}
        
        # BORRAR details que están en history
        logger.info("🗑️  Borrando details duplicados...")
        result = db.execute(text("""
            DELETE FROM tb_sale_order_detail sod
            USING tb_sale_order_detail_history h
            WHERE sod.sod_id = h.sod_id
              AND sod.soh_id = h.soh_id
              AND sod.bra_id = h.bra_id
              AND sod.comp_id = h.comp_id
        """))
        
        details_borrados = result.rowcount
        db.commit()
        
        logger.info(f"✅ Details borrados: {details_borrados}")
        
        return {"details_borrados": details_borrados}
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        db.rollback()
        return {"details_borrados": 0, "error": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("\n" + "="*70)
    logger.info("LIMPIAR REGISTROS ARCHIVADOS (HISTORY)")
    logger.info("="*70 + "\n")
    
    # 1. Limpiar headers
    result_headers = sync_archived_headers()
    
    # 2. Limpiar details
    result_details = sync_archived_details()
    
    logger.info("\n" + "="*70)
    logger.info(f"RESULTADO FINAL:")
    logger.info(f"  - Headers borrados: {result_headers.get('headers_borrados', 0)}")
    logger.info(f"  - Details borrados: {result_details.get('details_borrados', 0)}")
    logger.info("="*70 + "\n")
