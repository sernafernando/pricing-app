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
        
        # 1. Contar cuántos pedidos están en history pero siguen activos (ssos_id=20)
        result = db.execute(text("""
            SELECT COUNT(DISTINCT h.soh_id)
            FROM tb_sale_order_header_history h
            INNER JOIN tb_sale_order_header soh 
                ON h.soh_id = soh.soh_id 
                AND h.bra_id = soh.bra_id
                AND h.comp_id = soh.comp_id
            WHERE soh.ssos_id = 20
        """))
        
        total_a_archivar = result.scalar()
        logger.info(f"📊 Pedidos a archivar: {total_a_archivar}")
        
        if total_a_archivar == 0:
            logger.info("✅ No hay pedidos para archivar")
            return {"archivados": 0}
        
        # 2. Mostrar algunos ejemplos
        result = db.execute(text("""
            SELECT 
                soh.soh_id,
                soh.soh_cd as fecha_creacion,
                soh.ssos_id as estado_actual,
                MAX(h.sohh_cd) as ultima_historia
            FROM tb_sale_order_header_history h
            INNER JOIN tb_sale_order_header soh 
                ON h.soh_id = soh.soh_id 
                AND h.bra_id = soh.bra_id
                AND h.comp_id = soh.comp_id
            WHERE soh.ssos_id = 20
            GROUP BY soh.soh_id, soh.soh_cd, soh.ssos_id
            ORDER BY soh.soh_cd ASC
            LIMIT 10
        """))
        
        logger.info("\n📋 Ejemplos de pedidos a archivar:")
        logger.info(f"{'SOH_ID':<10} {'FECHA CREACIÓN':<20} {'ESTADO':<10} {'ÚLTIMA HISTORIA':<20}")
        logger.info("-" * 70)
        for row in result:
            logger.info(f"{row[0]:<10} {str(row[1]):<20} {row[2]:<10} {str(row[3]):<20}")
        
        # 3. Actualizar: marcar como ssos_id=50 (Ok Para Emisión / Completado)
        logger.info("\n🔧 Actualizando estados...")
        
        result = db.execute(text("""
            UPDATE tb_sale_order_header soh
            SET ssos_id = 50
            FROM tb_sale_order_header_history h
            WHERE soh.soh_id = h.soh_id 
              AND soh.bra_id = h.bra_id
              AND soh.comp_id = h.comp_id
              AND soh.ssos_id = 20
        """))
        
        archivados = result.rowcount
        db.commit()
        
        logger.info(f"✅ Archivados: {archivados} pedidos (ssos_id: 20 → 50)")
        
        return {"archivados": archivados}
        
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
