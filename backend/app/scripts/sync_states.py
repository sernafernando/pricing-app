"""
Script para sincronizar estados/provincias desde el ERP.
Usa el Cloudflare Worker / gbp-parser para obtener los datos.

Ejecutar:
    python -m app.scripts.sync_states
    python -m app.scripts.sync_states --country-id 54
    python -m app.scripts.sync_states --state-id 54020
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
from app.core.database import SessionLocal
from app.models.tb_state import TBState
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL del gbp-parser
WORKER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_states_from_erp(country_id: int = None, state_id: int = None):
    """
    Obtiene estados/provincias desde el ERP vía gbp-parser.

    Args:
        country_id: ID de país
        state_id: ID de estado específico

    Returns:
        Lista de registros
    """
    params = {
        'strScriptLabel': 'scriptState'
    }

    if country_id:
        params['countryID'] = country_id
    if state_id:
        params['stateID'] = state_id

    logger.info(f"Consultando ERP con params: {params}")

    try:
        response = requests.get(WORKER_URL, params=params, timeout=60)
        response.raise_for_status()

        data = response.json()

        if isinstance(data, list):
            return data
        else:
            logger.error(f"Respuesta inesperada del worker: {type(data)}")
            return []

    except requests.exceptions.RequestException as e:
        logger.error(f"Error al consultar el worker: {e}")
        raise


def sync_states(country_id: int = 54, state_id: int = None):
    """
    Sincroniza estados/provincias desde el ERP.

    Args:
        country_id: ID de país (default 54 = Argentina)
        state_id: ID específico de estado (opcional)
    """
    db_local = None

    try:
        logger.info("=== Iniciando sincronización de estados/provincias ===")

        db_local = SessionLocal()

        total_nuevos = 0
        total_actualizados = 0

        # Obtener registros del ERP
        registros_erp = fetch_states_from_erp(country_id=country_id, state_id=state_id)

        logger.info(f"Recibidos {len(registros_erp)} registros del ERP")

        if not registros_erp:
            logger.info("No hay registros para sincronizar")
            return (0, 0)

        # Procesar registros
        for record in registros_erp:
            country_id_val = record.get('country_id')
            state_id_val = record.get('state_id')

            if not country_id_val or not state_id_val:
                logger.warning(f"Registro sin country_id o state_id: {record}")
                continue

            # Preparar datos (columnas lowercase, .get() con camelCase del ERP)
            datos = {
                'country_id': country_id_val,
                'state_id': state_id_val,
                'state_desc': record.get('state_desc'),
                'state_afip': record.get('state_afip'),
                'state_jurisdiccion': record.get('state_jurisdiccion'),
                'state_arba_cot': record.get('state_arba_cot'),
                'state_visatodopago': record.get('state_VISATodoPago'),
                'country_visatodopago': record.get('country_VISATodopago'),
                'mlstatedescription': record.get('MLStateDescription'),
                'state_enviopackid': record.get('state_EnvioPackID'),
            }

            # Verificar si existe (PK compuesta: country_id, state_id)
            existente = db_local.query(TBState).filter(
                TBState.country_id == country_id_val,
                TBState.state_id == state_id_val
            ).first()

            if existente:
                for key, value in datos.items():
                    setattr(existente, key, value)
                total_actualizados += 1
            else:
                nuevo_registro = TBState(**datos)
                db_local.add(nuevo_registro)
                total_nuevos += 1

        # Commit final
        db_local.commit()

        logger.info("\n=== Sincronización completada ===")
        logger.info(f"  Total nuevos: {total_nuevos}")
        logger.info(f"  Total actualizados: {total_actualizados}")
        logger.info(f"  Total procesados: {total_nuevos + total_actualizados}")

        return (total_nuevos, total_actualizados)

    except Exception as e:
        logger.error(f"Error durante la sincronización: {e}")
        if db_local:
            db_local.rollback()
        raise

    finally:
        if db_local:
            db_local.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar estados/provincias desde ERP')
    parser.add_argument(
        '--country-id',
        type=int,
        default=54,
        help='ID de país (default 54 = Argentina)'
    )
    parser.add_argument(
        '--state-id',
        type=int,
        help='ID de estado específico'
    )

    args = parser.parse_args()

    sync_states(country_id=args.country_id, state_id=args.state_id)
