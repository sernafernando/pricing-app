"""
Script para sincronización COMPLETA diaria de items publicados de MercadoLibre
Actualiza TODAS las publicaciones (no solo las nuevas/modificadas)

Estrategia:
- Sincronización completa: 1 vez al día (este script - por lotes usando mlpIdFrom/mlpIdTo)
- Sincronización incremental: cada hora (sync_ml_items_publicados_incremental.py)

Modos de ejecución:
- FULL: Sincroniza TODOS los items sin filtros (por defecto)
- SMART: Sincroniza solo items modificados en los últimos N días (usa updateFrom/updateTo)

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend

    # Modo FULL (todos los items)
    python -m app.scripts.sync_ml_items_publicados_full

    # Modo SMART (solo modificados en últimos 30 días)
    python -m app.scripts.sync_ml_items_publicados_full --smart --days 30
"""

import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
import argparse
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal

# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

API_URL = "http://localhost:8002/api/gbp-parser"


def convertir_a_numero(valor, default=None):
    """Convierte string a número, maneja decimales y nulos"""
    try:
        if valor is None or valor == "" or valor == " ":
            return default
        if isinstance(valor, bool):
            return default
        if isinstance(valor, (int, float)):
            return valor
        valor_str = str(valor).strip().replace(",", "")
        if valor_str == "":
            return default
        return float(valor_str)
    except:
        return default


def convertir_a_entero(valor, default=None):
    """Convierte a entero, truncando decimales"""
    try:
        num = convertir_a_numero(valor, default)
        if num is None:
            return default
        return int(float(num))
    except:
        return default


def convertir_a_boolean(valor):
    """Convierte varios formatos a boolean"""
    if isinstance(valor, bool):
        return valor
    if valor is None or valor == "":
        return False
    if isinstance(valor, str):
        return valor.lower() in ("true", "1", "t", "yes", "y")
    if isinstance(valor, (int, float)):
        return valor != 0
    return bool(valor)


def convertir_fecha(valor):
    """Convierte string a datetime"""
    if not valor or valor == "" or valor == " ":
        return None
    try:
        if isinstance(valor, datetime):
            return valor
        # Formato: "5/1/2025 12:00:00 AM"
        return datetime.strptime(valor, "%m/%d/%Y %I:%M:%S %p")
    except:
        try:
            return datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except:
            return None


