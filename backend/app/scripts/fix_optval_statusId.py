"""
Script one-time para actualizar optval_statusId de registros existentes
que tienen None y traerlos del ERP

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.fix_optval_statusId
"""

import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
import app.models  # noqa
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

API_URL = "http://localhost:8002/api/gbp-parser"


def convertir_a_entero(valor, default=None):
    """Convierte a entero, truncando decimales"""
    try:
        if valor is None or valor == "" or valor == " ":
            return default
        if isinstance(valor, bool):
            return default
        if isinstance(valor, (int, float)):
            return int(float(valor))
        valor_str = str(valor).strip().replace(",", "")
        if valor_str == "":
            return default
        return int(float(valor_str))
    except:
        return default


async def fix_optval_statusId(db: Session):
    """
    Actualiza registros con optval_statusId = None trayendo los datos del ERP
    """

    # Contar cuántos registros tienen optval_statusId = None
    registros_null = (
        db.query(MercadoLibreItemPublicado).filter(MercadoLibreItemPublicado.optval_statusId.is_(None)).count()
    )

    print(f"📊 Registros con optval_statusId = None: {registros_null}")

    if registros_null == 0:
        print("✅ No hay registros para actualizar")
        return 0

    print("🔄 Actualizando registros...\n")

    actualizados = 0
    errores = 0

    try:
        # Traer todos los items de los últimos 90 días del ERP
        hoy = datetime.now()
        desde = (hoy - timedelta(days=90)).strftime("%Y-%m-%d")
        hasta = hoy.strftime("%Y-%m-%d")

        params = {"strScriptLabel": "scriptMLItemsPublicados", "fromDate": desde, "toDate": hasta}

        print("📡 Consultando API del ERP (últimos 90 días)...")

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(API_URL, params=params)
            response.raise_for_status()
            items_erp = response.json()

        print(f"   Recibidos {len(items_erp)} items del ERP")

        # Crear diccionario mlp_id -> optval_statusId
        status_map = {}
        for item in items_erp:
            mlp_id = convertir_a_entero(item.get("mlp_id"))
            optval_statusId = convertir_a_entero(item.get("optval_statusId"))
            if mlp_id and optval_statusId:
                status_map[mlp_id] = optval_statusId

        print(f"   Mapeados {len(status_map)} items con status\n")

        # Actualizar registros en BD
        registros_a_actualizar = (
            db.query(MercadoLibreItemPublicado).filter(MercadoLibreItemPublicado.optval_statusId.is_(None)).all()
        )

        print(f"🔧 Actualizando {len(registros_a_actualizar)} registros...")

        for i, registro in enumerate(registros_a_actualizar, 1):
            try:
                if registro.mlp_id in status_map:
                    registro.optval_statusId = status_map[registro.mlp_id]
                    actualizados += 1

                    # Commit cada 100 registros
                    if i % 100 == 0:
                        db.commit()
                        print(f"   ✓ {i} registros procesados...")

            except Exception as e:
                errores += 1
                print(f"   ⚠️  Error actualizando mlp_id {registro.mlp_id}: {str(e)}")
                db.rollback()
                continue

        # Commit final
        db.commit()

        # Verificar cuántos quedan con None
        registros_null_final = (
            db.query(MercadoLibreItemPublicado).filter(MercadoLibreItemPublicado.optval_statusId.is_(None)).count()
        )

        print("\n✅ Actualización completada!")
        print(f"   Actualizados: {actualizados}")
        print(f"   Errores: {errores}")
        print(f"   Registros con None restantes: {registros_null_final}")
        print("   (Los registros con None restantes son items antiguos no disponibles en los últimos 90 días)")

        return actualizados

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        db.rollback()
        return 0


if __name__ == "__main__":
    print("🚀 Actualización de optval_statusId\n")

    db = SessionLocal()
    try:
        result = asyncio.run(fix_optval_statusId(db))
    finally:
        db.close()
