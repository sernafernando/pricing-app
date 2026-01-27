"""
Sync de commercial transactions usando GUID Approach.

Este script implementa el enfoque GUID para tb_commercial_transactions:
1. Traer transacciones del período (ej: último mes)
2. Comparar con ct_guid para detectar cambios
3. Si GUID existe → UPDATE
4. Si GUID no existe → INSERT
5. Detecta AMBOS: inserts Y updates

Ejecutar:
    python -m app.scripts.sync_commercial_transactions_guid
    python -m app.scripts.sync_commercial_transactions_guid --days 30
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from datetime import datetime, timedelta
from typing import Any
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.commercial_transaction import CommercialTransaction
import logging
from uuid import UUID

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def parse_datetime(value: Any) -> datetime | None:
    """Parsea un valor de fecha/hora desde el ERP."""
    if not value:
        return None
    try:
        if 'T' in str(value):
            return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        else:
            return datetime.strptime(str(value), '%m/%d/%Y %I:%M:%S %p')
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Error parseando datetime '{value}': {e}")
        return None


def parse_bool(value: Any) -> bool | None:
    """Parsea un valor booleano desde el ERP."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes')
    return bool(value)


def parse_decimal(value: Any) -> float | None:
    """Parsea un valor decimal desde el ERP."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_int(value: Any) -> int | None:
    """Parsea un valor entero desde el ERP."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_uuid(value: Any) -> UUID | None:
    """Parsea un UUID desde el ERP."""
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Error parseando UUID '{value}': {e}")
        return None


