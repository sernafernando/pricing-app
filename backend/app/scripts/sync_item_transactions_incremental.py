"""
Script para sincronización incremental de item transactions
Sincroniza solo los items nuevos desde el último it_transaction

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_item_transactions_incremental
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
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.item_transaction import ItemTransaction
import uuid

async def sync_item_transactions_incremental(db: Session):
    """
    Sincroniza item transactions de forma incremental
    Solo trae los items nuevos desde el último it_transaction
    """

    # Obtener el último it_transaction sincronizado
    ultimo_it = db.query(func.max(ItemTransaction.it_transaction)).scalar()

    if ultimo_it is None:
        print("⚠️  No hay item transactions en la base de datos.")
        print("   Ejecuta primero sync_item_transactions_2025.py para la carga inicial")
        return 0, 0, 0

    print(f"📊 Último it_transaction en BD: {ultimo_it}")
    print(f"🔄 Buscando item transactions nuevos...\n")

    try:
        # Llamar al endpoint externo usando itTransaction
        url = "https://parser-worker-js.gaussonline.workers.dev/consulta"
        params = {
            "strScriptLabel": "scriptItemTransaction",
            "itTransaction": ultimo_it
        }

        print(f"📅 Consultando API desde it_transaction > {ultimo_it}...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            items_data = response.json()

        if not isinstance(items_data, list):
            print(f"❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(items_data) == 1 and "Column1" in items_data[0]:
            print(f"   ⚠️  No hay datos disponibles")
            return 0, 0, 0

        if not items_data or len(items_data) == 0:
            print(f"✅ No hay item transactions nuevos. Base de datos actualizada.")
            return 0, 0, 0

        print(f"   Encontrados {len(items_data)} item transactions nuevos")
        print(f"   Rango: {min(i.get('it_transaction') for i in items_data)} - {max(i.get('it_transaction') for i in items_data)}\n")

        # Insertar items nuevos
        items_insertados = 0
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

        for item_json in items_data:
            try:
                it_transaction = item_json.get("it_transaction")

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
                    comp_id=item_json.get("comp_id"),
                    bra_id=item_json.get("bra_id"),
                    ct_transaction=item_json.get("ct_transaction"),
                    it_transaction=it_transaction,
                    item_id=item_json.get("item_id"),
                    it_qty=item_json.get("it_qty"),
                    it_pricewithoothers=item_json.get("it_priceWithOutOthers"),
                    it_price=item_json.get("it_price"),
                    curr_id=item_json.get("curr_id"),
                    it_exchangetobranchcurrency=item_json.get("it_exchangeToBranchCurrency"),
                    it_priceofcost=item_json.get("it_priceOfCost"),
                    it_priceofcostpp=item_json.get("it_priceOfCostPP"),
                    it_priceofcostlastpurchase=item_json.get("it_priceOfCostLastPurchase"),
                    it_pricebofcost=item_json.get("it_priceBOfCost"),
                    it_pricebofcostpp=item_json.get("it_priceBOfCostPP"),
                    it_pricebofcostlastpurchase=item_json.get("it_priceBOfCostLastPurchase"),
                    it_originalprice=item_json.get("it_OriginalPrice"),
                    it_originalpricecurrency=item_json.get("it_OriginalPriceCurrency"),
                    it_exchangetooriginalpricecurrency=item_json.get("it_exchangeToOriginalPriceCurrency"),
                    stor_id=item_json.get("stor_id"),
                    it_storeprevious=item_json.get("it_storePrevious"),
                    prli_id=item_json.get("prli_id"),
                    byor_id=item_json.get("byor_id"),
                    it_isproduction=item_json.get("it_isProduction"),
                    it_isassociation=item_json.get("it_isAssociation"),
                    it_isassociationgroup=item_json.get("it_isAssociationGroup"),
                    it_cd=parse_date(item_json.get("it_cd")),
                    it_packinginvoicepend=item_json.get("it_packingInvoicePend"),
                    it_order=item_json.get("it_order"),
                    so_id=item_json.get("so_id"),
                    it_guarantee=item_json.get("it_guarantee"),
                    it_itemdiscounttotal=item_json.get("it_itemDiscountTotal"),
                    it_totaldiscounttotal=item_json.get("it_totalDiscountTotal"),
                    it_creditint=item_json.get("it_CreditInt"),
                    it_creditintplus=item_json.get("it_CreditIntPlus"),
                    puco_id=item_json.get("puco_id"),
                    it_poh_bra_id=item_json.get("it_poh_bra_id"),
                    it_poh_id=item_json.get("it_poh_id"),
                    it_soh_id=item_json.get("it_soh_id"),
                    it_sod_id=item_json.get("it_sod_id"),
                    rmah_id=item_json.get("rmah_id"),
                    rmad_id=item_json.get("rmad_id"),
                    it_qty_rma=item_json.get("it_qty_rma"),
                    it_tis_id_aux=item_json.get("it_tis_id_aux"),
                    it_note1=item_json.get("it_note1"),
                    it_note2=item_json.get("it_note2"),
                    it_packinginvoiceselected=item_json.get("it_packingInvoiceSelected"),
                    it_cancelled=item_json.get("it_cancelled"),
                    it_priceb=item_json.get("it_priceB"),
                    it_ismade=item_json.get("it_isMade"),
                    it_item_id_origin=item_json.get("it_item_id_origin"),
                    tmp_tis_id=item_json.get("tmp_tis_id"),
                    it_packinginvoicependoriginal=item_json.get("it_packingInvoicePendOriginal"),
                    it_packinginvoiceselectedguid=guid_value,
                    it_transaction_original=item_json.get("it_transaction_original"),
                    it_transaction_nostockdiscount=item_json.get("it_transaction_NoStockDiscount"),
                    it_salescurrid4exchangetobranchcurrency=item_json.get("it_SalesCurrId4exchangeToBranchCurrency"),
                    it_allusetag1=item_json.get("it_AllUseTag1"),
                    it_allusetag2=item_json.get("it_AllUseTag2"),
                    it_allusetag3=item_json.get("it_AllUseTag3"),
                    it_allusetag4=item_json.get("it_AllUseTag4"),
                    it_discount1=item_json.get("it_Discount1"),
                    it_discount2=item_json.get("it_Discount2"),
                    it_discount3=item_json.get("it_Discount3"),
                    it_discount4=item_json.get("it_Discount4"),
                    coslis_id=item_json.get("coslis_id"),
                    coslis_idb=item_json.get("coslis_idB"),
                    supp_id=item_json.get("supp_id"),
                    camp_id=item_json.get("camp_id"),
                    it_transaction_originalew=item_json.get("it_transaction_originalEW"),
                    it_isinternaltransfer=item_json.get("it_IsInternalTransfer"),
                    it_isrmasuppliercreditnote=item_json.get("it_isRMASupplierCreditNote"),
                    it_isfaststockadjustment=item_json.get("it_IsFastStockAdjustment"),
                    it_isstockadjustment=item_json.get("it_IsStockAdjustment"),
                    it_isstockcontrol=item_json.get("it_IsStockControl"),
                    sdlmt_id=item_json.get("sdlmt_id"),
                    sreas_id=item_json.get("sreas_id"),
                    it_loannumberofpays=item_json.get("it_loanNumberOfPays"),
                    sitt_id=item_json.get("sitt_id"),
                    it_deliverydate=parse_date(item_json.get("it_deliveryDate")),
                    itstkpld_id=item_json.get("itstkpld_id"),
                    it_nostockcheck=item_json.get("it_NoStockCheck"),
                    it_transaction_originaldiv=item_json.get("it_transaction_originaLDIV"),
                    it_surcharge1=item_json.get("it_surcharge1"),
                    it_surcharge2=item_json.get("it_surcharge2"),
                    it_surcharge3=item_json.get("it_surcharge3"),
                    it_surcharge4=item_json.get("it_surcharge4"),
                    stor_id_related4branchtransfer=item_json.get("stor_id_related4BranchTransfer"),
                    it_transaction_related4branchtransfer=item_json.get("it_transaction_related4BranchTransfer"),
                    it_pod_id=item_json.get("it_pod_id"),
                    pubh_id=item_json.get("pubh_id"),
                    it_ewaddress=item_json.get("it_EWAddress"),
                    it_insurancedays=item_json.get("it_insuranceDays"),
                    insud_id=item_json.get("insud_id"),
                    insud_certificatenumber=item_json.get("insud_certificateNumber"),
                    it_priceofprli_id4creditincash=item_json.get("it_priceOfprli_id4CreditInCash"),
                    it_ispcconfig=item_json.get("it_isPCConfig"),
                    it_isblocked4delivery=item_json.get("it_isBlocked4Delivery"),
                    it_isfrompconfigctrlid=item_json.get("it_isFromPCConfigCTRLId"),
                    item_idfrompreinvoice=item_json.get("item_idfromPreInvoice"),
                    it_mlcost=item_json.get("it_MLCost"),
                    it_iscompensed=item_json.get("it_isCompensed"),
                    ws_price=item_json.get("ws_price"),
                    ws_curr_id=item_json.get("ws_curr_Id"),
                    mlo_id=item_json.get("mlo_id"),
                    it_deliverycharge=item_json.get("it_deliveryCharge"),
                    it_mpcost=item_json.get("it_MPCost"),
                    it_mecost=item_json.get("it_MECost"),
                    it_packinginvoicependcancell_user_id=item_json.get("it_packingInvoicePendCancell_user_id"),
                    it_packinginvoicependcancell_cd=parse_date(item_json.get("it_packingInvoicePendCancell_cd")),
                    it_disableprintinemission=item_json.get("it_disablePrintInEmmition"),
                    it_packinginvoiceqtyinvoiced=item_json.get("it_packingInvoiceQTYInvoiced"),
                    wscup_id=item_json.get("wscup_id"),
                    it_isinbranchtransfertotalizerstorage=item_json.get("it_isInBranchTransferTotalizerStorage"),
                    tis_itemdiscountplan=item_json.get("tis_itemDiscountPlan"),
                    it_itemdiscount=item_json.get("it_itemDiscount")
                )

                db.add(item)
                items_insertados += 1

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

        # Obtener nuevo máximo
        nuevo_max = db.query(func.max(ItemTransaction.it_transaction)).scalar()

        print(f"\n✅ Sincronización completada!")
        print(f"   Insertados: {items_insertados}")
        print(f"   Errores: {items_errores}")
        print(f"   Nuevo it_transaction máximo: {nuevo_max}")

        return items_insertados, 0, items_errores

    except httpx.HTTPError as e:
        print(f"❌ Error al consultar API externa: {str(e)}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"❌ Error en sincronización: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0, 0, 0


async def main():
    """
    Sincronización incremental de item transactions
    """
    print("🚀 Sincronización incremental de item transactions")
    print("=" * 60)

    db = SessionLocal()

    try:
        await sync_item_transactions_incremental(db)
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
