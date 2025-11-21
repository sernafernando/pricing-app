"""
Script para sincronizar cabecera de órdenes de venta desde el ERP
Tabla: tbSaleOrderHeader

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_sale_order_header
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Cargar .env
from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

import requests
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.sale_order_header import SaleOrderHeader


def fetch_sale_order_header_from_erp(from_date: date = None, to_date: date = None):
    """Obtiene cabecera de órdenes de venta desde el ERP vía GBP Worker"""
    url = "http://localhost:8002/api/gbp-parser"

    # Por defecto, últimos 6 meses
    if not from_date:
        from_date = date.today() - timedelta(days=180)
    if not to_date:
        to_date = date.today()

    params = {
        'strScriptLabel': 'scriptSaleOrderHeader',
        'fromDate': from_date.isoformat(),
        'toDate': to_date.isoformat()
    }

    print(f"📥 Descargando órdenes de venta desde {from_date} hasta {to_date}...")

    try:
        response = requests.get(url, params=params, timeout=300)
        response.raise_for_status()
        data = response.json()

        print(f"  ✓ Obtenidos {len(data)} registros")
        return data

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error consultando ERP: {e}")
        return []


def sync_sale_order_header(db: Session, data: list):
    """Sincroniza las órdenes de venta en la base de datos local"""

    if not data:
        print("  ⚠️  No hay datos para sincronizar")
        return 0, 0, 0

    print(f"\n💾 Sincronizando {len(data)} registros...")

    insertados = 0
    actualizados = 0
    errores = 0

    for record in data:
        try:
            soh_id = record.get('soh_id')

            # Buscar registro existente
            existente = db.query(SaleOrderHeader).filter(
                SaleOrderHeader.soh_id == soh_id
            ).first()

            # Función helper para convertir fechas
            def parse_datetime(value):
                if not value:
                    return None
                try:
                    return datetime.fromisoformat(value.replace('T', ' '))
                except:
                    return None

            # Preparar datos
            data_record = {
                'soh_id': soh_id,
                'comp_id': record.get('comp_id'),
                'bra_id': record.get('bra_id'),
                'soh_cd': parse_datetime(record.get('soh_cd')),
                'soh_deliveryDate': parse_datetime(record.get('soh_deliveryDate')),
                'soh_observation1': record.get('soh_observation1'),
                'soh_observation2': record.get('soh_observation2'),
                'soh_observation3': record.get('soh_observation3'),
                'soh_observation4': record.get('soh_observation4'),
                'soh_quotation': record.get('soh_quotation'),
                'sm_id': record.get('sm_id'),
                'cust_id': record.get('cust_id'),
                'st_id': record.get('st_id'),
                'disc_id': record.get('disc_id'),
                'dl_id': record.get('dl_id'),
                'cb_id': record.get('cb_id'),
                'soh_lastUpdate': parse_datetime(record.get('soh_lastUpdate')),
                'soh_limitDate': parse_datetime(record.get('soh_limitDate')),
                'tt_id': record.get('tt_id'),
                'tt_class': record.get('tt_class'),
                'soh_StatusOf': record.get('soh_StatusOf'),
                'user_id': record.get('user_id'),
                'soh_isEditing': record.get('soh_isEditing'),
                'soh_isEditingCd': parse_datetime(record.get('soh_isEditingCd')),
                'df_id': record.get('df_id'),
                'soh_total': record.get('soh_total'),
                'ssos_id': record.get('ssos_id'),
                'soh_ExchangeToCustomerCurrency': record.get('soh_ExchangeToCustomerCurrency'),
                'chp_id': record.get('chp_id'),
                'soh_PL_df_Id': record.get('soh_PL_df_Id'),
                'soh_CustomerCurrency': record.get('soh_CustomerCurrency'),
                'soh_WithCollection': record.get('soh_WithCollection'),
                'soh_WithCollectionGUID': record.get('soh_WithCollectionGUID'),
                'soh_discount': record.get('soh_discount'),
                'soh_loan': record.get('soh_loan'),
                'soh_packagesQty': record.get('soh_packagesQty'),
                'soh_internalAnnotation': record.get('soh_internalAnnotation'),
                'curr_id4Exchange': record.get('curr_id4Exchange'),
                'curr_idExchange': record.get('curr_idExchange'),
                'soh_ATotal': record.get('soh_ATotal'),
                'df_id4PL': record.get('df_id4PL'),
                'somp_id': record.get('somp_id'),
                'soh_FEIdNumber': record.get('soh_FEIdNumber'),
                'soh_inCash': record.get('soh_inCash'),
                'custf_id': record.get('custf_id'),
                'cust_id_guarantor': record.get('cust_id_guarantor'),
                'ccp_id': record.get('ccp_id'),
                'soh_MLdeliveryLabel': record.get('soh_MLdeliveryLabel'),
                'soh_deliveryAddress': record.get('soh_deliveryAddress'),
                'soh_MLQuestionsAndAnswers': record.get('soh_MLQuestionsAndAnswers'),
                'aux_3RDSales_lastCTTransaction': record.get('aux_3RDSales_lastCTTransaction'),
                'soh_MLId': record.get('soh_MLId'),
                'soh_MLGUIA': record.get('soh_MLGUIA'),
                'pro_id': record.get('pro_id'),
                'aux_collectionInterest_lastCTTransaction': record.get('aux_collectionInterest_lastCTTransaction'),
                'ws_cust_Id': record.get('ws_cust_Id'),
                'ws_internalID': record.get('ws_internalID'),
                'ws_paymentGateWayStatusID': record.get('ws_paymentGateWayStatusID'),
                'ws_paymentGateWayReferenceID': record.get('ws_paymentGateWayReferenceID'),
                'ws_IPFrom': record.get('ws_IPFrom'),
                'ws_st_id': record.get('ws_st_id'),
                'ws_dl_id': record.get('ws_dl_id'),
                'soh_htmlNote': record.get('soh_htmlNote'),
                'prli_id': record.get('prli_id'),
                'stor_id': record.get('stor_id'),
                'mlo_id': record.get('mlo_id'),
                'MLShippingID': record.get('MLShippingID'),
                'soh_exchange2Currency4Total': record.get('soh_exchange2Currency4Total'),
                'soh_Currency4Total': record.get('soh_Currency4Total'),
                'soh_uniqueID': record.get('soh_uniqueID'),
                'soh_note4ExternalUse': record.get('soh_note4ExternalUse'),
                'soh_autoprocessLastOrder': record.get('soh_autoprocessLastOrder'),
                'dc_id': record.get('dc_id'),
                'soh_isPrintedFromSOPreparation': record.get('soh_isPrintedFromSOPreparation'),
                'soh_persistExchange': record.get('soh_persistExchange'),
                'ct_transaction_preCollection': record.get('ct_transaction_preCollection'),
                'soh_iseMailEnvied': record.get('soh_iseMailEnvied'),
                'soh_deliveryLabel': record.get('soh_deliveryLabel'),
                'ct_transaction_preInvoice': record.get('ct_transaction_preInvoice')
            }

            if existente:
                # Actualizar
                for key, value in data_record.items():
                    if key != 'soh_id':  # No actualizar PK
                        setattr(existente, key, value)
                actualizados += 1
            else:
                # Insertar nuevo
                nuevo = SaleOrderHeader(**data_record)
                db.add(nuevo)
                insertados += 1

            # Commit cada 500 registros
            if (insertados + actualizados) % 500 == 0:
                db.commit()
                print(f"  📊 Progreso: {insertados + actualizados}/{len(data)}")

        except Exception as e:
            errores += 1
            print(f"  ⚠️  Error en registro {record.get('soh_id')}: {str(e)}")
            db.rollback()  # Rollback para poder continuar con los demás
            continue

    # Commit final
    db.commit()

    return insertados, actualizados, errores


def main():
    print("=" * 60)
    print("SINCRONIZACIÓN DE SALE ORDER HEADER")
    print("=" * 60)

    db = SessionLocal()

    try:
        # 1. Obtener datos del ERP (últimos 6 meses por defecto)
        data = fetch_sale_order_header_from_erp()

        # 2. Sincronizar en PostgreSQL
        insertados, actualizados, errores = sync_sale_order_header(db, data)

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