async def sync_commercial_transactions_guid(
    db: Session, 
    days: int = 30,
    fecha_desde: datetime = None,
    fecha_hasta: datetime = None
) -> dict[str, int | str]:
    """
    Sincroniza commercial transactions usando enfoque GUID.
    
    Implementa el GUID approach para tb_commercial_transactions:
    1. Traer transacciones de los últimos X días
    2. Comparar con ct_guid en DB
    3. Si GUID existe y es diferente → UPDATE
    4. Si GUID no existe → INSERT
    
    Args:
        db: Sesión de base de datos
        days: Días hacia atrás para traer (default 30)
    
    Returns:
        dict: {"nuevos": int, "actualizados": int, "error": str (optional)}
    """
    try:
        # 1. Calcular rango de fechas
        if fecha_desde and fecha_hasta:
            # Usar rango específico
            pass
        else:
            # Usar days
            fecha_hasta = datetime.now()
            fecha_desde = fecha_hasta - timedelta(days=days)
        
        fecha_desde_str = fecha_desde.strftime("%Y-%m-%d %H:%M:%S")
        fecha_hasta_str = fecha_hasta.strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"🏢 Commercial Transactions: {fecha_desde_str} hasta {fecha_hasta_str}")
        
        # 2. Consultar ERP
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 min timeout
            response = await client.get(WORKER_URL, params={
                "strScriptLabel": "scriptCommercial",
                "fromDate": fecha_desde_str,
                "toDate": fecha_hasta_str
            })
            response.raise_for_status()
            data = response.json()
        
        # 3. Validar respuesta
        if not isinstance(data, list) or len(data) == 0:
            logger.info("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}
        
        if len(data) == 1 and "Column1" in data[0]:
            logger.info("✓ (sin transacciones en el período)")
            return {"nuevos": 0, "actualizados": 0}
        
        logger.info(f"Recibidas {len(data)} transacciones del ERP")
        
        # 4. Bulk fetch - Traer todos los GUIDs existentes de una vez (evita N+1)
        incoming_guids = []
        for record in data:
            guid = parse_uuid(record.get('ct_guid'))
            if guid:
                incoming_guids.append(guid)
        
        logger.info(f"Consultando {len(incoming_guids)} GUIDs en DB...")
        existing_records = db.query(CommercialTransaction).filter(
            CommercialTransaction.ct_guid.in_(incoming_guids)
        ).all()
        
        # Crear mapa GUID → registro para lookup O(1)
        existing_map = {str(record.ct_guid): record for record in existing_records}
        logger.info(f"Encontrados {len(existing_map)} registros existentes en DB")
        
        nuevos = 0
        actualizados = 0
        errores = 0
        
        # 5. Procesar transacciones
        for record in data:
            try:
                ct_transaction = parse_int(record.get('ct_transaction'))
                ct_guid = parse_uuid(record.get('ct_guid'))
                
                if not ct_transaction:
                    logger.warning(f"Registro sin ct_transaction: {record}")
                    errores += 1
                    continue
                
                if not ct_guid:
                    logger.warning(f"Registro sin ct_guid (ct_transaction={ct_transaction})")
                    errores += 1
                    continue
                
                # 5. Buscar en el mapa (O(1) lookup, no query a DB)
                existente = existing_map.get(str(ct_guid))
                
                # 6. Preparar datos
                datos = {
                    'comp_id': parse_int(record.get('comp_id')),
                    'bra_id': parse_int(record.get('bra_id')),
                    'ct_transaction': ct_transaction,
                    'ct_pointOfSale': parse_int(record.get('ct_pointOfSale')),
                    'ct_kindOf': record.get('ct_kindOf'),
                    'ct_docNumber': record.get('ct_docNumber'),
                    
                    # Fechas
                    'ct_date': parse_datetime(record.get('ct_date')),
                    'ct_taxDate': parse_datetime(record.get('ct_taxDate')),
                    'ct_payDate': parse_datetime(record.get('ct_payDate')),
                    'ct_deliveryDate': parse_datetime(record.get('ct_deliveryDate')),
                    'ct_processingDate': parse_datetime(record.get('ct_processingDate')),
                    'ct_lastPayDate': parse_datetime(record.get('ct_lastPayDate')),
                    'ct_cd': parse_datetime(record.get('ct_cd')),
                    
                    # Relaciones
                    'supp_id': parse_int(record.get('supp_id')),
                    'cust_id': parse_int(record.get('cust_id')),
                    'cust_id_related': parse_int(record.get('cust_id_related')),
                    'cust_id_guarantor': parse_int(record.get('cust_id_guarantor')),
                    'custf_id': parse_int(record.get('custf_id')),
                    'ba_id': parse_int(record.get('ba_id')),
                    'cb_id': parse_int(record.get('cb_id')),
                    'user_id': parse_int(record.get('user_id')),
                    
                    # Montos
                    'ct_subtotal': parse_decimal(record.get('ct_subtotal')),
                    'ct_total': parse_decimal(record.get('ct_total')),
                    'ct_discount': parse_decimal(record.get('ct_discount')),
                    'ct_adjust': parse_decimal(record.get('ct_adjust')),
                    'ct_taxes': parse_decimal(record.get('ct_taxes')),
                    'ct_ATotal': parse_decimal(record.get('ct_ATotal')),
                    'ct_ABalance': parse_decimal(record.get('ct_ABalance')),
                    'ct_AAdjust': parse_decimal(record.get('ct_AAdjust')),
                    'ct_inCash': parse_decimal(record.get('ct_inCash')),
                    'ct_optionalValue': parse_decimal(record.get('ct_optionalValue')),
                    'ct_documentTotal': parse_decimal(record.get('ct_documentTotal')),
                    
                    # Monedas
                    'curr_id_transaction': parse_int(record.get('curr_id_transaction')),
                    'ct_ACurrency': parse_int(record.get('ct_ACurrency')),
                    'ct_ACurrencyExchange': parse_decimal(record.get('ct_ACurrencyExchange')),
                    'ct_CompanyCurrency': parse_int(record.get('ct_CompanyCurrency')),
                    'ct_Branch2CompanyCurrencyExchange': parse_decimal(record.get('ct_Branch2CompanyCurrencyExchange')),
                    
                    # Estados
                    'ct_Pending': parse_bool(record.get('ct_Pending')),
                    'ct_isCancelled': parse_bool(record.get('ct_isCancelled')),
                    'ct_isSelected': parse_bool(record.get('ct_isSelected')),
                    'ct_isMigrated': parse_bool(record.get('ct_isMigrated')),
                    
                    # GUID
                    'ct_guid': ct_guid,
                    
                    # Otros campos importantes
                    'ct_note': record.get('ct_note'),
                    'hacc_transaction': parse_int(record.get('hacc_transaction')),
                    'sm_id': parse_int(record.get('sm_id')),
                    'country_id': parse_int(record.get('country_id')),
                    'state_id': parse_int(record.get('state_id')),
                }
                
                if existente:
                    # 7. UPDATE - Actualizar todos los campos
                    for key, value in datos.items():
                        if key != 'ct_transaction':  # No cambiar PK
                            setattr(existente, key, value)
                    actualizados += 1
                else:
                    # 8. INSERT - Crear nuevo
                    nuevo = CommercialTransaction(**datos)
                    db.add(nuevo)
                    nuevos += 1
                
                # 9. Commit cada 500 registros
                if (nuevos + actualizados) % 500 == 0:
                    db.commit()
                    logger.info(f"  Procesados: {nuevos + actualizados} ({nuevos} nuevos, {actualizados} actualizados)")
            
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Error procesando registro (ct_transaction={record.get('ct_transaction')}): {e}", exc_info=True)
                errores += 1
                continue
        
        # 10. Commit final
        db.commit()
        logger.info(f"✓ ({nuevos} nuevos, {actualizados} actualizados, {errores} errores)")
        return {"nuevos": nuevos, "actualizados": actualizados, "errores": errores}
    
    except httpx.HTTPError as e:
        logger.error(f"Error HTTP consultando ERP: {e}", exc_info=True)
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "errores": 0, "error": f"HTTP Error: {str(e)}"}
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f"Error procesando respuesta del ERP: {e}", exc_info=True)
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "errores": 0, "error": f"Parse Error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error inesperado en sync_commercial_transactions_guid: {e}", exc_info=True)
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "errores": 0, "error": str(e)}


