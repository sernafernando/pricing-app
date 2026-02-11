"""
Sync híbrido de customers: filtrar por timestamp + comparar con GUID.

Este script implementa el enfoque híbrido para tb_customer:
1. Filtrar por cust_LastUpdate >= fecha (reduce 300k → ~50 registros)
2. Comparar con cust_GBPComunityID (GUID) para detectar cambios reales

Ejecutar:
    python -m app.scripts.sync_customers_hybrid
    python -m app.scripts.sync_customers_hybrid --minutes 60
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from datetime import datetime, timedelta
import httpx
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.tb_customer import TBCustomer
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def parse_datetime(value) -> datetime | None:
    """Parsea un valor de fecha/hora desde el ERP."""
    if not value:
        return None
    try:
        if "T" in str(value):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        else:
            return datetime.strptime(str(value), "%m/%d/%Y %I:%M:%S %p")
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Error parseando datetime '{value}': {e}")
        return None


def parse_bool(value) -> bool | None:
    """Parsea un valor booleano desde el ERP."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


async def sync_customers_hybrid(db: Session, minutes: int = 30) -> dict[str, int | str]:
    """
    Sincroniza customers usando enfoque híbrido.

    Implementa el enfoque híbrido para tb_customer:
    1. Filtrar por cust_LastUpdate >= fecha_limite (reduce 300k → ~50 registros)
    2. Comparar con cust_GBPComunityID (GUID) para detectar cambios reales
    3. Solo actualizar si el GUID cambió (evita falsos positivos)

    Args:
        db: Sesión de base de datos
        minutes: Minutos hacia atrás para filtrar (default 30)

    Returns:
        dict: {"nuevos": int, "actualizados": int, "error": str (optional)}
    """
    logger.info(f"👥 Customers (últimos {minutes} min - híbrido)...")

    try:
        # 1. Calcular fecha límite con DATETIME (no solo DATE)
        fecha_limite = datetime.now() - timedelta(minutes=minutes)
        fecha_str = fecha_limite.strftime("%Y-%m-%d %H:%M:%S")

        # 2. Consultar ERP con filtro de timestamp
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(
                WORKER_URL, params={"strScriptLabel": "scriptCustomer", "lastUpdate": fecha_str}
            )
            response.raise_for_status()
            data = response.json()

        # 3. Validar respuesta
        if not isinstance(data, list) or len(data) == 0:
            logger.info("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            logger.info("✓ (sin cambios recientes)")
            return {"nuevos": 0, "actualizados": 0}

        logger.info(f"Recibidos {len(data)} registros del ERP")

        nuevos = 0
        actualizados = 0

        # 4. Procesar registros
        for record in data:
            comp_id = record.get("comp_id", 1)
            cust_id = record.get("cust_id")
            cust_guid = record.get("cust_GBPComunityID")  # ⬅️ GUID del ERP

            if not cust_id:
                logger.warning(f"Registro sin cust_id: {record}")
                continue

            # 5. Buscar existente en DB
            existente = (
                db.query(TBCustomer).filter(TBCustomer.comp_id == comp_id, TBCustomer.cust_id == cust_id).first()
            )

            # 6. Preparar datos
            datos = {
                "comp_id": comp_id,
                "cust_id": cust_id,
                "bra_id": record.get("bra_id"),
                "cust_name": record.get("cust_name"),
                "cust_name1": record.get("cust_name1"),
                "fc_id": record.get("fc_id"),
                "cust_taxnumber": record.get("cust_taxNumber"),
                "tnt_id": record.get("tnt_id"),
                "cust_address": record.get("cust_address"),
                "cust_city": record.get("cust_city"),
                "cust_zip": record.get("cust_zip"),
                "country_id": record.get("country_id"),
                "state_id": record.get("state_id"),
                "cust_phone1": record.get("cust_phone1"),
                "cust_cellphone": record.get("cust_cellPhone"),
                "cust_email": record.get("cust_email"),
                "sm_id": record.get("sm_id"),
                "sm_id_2": record.get("sm_id_2"),
                "cust_inactive": parse_bool(record.get("cust_inactive")),
                "prli_id": record.get("prli_id"),
                "cust_mercadolibrenickname": record.get("cust_MercadoLibreNickName"),
                "cust_mercadolibreid": record.get("cust_MercadoLibreID"),
                "cust_gbpcomunityid": cust_guid,  # ⬅️ Guardar GUID
                "cust_cd": parse_datetime(record.get("cust_cd")),
                "cust_lastupdate": parse_datetime(record.get("cust_LastUpdate")),
            }

            if existente:
                # 7. COMPARAR CON GUID - Solo actualizar si cambió el GUID
                if existente.cust_gbpcomunityid != cust_guid:
                    for key, value in datos.items():
                        setattr(existente, key, value)
                    actualizados += 1
                # Si el GUID es igual, no hay cambios reales (skip)
            else:
                # 8. Insertar nuevo
                nuevo_registro = TBCustomer(**datos)
                db.add(nuevo_registro)
                nuevos += 1

            # 9. Commit cada 100 registros
            if (nuevos + actualizados) % 100 == 0:
                db.commit()

        # 10. Commit final
        db.commit()
        logger.info(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except httpx.HTTPError as e:
        logger.error(f"Error HTTP consultando ERP: {e}", exc_info=True)
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "error": f"HTTP Error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error inesperado en sync_customers_hybrid: {e}", exc_info=True)
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Sync híbrido de customers")
    parser.add_argument("--minutes", type=int, default=30, help="Minutos hacia atrás para filtrar (default 30)")

    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = asyncio.run(sync_customers_hybrid(db, args.minutes))
        logger.info(f"Resultado: {result}")
    finally:
        db.close()
