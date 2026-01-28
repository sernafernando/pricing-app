"""
Script para archivar pedidos que ya pasaron a tb_sale_order_header_history.

Cuando un pedido pasa a history en el ERP, significa que ya fue completado/facturado/despachado,
pero la fila en tb_sale_order_header sigue existiendo con el estado viejo (ej: ssos_id=20).

Este script:
1. Busca pedidos que existen en tb_sale_order_header_history
2. Actualiza su ssos_id en tb_sale_order_header a un estado "archivado"

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


def sync_archived_orders():
    """
    Marca como archivados los pedidos que están en tb_sale_order_header_history.
    """
    db = SessionLocal()
    
    try:
        logger.info("🔄 Buscando pedidos archivados en history...")
        
        # 1. Contar cuántos pedidos tienen diferente estado en header vs último history
        result = db.execute(text("""
            WITH ultimo_history AS (
                SELECT DISTINCT ON (h.soh_id, h.bra_id, h.comp_id)
                    h.soh_id,
                    h.bra_id,
                    h.comp_id,
                    h.ssos_id as ultimo_ssos_id
                FROM tb_sale_order_header_history h
                ORDER BY h.soh_id, h.bra_id, h.comp_id, h.sohh_cd DESC
            )
            SELECT COUNT(*)
            FROM tb_sale_order_header soh
            INNER JOIN ultimo_history uh 
                ON soh.soh_id = uh.soh_id 
                AND soh.bra_id = uh.bra_id
                AND soh.comp_id = uh.comp_id
            WHERE soh.ssos_id != uh.ultimo_ssos_id
        """))
        
        total_a_actualizar = result.scalar()
        logger.info(f"📊 Pedidos desincronizados: {total_a_actualizar}")
        
        if total_a_actualizar == 0:
            logger.info("✅ Todos los pedidos están sincronizados con history")
            return {"actualizados": 0}
        
        # 2. Mostrar algunos ejemplos
        result = db.execute(text("""
            WITH ultimo_history AS (
                SELECT DISTINCT ON (h.soh_id, h.bra_id, h.comp_id)
                    h.soh_id,
                    h.bra_id,
                    h.comp_id,
                    h.ssos_id as ultimo_ssos_id,
                    h.sohh_cd as fecha_historia
                FROM tb_sale_order_header_history h
                ORDER BY h.soh_id, h.bra_id, h.comp_id, h.sohh_cd DESC
            )
            SELECT 
                soh.soh_id,
                soh.soh_cd as fecha_creacion,
                soh.ssos_id as estado_header,
                uh.ultimo_ssos_id as estado_history,
                uh.fecha_historia
            FROM tb_sale_order_header soh
            INNER JOIN ultimo_history uh 
                ON soh.soh_id = uh.soh_id 
                AND soh.bra_id = uh.bra_id
                AND soh.comp_id = uh.comp_id
            WHERE soh.ssos_id != uh.ultimo_ssos_id
            ORDER BY soh.soh_cd ASC
            LIMIT 10
        """))
        
        logger.info("\n📋 Ejemplos de pedidos desincronizados:")
        logger.info(f"{'SOH_ID':<10} {'FECHA':<12} {'HEADER':<8} {'HISTORY':<8} {'ÚLTIMA HISTORIA':<20}")
        logger.info("-" * 70)
        for row in result:
            logger.info(f"{row[0]:<10} {str(row[1])[:10]:<12} {row[2]:<8} {row[3]:<8} {str(row[4]):<20}")
        
        # 3. Actualizar: usar el ÚLTIMO estado del history (más reciente)
        logger.info("\n🔧 Sincronizando estados desde último registro de history...")
        
        result = db.execute(text("""
            WITH ultimo_history AS (
                SELECT DISTINCT ON (h.soh_id, h.bra_id, h.comp_id)
                    h.soh_id,
                    h.bra_id,
                    h.comp_id,
                    h.ssos_id as ultimo_ssos_id,
                    h.sohh_cd as fecha_historia
                FROM tb_sale_order_header_history h
                ORDER BY h.soh_id, h.bra_id, h.comp_id, h.sohh_cd DESC
            )
            UPDATE tb_sale_order_header soh
            SET ssos_id = uh.ultimo_ssos_id
            FROM ultimo_history uh
            WHERE soh.soh_id = uh.soh_id 
              AND soh.bra_id = uh.bra_id
              AND soh.comp_id = uh.comp_id
              AND soh.ssos_id != uh.ultimo_ssos_id
        """))
        
        actualizados = result.rowcount
        db.commit()
        
        logger.info(f"✅ Actualizados: {actualizados} pedidos con último estado de history")
        
        return {"actualizados": actualizados}
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        db.rollback()
        return {"archivados": 0, "error": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("\n" + "="*70)
    logger.info("SINCRONIZAR PEDIDOS ARCHIVADOS")
    logger.info("="*70 + "\n")
    
    result = sync_archived_orders()
    
    logger.info("\n" + "="*70)
    logger.info(f"RESULTADO: {result}")
    logger.info("="*70 + "\n")
