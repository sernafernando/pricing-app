"""
Script para sincronizar item transactions de agosto 2025 únicamente
Este script es para recuperar el mes que falló por timeout

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_item_transactions_agosto_2025
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.item_transaction import ItemTransaction
import uuid

async def sync_item_transactions_agosto(db: Session):
    """
    Sincroniza item transactions de agosto 2025
    """
    print(f"\n📅 Sincronizando item transactions de agosto 2025...")
    print(f"   Desde: 2025-08-01")
    print(f"   Hasta: 2025-08-31\n")

    try:
        # Llamar al endpoint externo
        url = "http://localhost:8002/api/gbp-parser"
        params = {
            "strScriptLabel": "scriptItemTransaction",
            "fromDate": "2025-08-01",
            "toDate": "2025-08-31"
        }

        async with httpx.AsyncClient(timeout=180.0) as client:  # 3 minutos de timeout
            response = await client.get(url, params=params)
            response.raise_for_status()
            items_data = response.json()

        if not isinstance(items_data, list):
            print(f"❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(items_data) == 1 and "Column1" in items_data[0]:
            print(f"   ⚠️  No hay datos disponibles para agosto 2025")
            return 0, 0, 0

        print(f"   Procesando {len(items_data)} item transactions...")

        # Insertar o actualizar items
        items_insertados = 0
        items_actualizados = 0
        items_errores = 0

        def parse_date(date_str):
            if not date_str:
                return None
            try:
                if isinstance(date_str, str):
                    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return date_str
            except:
                return None

        def to_bool(value):
            """Convierte cualquier valor a booleano"""
            if value is None:
                return False
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes', 't')
            return False

        def to_decimal(value):
            """Convierte a decimal, retorna None si no es válido"""
            if value is None or value == '':
                return None
            try:
                return float(value)
            except:
                return None

        def to_int(value):
            """Convierte a entero, retorna None si no es válido"""
            if value is None or value == '':
                return None
            try:
                return int(value)
            except:
                return None

        for item_json in items_data:
            try:
                # Verificar que tenga it_transaction
                it_transaction = item_json.get("it_transaction")
                if it_transaction is None:
                    print(f"   ⚠️  Item sin it_transaction, omitiendo...")
                    items_errores += 1
                    continue

                # Verificar si ya existe
                item_existente = db.query(ItemTransaction).filter(
                    ItemTransaction.it_transaction == it_transaction
                ).first()

                if item_existente:
                    items_actualizados += 1
                    continue  # Skip si ya existe

                # Procesar GUID
                guid_str = item_json.get("it_packinginvoiceselectedguid")
                guid_value = None
                if guid_str:
                    try:
                        guid_value = uuid.UUID(guid_str)
                    except:
                        pass

                # Crear nuevo item transaction
                item = ItemTransaction(
                    comp_id=to_int(item_json.get("comp_id")),
                    bra_id=to_int(item_json.get("bra_id")),
                    ct_transaction=to_int(item_json.get("ct_transaction")),
                    it_transaction=it_transaction,
                    item_id=to_int(item_json.get("item_id")),
                    it_qty=to_decimal(item_json.get("it_qty")),
                    it_pricewithoothers=to_decimal(item_json.get("it_priceWithOutOthers")),
                    it_price=to_decimal(item_json.get("it_price")),
                    curr_id=to_int(item_json.get("curr_id")),
                    it_exchangetobranchcurrency=to_decimal(item_json.get("it_exchangeToBranchCurrency")),
                    it_priceofcost=to_decimal(item_json.get("it_priceOfCost")),
                    it_priceofcostpp=to_decimal(item_json.get("it_priceOfCostPP")),
                    it_priceofcostlastpurchase=to_decimal(item_json.get("it_priceOfCostLastPurchase")),
                    it_pricebofcost=to_decimal(item_json.get("it_priceBOfCost")),
                    it_pricebofcostpp=to_decimal(item_json.get("it_priceBOfCostPP")),
                    it_pricebofcostlastpurchase=to_decimal(item_json.get("it_priceBOfCostLastPurchase")),
                    it_originalprice=to_decimal(item_json.get("it_OriginalPrice")),
                    it_originalpricecurrency=to_int(item_json.get("it_OriginalPriceCurrency")),
                    it_exchangetooriginalpricecurrency=to_decimal(item_json.get("it_exchangeToOriginalPriceCurrency")),
                    stor_id=to_int(item_json.get("stor_id")),
                    it_storeprevious=to_int(item_json.get("it_storePrevious")),
                    prli_id=to_int(item_json.get("prli_id")),
                    byor_id=to_int(item_json.get("byor_id")),
                    it_isproduction=to_bool(item_json.get("it_isProduction")),
                    it_isassociation=to_bool(item_json.get("it_isAssociation")),
                    it_isassociationgroup=to_bool(item_json.get("it_isAssociationGroup")),
                    it_cd=parse_date(item_json.get("it_cd")),
                    it_packinginvoicepend=to_decimal(item_json.get("it_packingInvoicePend")),
                    it_order=to_int(item_json.get("it_order")),
                    so_id=to_int(item_json.get("so_id")),
                    it_guarantee=to_int(item_json.get("it_guarantee")),
                    it_itemdiscounttotal=to_decimal(item_json.get("it_itemDiscountTotal")),
                    it_totaldiscounttotal=to_decimal(item_json.get("it_totalDiscountTotal")),
                    it_creditint=to_decimal(item_json.get("it_CreditInt")),
                    it_creditintplus=to_decimal(item_json.get("it_CreditIntPlus")),
                    puco_id=to_int(item_json.get("puco_id")),
                    it_poh_bra_id=to_int(item_json.get("it_poh_bra_id")),
                    it_poh_id=to_int(item_json.get("it_poh_id")),
                    it_soh_id=to_int(item_json.get("it_soh_id")),
                    it_sod_id=to_int(item_json.get("it_sod_id")),
                    rmah_id=to_int(item_json.get("rmah_id")),
                    rmad_id=to_int(item_json.get("rmad_id")),
                    it_qty_rma=to_decimal(item_json.get("it_qty_rma")),
                    it_tis_id_aux=to_int(item_json.get("it_tis_id_aux")),
                    it_note1=item_json.get("it_note1"),
                    it_note2=item_json.get("it_note2"),
                    it_packinginvoiceselected=to_decimal(item_json.get("it_packingInvoiceSelected")),
                    it_cancelled=to_bool(item_json.get("it_cancelled")),
                    it_priceb=to_decimal(item_json.get("it_priceB")),
                    it_ismade=to_bool(item_json.get("it_isMade")),
                    it_item_id_origin=to_int(item_json.get("it_item_id_origin")),
                    tmp_tis_id=to_int(item_json.get("tmp_tis_id")),
                    it_packinginvoicependoriginal=to_decimal(item_json.get("it_packingInvoicePendOriginal")),
                    it_packinginvoiceselectedguid=guid_value,
                    it_transaction_original=to_int(item_json.get("it_transaction_original")),
                    it_transaction_nostockdiscount=to_int(item_json.get("it_transaction_NoStockDiscount")),
                    it_salescurrid4exchangetobranchcurrency=to_int(item_json.get("it_SalesCurrId4exchangeToBranchCurrency")),
                    it_allusetag1=item_json.get("it_AllUseTag1"),
                    it_allusetag2=item_json.get("it_AllUseTag2"),
                    it_allusetag3=item_json.get("it_AllUseTag3"),
                    it_allusetag4=item_json.get("it_AllUseTag4"),
                    it_discount1=to_decimal(item_json.get("it_Discount1")),
                    it_discount2=to_decimal(item_json.get("it_Discount2")),
                    it_discount3=to_decimal(item_json.get("it_Discount3")),
                    it_discount4=to_decimal(item_json.get("it_Discount4")),
                    coslis_id=to_int(item_json.get("coslis_id")),
                    coslis_idb=to_int(item_json.get("coslis_idB")),
                    supp_id=to_int(item_json.get("supp_id")),
                    camp_id=to_int(item_json.get("camp_id")),
                    it_transaction_originalew=to_int(item_json.get("it_transaction_originalEW")),
                    it_isinternaltransfer=to_bool(item_json.get("it_IsInternalTransfer")),
                    it_isrmasuppliercreditnote=to_bool(item_json.get("it_isRMASupplierCreditNote")),
                    it_isfaststockadjustment=to_bool(item_json.get("it_IsFastStockAdjustment")),
                    it_isstockadjustment=to_bool(item_json.get("it_IsStockAdjustment")),
                    it_isstockcontrol=to_bool(item_json.get("it_IsStockControl")),
                    sdlmt_id=to_int(item_json.get("sdlmt_id")),
                    sreas_id=to_int(item_json.get("sreas_id")),
                    it_loannumberofpays=to_int(item_json.get("it_loanNumberOfPays")),
                    sitt_id=to_int(item_json.get("sitt_id")),
                    it_deliverydate=parse_date(item_json.get("it_deliveryDate")),
                    itstkpld_id=to_int(item_json.get("itstkpld_id")),
                    it_nostockcheck=to_bool(item_json.get("it_NoStockCheck")),
                    it_transaction_originaldiv=to_int(item_json.get("it_transaction_originaLDIV")),
                    it_surcharge1=to_decimal(item_json.get("it_surcharge1")),
                    it_surcharge2=to_decimal(item_json.get("it_surcharge2")),
                    it_surcharge3=to_decimal(item_json.get("it_surcharge3")),
                    it_surcharge4=to_decimal(item_json.get("it_surcharge4")),
                    stor_id_related4branchtransfer=to_int(item_json.get("stor_id_related4BranchTransfer")),
                    it_transaction_related4branchtransfer=to_int(item_json.get("it_transaction_related4BranchTransfer")),
                    it_pod_id=to_int(item_json.get("it_pod_id")),
                    pubh_id=to_int(item_json.get("pubh_id")),
                    it_ewaddress=item_json.get("it_EWAddress"),
                    it_insurancedays=to_int(item_json.get("it_insuranceDays")),
                    insud_id=to_int(item_json.get("insud_id")),
                    insud_certificatenumber=to_int(item_json.get("insud_certificateNumber")),
                    it_priceofprli_id4creditincash=to_int(item_json.get("it_priceOfprli_id4CreditInCash")),
                    it_ispcconfig=to_bool(item_json.get("it_isPCConfig")),
                    it_isblocked4delivery=to_bool(item_json.get("it_isBlocked4Delivery")),
                    it_isfrompconfigctrlid=to_int(item_json.get("it_isFromPCConfigCTRLId")),
                    item_idfrompreinvoice=to_int(item_json.get("item_idfromPreInvoice")),
                    it_mlcost=to_decimal(item_json.get("it_MLCost")),
                    it_iscompensed=to_bool(item_json.get("it_isCompensed")),
                    ws_price=to_decimal(item_json.get("ws_price")),
                    ws_curr_id=to_int(item_json.get("ws_curr_Id")),
                    mlo_id=to_int(item_json.get("mlo_id")),
                    it_deliverycharge=to_decimal(item_json.get("it_deliveryCharge")),
                    it_mpcost=to_decimal(item_json.get("it_MPCost")),
                    it_mecost=to_decimal(item_json.get("it_MECost")),
                    it_packinginvoicependcancell_user_id=to_int(item_json.get("it_packingInvoicePendCancell_user_id")),
                    it_packinginvoicependcancell_cd=parse_date(item_json.get("it_packingInvoicePendCancell_cd")),
                    it_disableprintinemission=to_bool(item_json.get("it_disablePrintInEmmition")),
                    it_packinginvoiceqtyinvoiced=to_decimal(item_json.get("it_packingInvoiceQTYInvoiced")),
                    wscup_id=to_int(item_json.get("wscup_id")),
                    it_isinbranchtransfertotalizerstorage=to_bool(item_json.get("it_isInBranchTransferTotalizerStorage")),
                    tis_itemdiscountplan=to_decimal(item_json.get("tis_itemDiscountPlan")),
                    it_itemdiscount=to_decimal(item_json.get("it_itemDiscount"))
                )

                db.add(item)
                items_insertados += 1

                # Commit cada 100 items
                if items_insertados % 100 == 0:
                    db.commit()
                    print(f"   ✓ {items_insertados} items insertados...")

            except Exception as e:
                print(f"   ⚠️  Error procesando item {item_json.get('it_transaction')}: {str(e)}")
                items_errores += 1
                db.rollback()
                continue

        # Commit final
        db.commit()

        print(f"   ✅ Insertados: {items_insertados} | Actualizados: {items_actualizados} | Errores: {items_errores}")
        return items_insertados, items_actualizados, items_errores

    except httpx.HTTPError as e:
        print(f"   ❌ Error al consultar API externa: {str(e)}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"   ❌ Error en sincronización: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0, 0, 0


async def main():
    """
    Sincroniza item transactions de agosto 2025 únicamente
    """
    print("🚀 Sincronización de item transactions - Agosto 2025")
    print("=" * 60)

    db = SessionLocal()

    try:
        insertados, actualizados, errores = await sync_item_transactions_agosto(db)

        print("\n" + "=" * 60)
        print("📊 RESUMEN")
        print("=" * 60)
        print(f"✅ Items insertados: {insertados}")
        print(f"⏭️  Duplicados (omitidos): {actualizados}")
        print(f"❌ Errores: {errores}")
        print(f"📦 Total procesados: {insertados + actualizados + errores}")
        print("=" * 60)
        print("🎉 Sincronización completada!")

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
