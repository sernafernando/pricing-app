"""
Script para sincronización incremental de datos de usuarios MercadoLibre.

Estrategia:
- Carga inicial: pagina por MES usando fromDate/toDate (sobre mlu_cd)
  porque los MLUser_Id no son secuenciales (van de 283 a 3.2B con huecos).
- Incremental (orquestador): pagina por fecha desde la última mlu_cd conocida.

Tabla ERP: tbMercadoLibre_UsersData
Tabla PG:  tb_mercadolibre_users_data

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_users_data_incremental
"""

import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal

# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.mercadolibre_user_data import MercadoLibreUserData

API_URL = "http://localhost:8002/api/gbp-parser"
API_TIMEOUT = 300.0

# Fecha de inicio de datos en el ERP
ERP_DATA_START = date(2022, 10, 1)


def to_string(value: object) -> str | None:
    """Convierte a string, retorna None si es None o vacío."""
    if value is None or value == "":
        return None
    return str(value)


def to_int(value: object) -> int | None:
    """Convierte a entero, retorna None si no es válido."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _build_user(record: dict) -> MercadoLibreUserData | None:
    """Construye un MercadoLibreUserData a partir de un dict del ERP."""
    mluser_id = to_int(record.get("MLUser_Id"))
    if mluser_id is None:
        return None

    return MercadoLibreUserData(
        mluser_id=mluser_id,
        nickname=to_string(record.get("nickname")),
        identification_type=to_string(record.get("identificationType")),
        identification_number=to_string(record.get("identificationNumber")),
        address=to_string(record.get("address")),
        citi=to_string(record.get("citi")),
        zip_code=to_string(record.get("zip_code")),
        state=to_string(record.get("state")),
        phone=to_string(record.get("phone")),
        alternative_phone=to_string(record.get("alternative_phone")),
        secure_email=to_string(record.get("secure_email")),
        email=to_string(record.get("email")),
        receiver_name=to_string(record.get("receiver_name")),
        receiver_phone=to_string(record.get("receiver_phone")),
        mlu_cd=to_string(record.get("mlu_cd")),
        billing_state_name=to_string(record.get("billing_STATE_NAME")),
        billing_doc_number=to_string(record.get("billing_DOC_NUMBER")),
        billing_street_name=to_string(record.get("billing_STREET_NAME")),
        billing_city_name=to_string(record.get("billing_CITY_NAME")),
        billing_zip_code=to_string(record.get("billing_ZIP_CODE")),
        billing_street_number=to_string(record.get("billing_STREET_NUMBER")),
        billing_doc_type=to_string(record.get("billing_DOC_TYPE")),
        billing_first_name=to_string(record.get("billing_FIRST_NAME")),
        billing_last_name=to_string(record.get("billing_LAST_NAME")),
        billing_site_id=to_string(record.get("billing_SITE_ID")),
    )


async def _fetch_by_dates(client: httpx.AsyncClient, from_date: str, to_date: str, verbose: bool = False) -> list[dict]:
    """Trae registros del ERP filtrados por rango de fechas (mlu_cd)."""
    params = {
        "strScriptLabel": "scriptMLUsersData",
        "fromDate": from_date,
        "toDate": to_date,
    }

    if verbose:
        print(f"\n      [verbose] GET {API_URL} params={params}", flush=True)

    response = await client.get(API_URL, params=params)
    response.raise_for_status()

    raw_text = response.text
    if verbose:
        size_kb = len(raw_text) / 1024
        print(f"      [verbose] Status={response.status_code} Size={size_kb:.1f}KB", flush=True)
        print(f"      [verbose] First 200 chars: {raw_text[:200]}", flush=True)

    data = response.json()

    if not isinstance(data, list):
        if verbose:
            print(f"      [verbose] Not a list: {type(data)}", flush=True)
        return []

    # Respuesta vacía del ERP
    if len(data) == 1 and ("Column1" in data[0] or "error" in data[0]):
        if verbose:
            print(f"      [verbose] Empty/error response: {data[0]}", flush=True)
        return []

    if verbose:
        print(f"      [verbose] Parsed {len(data)} records", flush=True)
        if data:
            print(f"      [verbose] First record keys: {list(data[0].keys())}", flush=True)

    return data


async def _insert_records(db: Session, records: list[dict]) -> tuple[int, int]:
    """Inserta registros en la BD con merge (upsert por PK). Retorna (insertados, errores)."""
    insertados = 0
    errores = 0

    for record in records:
        try:
            user = _build_user(record)
            if user is None:
                print(f"\n   ⚠️  Record sin MLUser_Id: {record}", flush=True)
                errores += 1
                continue

            db.merge(user)
            insertados += 1

            if insertados % 100 == 0:
                db.commit()

        except Exception as e:
            print(f"\n   ⚠️  Error procesando usuario {record.get('MLUser_Id')}: {str(e)}", flush=True)
            errores += 1
            db.rollback()
            continue

    db.commit()
    return insertados, errores


def _next_month(d: date) -> date:
    """Avanza al primer día del mes siguiente."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _generate_monthly_ranges(start: date, end: date) -> list[tuple[str, str]]:
    """Genera rangos mensuales como pares de strings MM/DD/YYYY."""
    ranges = []
    current = date(start.year, start.month, 1)
    while current < end:
        month_end = _next_month(current) - timedelta(days=1)
        if month_end > end:
            month_end = end
        ranges.append(
            (
                current.strftime("%m/%d/%Y") + " 00:00:00",
                month_end.strftime("%m/%d/%Y") + " 23:59:59",
            )
        )
        current = _next_month(current)
    return ranges