async def sync_items_publicados_full(db: Session, smart_mode: bool = False, days: int = 30):
    """
    Sincroniza publicaciones de ML con dos modos:
    - FULL: Sincroniza TODAS las publicaciones (sin filtrar por status)
    - SMART: Sincroniza solo items modificados en los últimos N días

    Ahora usa paginación por mlpId para evitar timeouts

    Args:
        db: Session de SQLAlchemy
        smart_mode: Si True, usa updateFrom/updateTo para filtrar por fecha de modificación
        days: Cantidad de días hacia atrás para el modo SMART (default: 30)
    """
    modo = "SMART" if smart_mode else "FULL"
    print(f"📅 Sincronizando publicaciones en modo {modo}...")
    if smart_mode:
        print(f"   🧠 Filtrando por items modificados en los últimos {days} días")

    # Obtener rango de mlp_id en la BD
    from sqlalchemy import func

    result = db.query(func.min(MercadoLibreItemPublicado.mlp_id), func.max(MercadoLibreItemPublicado.mlp_id)).first()

    min_id = result[0] if result[0] else 1
    max_id = result[1] if result[1] else 20000

    print(f"   📊 Rango de IDs en BD: {min_id} - {max_id}")

    BATCH_SIZE = 500
    total_insertados = 0
    total_actualizados = 0
    total_errores = 0

    # Procesar por lotes
    current_id = 1  # Empezar desde 1 para incluir items nuevos

    # Preparar filtros de fecha si está en modo SMART
    updateFrom = None
    updateTo = None
    if smart_mode:
        from datetime import datetime, timedelta

        hoy = datetime.now()
        desde = hoy - timedelta(days=days)
        updateFrom = desde.strftime("%Y-%m-%d %H:%M:%S")
        updateTo = hoy.strftime("%Y-%m-%d %H:%M:%S")

    async with httpx.AsyncClient(timeout=300.0) as client:
        while current_id <= max_id + BATCH_SIZE:  # +BATCH_SIZE para capturar nuevos
            batch_end = current_id + BATCH_SIZE - 1

            modo_texto = f" (modificados últimos {days}d)" if smart_mode else ""
            print(f"\n📦 Procesando lote: mlp_id {current_id} - {batch_end}{modo_texto}")

            params = {"strScriptLabel": "scriptMLItemsPublicados", "mlpIdFrom": current_id, "mlpIdTo": batch_end}

            # Agregar filtros de fecha si está en modo SMART
            if smart_mode:
                params["updateFrom"] = updateFrom
                params["updateTo"] = updateTo

            try:
                response = await client.get(API_URL, params=params)
                response.raise_for_status()
                data = response.json()

                if not data or len(data) == 0:
                    print("   ⏭️  Sin datos en este rango")
                    current_id = batch_end + 1
                    continue

                print(f"   📦 Recibidos {len(data)} items de GBP")

                insertados = 0
                actualizados = 0
                errores = 0

                for i, item_data in enumerate(data, 1):
                    try:
                        mlp_id = convertir_a_entero(item_data.get("mlp_id"))
                        if not mlp_id:
                            continue

                        # Buscar si existe
                        item_existente = (
                            db.query(MercadoLibreItemPublicado)
                            .filter(MercadoLibreItemPublicado.mlp_id == mlp_id)
                            .first()
                        )

                        # Preparar datos
                        item_dict = {
                            "mlp_id": mlp_id,
                            "comp_id": convertir_a_entero(item_data.get("comp_id")),
                            "bra_id": convertir_a_entero(item_data.get("bra_id")),
                            "stor_id": convertir_a_entero(item_data.get("stor_id")),
                            "prli_id": convertir_a_entero(item_data.get("prli_id")),
                            "item_id": convertir_a_entero(item_data.get("item_id")),
                            "user_id": convertir_a_entero(item_data.get("user_id")),
                            "mlp_publicationID": item_data.get("mlp_publicationID"),
                            "mlp_itemTitle": item_data.get("mlp_itemTitle"),
                            "mlp_itemSubTitle": item_data.get("mlp_itemSubTitle"),
                            "mlp_price": convertir_a_numero(item_data.get("mlp_price")),
                            "curr_id": convertir_a_entero(item_data.get("curr_id")),
                            "mlp_sold_quantity": convertir_a_entero(item_data.get("mlp_sold_quantity")),
                            "mlp_Active": convertir_a_boolean(item_data.get("mlp_Active")),
                            "mlp_listing_type_id": item_data.get("mlp_listing_type_id"),
                            "mlp_permalink": item_data.get("mlp_permalink"),
                            "mlp_thumbnail": item_data.get("mlp_thumbnail"),
                            "mlp_lastUpdate": convertir_fecha(item_data.get("mlp_lastUpdate")),
                            "mlp_free_shipping": convertir_a_boolean(item_data.get("mlp_free_shipping")),
                            "mlp_catalog_product_id": item_data.get("mlp_catalog_product_id"),
                            "mlp_official_store_id": convertir_a_entero(item_data.get("mlp_official_store_id")),
                            "health": convertir_a_numero(item_data.get("health")),
                            "optval_statusId": convertir_a_entero(item_data.get("optval_statusId")),
                        }

                        if not item_existente:
                            # Insertar nuevo
                            nuevo_item = MercadoLibreItemPublicado(**item_dict)
                            db.add(nuevo_item)
                            insertados += 1
                        else:
                            # Actualizar existente
                            for key, value in item_dict.items():
                                if key != "mlp_id":
                                    setattr(item_existente, key, value)
                            actualizados += 1

                        # Commit cada 100 items
                        if i % 100 == 0:
                            try:
                                db.commit()
                            except Exception as e:
                                db.rollback()
                                print(f"   ❌ Error en commit: {str(e)}")
                                errores += 1

                    except Exception as e:
                        print(f"   ❌ Error procesando item: {str(e)}")
                        errores += 1
                        continue

                # Commit final del lote
                try:
                    db.commit()
                    print(
                        f"   ✅ Lote procesado: +{insertados} nuevos, ~{actualizados} actualizados, ✗{errores} errores"
                    )
                except Exception as e:
                    db.rollback()
                    print(f"   ❌ Error en commit final del lote: {str(e)}")

                total_insertados += insertados
                total_actualizados += actualizados
                total_errores += errores

            except httpx.HTTPStatusError as e:
                print(f"   ❌ Error HTTP en lote: {e}")
                total_errores += 1
            except Exception as e:
                print(f"   ❌ Error en lote: {str(e)}")
                total_errores += 1

            # Siguiente lote
            current_id = batch_end + 1

    print(f"\n{'=' * 60}")
    print("✅ Sincronización FULL completada!")
    print(f"   Insertados: {total_insertados}")
    print(f"   Actualizados: {total_actualizados}")
    print(f"   Errores: {total_errores}")
    print(f"{'=' * 60}")

    return total_insertados, total_actualizados, total_errores


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincronización de Items Publicados ML - Modo FULL o SMART")
    parser.add_argument(
        "--smart", action="store_true", help="Modo SMART: sincroniza solo items modificados recientemente (más rápido)"
    )
    parser.add_argument("--days", type=int, default=30, help="Días hacia atrás para modo SMART (default: 30)")

    args = parser.parse_args()

    modo = "SMART" if args.smart else "FULL"

    print("=" * 60)
    print(f"📦 Sincronización de Items Publicados ML - Modo {modo}")
    if args.smart:
        print(f"🧠 Filtro: Items modificados en últimos {args.days} días")
    print(f"🕐 Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    db = SessionLocal()
    try:
        result = asyncio.run(sync_items_publicados_full(db, smart_mode=args.smart, days=args.days))
    finally:
        db.close()

    print("=" * 60)
    print(f"🕐 Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
