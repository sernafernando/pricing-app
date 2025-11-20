"""
Script para sincronización incremental de transacciones comerciales
Sincroniza solo las transacciones nuevas desde el último ct_transaction

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_commercial_transactions_incremental
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
# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.commercial_transaction import CommercialTransaction
import uuid

async def sync_transacciones_incrementales(db: Session, batch_size: int = 1000):
    """
    Sincroniza transacciones comerciales de forma incremental
    Solo trae las transacciones nuevas desde el último ct_transaction
    """

    # Obtener el último ct_transaction sincronizado
    ultimo_ct = db.query(func.max(CommercialTransaction.ct_transaction)).scalar()

    if ultimo_ct is None:
        print("⚠️  No hay transacciones en la base de datos.")
        print("   Ejecuta primero sync_commercial_transactions_2025.py para la carga inicial")
        return 0, 0, 0

    print(f"📊 Último ct_transaction en BD: {ultimo_ct}")
    print(f"🔄 Buscando transacciones nuevas...\n")

    try:
        # El endpoint necesita fechas, pero usaremos un rango amplio
        # y filtraremos por ct_transaction en el código
        hoy = datetime.now()
        desde = hoy.replace(day=1).strftime('%Y-%m-%d')  # Primer día del mes actual
        hasta = hoy.strftime('%Y-%m-%d')

        # Llamar al endpoint externo
        url = "http://localhost:8002/api/gbp-parser"
        params = {
            "strScriptLabel": "scriptCommercial",
            "fromDate": desde,
            "toDate": hasta
        }

        print(f"📅 Consultando API desde {desde} hasta {hasta}...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            transacciones_data = response.json()

        if not isinstance(transacciones_data, list):
            print(f"❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(transacciones_data) == 1 and "Column1" in transacciones_data[0]:
            print(f"   ⚠️  No hay datos disponibles")
            return 0, 0, 0

        # Filtrar solo transacciones nuevas (ct_transaction > ultimo_ct)
        transacciones_nuevas = [
            t for t in transacciones_data
            if t.get("ct_transaction") and t.get("ct_transaction") > ultimo_ct
        ]

        if not transacciones_nuevas:
            print(f"✅ No hay transacciones nuevas. Base de datos actualizada.")
            return 0, 0, 0

        print(f"   Encontradas {len(transacciones_nuevas)} transacciones nuevas")
        print(f"   Rango: {min(t.get('ct_transaction') for t in transacciones_nuevas)} - {max(t.get('ct_transaction') for t in transacciones_nuevas)}\n")

        # Insertar transacciones nuevas
        transacciones_insertadas = 0
        transacciones_errores = 0

        def parse_date(date_str):
            if not date_str:
                return None
            try:
                if isinstance(date_str, str):
                    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return date_str
            except:
                return None

        for trans_json in transacciones_nuevas:
            try:
                ct_transaction = trans_json.get("ct_transaction")

                # Procesar el GUID
                guid_str = trans_json.get("ct_guid")
                guid_value = None
                if guid_str:
                    try:
                        guid_value = uuid.UUID(guid_str)
                    except:
                        pass

                # Crear nueva transacción
                trans = CommercialTransaction(
                    comp_id=trans_json.get("comp_id"),
                    bra_id=trans_json.get("bra_id"),
                    ct_transaction=ct_transaction,
                    ct_pointOfSale=trans_json.get("ct_pointOfSale"),
                    ct_kindOf=trans_json.get("ct_kindOf"),
                    ct_docNumber=trans_json.get("ct_docNumber"),
                    ct_date=parse_date(trans_json.get("ct_date")),
                    ct_taxDate=parse_date(trans_json.get("ct_taxDate")),
                    ct_payDate=parse_date(trans_json.get("ct_payDate")),
                    ct_deliveryDate=parse_date(trans_json.get("ct_deliveryDate")),
                    ct_processingDate=parse_date(trans_json.get("ct_processingDate")),
                    ct_lastPayDate=parse_date(trans_json.get("ct_lastPayDate")),
                    ct_cd=parse_date(trans_json.get("ct_cd")),
                    supp_id=trans_json.get("supp_id"),
                    cust_id=trans_json.get("cust_id"),
                    cust_id_related=trans_json.get("cust_id_related"),
                    cust_id_guarantor=trans_json.get("cust_id_guarantor"),
                    custf_id=trans_json.get("custf_id"),
                    ba_id=trans_json.get("ba_id"),
                    cb_id=trans_json.get("cb_id"),
                    user_id=trans_json.get("user_id"),
                    ct_subtotal=trans_json.get("ct_subtotal"),
                    ct_total=trans_json.get("ct_total"),
                    ct_discount=trans_json.get("ct_discount"),
                    ct_adjust=trans_json.get("ct_adjust"),
                    ct_taxes=trans_json.get("ct_taxes"),
                    ct_ATotal=trans_json.get("ct_ATotal"),
                    ct_ABalance=trans_json.get("ct_ABalance"),
                    ct_AAdjust=trans_json.get("ct_AAdjust"),
                    ct_inCash=trans_json.get("ct_inCash"),
                    ct_optionalValue=trans_json.get("ct_optionalValue"),
                    ct_documentTotal=trans_json.get("ct_documentTotal"),
                    curr_id_transaction=trans_json.get("curr_id_transaction"),
                    ct_ACurrency=trans_json.get("ct_ACurrency"),
                    ct_ACurrencyExchange=trans_json.get("ct_ACurrencyExchange"),
                    ct_CompanyCurrency=trans_json.get("ct_CompanyCurrency"),
                    ct_Branch2CompanyCurrencyExchange=trans_json.get("ct_Branch2CompanyCurrencyExchange"),
                    ct_dfExchange=trans_json.get("ct_dfExchange"),
                    curr_id4Exchange=trans_json.get("curr_id4Exchange"),
                    ct_curr_IdExchange=trans_json.get("ct_curr_IdExchange"),
                    curr_id4dfExchange=trans_json.get("curr_id4dfExchange"),
                    ct_dfExchangeOriginal=trans_json.get("ct_dfExchangeOriginal"),
                    ct_curr_IdExchangeOriginal=trans_json.get("ct_curr_IdExchangeOriginal"),
                    hacc_transaction=trans_json.get("hacc_transaction"),
                    sm_id=trans_json.get("sm_id"),
                    disc_id=trans_json.get("disc_id"),
                    df_id=trans_json.get("df_id"),
                    dl_id=trans_json.get("dl_id"),
                    st_id=trans_json.get("st_id"),
                    sd_id=trans_json.get("sd_id"),
                    puco_id=trans_json.get("puco_id"),
                    country_id=trans_json.get("country_id"),
                    state_id=trans_json.get("state_id"),
                    ct_Pending=trans_json.get("ct_Pending"),
                    ct_isAvailableForImport=trans_json.get("ct_isAvailableForImport"),
                    ct_isAvailableForPayment=trans_json.get("ct_isAvailableForPayment"),
                    ct_isCancelled=trans_json.get("ct_isCancelled"),
                    ct_isSelected=trans_json.get("ct_isSelected"),
                    ct_isMigrated=trans_json.get("ct_isMigrated"),
                    ct_powerBoardOK=trans_json.get("ct_powerBoardOK"),
                    ct_Fiscal_Check4EmptyNumbers=trans_json.get("ct_Fiscal_Check4EmptyNumbers"),
                    ct_DisableExchangeDifferenceInterest=trans_json.get("ct_DisableExchangeDifferenceInterest"),
                    ct_soh_bra_id=trans_json.get("ct_soh_bra_id"),
                    ct_soh_id=trans_json.get("ct_soh_id"),
                    ct_transaction_PackingList=trans_json.get("ct_transaction_PackingList"),
                    ws_cust_Id=trans_json.get("ws_cust_Id"),
                    ws_internalID=trans_json.get("ws_internalID"),
                    ws_isLiquidated=trans_json.get("ws_isLiquidated"),
                    ws_isLiquidatedCD=trans_json.get("ws_isLiquidatedCD"),
                    ws_is4Liquidation=trans_json.get("ws_is4Liquidation"),
                    ws_LiquidationNumber=trans_json.get("ws_LiquidationNumber"),
                    ws_st_id=trans_json.get("ws_st_id"),
                    ws_dl_id=trans_json.get("ws_dl_id"),
                    ct_CAI=trans_json.get("ct_CAI"),
                    ct_CAIDate=parse_date(trans_json.get("ct_CAIDate")),
                    ct_FEIdNumber=trans_json.get("ct_FEIdNumber"),
                    ct_Discount1=trans_json.get("ct_Discount1"),
                    ct_Discount2=trans_json.get("ct_Discount2"),
                    ct_Discount3=trans_json.get("ct_Discount3"),
                    ct_Discount4=trans_json.get("ct_Discount4"),
                    ct_discountPlanCoeficient=trans_json.get("ct_discountPlanCoeficient"),
                    ct_packagesQty=trans_json.get("ct_packagesQty"),
                    ct_TransactionBarCode=trans_json.get("ct_TransactionBarCode"),
                    ct_CreditIntPercentage=trans_json.get("ct_CreditIntPercentage"),
                    ct_CreditIntPlusPercentage=trans_json.get("ct_CreditIntPlusPercentage"),
                    ctl_daysPastDue=trans_json.get("ctl_daysPastDue"),
                    ccp_id=trans_json.get("ccp_id"),
                    sctt_id=trans_json.get("sctt_id"),
                    suppa_id=trans_json.get("suppa_id"),
                    pt_id=trans_json.get("pt_id"),
                    fc_id=trans_json.get("fc_id"),
                    pro_id=trans_json.get("pro_id"),
                    supp_id4CreditCardLiquidation=trans_json.get("supp_id4CreditCardLiquidation"),
                    def_id=trans_json.get("def_id"),
                    mlo_id=trans_json.get("mlo_id"),
                    dc_id=trans_json.get("dc_id"),
                    ct_AllUseTag1=trans_json.get("ct_AllUseTag1"),
                    ct_AllUseTag2=trans_json.get("ct_AllUseTag2"),
                    ct_AllUseTag3=trans_json.get("ct_AllUseTag3"),
                    ct_AllUseTag4=trans_json.get("ct_AllUseTag4"),
                    ct_guid=guid_value,
                    ct_transaction4ThirdSales=trans_json.get("ct_transaction4ThirdSales"),
                    ct_documentNumber=trans_json.get("ct_documentNumber"),
                    ct_note=trans_json.get("ct_note")
                )

                db.add(trans)
                transacciones_insertadas += 1

                # Commit cada 50 transacciones
                if transacciones_insertadas % 50 == 0:
                    db.commit()
                    print(f"   ✓ {transacciones_insertadas} transacciones insertadas...")

            except Exception as e:
                print(f"   ⚠️  Error procesando transacción {trans_json.get('ct_transaction')}: {str(e)}")
                transacciones_errores += 1
                db.rollback()
                continue

        # Commit final
        db.commit()

        # Obtener nuevo máximo
        nuevo_max = db.query(func.max(CommercialTransaction.ct_transaction)).scalar()

        print(f"\n✅ Sincronización completada!")
        print(f"   Insertadas: {transacciones_insertadas}")
        print(f"   Errores: {transacciones_errores}")
        print(f"   Nuevo ct_transaction máximo: {nuevo_max}")

        return transacciones_insertadas, 0, transacciones_errores

    except httpx.HTTPError as e:
        print(f"❌ Error al consultar API externa: {str(e)}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"❌ Error en sincronización: {str(e)}")
        return 0, 0, 0


async def main():
    """
    Sincronización incremental de transacciones comerciales
    """
    print("🚀 Sincronización incremental de transacciones comerciales")
    print("=" * 60)

    db = SessionLocal()

    try:
        insertadas, actualizadas, errores = await sync_transacciones_incrementales(db)

        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
