"""
Script para sincronizar ÓRDENES DE COMPRA del ERP (Purchase Orders).
Diseñado para ejecutarse cada 5-10 minutos para datos casi en tiempo real.

Tablas sincronizadas:
- tbPurchaseOrderHeader (cabecera de órdenes)
- tbPurchaseOrderDetail (detalle de órdenes)

Ejecutar:
    python -m app.scripts.sync_purchase_orders_all
    python -m app.scripts.sync_purchase_orders_all --days 7
    python -m app.scripts.sync_purchase_orders_all --days 1  # Solo hoy
"""

import sys
import os
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Cargar variables de entorno desde .env
    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

import argparse
import httpx
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import SessionLocal, get_background_db
from app.models.purchase_order_header import PurchaseOrderHeader
from app.models.purchase_order_detail import PurchaseOrderDetail

# URL del endpoint gbp-parser
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def parse_dt(val: str | None) -> datetime | None:
    """Parse fecha del ERP. Soporta ISO format y US format con AM/PM."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("T", " ").replace("Z", ""))
    except ValueError:
        pass
    # Fallback: US format "3/3/2026 4:00:59 PM" del GBP
    from dateutil import parser as dateutil_parser

    try:
        return dateutil_parser.parse(val)
    except (ValueError, TypeError):
        return None


def parse_bool(val) -> bool | None:
    """Convierte valores del ERP a bool o None.

    El ERP devuelve '' (string vacío) para booleanos sin setear, que SQLAlchemy
    Boolean rechaza con 'Not a boolean value'. Normaliza '' y desconocidos a None.
    """
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("true", "1", "t", "y", "yes", "si"):
        return True
    if s in ("false", "0", "f", "n", "no"):
        return False
    return None


async def sync_purchase_order_header(db: Session, days: int = 7) -> tuple[int, int, int]:
    """
    Sincroniza cabecera de órdenes de compra.

    Filtra por poh_isEditingCd usando updateFromDate/updateToDate.

    Args:
        db: Sesión de base de datos
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)

    Returns:
        tuple: (nuevos, actualizados, errores)
    """
    print(f"  📋 Purchase Order Header (últimos {days} días)...", end=" ", flush=True)

    try:
        # Fecha desde: día inicial a las 00:00:00
        from_date = (date.today() - timedelta(days=days)).isoformat()
        # Fecha hasta: día SIGUIENTE a las 00:00:00 (incluye todo el día de hoy)
        to_date = (date.today() + timedelta(days=1)).isoformat()

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(
                GBP_PARSER_URL,
                params={
                    "strScriptLabel": "scriptPurchaseOrderHeader",
                    "updateFromDate": from_date,
                    "updateToDate": to_date,
                },
            )
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return (0, 0, 0)

        nuevos = 0
        actualizados = 0
        errores = 0

        for record in data:
            try:
                comp_id = record.get("comp_id")
                bra_id = record.get("bra_id")
                poh_id = record.get("poh_id")

                if not all([comp_id, bra_id, poh_id]):
                    errores += 1
                    continue

                existente = (
                    db.query(PurchaseOrderHeader)
                    .filter(
                        and_(
                            PurchaseOrderHeader.comp_id == comp_id,
                            PurchaseOrderHeader.bra_id == bra_id,
                            PurchaseOrderHeader.poh_id == poh_id,
                        )
                    )
                    .first()
                )

                datos = {
                    "comp_id": comp_id,
                    "bra_id": bra_id,
                    "poh_id": poh_id,
                    "poh_cd": parse_dt(record.get("poh_cd")),
                    "poh_estdeliverydate": parse_dt(record.get("poh_estDeliveryDate")),
                    "poh_deliverydate": parse_dt(record.get("poh_deliveryDate")),
                    "poh_observation1": record.get("poh_observation1"),
                    "poh_observation2": record.get("poh_observation2"),
                    "poh_observation3": record.get("poh_observation3"),
                    "poh_observation4": record.get("poh_observation4"),
                    "supp_id": record.get("supp_id"),
                    "poh_quotation": record.get("poh_quotation"),
                    "pt_id": record.get("pt_id"),
                    "poh_isediting": parse_bool(record.get("poh_isEditing")),
                    "poh_iseditingcd": parse_dt(record.get("poh_isEditingCd")),
                    "ptr_id": record.get("ptr_id"),
                    "poh_acurrency": record.get("poh_ACurrency"),
                    "poh_acurrencyexchange": record.get("poh_ACurrencyExchange"),
                    "poh_perceptions": record.get("poh_Perceptions"),
                    "poh_taxes": record.get("poh_Taxes"),
                    "poh_charges": record.get("poh_Charges"),
                    "poh_discount1": record.get("poh_Discount1"),
                    "poh_discount2": record.get("poh_Discount2"),
                    "poh_discount3": record.get("poh_Discount3"),
                    "poh_discount4": record.get("poh_Discount4"),
                    "pho_selectedinrecepcion": parse_bool(record.get("pho_selectedInRecepcion")),
                    "user_id": record.get("user_id"),
                    "poh_validup2date": parse_dt(record.get("poh_validUp2Date")),
                    "poa_id": record.get("poa_id"),
                    "poh_pendingcoeficient": record.get("poh_pendingCoeficient"),
                    "poh_taxcoeficient": record.get("poh_taxCoeficient"),
                    "simi_id": record.get("simi_id"),
                    "pro_id": record.get("pro_id"),
                    "poh_total": record.get("poh_total"),
                    "poh_totalinsuppcurrency": record.get("poh_totalinSuppCurrency"),
                    "poh_isemailenvied": parse_bool(record.get("poh_iseMailEnvied")),
                }

                # Savepoint por registro: si un valor no entra en su columna/tipo,
                # se aísla ese registro (reportado con su PK) sin tumbar el lote.
                with db.begin_nested():
                    if existente:
                        for key, value in datos.items():
                            setattr(existente, key, value)
                    else:
                        db.add(PurchaseOrderHeader(**datos))
                    db.flush()

                if existente:
                    actualizados += 1
                else:
                    nuevos += 1

                # Commit cada 500
                if (nuevos + actualizados) % 500 == 0:
                    db.commit()

            except Exception as e:
                errores += 1
                error_key = type(e).__name__
                if errores <= 10:
                    print(f"\n  ⚠️  poh_id={record.get('poh_id')} [{error_key}]: {str(e)[:400]}")
                continue

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"\n  ❌ Error en commit final (header): {str(e)[:400]}")
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados, {errores} errores)")
        return (nuevos, actualizados, errores)

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return (0, 0, 0)


async def sync_purchase_order_detail(db: Session, days: int = 7) -> tuple[int, int, int]:
    """
    Sincroniza detalle de órdenes de compra.

    Filtra por pod_isEditingCd usando fromDate/toDate (no updateFromDate).

    Args:
        db: Sesión de base de datos
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)

    Returns:
        tuple: (nuevos, actualizados, errores)
    """
    print(f"  📋 Purchase Order Detail (últimos {days} días)...", end=" ", flush=True)

    try:
        # Fecha desde: día inicial a las 00:00:00
        from_date = (date.today() - timedelta(days=days)).isoformat()
        # Fecha hasta: día SIGUIENTE a las 00:00:00 (incluye todo el día de hoy)
        to_date = (date.today() + timedelta(days=1)).isoformat()

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(
                GBP_PARSER_URL,
                params={
                    "strScriptLabel": "scriptPurchaseOrderDetail",
                    "fromDate": from_date,
                    "toDate": to_date,
                },
            )
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return (0, 0, 0)

        nuevos = 0
        actualizados = 0
        errores = 0
        errores_por_tipo: dict[str, int] = {}

        for record in data:
            try:
                comp_id = record.get("comp_id")
                bra_id = record.get("bra_id")
                poh_id = record.get("poh_id")
                pod_id = record.get("pod_id")

                if not all([comp_id, bra_id, poh_id, pod_id]):
                    errores += 1
                    error_key = "campos_null"
                    errores_por_tipo[error_key] = errores_por_tipo.get(error_key, 0) + 1
                    if errores <= 3:
                        print(f"\n  ⚠️  PKs nulas: comp_id={comp_id}, bra_id={bra_id}, poh_id={poh_id}, pod_id={pod_id}")
                    continue

                existente = (
                    db.query(PurchaseOrderDetail)
                    .filter(
                        and_(
                            PurchaseOrderDetail.comp_id == comp_id,
                            PurchaseOrderDetail.bra_id == bra_id,
                            PurchaseOrderDetail.poh_id == poh_id,
                            PurchaseOrderDetail.pod_id == pod_id,
                        )
                    )
                    .first()
                )

                datos = {
                    "comp_id": comp_id,
                    "bra_id": bra_id,
                    "poh_id": poh_id,
                    "pod_id": pod_id,
                    "item_id": record.get("item_id"),
                    "curr_id": record.get("curr_id"),
                    "cont_id": record.get("cont_id"),
                    "pod_qty": record.get("pod_qty"),
                    "pod_price": record.get("pod_price"),
                    "tax_id": record.get("tax_id"),
                    "pod_isprocessed": parse_bool(record.get("pod_isProcessed")),
                    "pod_isediting": parse_bool(record.get("pod_isEditing")),
                    "pod_iseditingcd": parse_dt(record.get("pod_isEditingCd")),
                    "pod_obs": record.get("pod_obs"),
                    "pod_priceb": record.get("pod_priceB"),
                    "pod_custom": parse_bool(record.get("pod_custom")),
                    "pod_customnumber": record.get("pod_customNumber"),
                    "pod_discount1": record.get("pod_Discount1"),
                    "pod_discount2": record.get("pod_Discount2"),
                    "pod_discount3": record.get("pod_Discount3"),
                    "pod_discount4": record.get("pod_Discount4"),
                    "djai_id": record.get("djai_id"),
                    "pod_initqty": record.get("pod_initQty"),
                    "pod_confirmedqty": record.get("pod_confirmedQTY"),
                    "pod_surcharge1": record.get("pod_surcharge1"),
                    "pod_surcharge2": record.get("pod_surcharge2"),
                    "pod_surcharge3": record.get("pod_surcharge3"),
                    "pod_surcharge4": record.get("pod_surcharge4"),
                    "pod_pricewithdiscountandcharges": record.get("pod_priceWithDiscountAndCharges"),
                    "simi_id": record.get("simi_id"),
                    "simid_id": record.get("simid_id"),
                    "pod_origin": record.get("pod_Origin"),
                    "pod_from": record.get("pod_From"),
                    "pod_stamp": record.get("pod_Stamp"),
                    "pod_lotnumber": record.get("pod_LotNumber"),
                    "pod_expirationdate": parse_dt(record.get("pod_ExpirationDate")),
                    "pod_includeinavailablestock": parse_bool(record.get("pod_includeInAvailableStock")),
                    "pod_id_from": record.get("pod_id_from"),
                    "pod_id_from_cd": parse_dt(record.get("pod_id_from_CD")),
                    "stor_id": record.get("stor_id"),
                }

                # Savepoint por registro: aísla el registro que no entra en su
                # columna/tipo (reportado con su PK) sin perder todo el lote.
                with db.begin_nested():
                    if existente:
                        for key, value in datos.items():
                            setattr(existente, key, value)
                    else:
                        db.add(PurchaseOrderDetail(**datos))
                    db.flush()

                if existente:
                    actualizados += 1
                else:
                    nuevos += 1

                # Commit cada 100
                if (nuevos + actualizados) % 100 == 0:
                    db.commit()

            except Exception as e:
                errores += 1
                error_key = type(e).__name__
                errores_por_tipo[error_key] = errores_por_tipo.get(error_key, 0) + 1
                if errores <= 10:
                    print(
                        f"\n  ⚠️  pod_id={record.get('pod_id')} poh_id={record.get('poh_id')} "
                        f"[{error_key}]: {str(e)[:400]}"
                    )
                continue

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"\n  ❌ Error en commit final (detail): {str(e)[:400]}")
            if errores_por_tipo:
                print(f"  📊 Errores por tipo: {errores_por_tipo}")
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados, {errores} errores)")
        return (nuevos, actualizados, errores)

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return (0, 0, 0)


async def main_async(days: int = 7) -> None:
    """
    Función principal async.

    Cuando corre como background task dentro de uvicorn, usa get_background_db()
    para abrir/cerrar una sesión por cada tabla — no retiene conexiones del pool
    durante toda la sincronización.

    Cuando corre como script standalone (python -m), usa SessionLocal() con
    NullPool (detectado automáticamente por _is_script_context()).

    Args:
        days: Días hacia atrás para sincronizar (default: 7 para ejecuciones frecuentes)
    """
    from app.core.database import _is_script_context

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"SYNC PURCHASE ORDERS (últimos {days} días) - {timestamp}")
    print("=" * 60)

    if _is_script_context():
        # Script standalone: una sola sesión (NullPool, no compite con nadie)
        db = SessionLocal()
        try:
            result_header = await sync_purchase_order_header(db, days)
            result_detail = await sync_purchase_order_detail(db, days)
        except Exception as e:
            print(f"\n❌ Error durante la sincronización: {str(e)}")
            import traceback

            traceback.print_exc()
            db.rollback()
            sys.exit(1)
        finally:
            db.close()
    else:
        # Background task en uvicorn: sesión corta por tabla para no drenar el pool
        with get_background_db() as db:
            result_header = await sync_purchase_order_header(db, days)

        with get_background_db() as db:
            result_detail = await sync_purchase_order_detail(db, days)

    print("\n" + "=" * 60)
    print("✅ SINCRONIZACIÓN COMPLETADA")
    print("=" * 60)
    print(f"Purchase Order Header: {result_header[0]} nuevos, {result_header[1]} actualizados")
    print(f"Purchase Order Detail: {result_detail[0]} nuevos, {result_detail[1]} actualizados")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Purchase Orders desde ERP")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Días hacia atrás para sincronizar (default: 7 para ejecuciones cada 5-10 min)",
    )
    args = parser.parse_args()

    import asyncio

    asyncio.run(main_async(args.days))


if __name__ == "__main__":
    main()
