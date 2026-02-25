"""
Script para sincronizar tb_storage desde el ERP (tbStorage)
Tabla de lookup chica - siempre hace full sync.

Modos de uso:
    # Full (toda la tabla)
    python -m app.scripts.sync_storage

    # Un depósito específico
    python -m app.scripts.sync_storage --stor-id 1
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

import argparse
import asyncio
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.models.tb_storage import TbStorage

# URL del gbp-parser
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"

VALID_FIELDS = {"comp_id", "stor_id", "stor_desc", "bra_id", "stor_disabled"}

# Campos renombrados del ERP
FIELD_MAP = {
    "bra_id4DfId_OnDivideByStorage": "bra_id",
    "stor_disabled4Selection": "stor_disabled",
}


def is_erp_error(data: list) -> bool:
    """Detecta respuestas de error del ERP (ej: [{"Column1":"-9"}])"""
    if len(data) == 1 and isinstance(data[0], dict):
        first = data[0]
        if "Column1" in first:
            try:
                return int(first["Column1"]) < 0
            except (ValueError, TypeError):
                return False
        if not any(field in first for field in VALID_FIELDS):
            return True
    return False


async def fetch_from_erp(params: dict) -> list:
    """Consulta el ERP vía gbp-parser."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(GBP_PARSER_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list) or is_erp_error(data):
            return []
        return data


def normalize_row(row: dict) -> dict | None:
    """Normaliza y filtra una fila del ERP."""
    # Renombrar campos del ERP
    for erp_name, local_name in FIELD_MAP.items():
        if erp_name in row:
            row[local_name] = row.pop(erp_name)

    if not row.get("comp_id") or row.get("stor_id") is None:
        return None

    # Convertir booleanos
    if "stor_disabled" in row and row["stor_disabled"] is not None:
        row["stor_disabled"] = bool(row["stor_disabled"])

    return {k: v for k, v in row.items() if k in VALID_FIELDS}


def sync_full(db: Session, stor_id: int | None = None) -> None:
    """Sincronización completa de tb_storage"""
    label = f"stor_id={stor_id}" if stor_id else "toda la tabla"
    print(f"\n🔄 Sincronización de tb_storage ({label})")
    print("=" * 60)

    params: dict = {"strScriptLabel": "scriptStorage"}
    if stor_id is not None:
        params["storID"] = stor_id

    print("📡 Consultando ERP...")
    data = asyncio.run(fetch_from_erp(params))

    if not data:
        print("⚠️  No se obtuvieron datos del ERP")
        return

    print(f"✓ Obtenidos {len(data)} registros del ERP")
    print("💾 Actualizando base de datos...")

    normalized_data = []
    for row in data:
        normalized = normalize_row(row)
        if normalized:
            normalized_data.append(normalized)

    if not normalized_data:
        print("⚠️  Ningún registro válido para insertar")
        return

    # Upsert todo de una (tabla chica)
    stmt = insert(TbStorage)
    stmt = stmt.on_conflict_do_update(
        index_elements=["comp_id", "stor_id"],
        set_={
            "stor_desc": stmt.excluded.stor_desc,
            "bra_id": stmt.excluded.bra_id,
            "stor_disabled": stmt.excluded.stor_disabled,
        },
    )
    db.execute(stmt, normalized_data)
    db.commit()

    print("\n✅ Sincronización finalizada")
    print(f"   Total actualizado: {len(normalized_data)} registros")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronizar tb_storage (depósitos)")
    parser.add_argument("--stor-id", type=int, default=None, help="Sincronizar un depósito específico")

    args = parser.parse_args()

    db = SessionLocal()

    try:
        sync_full(db, stor_id=args.stor_id)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
