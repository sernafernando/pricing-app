"""
Script para sincronizar historial de tipos de cambio desde el ERP
Tabla: tbCurExchHistory

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_cur_exch_history
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Cargar .env
from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

import requests
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.cur_exch_history import CurExchHistory


def fetch_exch_history_from_erp(from_date: date = None, to_date: date = None):
    """Obtiene el historial de tipos de cambio desde el ERP vía GBP Worker"""
    url = "http://localhost:8002/api/gbp-parser"

    # Por defecto, últimos 2 años
    if not from_date:
        from_date = date.today() - timedelta(days=730)
    if not to_date:
        # Sumar 1 día para incluir registros de HOY
        to_date = date.today() + timedelta(days=1)

    params = {
        "strScriptLabel": "scriptCurExchHistory",
        "fromDate": from_date.isoformat(),
        "toDate": to_date.isoformat(),
    }

    print(f"📥 Descargando tipos de cambio desde {from_date} hasta {to_date}...")

    try:
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()
        data = response.json()

        print(f"  ✓ Obtenidos {len(data)} registros")
        return data

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error consultando ERP: {e}")
        return []


def sync_exch_history(db: Session, data: list):
    """Sincroniza los tipos de cambio en la base de datos local"""

    if not data:
        print("  ⚠️  No hay datos para sincronizar")
        return 0, 0, 0

    print(f"\n💾 Sincronizando {len(data)} registros...")

    insertados = 0
    actualizados = 0
    errores = 0

    for record in data:
        try:
            ceh_id = record.get("ceh_id")

            # Buscar registro existente
            existente = db.query(CurExchHistory).filter(CurExchHistory.ceh_id == ceh_id).first()

            # Convertir fecha
            ceh_cd = None
            if record.get("ceh_cd"):
                try:
                    ceh_cd = datetime.fromisoformat(record["ceh_cd"].replace("T", " "))
                except:
                    pass

            if existente:
                # Actualizar
                existente.comp_id = record.get("comp_id")
                existente.curr_id_1 = record.get("curr_id_1")
                existente.curr_id_2 = record.get("curr_id_2")
                existente.ceh_cd = ceh_cd
                existente.ceh_exchange = record.get("ceh_exchange")
                actualizados += 1
            else:
                # Insertar nuevo
                nuevo = CurExchHistory(
                    ceh_id=ceh_id,
                    comp_id=record.get("comp_id"),
                    curr_id_1=record.get("curr_id_1"),
                    curr_id_2=record.get("curr_id_2"),
                    ceh_cd=ceh_cd,
                    ceh_exchange=record.get("ceh_exchange"),
                )
                db.add(nuevo)
                insertados += 1

            # Commit cada 500 registros
            if (insertados + actualizados) % 500 == 0:
                db.commit()
                print(f"  📊 Progreso: {insertados + actualizados}/{len(data)}")

        except Exception as e:
            errores += 1
            print(f"  ⚠️  Error en registro {record.get('ceh_id')}: {str(e)}")
            db.rollback()  # Rollback para poder continuar con los demás
            continue

    # Commit final
    db.commit()

    return insertados, actualizados, errores


def main():
    print("=" * 60)
    print("SINCRONIZACIÓN DE CURRENCY EXCHANGE HISTORY")
    print("=" * 60)

    db = SessionLocal()

    try:
        # 1. Obtener datos del ERP (últimos 2 años por defecto)
        data = fetch_exch_history_from_erp()

        # 2. Sincronizar en PostgreSQL
        insertados, actualizados, errores = sync_exch_history(db, data)

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
