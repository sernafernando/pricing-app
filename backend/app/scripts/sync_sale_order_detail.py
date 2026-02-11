"""
Script para sincronizar detalle de órdenes de venta desde el ERP
Tabla: tbSaleOrderDetail

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_sale_order_detail
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
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.sale_order_detail import SaleOrderDetail


def fetch_sale_order_detail_from_erp(from_date: date = None, to_date: date = None):
    """Obtiene detalle de órdenes de venta desde el ERP vía GBP Worker"""
    url = "http://localhost:8002/api/gbp-parser"

    # Por defecto, últimos 6 meses
    if not from_date:
        from_date = date.today() - timedelta(days=180)
    if not to_date:
        # Sumar 1 día para incluir registros de HOY
        to_date = date.today() + timedelta(days=1)

    params = {
        "strScriptLabel": "scriptSaleOrderDetail",
        "fromDate": from_date.isoformat(),
        "toDate": to_date.isoformat(),
    }

    print(f"📥 Descargando detalles de órdenes desde {from_date} hasta {to_date}...")

    try:
        response = requests.get(url, params=params, timeout=300)
        response.raise_for_status()
        data = response.json()

        print(f"  ✓ Obtenidos {len(data)} registros")
        return data

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error consultando ERP: {e}")
        return []


def sync_sale_order_detail(db: Session, data: list):
    """Sincroniza los detalles de órdenes en la base de datos local"""

    if not data:
        print("  ⚠️  No hay datos para sincronizar")
        return 0, 0, 0

    print(f"\n💾 Sincronizando {len(data)} registros...")

    insertados = 0
    actualizados = 0
    errores = 0

    for record in data:
        try:
            comp_id = record.get("comp_id")
            bra_id = record.get("bra_id")
            soh_id = record.get("soh_id")
            sod_id = record.get("sod_id")

            # Buscar registro existente por clave compuesta
            existente = (
                db.query(SaleOrderDetail)
                .filter(
                    and_(
                        SaleOrderDetail.comp_id == comp_id,
                        SaleOrderDetail.bra_id == bra_id,
                        SaleOrderDetail.soh_id == soh_id,
                        SaleOrderDetail.sod_id == sod_id,
                    )
                )
                .first()
            )

            # Función helper para convertir fechas
            def parse_datetime(value):
                if not value:
                    return None
                try:
                    return datetime.fromisoformat(value.replace("T", " "))
                except:
                    return None

            # Función helper para convertir a numeric (evitar booleans)
            def parse_numeric(value):
                if value is None:
                    return None
                if isinstance(value, bool):
                    return 1.0 if value else 0.0
                try:
                    return float(value)
                except:
                    return None

            # Preparar datos (mapear keys del ERP a nombres de columnas en minúsculas)
            data_record = {
                "comp_id": comp_id,
                "bra_id": bra_id,
                "soh_id": soh_id,
                "sod_id": sod_id,
                "sod_priority": record.get("sod_priority"),
                "item_id": record.get("item_id"),
                "sod_detail": record.get("sod_detail"),
                "curr_id": record.get("curr_id"),
                "sod_initqty": parse_numeric(record.get("sod_initQty")),
                "sod_qty": parse_numeric(record.get("sod_qty")),
                "prli_id": record.get("prli_id"),
                "sod_price": parse_numeric(record.get("sod_price")),
                "stor_id": record.get("stor_id"),
                "sod_lastupdate": parse_datetime(record.get("sod_lastUpdate")),
                "sod_isediting": record.get("sod_isEditing"),
                "sod_insertdate": parse_datetime(record.get("sod_insertDate")),
                "user_id": record.get("user_id"),
                "sod_quotation": record.get("sod_quotation"),
                "sod_iscredit": record.get("sod_isCredit"),
                "sod_cost": parse_numeric(record.get("sod_cost")),
                "sod_costtax": parse_numeric(record.get("sod_costTax")),
                "rmah_id": record.get("rmah_id"),
                "rmad_id": record.get("rmad_id"),
                "sod_note1": record.get("sod_note1"),
                "sod_note2": record.get("sod_note2"),
                "sod_itemdiscount": parse_numeric(record.get("sod_itemDiscount")),
                "sod_tis_id_origin": record.get("sod_tis_id_origin"),
                "sod_item_id_origin": record.get("sod_item_id_origin"),
                "sod_isparentassociate": record.get("sod_isParentAssociate"),
                "is_id": record.get("is_id"),
                "it_transaction": record.get("it_transaction"),
                "sod_ismade": record.get("sod_isMade"),
                "sod_expirationdate": parse_datetime(record.get("sod_expirationDate")),
                "acc_count_id": record.get("acc_count_id"),
                "sod_packagesqty": record.get("sod_packagesQty"),
                "item_id_ew": record.get("item_id_EW"),
                "tis_idofthisew": record.get("tis_idOfThisEW"),
                "camp_id": record.get("camp_id"),
                "sdlmt_id": record.get("sdlmt_id"),
                "sreas_id": record.get("sreas_id"),
                "sod_loannumberofpays": record.get("sod_loanNumberOfPays"),
                "sod_loandateoffirstpay": parse_datetime(record.get("sod_loanDateOfFirstPay")),
                "sod_loandayofmonthofnextpays": record.get("sod_loanDayOfMonthOfNextPays"),
                "sod_itemdeliverydate": parse_datetime(record.get("sod_itemDeliveryDate")),
                "sod_idofthisew": record.get("sod_idOfThisEW"),
                "sod_isfrompconfigctrlid": record.get("sod_isFromPCConfigCTRLId"),
                "sod_ewaddress": record.get("sod_EWAddress"),
                "sod_pcconfgistransfered2branch": record.get("sod_PCCOnfigIsTransfered2Branch"),
                "sod_mlcost": parse_numeric(record.get("sod_MLCost")),
                "sod_itemassociationcoeficient": parse_numeric(record.get("sod_itemAssociationCoeficient")),
                "ws_price": parse_numeric(record.get("ws_price")),
                "ws_curr_id": record.get("ws_curr_Id"),
                "sops_id": record.get("sops_id"),
                "mlo_id": record.get("mlo_id"),
                "sops_supp_id": record.get("sops_supp_id"),
                "sops_bra_id": record.get("sops_bra_id"),
                "sops_date": parse_datetime(record.get("sops_date")),
                "sod_mecost": parse_numeric(record.get("sod_MECost")),
                "sod_mpcost": parse_numeric(record.get("sod_MPCost")),
                "sod_isdivided": record.get("sod_isDivided"),
                "sod_isdivided_date": parse_datetime(record.get("sod_isDivided_Date")),
                "user_id_division": record.get("user_id_division"),
                "sodi_id": record.get("sodi_id"),
                "sod_isdivided_costcoeficient": parse_numeric(record.get("sod_isDivided_costCoeficient")),
                "sod_deliverycharge": record.get("sod_DeliveryCharge"),  # Boolean
                "sod_itemdesc": record.get("sod_itemDesc"),
                "sops_poh_bra_id": record.get("sops_poh_bra_id"),
                "sops_poh_id": record.get("sops_poh_id"),
                "sops_note": record.get("sops_note"),
                "sops_user_id": record.get("sops_user_id"),
                "sops_lastupdate": parse_datetime(record.get("sops_lastUpdate")),
                "ct_transaction_selectfrompacking": record.get("ct_transaction_SelectFromPacking"),
                "sodt_qty": parse_numeric(record.get("sodt_qty")),
                "sod_disableprintinemmition": record.get("sod_disablePrintInEmmition"),
                "sod_discountbyitem": parse_numeric(record.get("sod_discountByItem")),
                "sod_discountbytotal": parse_numeric(record.get("sod_discountByTotal")),
                "sod_creditint": parse_numeric(record.get("sod_creditInt")),
                "sod_creditintplus": parse_numeric(record.get("sod_creditIntPlus")),
                "sod_priceneto": parse_numeric(record.get("sod_priceNeto")),
                "sod_combocoeficient": parse_numeric(record.get("sod_comboCoeficient")),
                "sod_montlypaymentfrom": parse_numeric(record.get("sod_montlyPaymentFrom")),
                "sod_montlypaymentto": parse_numeric(record.get("sod_montlyPaymentTo")),
                "wscup_id": record.get("wscup_id"),
                "sod_candeletecomboinso": record.get("sod_canDeleteCOMBOInSO"),
                "sod_exclude4availablestock": record.get("sod_exclude4AvailableStock"),
                "sod_discountplan": parse_numeric(record.get("sod_discountPlan")),
                "tax_id4iva": record.get("tax_id4IVA"),
                "sod_pending4pod_idrelation": record.get("sod_pending4pod_IdRelation"),  # Boolean
                "sod_mercadolibre_mustupdatestock": record.get("sod_MercadoLibre_MustUpdateStock"),
                "sod_auxtmpvalue": parse_numeric(record.get("sod_auxTMPValue")),
                "sod_itemdiscount2": parse_numeric(record.get("sod_itemDiscount2")),
            }

            if existente:
                # Actualizar
                for key, value in data_record.items():
                    setattr(existente, key, value)
                actualizados += 1
            else:
                # Insertar nuevo
                nuevo = SaleOrderDetail(**data_record)
                db.add(nuevo)
                insertados += 1

            # Commit cada 500 registros
            if (insertados + actualizados) % 500 == 0:
                db.commit()
                print(f"  📊 Progreso: {insertados + actualizados}/{len(data)}")

        except Exception as e:
            errores += 1
            print(
                f"  ⚠️  Error en registro (comp_id={record.get('comp_id')}, bra_id={record.get('bra_id')}, soh_id={record.get('soh_id')}, sod_id={record.get('sod_id')}): {str(e)}"
            )
            db.rollback()  # Rollback para poder continuar con los demás
            continue

    # Commit final
    db.commit()

    return insertados, actualizados, errores


def main():
    print("=" * 60)
    print("SINCRONIZACIÓN DE SALE ORDER DETAIL")
    print("=" * 60)

    db = SessionLocal()

    try:
        # 1. Obtener datos del ERP (últimos 6 meses por defecto)
        data = fetch_sale_order_detail_from_erp()

        # 2. Sincronizar en PostgreSQL
        insertados, actualizados, errores = sync_sale_order_detail(db, data)

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
