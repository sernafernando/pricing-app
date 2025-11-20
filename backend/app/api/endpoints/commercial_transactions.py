from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timedelta
import httpx
from app.core.database import get_db
from app.models.commercial_transaction import CommercialTransaction
from app.api.deps import get_current_user
from pydantic import BaseModel
from decimal import Decimal
import uuid

router = APIRouter()

# Schemas
class CommercialTransactionResponse(BaseModel):
    ct_transaction: int
    ct_kindOf: Optional[str]
    ct_docNumber: Optional[str]
    ct_date: Optional[datetime]
    cust_id: Optional[int]
    ct_total: Optional[Decimal]
    ct_subtotal: Optional[Decimal]
    ct_guid: Optional[str]

    class Config:
        from_attributes = True


class SyncCommercialTransactionsRequest(BaseModel):
    from_date: str  # YYYY-MM-DD
    to_date: str    # YYYY-MM-DD


# Endpoints

@router.post("/commercial-transactions/sync")
async def sync_commercial_transactions(
    request: SyncCommercialTransactionsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Sincroniza transacciones comerciales desde el endpoint externo del ERP
    """
    try:
        # Llamar al endpoint externo
        url = "http://localhost:8002/api/gbp-parser"
        params = {
            "strScriptLabel": "scriptCommercial",
            "fromDate": request.from_date,
            "toDate": request.to_date
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            transactions_data = response.json()

        if not isinstance(transactions_data, list):
            raise HTTPException(status_code=500, detail="Respuesta inválida del endpoint externo")

        # Verificar si hay datos
        if len(transactions_data) == 1 and "Column1" in transactions_data[0]:
            return {
                "success": True,
                "message": "No hay datos disponibles para este período",
                "transacciones_insertadas": 0,
                "transacciones_actualizadas": 0,
                "transacciones_errores": 0
            }

        # Insertar o actualizar transacciones
        transacciones_insertadas = 0
        transacciones_actualizadas = 0
        transacciones_errores = 0

        for trans_json in transactions_data:
            try:
                ct_transaction = trans_json.get("ct_transaction")
                if ct_transaction is None:
                    transacciones_errores += 1
                    continue

                # Verificar si ya existe
                trans_existente = db.query(CommercialTransaction).filter(
                    CommercialTransaction.ct_transaction == ct_transaction
                ).first()

                # Procesar el GUID
                guid_str = trans_json.get("ct_guid")
                guid_value = None
                if guid_str:
                    try:
                        guid_value = uuid.UUID(guid_str)
                    except:
                        pass

                # Procesar fechas
                def parse_date(date_str):
                    if not date_str:
                        return None
                    try:
                        if isinstance(date_str, str):
                            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        return date_str
                    except:
                        return None

                if trans_existente:
                    # Actualizar transacción existente
                    for key, value in trans_json.items():
                        if hasattr(trans_existente, key):
                            # Manejar fechas
                            if 'date' in key.lower() or 'Date' in key:
                                value = parse_date(value)
                            # Manejar GUID
                            elif key == 'ct_guid' and value:
                                value = guid_value
                            setattr(trans_existente, key, value)

                    transacciones_actualizadas += 1
                else:
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

                # Commit cada 100 transacciones
                if (transacciones_insertadas + transacciones_actualizadas) % 100 == 0:
                    db.commit()

            except Exception as e:
                print(f"Error procesando transacción {trans_json.get('ct_transaction')}: {str(e)}")
                transacciones_errores += 1
                continue

        # Commit final
        db.commit()

        return {
            "success": True,
            "message": f"Sincronización completada",
            "transacciones_insertadas": transacciones_insertadas,
            "transacciones_actualizadas": transacciones_actualizadas,
            "transacciones_errores": transacciones_errores,
            "total_procesadas": len(transactions_data)
        }

    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar API externa: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error en sincronización: {str(e)}")


@router.get("/commercial-transactions", response_model=List[CommercialTransactionResponse])
async def get_commercial_transactions(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    ct_kindOf: Optional[str] = Query(None, description="Tipo de documento"),
    cust_id: Optional[int] = Query(None, description="ID de cliente"),
    limit: int = Query(1000, le=5000),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene transacciones comerciales con filtros
    """
    query = db.query(CommercialTransaction)

    if from_date:
        query = query.filter(CommercialTransaction.ct_date >= datetime.fromisoformat(from_date))

    if to_date:
        fecha_hasta = datetime.fromisoformat(to_date) + timedelta(days=1)
        query = query.filter(CommercialTransaction.ct_date < fecha_hasta)

    if ct_kindOf:
        query = query.filter(CommercialTransaction.ct_kindOf == ct_kindOf)

    if cust_id:
        query = query.filter(CommercialTransaction.cust_id == cust_id)

    transactions = query.order_by(desc(CommercialTransaction.ct_date)).limit(limit).offset(offset).all()

    return transactions


@router.get("/commercial-transactions/stats")
async def get_commercial_transactions_stats(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene estadísticas de transacciones comerciales
    """
    query = db.query(
        func.count(CommercialTransaction.ct_transaction).label('total_transacciones'),
        func.sum(CommercialTransaction.ct_total).label('monto_total'),
        func.count(func.distinct(CommercialTransaction.cust_id)).label('clientes_unicos')
    )

    if from_date:
        query = query.filter(CommercialTransaction.ct_date >= datetime.fromisoformat(from_date))

    if to_date:
        fecha_hasta = datetime.fromisoformat(to_date) + timedelta(days=1)
        query = query.filter(CommercialTransaction.ct_date < fecha_hasta)

    result = query.first()

    # Estadísticas por tipo de documento
    tipo_query = db.query(
        CommercialTransaction.ct_kindOf,
        func.count(CommercialTransaction.ct_transaction).label('cantidad'),
        func.sum(CommercialTransaction.ct_total).label('monto')
    )

    if from_date:
        tipo_query = tipo_query.filter(CommercialTransaction.ct_date >= datetime.fromisoformat(from_date))
    if to_date:
        tipo_query = tipo_query.filter(CommercialTransaction.ct_date < datetime.fromisoformat(to_date) + timedelta(days=1))

    por_tipo = tipo_query.group_by(CommercialTransaction.ct_kindOf).all()

    return {
        "total_transacciones": result.total_transacciones or 0,
        "monto_total": float(result.monto_total or 0),
        "clientes_unicos": result.clientes_unicos or 0,
        "por_tipo": {
            item.ct_kindOf: {
                "cantidad": item.cantidad,
                "monto": float(item.monto or 0)
            }
            for item in por_tipo if item.ct_kindOf
        }
    }
