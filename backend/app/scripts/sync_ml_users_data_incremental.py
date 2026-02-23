"""
Script para sincronización incremental de datos de usuarios MercadoLibre.
Sincroniza solo los registros nuevos desde el último mluser_id.
Trabaja en chunks de CHUNK_SIZE para evitar timeouts.

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
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal

# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.mercadolibre_user_data import MercadoLibreUserData

CHUNK_SIZE = 5000
API_URL = "http://localhost:8002/api/gbp-parser"
API_TIMEOUT = 180.0


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


async def _fetch_chunk(client: httpx.AsyncClient, id_from: int, id_to: int) -> list[dict]:
    """Trae un chunk de registros del ERP vía gbp-parser."""
    params = {
        "strScriptLabel": "scriptMLUsersData",
        "idFrom": id_from,
        "idTo": id_to,
    }
    response = await client.get(API_URL, params=params)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list):
        return []

    # Respuesta vacía del ERP
    if len(data) == 1 and "Column1" in data[0]:
        return []

    return data


async def _insert_records(db: Session, records: list[dict]) -> tuple[int, int]:
    """Inserta registros en la BD. Retorna (insertados, errores)."""
    insertados = 0
    errores = 0

    for record in records:
        try:
            user = _build_user(record)
            if user is None:
                errores += 1
                continue

            db.add(user)
            insertados += 1

            if insertados % 50 == 0:
                db.commit()

        except Exception as e:
            print(f"   ⚠️  Error procesando usuario {record.get('MLUser_Id')}: {str(e)}")
            errores += 1
            db.rollback()
            continue

    db.commit()
    return insertados, errores


async def sync_ml_users_data_incremental(db: Session) -> tuple[int, int, int]:
    """
    Sincroniza datos de usuarios de MercadoLibre de forma incremental.
    Trabaja en chunks de CHUNK_SIZE usando idFrom/idTo para evitar timeouts.

    Returns:
        tuple: (insertados, actualizados, errores)
    """

    # Obtener el último mluser_id sincronizado
    ultimo_id = db.query(func.max(MercadoLibreUserData.mluser_id)).scalar()

    if ultimo_id is None:
        ultimo_id = 0
        print("⚠️  No hay datos de usuarios ML en la base de datos. Carga inicial...")

    print(f"📊 Último mluser_id en BD: {ultimo_id}")
    print(f"🔄 Buscando registros nuevos (chunks de {CHUNK_SIZE})...\n")

    total_insertados = 0
    total_errores = 0
    chunk_num = 0

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            current_from = ultimo_id
            while True:
                current_to = current_from + CHUNK_SIZE
                chunk_num += 1

                print(f"   📦 Chunk {chunk_num}: idFrom={current_from} idTo={current_to}")

                records = await _fetch_chunk(client, current_from, current_to)

                if not records:
                    print(f"   ✅ Chunk {chunk_num}: sin registros, fin de datos")
                    break

                print(f"   📥 Chunk {chunk_num}: {len(records)} registros recibidos")

                insertados, errores = await _insert_records(db, records)
                total_insertados += insertados
                total_errores += errores

                print(f"   ✓ Chunk {chunk_num}: {insertados} insertados, {errores} errores")

                # Avanzar al siguiente rango
                current_from = current_to

        # Obtener nuevo máximo
        nuevo_max = db.query(func.max(MercadoLibreUserData.mluser_id)).scalar()

        print(f"\n✅ Sincronización completada! ({chunk_num} chunks)")
        print(f"   Insertados: {total_insertados}")
        print(f"   Errores: {total_errores}")
        print(f"   Nuevo mluser_id máximo: {nuevo_max}")

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