if __name__ == "__main__":
    import argparse
    import asyncio
    from datetime import datetime
    
    parser = argparse.ArgumentParser(description='Sync GUID de commercial transactions')
    parser.add_argument(
        '--days',
        type=int,
        default=None,
        help='Días hacia atrás para traer (default 30)'
    )
    parser.add_argument(
        '--from-date',
        type=str,
        default=None,
        help='Fecha desde (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--to-date',
        type=str,
        default=None,
        help='Fecha hasta (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--chunk-days',
        type=int,
        default=None,
        help='Dividir en chunks de N días para no saturar memoria'
    )
    
    args = parser.parse_args()
    
    # Validar parámetros
    if args.from_date and args.to_date:
        # Modo rango específico
        fecha_desde = datetime.strptime(args.from_date, '%Y-%m-%d')
        fecha_hasta = datetime.strptime(args.to_date, '%Y-%m-%d')
        days = (fecha_hasta - fecha_desde).days
        
        if args.chunk_days and days > args.chunk_days:
            # Dividir en chunks
            logger.info(f"Dividiendo {days} días en chunks de {args.chunk_days} días")
            
            db = SessionLocal()
            try:
                total_nuevos = 0
                total_actualizados = 0
                total_errores = 0
                
                current_date = fecha_desde
                chunk_num = 1
                while current_date < fecha_hasta:
                    chunk_end = min(current_date + timedelta(days=args.chunk_days), fecha_hasta)
                    
                    logger.info(f"\n{'='*60}")
                    logger.info(f"CHUNK {chunk_num}: {current_date.date()} a {chunk_end.date()}")
                    logger.info(f"{'='*60}")
                    
                    chunk_days_count = (chunk_end - current_date).days
                    result = asyncio.run(sync_commercial_transactions_guid(
                        db, 
                        chunk_days_count,
                        fecha_desde=current_date,
                        fecha_hasta=chunk_end
                    ))
                    
                    total_nuevos += result.get('nuevos', 0)
                    total_actualizados += result.get('actualizados', 0)
                    total_errores += result.get('errores', 0)
                    
                    current_date = chunk_end
                    chunk_num += 1
                
                logger.info(f"\n{'='*60}")
                logger.info(f"TOTAL: {total_nuevos} nuevos, {total_actualizados} actualizados, {total_errores} errores")
                logger.info(f"{'='*60}")
            finally:
                db.close()
        else:
            # Sin chunks
            db = SessionLocal()
            try:
                result = asyncio.run(sync_commercial_transactions_guid(
                    db, 
                    days,
                    fecha_desde=fecha_desde,
                    fecha_hasta=fecha_hasta
                ))
                logger.info(f"Resultado final: {result}")
            finally:
                db.close()
    elif args.days:
        # Modo --days (legacy)
        db = SessionLocal()
        try:
            result = asyncio.run(sync_commercial_transactions_guid(db, args.days))
            logger.info(f"Resultado final: {result}")
        finally:
            db.close()
    else:
        # Default: 30 días
        logger.info("Usando default: últimos 30 días")
        db = SessionLocal()
        try:
            result = asyncio.run(sync_commercial_transactions_guid(db, 30))
            logger.info(f"Resultado final: {result}")
        finally:
            db.close()
