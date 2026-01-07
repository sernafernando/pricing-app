#!/usr/bin/env python3
"""
Script para actualizar estados de envíos Turbo desde ML Webhook API.

Uso:
    python scripts/actualizar_estados_turbo.py [--limit N] [--batch-size N]

Opciones:
    --limit N           Limitar a N envíos (default: todos)
    --batch-size N      Tamaño de batch para requests paralelos (default: 50)
    --only-pending      Solo actualizar envíos con estado pending

Ejemplo:
    # Actualizar todos los envíos Turbo
    python scripts/actualizar_estados_turbo.py

    # Actualizar solo 100 envíos en batches de 25
    python scripts/actualizar_estados_turbo.py --limit 100 --batch-size 25

    # Solo actualizar los que están pendientes
    python scripts/actualizar_estados_turbo.py --only-pending

Configurar como cron (ejecutar diariamente a las 6 AM):
    0 6 * * * cd /var/www/html/pricing-app/backend && python scripts/actualizar_estados_turbo.py >> /var/log/turbo_estados.log 2>&1
"""
import sys
import os
import asyncio
import logging
import argparse
from datetime import datetime

# Agregar parent directory al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.services.ml_webhook_service import fetch_shipment_data

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def actualizar_estado_envio(db: Session, shipping_id: str) -> tuple[str, bool, str, str]:
    """
    Actualiza el estado de un envío desde ML Webhook.
    
    Returns:
        (shipping_id, success, estado_anterior, estado_nuevo)
    """
    try:
        # Obtener envío de BD
        envio = db.query(MercadoLibreOrderShipping).filter(
            MercadoLibreOrderShipping.mlshippingid == shipping_id
        ).first()
        
        if not envio:
            logger.warning(f"Envío {shipping_id} no encontrado en BD")
            return (shipping_id, False, None, None)
        
        estado_anterior = envio.mlstatus
        
        # Consultar ML Webhook
        ml_data = await fetch_shipment_data(shipping_id)
        
        if not ml_data:
            logger.warning(f"No se pudo obtener datos de ML para {shipping_id}")
            return (shipping_id, False, estado_anterior, None)
        
        # Extraer estado
        nuevo_estado = ml_data.get('status', '').lower()
        
        if not nuevo_estado:
            logger.warning(f"Estado vacío en respuesta de ML para {shipping_id}")
            return (shipping_id, False, estado_anterior, None)
        
        # Actualizar solo si cambió
        if estado_anterior != nuevo_estado:
            envio.mlstatus = nuevo_estado
            logger.info(f"✅ {shipping_id}: {estado_anterior} → {nuevo_estado}")
            return (shipping_id, True, estado_anterior, nuevo_estado)
        else:
            logger.debug(f"⏭️  {shipping_id}: sin cambios ({estado_anterior})")
            return (shipping_id, True, estado_anterior, estado_anterior)
            
    except Exception as e:
        logger.error(f"❌ Error actualizando {shipping_id}: {e}")
        return (shipping_id, False, None, None)


async def actualizar_estados_batch(
    db: Session,
    shipping_ids: list[str],
    batch_size: int = 50
):
    """
    Actualiza estados de múltiples envíos en batches paralelos.
    """
    total = len(shipping_ids)
    actualizados = 0
    sin_cambios = 0
    fallidos = 0
    cambios = []
    
    logger.info(f"📦 Procesando {total} envíos en batches de {batch_size}")
    
    for i in range(0, total, batch_size):
        batch = shipping_ids[i:i+batch_size]
        logger.info(f"Procesando batch {i//batch_size + 1}/{(total + batch_size - 1)//batch_size}")
        
        # Ejecutar requests en paralelo
        tasks = [actualizar_estado_envio(db, sid) for sid in batch]
        resultados = await asyncio.gather(*tasks)
        
        for shipping_id, success, estado_ant, estado_nuevo in resultados:
            if success:
                if estado_ant != estado_nuevo:
                    actualizados += 1
                    cambios.append({
                        'shipping_id': shipping_id,
                        'anterior': estado_ant,
                        'nuevo': estado_nuevo
                    })
                else:
                    sin_cambios += 1
            else:
                fallidos += 1
        
        # Commit después de cada batch
        db.commit()
        logger.info(f"✅ Batch {i//batch_size + 1} completado y commiteado")
        
        # Rate limiting: pausa entre batches
        if i + batch_size < total:
            await asyncio.sleep(0.5)
    
    return {
        'total': total,
        'actualizados': actualizados,
        'sin_cambios': sin_cambios,
        'fallidos': fallidos,
        'cambios': cambios
    }


def main():
    parser = argparse.ArgumentParser(description='Actualizar estados de envíos Turbo desde ML Webhook')
    parser.add_argument('--limit', type=int, default=None, help='Limitar a N envíos')
    parser.add_argument('--batch-size', type=int, default=50, help='Tamaño de batch (default: 50)')
    parser.add_argument('--only-pending', action='store_true', help='Solo actualizar envíos pendientes')
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("🚀 ACTUALIZACIÓN DE ESTADOS DE ENVÍOS TURBO")
    logger.info("=" * 80)
    logger.info(f"Fecha: {datetime.now()}")
    logger.info(f"Límite: {args.limit or 'todos'}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Solo pendientes: {args.only_pending}")
    logger.info("")
    
    db = SessionLocal()
    
    try:
        # Obtener todos los envíos Turbo (excluyendo TEST)
        query = db.query(MercadoLibreOrderShipping.mlshippingid).filter(
            MercadoLibreOrderShipping.mlshipping_method_id == '515282',
            ~MercadoLibreOrderShipping.mlshippingid.like('TEST_%')
        )
        
        if args.only_pending:
            query = query.filter(
                MercadoLibreOrderShipping.mlstatus.in_(['ready_to_ship', 'not_delivered'])
            )
        
        if args.limit:
            query = query.limit(args.limit)
        
        shipping_ids = [str(row[0]) for row in query.all()]
        
        if not shipping_ids:
            logger.info("⚠️  No hay envíos para actualizar")
            return
        
        logger.info(f"📋 Encontrados {len(shipping_ids)} envíos Turbo")
        logger.info("")
        
        # Ejecutar actualización
        resultado = asyncio.run(
            actualizar_estados_batch(db, shipping_ids, args.batch_size)
        )
        
        # Resumen
        logger.info("")
        logger.info("=" * 80)
        logger.info("📊 RESUMEN")
        logger.info("=" * 80)
        logger.info(f"Total procesados:      {resultado['total']}")
        logger.info(f"✅ Actualizados:       {resultado['actualizados']}")
        logger.info(f"⏭️  Sin cambios:        {resultado['sin_cambios']}")
        logger.info(f"❌ Fallidos:           {resultado['fallidos']}")
        logger.info(f"Porcentaje éxito:      {((resultado['actualizados'] + resultado['sin_cambios']) / resultado['total'] * 100):.1f}%")
        logger.info("")
        
        # Mostrar cambios
        if resultado['cambios']:
            logger.info("📝 CAMBIOS DETECTADOS:")
            logger.info("")
            for cambio in resultado['cambios'][:20]:  # Mostrar máximo 20
                logger.info(f"  {cambio['shipping_id']}: {cambio['anterior']} → {cambio['nuevo']}")
            
            if len(resultado['cambios']) > 20:
                logger.info(f"  ... y {len(resultado['cambios']) - 20} cambios más")
        else:
            logger.info("ℹ️  No se detectaron cambios de estado")
        
        logger.info("")
        logger.info("✅ SCRIPT COMPLETADO")
        logger.info("=" * 80)
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrumpido por usuario")
        db.rollback()
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()
