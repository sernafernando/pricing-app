"""
Script para actualización de envíos de órdenes de MercadoLibre por fecha de lastUpdate.
A diferencia del incremental (que trae NUEVOS registros por mlm_id),
este script busca registros MODIFICADOS y los actualiza (upsert por mlm_id).

Modos de uso:
    # Por defecto: desde MAX(mlos_lastupdate) hasta hoy
    python -m app.scripts.sync_ml_orders_shipping_updater

    # Últimos N días
    python -m app.scripts.sync_ml_orders_shipping_updater --days 7

    # Rango de fechas explícito
    python -m app.scripts.sync_ml_orders_shipping_updater --from-date 2025-01-01 --to-date 2025-01-31
"""

import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import argparse
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal

# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parsea una fecha del API externo a datetime."""
    if not date_str:
        return None
    if not isinstance(date_str, str):
        return date_str  # type: ignore[return-value]
    try:
        # Formato: 9/2/2025 12:00:00 AM
        return datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        pass
    try:
        # Formato ISO
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_decimal(value: object) -> Optional[float]:
    """Convierte a decimal, retorna None si no es válido."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def to_int(value: object) -> Optional[int]:
    """Convierte a entero, retorna None si no es válido."""
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def to_string(value: object) -> Optional[str]:
    """Convierte a string, retorna None si es None o vacío."""
    if value is None or value == "":
        return None
    return str(value).strip()


# ---------------------------------------------------------------------------
# Campos que se actualizan en un upsert
# ---------------------------------------------------------------------------

# Mapeo: clave JSON del API → nombre de columna en el modelo
FIELD_MAP: dict[str, tuple[str, callable]] = {
    "comp_id": ("comp_id", to_int),
    "mlo_id": ("mlo_id", to_int),
    "MLshippingID": ("mlshippingid", to_string),
    "MLshipment_type": ("mlshipment_type", to_string),
    "MLshipping_mode": ("mlshipping_mode", to_string),
    "mlm_JSON": ("mlm_json", to_string),
    "MLcost": ("mlcost", to_decimal),
    "MLlogistic_type": ("mllogistic_type", to_string),
    "MLstatus": ("mlstatus", to_string),
    "MLestimated_handling_limit": ("mlestimated_handling_limit", parse_date),
    "MLestimated_delivery_final": ("mlestimated_delivery_final", parse_date),
    "MLestimated_delivery_limit": ("mlestimated_delivery_limit", parse_date),
    "MLreceiver_address": ("mlreceiver_address", to_string),
    "MLstreet_name": ("mlstreet_name", to_string),
    "MLstreet_number": ("mlstreet_number", to_string),
    "MLcomment": ("mlcomment", to_string),
    "MLzip_code": ("mlzip_code", to_string),
    "MLcity_name": ("mlcity_name", to_string),
    "MLstate_name": ("mlstate_name", to_string),
    "MLcity_id": ("mlcity_id", to_string),
    "MLstate_id": ("mlstate_id", to_string),
    "MLconuntry_name": ("mlconuntry_name", to_string),
    "MLreceiver_name": ("mlreceiver_name", to_string),
    "MLreceiver_phone": ("mlreceiver_phone", to_string),
    "MLlist_cost": ("mllist_cost", to_decimal),
    "MLdelivery_type": ("mldelivery_type", to_string),
    "MLshipping_method_id": ("mlshipping_method_id", to_string),
    "MLtracking_number": ("mltracking_number", to_string),
    "MLShippmentCost4Buyer": ("mlshippmentcost4buyer", to_decimal),
    "MLShippmentCost4Seller": ("mlshippmentcost4seller", to_decimal),
    "MLShippmentGrossAmount": ("mlshippmentgrossamount", to_decimal),
    "MLfulfilled": ("mlfulfilled", to_string),
    "MLCross_Docking": ("mlcross_docking", to_string),
    "MLSelf_Service": ("mlself_service", to_string),
    "ML_logistic_type": ("ml_logistic_type", to_string),
    "ML_tracking_method": ("ml_tracking_method", to_string),
    "ML_date_first_printed": ("ml_date_first_printed", parse_date),
    "ML_base_cost": ("ml_base_cost", to_decimal),
    "ML_estimated_delivery_time_date": ("ml_estimated_delivery_time_date", parse_date),
    "ML_estimated_delivery_time_shipping": ("ml_estimated_delivery_time_shipping", to_int),
    "mlos_lastUpdate": ("mlos_lastupdate", parse_date),
    "MLShippmentColectaDayTime": ("mlshippmentcolectadaytime", parse_date),
    "MLturbo": ("mlturbo", to_string),
}


def _build_shipping_kwargs(shipping_json: dict) -> dict:
    """Construye un dict de kwargs a partir del JSON del API usando FIELD_MAP."""
    kwargs: dict = {}
    for api_key, (model_col, converter) in FIELD_MAP.items():
        kwargs[model_col] = converter(shipping_json.get(api_key))
    return kwargs


# ---------------------------------------------------------------------------
# Core sync
# ---------------------------------------------------------------------------


async def sync_ml_orders_shipping_updater(
    db: Session,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> tuple[int, int, int]:
    """
    Sincroniza envíos de órdenes de MercadoLibre buscando por mlos_lastUpdate.
    Hace upsert: actualiza si existe, inserta si no.

    Returns:
        (insertados, actualizados, errores)
    """
    print("\n📦 Actualizando envíos ML por lastUpdate...")

    try:
        # --- Resolver fechas ---
        if from_date is None:
            ultimo_update = db.query(func.max(MercadoLibreOrderShipping.mlos_lastupdate)).scalar()
            if ultimo_update is None:
                print("⚠️  No hay envíos sincronizados aún.")
                print("   Ejecutá primero sync_ml_orders_shipping_2025.py")
                return 0, 0, 0
            from_date = ultimo_update.replace(hour=0, minute=0, second=0, microsecond=0)

        if to_date is None:
            to_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)

        # Forzar horas: inicio 00:00:00, fin 23:59:59
        from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
        to_date = to_date.replace(hour=23, minute=59, second=59, microsecond=0)

        from_date_str = from_date.strftime("%m/%d/%Y %I:%M:%S %p")
        to_date_str = to_date.strftime("%m/%d/%Y %I:%M:%S %p")

        print(f"   Rango: {from_date.strftime('%Y-%m-%d %H:%M:%S')} → {to_date.strftime('%Y-%m-%d %H:%M:%S')}")

        # --- Llamar al endpoint externo ---
        url = "http://localhost:8002/api/gbp-parser"
        params = {
            "strScriptLabel": "scriptMLOrdersShipping",
            "fromDate": from_date_str,
            "toDate": to_date_str,
        }

        print("   Consultando API...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            shipping_data = response.json()

        if not isinstance(shipping_data, list):
            print("❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(shipping_data) == 1 and "Column1" in shipping_data[0]:
            print("   ⚠️  No hay datos disponibles")
            return 0, 0, 0

        if not shipping_data:
            print("✅ No hay envíos modificados en el rango.")
            return 0, 0, 0

        print(f"   Procesando {len(shipping_data)} envíos...")

        # --- Upsert ---
        insertados = 0
        actualizados = 0
        errores = 0

        for shipping_json in shipping_data:
            try:
                mlm_id = shipping_json.get("mlm_id")
                if mlm_id is None:
                    print("   ⚠️  Envío sin mlm_id, omitiendo...")
                    errores += 1
                    continue

                kwargs = _build_shipping_kwargs(shipping_json)

                # Buscar existente
                existente = (
                    db.query(MercadoLibreOrderShipping).filter(MercadoLibreOrderShipping.mlm_id == mlm_id).first()
                )

                if existente:
                    # UPDATE: actualizar todos los campos
                    for col, value in kwargs.items():
                        setattr(existente, col, value)
                    actualizados += 1
                else:
                    # INSERT: crear nuevo registro
                    shipping = MercadoLibreOrderShipping(mlm_id=mlm_id, **kwargs)
                    db.add(shipping)
                    insertados += 1

                # Commit cada 50 registros
                if (insertados + actualizados) % 50 == 0:
                    db.commit()
                    print(f"   ✓ Procesados: {insertados} insertados, {actualizados} actualizados...")

            except Exception as e:
                print(f"   ⚠️  Error procesando envío {shipping_json.get('mlm_id')}: {str(e)}")
                errores += 1
                db.rollback()
                continue

        # Commit final
        db.commit()

        print(f"\n   ✅ Insertados: {insertados} | Actualizados: {actualizados} | Errores: {errores}")

        return insertados, actualizados, errores

    except httpx.HTTPError as e:
        print(f"   ❌ Error al consultar API externa: {str(e)}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"   ❌ Error en sincronización: {str(e)}")
        import traceback

        traceback.print_exc()
        return 0, 0, 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parsea argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Actualiza envíos de órdenes ML por fecha de lastUpdate (upsert)",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Fecha inicio (YYYY-MM-DD). Default: MAX(mlos_lastupdate) en la DB",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        default=None,
        help="Fecha fin (YYYY-MM-DD). Default: hoy",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Últimos N días (sobreescribe --from-date y --to-date)",
    )
    return parser.parse_args()


def resolve_dates(args: argparse.Namespace) -> tuple[Optional[datetime], Optional[datetime]]:
    """Resuelve from_date y to_date según los argumentos CLI."""
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None

    if args.days is not None:
        to_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
        from_date = (datetime.now() - timedelta(days=args.days)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        if args.from_date:
            from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        if args.to_date:
            to_date = datetime.strptime(args.to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=0)

    return from_date, to_date


async def main() -> None:
    """Punto de entrada para ejecución standalone."""
    args = parse_args()
    from_date, to_date = resolve_dates(args)

    print("🚀 Actualización de envíos ML por lastUpdate")
    print("=" * 60)

    if from_date:
        print(f"   From: {from_date.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("   From: MAX(mlos_lastupdate) en la DB")
    if to_date:
        print(f"   To:   {to_date.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("   To:   Hoy 23:59:59")

    db = SessionLocal()

    try:
        insertados, actualizados, errores = await sync_ml_orders_shipping_updater(
            db, from_date=from_date, to_date=to_date
        )

        print("\n" + "=" * 60)
        print("📊 RESUMEN")
        print("=" * 60)
        print(f"✅ Insertados (nuevos): {insertados}")
        print(f"🔄 Actualizados: {actualizados}")
        print(f"❌ Errores: {errores}")
        print(f"📦 Total procesados: {insertados + actualizados + errores}")
        print("=" * 60)

        if insertados > 0 or actualizados > 0:
            print("🎉 Actualización completada!")
        else:
            print("✅ Sin cambios en el rango de fechas.")

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
