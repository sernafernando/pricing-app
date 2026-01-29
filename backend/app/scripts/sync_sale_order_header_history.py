"""
Script para sincronizar historial de cabecera de órdenes de venta desde el ERP
Tabla: tbSaleOrderHeaderHistory

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_sale_order_header_history
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
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.sale_order_header_history import SaleOrderHeaderHistory


def fetch_sale_order_header_history_from_erp(from_date: date = None, to_date: date = None):
    """Obtiene historial de cabecera de órdenes de venta desde el ERP vía GBP Worker"""
    url = "http://localhost:8002/api/gbp-parser"

    # Por defecto, últimos 6 meses
    if not from_date:
        from_date = date.today() - timedelta(days=180)
    if not to_date:
        to_date = date.today()

    params = {
        'strScriptLabel': 'scriptSaleOrderHeaderHistory',
        'updateFromDate': from_date.isoformat(),
        'updateToDate': to_date.isoformat()
    }

    print(f"📥 Descargando historial de órdenes desde {from_date} hasta {to_date}...")

    try:
        response = requests.get(url, params=params, timeout=300)
        response.raise_for_status()
        data = response.json()

        print(f"  ✓ Obtenidos {len(data)} registros")
        return data

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error consultando ERP: {e}")
        return []


def sync_sale_order_header_history(db: Session, data: list):
    """Sincroniza el historial de órdenes en la base de datos local"""

    if not data:
        print("  ⚠️  No hay datos para sincronizar")
        return 0, 0, 0

    print(f"\n💾 Sincronizando {len(data)} registros...")

    insertados = 0
    actualizados = 0
    errores = 0

    for record in data:
        try:
            comp_id = record.get('comp_id')
            bra_id = record.get('bra_id')
            soh_id = record.get('soh_id')
            sohh_id = record.get('sohh_id')
            
            # SKIP registros con sohh_id NULL (datos inválidos del ERP)
            if sohh_id is None:
                errores += 1
                continue

            # Buscar registro existente por clave compuesta
            existente = db.query(SaleOrderHeaderHistory).filter(
                and_(
                    SaleOrderHeaderHistory.comp_id == comp_id,
                    SaleOrderHeaderHistory.bra_id == bra_id,
                    SaleOrderHeaderHistory.soh_id == soh_id,
                    SaleOrderHeaderHistory.sohh_id == sohh_id
                )
            ).first()

            # Función helper para convertir fechas
            def parse_datetime(value):
                if not value:
                    return None
                try:
                    return datetime.fromisoformat(value.replace('T', ' '))
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
                'comp_id': comp_id,
                'bra_id': bra_id,
                'soh_id': soh_id,
                'sohh_id': sohh_id,
                'sohh_typeofhistory': record.get('sohh_TypeOfHistory'),
                'soh_cd': parse_datetime(record.get('soh_cd')),
                'soh_deliverydate': parse_datetime(record.get('soh_deliveryDate')),
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
                'soh_lastupdate': parse_datetime(record.get('soh_lastUpdate')),
                'soh_limitdate': parse_datetime(record.get('soh_limitDate')),
                'tt_id': record.get('tt_id'),
                'tt_class': record.get('tt_class'),
                'soh_statusof': record.get('soh_StatusOf'),
                'user_id': record.get('user_id'),
                'soh_isediting': record.get('soh_isEditing'),
                'soh_iseditingcd': parse_datetime(record.get('soh_isEditingCd')),
                'df_id': record.get('df_id'),
                'soh_total': parse_numeric(record.get('soh_total')),
                'ssos_id': record.get('ssos_id'),
                'soh_exchangetocustomercurrency': parse_numeric(record.get('soh_ExchangeToCustomerCurrency')),
                'soh_customercurrency': record.get('soh_CustomerCurrency'),
                'soh_discount': parse_numeric(record.get('soh_discount')),
                'soh_packagesqty': record.get('soh_packagesQty'),
                'soh_internalannotation': record.get('soh_internalAnnotation'),
                'curr_id4exchange': record.get('curr_id4Exchange'),
                'curr_idexchange': parse_numeric(record.get('curr_idExchange')),
                'soh_atotal': parse_numeric(record.get('soh_ATotal')),
                'soh_incash': parse_numeric(record.get('soh_inCash')),
                'ct_transaction': record.get('ct_transaction'),
                'sohh_cd': parse_datetime(record.get('sohh_cd')),
                'sohh_user_id': record.get('sohh_user_id'),
                'soh_mlquestionsandanswers': record.get('soh_MLQuestionsAndAnswers'),
                'soh_mlid': record.get('soh_MLId'),
                'soh_mlguia': record.get('soh_MLGUIA'),
                'ws_paymentgatewaystatusid': record.get('ws_paymentGateWayStatusID'),
                'soh_deliveryaddress': record.get('soh_deliveryAddress'),
                'stor_id': record.get('stor_id'),
                'mlo_id': record.get('mlo_id'),
                'soh_note4externaluse': record.get('soh_note4ExternalUse'),
                'sohh_ispackingofpreinvoice': record.get('sohh_isPackingOfPreInvoice'),
                'soh_uniqueid': record.get('soh_uniqueID')
            }

            if existente:
                # Actualizar
                for key, value in data_record.items():
                    setattr(existente, key, value)
                actualizados += 1
            else:
                # Insertar nuevo
                nuevo = SaleOrderHeaderHistory(**data_record)
                db.add(nuevo)
                insertados += 1

            # Commit cada 500 registros
            if (insertados + actualizados) % 500 == 0:
                db.commit()
                print(f"  📊 Progreso: {insertados + actualizados}/{len(data)}")

        except Exception as e:
            errores += 1
            print(f"  ⚠️  Error en registro (comp_id={record.get('comp_id')}, bra_id={record.get('bra_id')}, soh_id={record.get('soh_id')}, sohh_id={record.get('sohh_id')}): {str(e)}")
            db.rollback()  # Rollback para poder continuar con los demás
            continue

    # Commit final
    db.commit()

    return insertados, actualizados, errores


def main():
    print("=" * 60)
    print("SINCRONIZACIÓN DE SALE ORDER HEADER HISTORY")
    print("=" * 60)

    db = SessionLocal()

    try:
        # 1. Obtener datos del ERP (últimos 6 meses por defecto)
        data = fetch_sale_order_header_history_from_erp()

        # 2. Sincronizar en PostgreSQL
        insertados, actualizados, errores = sync_sale_order_header_history(db, data)

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