async def sync_ml_users_data_incremental(db: Session) -> tuple[int, int, int]:
    """
    Sincroniza datos de usuarios de MercadoLibre de forma incremental.

    - Si la tabla está vacía: carga inicial por meses desde Oct 2022.
    - Si ya tiene datos: trae los últimos 7 días (cubre re-runs y nuevos).

    Returns:
        tuple: (insertados, actualizados, errores)
    """

    count = db.query(func.count(MercadoLibreUserData.mluser_id)).scalar() or 0

    if count == 0:
        # ── Carga inicial: mes por mes ──
        print("⚠️  Tabla vacía. Iniciando carga completa por meses...")
        today = date.today()
        ranges = _generate_monthly_ranges(ERP_DATA_START, today)
        print(f"📊 {len(ranges)} meses a procesar ({ERP_DATA_START} → {today})\n")

        total_insertados = 0
        total_errores = 0

        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            for i, (from_dt, to_dt) in enumerate(ranges, 1):
                print(f"   📅 [{i}/{len(ranges)}] {from_dt} → {to_dt} ...", end=" ", flush=True)

                try:
                    records = await _fetch_by_dates(client, from_dt, to_dt)
                except Exception as e:
                    print(f"ERROR: {e}")
                    total_errores += 1
                    continue

                if not records:
                    print("0 registros")
                    continue

                insertados, errores = await _insert_records(db, records)
                total_insertados += insertados
                total_errores += errores
                print(f"{insertados} insertados" + (f", {errores} errores" if errores else ""))

        nuevo_max = db.query(func.max(MercadoLibreUserData.mluser_id)).scalar()
        nuevo_count = db.query(func.count(MercadoLibreUserData.mluser_id)).scalar()

        print("\n✅ Carga inicial completada!")
        print(f"   Total registros: {nuevo_count}")
        print(f"   Insertados: {total_insertados}")
        print(f"   Errores: {total_errores}")
        print(f"   Max mluser_id: {nuevo_max}")

        return total_insertados, 0, total_errores

    else:
        # ── Incremental: solo hoy ──
        today = date.today()
        start = today

        print(f"📊 {count} registros existentes en BD")
        print(f"🔄 Sync incremental: {today}\n")

        total_insertados = 0
        total_errores = 0

        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                current = start
                while current <= today:
                    desde = current.strftime("%m/%d/%Y") + " 00:00:00"
                    hasta = current.strftime("%m/%d/%Y") + " 23:59:59"

                    print(f"   📅 {desde} ...", end=" ", flush=True)

                    try:
                        records = await _fetch_by_dates(client, desde, hasta)
                    except Exception as e:
                        print(f"ERROR: {e}")
                        total_errores += 1
                        current += timedelta(days=1)
                        continue

                    if not records:
                        print("0 registros")
                        current += timedelta(days=1)
                        continue

                    print(f"{len(records)} recibidos ...", end=" ", flush=True)
                    insertados, errores = await _insert_records(db, records)
                    total_insertados += insertados
                    total_errores += errores
                    print(f"{insertados} insertados" + (f", {errores} errores" if errores else ""))

                    current += timedelta(days=1)

            nuevo_max = db.query(func.max(MercadoLibreUserData.mluser_id)).scalar()

            print("\n✅ Sync incremental completado!")
            print(f"   Insertados/actualizados: {total_insertados}")
            print(f"   Errores: {total_errores}")
            print(f"   Max mluser_id: {nuevo_max}")

            return total_insertados, 0, total_errores

        except httpx.HTTPError as e:
            print(f"❌ Error al consultar API externa: {str(e)}")
            return total_insertados, 0, total_errores
        except Exception as e:
            db.rollback()
            print(f"❌ Error en sincronización: {str(e)}")
            import traceback

            traceback.print_exc()
            return total_insertados, 0, total_errores


async def main() -> None:
    """
    Sincronización incremental de datos de usuarios MercadoLibre.
    """
    print("🚀 Sincronización incremental de usuarios MercadoLibre")
    print("=" * 60)

    db = SessionLocal()

    try:
        await sync_ml_users_data_incremental(db)
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
