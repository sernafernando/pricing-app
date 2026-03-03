"""
Script para sincronizar tb_supplier desde el ERP (tbSupplier)
Tabla de lookup chica - siempre hace full sync.

Modos de uso:
    # Full (toda la tabla)
    python -m app.scripts.sync_suppliers

    # Un proveedor específico
    python -m app.scripts.sync_suppliers --supp-id 456
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
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.models.tb_supplier import TBSupplier

# URL del gbp-parser
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"

VALID_FIELDS = {"comp_id", "supp_id", "supp_name", "supp_tax_number"}

# Campos renombrados del ERP
FIELD_MAP = {
    "supp_taxNumber": "supp_tax_number",
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
        if not any(field in first for field in {"comp_id", "supp_id", "supp_name"}):
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

    if not row.get("comp_id") or row.get("supp_id") is None:
        return None

    return {k: v for k, v in row.items() if k in VALID_FIELDS}


def sync_full(db: Session, supp_id: int | None = None) -> None:
    """Sincronización completa de tb_supplier"""
    label = f"supp_id={supp_id}" if supp_id else "toda la tabla"
    print(f"\n🔄 Sincronización de tb_supplier ({label})")
    print("=" * 60)

    params: dict = {"strScriptLabel": "scriptSupplier"}
    if supp_id is not None:
        params["suppID"] = supp_id

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
    stmt = insert(TBSupplier)
    stmt = stmt.on_conflict_do_update(
        index_elements=["comp_id", "supp_id"],
        set_={
            "supp_name": stmt.excluded.supp_name,
            "supp_tax_number": stmt.excluded.supp_tax_number,
        },
    )
    db.execute(stmt, normalized_data)
    db.commit()

    print("\n✅ Sincronización finalizada")
    print(f"   Total actualizado: {len(normalized_data)} registros")


def sync_suppliers() -> tuple[int, int]:
    """Entry point para sync_master_tables_small (sin args, maneja su propia session)."""
    db = SessionLocal()
    try:
        sync_full(db)
        count = db.execute(text("SELECT count(*) FROM tb_supplier")).scalar() or 0
        return (count, 0)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronizar tb_supplier (proveedores)")
    parser.add_argument("--supp-id", type=int, default=None, help="Sincronizar un proveedor específico")

    args = parser.parse_args()

    db = SessionLocal()

    try:
        sync_full(db, supp_id=args.supp_id)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
