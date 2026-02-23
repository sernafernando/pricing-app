"""
Sincronización incremental de datos de usuarios MercadoLibre.

Usa mlu_cd (fecha de creación) como high-water mark.
Trae solo los registros nuevos desde la última fecha sincronizada.

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

import app.models  # noqa
from app.models.mercadolibre_user_data import MercadoLibreUserData

API_URL = "http://localhost:8002/api/gbp-parser"
API_TIMEOUT = 120.0


def to_string(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _is_empty_response(data: list) -> bool:
    """Detecta respuestas vacías o de error del ERP."""
    if not data:
        return True
    if len(data) == 1 and ("Column1" in data[0] or "error" in data[0]):
        return True
    return False


async def sync_ml_users_data_incremental(
    db: Session,
) -> tuple[int, int, int]:
    """
    Sincroniza datos de usuarios de MercadoLibre de forma incremental.
    Usa la última mlu_cd como high-water mark para traer solo registros nuevos.

    Returns:
        tuple: (insertados, actualizados, errores)
    """

    ultima_fecha = db.query(func.max(MercadoLibreUserData.mlu_cd)).scalar()

    if ultima_fecha is None:
        print("⚠️  No hay datos de usuarios ML en la base de datos.")
        print("   La carga inicial se realiza vía cron.")
        return 0, 0, 0

    print(f"📊 Última mlu_cd en BD: {ultima_fecha}")
    print("🔄 Buscando registros nuevos...\n")

    try:
        params = {
            "strScriptLabel": "scriptMLUsersData",
            "fromDate": ultima_fecha,
        }

        print(f"📅 Consultando API desde mlu_cd >= {ultima_fecha}...")

        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            response = await client.get(API_URL, params=params)
            response.raise_for_status()
            users_data = response.json()

        if not isinstance(users_data, list):
            print("❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        if _is_empty_response(users_data):
            print("✅ No hay registros nuevos. Base de datos actualizada.")
            return 0, 0, 0

        print(f"   Encontrados {len(users_data)} registros\n")

        insertados = 0
        errores = 0

        for record in users_data:
            try:
                mluser_id = to_int(record.get("MLUser_Id"))
                if mluser_id is None:
                    errores += 1
                    continue

                user = MercadoLibreUserData(
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

                db.merge(user)
                insertados += 1

                if insertados % 50 == 0:
                    db.commit()
                    print(f"   ✓ {insertados} registros procesados...")

            except Exception as e:
                print(f"   ⚠️  Error procesando usuario {record.get('MLUser_Id')}: {e}")
                errores += 1
                db.rollback()
                continue

        db.commit()

        nueva_fecha = db.query(func.max(MercadoLibreUserData.mlu_cd)).scalar()

        print("\n✅ Sincronización completada!")
        print(f"   Procesados: {insertados}")
        print(f"   Errores: {errores}")
        print(f"   Nueva mlu_cd máxima: {nueva_fecha}")

        return insertados, 0, errores

    except httpx.HTTPError as e:
        print(f"❌ Error al consultar API externa: {e}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"❌ Error en sincronización: {e}")
        import traceback

        traceback.print_exc()
        return 0, 0, 0


async def main() -> None:
    print("🚀 Sincronización incremental de usuarios MercadoLibre")
    print("=" * 60)

    db = SessionLocal()

    try:
        await sync_ml_users_data_incremental(db)
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ Error general: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
