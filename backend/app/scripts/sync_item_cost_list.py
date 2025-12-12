"""
Script para sincronizar lista de costos de items desde el ERP
Tabla: tbItemCostList

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_item_cost_list
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Cargar .env
from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

import requests
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.item_cost_list import ItemCostList


def fetch_item_cost_list_from_erp():
    """Obtiene la lista de costos desde el ERP vía GBP Worker"""
    url = "http://localhost:8002/api/gbp-parser"
    params = {
        'strScriptLabel': 'scriptItemCostList'
    }

    print("📥 Descargando lista de costos desde ERP...")

    try:
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()
        data = response.json()

        print(f"  ✓ Obtenidos {len(data)} registros")
        return data

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error consultando ERP: {e}")
        return []


def sync_item_cost_list(db: Session, data: list):
    """Sincroniza los costos en la base de datos local"""

    if not data:
        print("  ⚠️  No hay datos para sincronizar")
        return 0, 0, 0

    print(f"\n💾 Sincronizando {len(data)} registros...")

    insertados = 0
    actualizados = 0
    errores = 0

    for record in data:
        try:
            # Buscar registro existente
            existente = db.query(ItemCostList).filter(
                and_(
                    ItemCostList.comp_id == record.get('comp_id'),
                    ItemCostList.coslis_id == record.get('coslis_id'),
                    ItemCostList.item_id == record.get('item_id')
                )
            ).first()

            # Convertir fecha si existe
            coslis_cd = None
            if record.get('coslis_cd'):
                try:
                    coslis_cd = datetime.fromisoformat(record['coslis_cd'].replace('T', ' '))
                except:
                    pass

            if existente:
                # Actualizar
                existente.coslis_price = record.get('coslis_price')
                existente.curr_id = record.get('curr_id')
                existente.coslis_cd = coslis_cd
                actualizados += 1
            else:
                # Insertar nuevo
                nuevo = ItemCostList(
                    comp_id=record.get('comp_id'),
                    coslis_id=record.get('coslis_id'),
                    item_id=record.get('item_id'),
                    coslis_price=record.get('coslis_price'),
                    curr_id=record.get('curr_id'),
                    coslis_cd=coslis_cd
                )
                db.add(nuevo)
                insertados += 1

            # Commit cada 500 registros
            if (insertados + actualizados) % 500 == 0:
                db.commit()
                print(f"  📊 Progreso: {insertados + actualizados}/{len(data)}")

        except Exception as e:
            errores += 1
            print(f"  ⚠️  Error en registro: {str(e)}")
            db.rollback()  # Rollback para poder continuar con los demás
            continue

    # Commit final
    db.commit()

    return insertados, actualizados, errores


async def sync_item_cost_list_incremental(db: Session):
    """
    Versión async para usar en sync_all_incremental.
    Sincroniza la lista de costos actuales desde el ERP.

    Args:
        db: Sesión de base de datos

    Returns:
        tuple: (insertados, actualizados, errores)
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info("=== Iniciando sincronización de Item Cost List ===")

    try:
        # Obtener datos del ERP
        data = fetch_item_cost_list_from_erp()

        if not data:
            logger.info("No hay datos para sincronizar")
            return (0, 0, 0)

        logger.info(f"Sincronizando {len(data)} registros...")

        insertados = 0
        actualizados = 0
        errores = 0

        for record in data:
            try:
                # Buscar registro existente
                existente = db.query(ItemCostList).filter(
                    and_(
                        ItemCostList.comp_id == record.get('comp_id'),
                        ItemCostList.coslis_id == record.get('coslis_id'),
                        ItemCostList.item_id == record.get('item_id')
                    )
                ).first()

                # Convertir fecha si existe
                coslis_cd = None
                if record.get('coslis_cd'):
                    try:
                        coslis_cd = datetime.fromisoformat(record['coslis_cd'].replace('T', ' ').replace('Z', ''))
                    except:
                        pass

                if existente:
                    # Actualizar solo si cambió el precio o la fecha
                    if (existente.coslis_price != record.get('coslis_price') or
                        existente.curr_id != record.get('curr_id') or
                        existente.coslis_cd != coslis_cd):
                        existente.coslis_price = record.get('coslis_price')
                        existente.curr_id = record.get('curr_id')
                        existente.coslis_cd = coslis_cd
                        actualizados += 1
                else:
                    # Insertar nuevo
                    nuevo = ItemCostList(
                        comp_id=record.get('comp_id'),
                        coslis_id=record.get('coslis_id'),
                        item_id=record.get('item_id'),
                        coslis_price=record.get('coslis_price'),
                        curr_id=record.get('curr_id'),
                        coslis_cd=coslis_cd
                    )
                    db.add(nuevo)
                    insertados += 1

                # Commit cada 500 registros
                if (insertados + actualizados) % 500 == 0:
                    db.commit()

            except Exception as e:
                errores += 1
                if errores <= 5:
                    logger.warning(f"Error en registro: {str(e)}")
                continue

        # Commit final
        db.commit()

        logger.info(f"✅ Sincronización completada: {insertados} nuevos, {actualizados} actualizados, {errores} errores")
        return (insertados, actualizados, errores)

    except Exception as e:
        logger.error(f"Error durante la sincronización: {e}")
        db.rollback()
        raise


def main():
    print("=" * 60)
    print("SINCRONIZACIÓN DE ITEM COST LIST")
    print("=" * 60)

    db = SessionLocal()

    try:
        # 1. Obtener datos del ERP
        data = fetch_item_cost_list_from_erp()

        # 2. Sincronizar en PostgreSQL
        insertados, actualizados, errores = sync_item_cost_list(db, data)

        print("\n" + "=" * 60)
        print("✅ COMPLETADO")
        print("=" * 60)
        print(f"Insertados: {insertados}")
        print(f"Actualizados: {actualizados}")
        print(f"Errores: {errores}")
        print()

    except Exception as e:
        print(f"\n❌ Error crítico: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
