"""
Script para agregar métricas de ventas ML - INCREMENTAL
Actualiza solo los últimos 10 MINUTOS de métricas cada vez que se ejecuta
Diseñado para correr cada 5 minutos en cron

Ejecutar:
    python app/scripts/agregar_metricas_ml_incremental.py
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import pymssql
import os
from datetime import datetime, date, timedelta
from decimal import Decimal
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.utils.ml_metrics_calculator import calcular_metricas_ml

# Load environment variables from .env file in backend directory
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

# SQL Server connection
SQL_SERVER_HOST = os.getenv("SQL_SERVER_HOST")
SQL_SERVER_DB = os.getenv("SQL_SERVER_DB")
SQL_SERVER_USER = os.getenv("SQL_SERVER_USER")
SQL_SERVER_PASSWORD = os.getenv("SQL_SERVER_PASSWORD")


def get_sql_server_connection():
    """Conectar a SQL Server"""
    return pymssql.connect(
        server=SQL_SERVER_HOST,
        database=SQL_SERVER_DB,
        user=SQL_SERVER_USER,
        password=SQL_SERVER_PASSWORD,
        timeout=120
    )


def fetch_data_from_sql_server(from_datetime: datetime, to_datetime: datetime) -> pd.DataFrame:
    """Ejecuta el query de scriptDashboard en SQL Server"""
    print(f"🔍 Consultando SQL Server (últimos 10 minutos)...")
    print(f"   Rango: {from_datetime} a {to_datetime}")

    conn = get_sql_server_connection()
    cursor = conn.cursor()

    # Query completo de scriptDashboard
    query = """
        SELECT DISTINCT
            tmlod.mlo_id [ID_de_Operación],
            tmlod.item_id [item_id],
            tct.ct_transaction [ct_transaction],
            tmloh.mlo_cd [Fecha],
            tb.brand_desc [Marca],
            tc.cat_desc [Categoría],
            tsc.subcat_desc [SubCategoría],
            ti.item_code [Código_Item],
            UPPER(ti.item_desc) [Descripción],
            tmlod.mlo_quantity [Cantidad],
            tmlod.mlo_unit_price [Monto_Unitario],
            tmlod.mlo_unit_price * tmlod.mlo_quantity [Monto_Total],
            (SELECT TOP 1 ticlh.iclh_price
             FROM tbItemCostListHistory ticlh
             WHERE ticlh.item_id = tmlod.item_id
               AND ticlh.iclh_cd <= tmloh.mlo_cd
             ORDER BY ticlh.iclh_id DESC) [Costo_sin_IVA],
            ttn.tax_percentage [IVA],
            tmlip.mlp_id [ML_id],
            tmloh.ml_pack_id [ML_pack_id],
            tmlip.mlp_price4FreeShipping [mlp_price4FreeShipping],
            tmlos.mlshippmentcost4seller [Costo_Envío],
            tmlos.mllogistic_type [ML_logistic_type],
            tmlos.mlshippment_id [MLShippingID],
            tmlod.mlo_sale_fee_amount [Comisión_en_pesos],
            tmlip.prli_id [priceList],
            ti.cat_id [cat_id],
            ti.subcat_id [subcat_id],
            'ARS' [Moneda_Costo],
            (SELECT TOP 1 ttc.tc_exchangeRate
             FROM tbTypeCurrency ttc
             WHERE ttc.curr_id = 2
               AND ttc.tc_date <= tmloh.mlo_cd
             ORDER BY ttc.tc_date DESC) [Cambio_al_Momento]
        FROM tbMercadoLibre_ordersDetail tmlod
        LEFT JOIN tbMercadoLibre_ordersHeader tmloh
            ON tmloh.comp_id = tmlod.comp_id AND tmloh.mlo_id = tmlod.mlo_id
        LEFT JOIN tbItem ti
            ON ti.comp_id = tmlod.comp_id AND ti.item_id = tmlod.item_id
        LEFT JOIN tbMercadoLibre_ItemsPublicados tmlip
            ON tmlip.comp_id = tmlod.comp_id AND tmlip.mlp_id = tmlod.mlp_id
        LEFT JOIN tbMercadoLibre_ordersShipping tmlos
            ON tmlos.comp_id = tmlod.comp_id AND tmlos.mlo_id = tmlod.mlo_id
        LEFT JOIN tbCommercialTransactions tct
            ON tct.comp_id = tmlod.comp_id AND tct.mlo_id = tmlod.mlo_id
        LEFT JOIN tbCategory tc
            ON tc.comp_id = ti.comp_id AND tc.cat_id = ti.cat_id
        LEFT JOIN tbSubCategory tsc
            ON tsc.comp_id = ti.comp_id AND tsc.cat_id = ti.cat_id AND tsc.subcat_id = ti.subcat_id
        LEFT JOIN tbBrand tb
            ON tb.comp_id = ti.comp_id AND tb.brand_id = ti.brand_id
        LEFT JOIN tbItemTaxes tit
            ON tmlod.comp_id = tit.comp_id AND tmlod.item_id = tit.item_id
        INNER JOIN tbTaxName ttn
            ON ttn.comp_id = ti.comp_id AND ttn.tax_id = tit.tax_id
        LEFT JOIN tbItemCostList ticl
            ON ticl.comp_id = tmlod.comp_id AND ticl.item_id = tmlod.item_id
        WHERE tmlod.item_id <> 460
            AND tmloh.mlo_cd BETWEEN ? AND ?
            AND tmloh.mlo_status <> 'cancelled'
            AND ticl.coslis_id = 1
            AND tmlod.item_id NOT IN (3042)
    """

    cursor.execute(query, (from_datetime, to_datetime))

    # Obtener nombres de columnas
    columns = [column[0] for column in cursor.description]

    # Convertir a lista de diccionarios
    rows = []
    for row in cursor:
        rows.append(dict(zip(columns, row)))

    cursor.close()
    conn.close()

    df = pd.DataFrame(rows)
    print(f"   ✓ Obtenidos {len(df)} registros")

    return df


def process_and_insert(db: Session, df: pd.DataFrame, min_free: float = 33000):
    """Procesa el DataFrame y lo inserta/actualiza en ml_ventas_metricas"""

    if df.empty:
        print("  ⚠️  DataFrame vacío, nada que procesar")
        return

    print(f"📊 Procesando {len(df)} registros...")

    # Calcular contar_si (items por MLShippingID / pack)
    df['contar_si'] = df.groupby('MLShippingID')['MLShippingID'].transform('count')

    total_insertados = 0
    total_actualizados = 0
    total_errores = 0

    for idx, row in df.iterrows():
        try:
            # Verificar si ya existe
            existente = db.query(MLVentaMetrica).filter(
                MLVentaMetrica.id_operacion == row['ID_de_Operación']
            ).first()

            # Extraer datos
            fecha_venta = pd.to_datetime(row['Fecha'])
            cantidad = int(row.get('Cantidad', 1))
            monto_unitario = float(row.get('Monto_Unitario', 0))
            monto_total = float(row.get('Monto_Total', 0))

            # Costo
            costo_sin_iva = float(row.get('Costo_sin_IVA', 0)) if pd.notna(row.get('Costo_sin_IVA')) else 0.0
            costo_total_sin_iva = costo_sin_iva * cantidad
            moneda_costo = row.get('Moneda_Costo', 'ARS')

            # Costo de envío
            costo_envio_ml = float(row.get('Costo_Envío', 0)) if pd.notna(row.get('Costo_Envío')) else 0.0

            # Tipo de logística
            tipo_logistica = row.get('ML_logistic_type', 'unknown')

            # IVA
            iva_percentage = float(row.get('IVA', 21)) if pd.notna(row.get('IVA')) else 21.0
            iva_multiplier = 1 + (iva_percentage / 100)

            # Datos para calcular comisión dinámicamente
            subcat_id = int(row.get('subcat_id')) if pd.notna(row.get('subcat_id')) else None
            pricelist_id = int(row.get('priceList')) if pd.notna(row.get('priceList')) else None
            comision_base_porcentaje = float(row.get('Comisión_base_%', 15.5)) if pd.notna(row.get('Comisión_base_%')) else 15.5

            # Usar helper centralizado para calcular métricas
            contar_si = row.get('contar_si', 1)
            metricas = calcular_metricas_ml(
                monto_unitario=monto_unitario,
                cantidad=cantidad,
                iva_porcentaje=iva_percentage,
                costo_unitario_sin_iva=costo_sin_iva,
                costo_envio_ml=costo_envio_ml if pd.notna(row.get('MLShippingID')) else None,
                count_per_pack=contar_si,
                # Calcular comisión dinámicamente
                subcat_id=subcat_id,
                pricelist_id=pricelist_id,
                fecha_venta=fecha_venta,
                comision_base_porcentaje=comision_base_porcentaje,
                db_session=db
            )

            monto_limpio = metricas['monto_limpio']
            ganancia = metricas['ganancia']
            markup_porcentaje = metricas['markup_porcentaje']
            costo_envio_prorrateado = metricas['costo_envio']
            comision_ml = metricas['comision_ml']  # Comisión calculada por el helper
            monto_total_sin_iva = monto_total / iva_multiplier

            # Porcentaje de comisión
            porcentaje_comision_ml = (comision_ml / monto_total_sin_iva * 100) if monto_total_sin_iva > 0 else 0.0

            # Cotización dólar
            cotizacion_dolar = float(row.get('Cambio_al_Momento', 0)) if pd.notna(row.get('Cambio_al_Momento')) else 0.0

            if existente:
                # Actualizar
                existente.ml_order_id = row.get('ML_id')
                existente.pack_id = int(row.get('ML_pack_id')) if pd.notna(row.get('ML_pack_id')) and str(row.get('ML_pack_id')).replace('.','').isdigit() else None
                existente.item_id = int(row.get('item_id')) if pd.notna(row.get('item_id')) else None
                existente.codigo = row.get('Código_Item')
                existente.descripcion = row.get('Descripción')
                existente.marca = row.get('Marca')
                existente.categoria = row.get('Categoría')
                existente.subcategoria = row.get('SubCategoría')
                existente.fecha_venta = fecha_venta
                existente.fecha_calculo = date.today()
                existente.cantidad = cantidad
                existente.monto_unitario = Decimal(str(round(monto_unitario, 2)))
                existente.monto_total = Decimal(str(round(monto_total, 2)))
                existente.cotizacion_dolar = Decimal(str(round(cotizacion_dolar, 4)))
                existente.costo_unitario_sin_iva = Decimal(str(round(costo_sin_iva, 6)))
                existente.costo_total_sin_iva = Decimal(str(round(costo_total_sin_iva, 2)))
                existente.moneda_costo = moneda_costo
                existente.tipo_lista = row.get('priceList')
                existente.porcentaje_comision_ml = Decimal(str(round(porcentaje_comision_ml, 2)))
                existente.comision_ml = Decimal(str(round(comision_ml, 2)))
                existente.costo_envio_ml = Decimal(str(round(costo_envio_ml, 2)))
                existente.tipo_logistica = tipo_logistica
                existente.monto_limpio = Decimal(str(round(monto_limpio, 2)))
                existente.costo_total = Decimal(str(round(costo_total_sin_iva, 2)))
                existente.ganancia = Decimal(str(round(ganancia, 2)))
                existente.markup_porcentaje = Decimal(str(round(markup_porcentaje, 2)))
                existente.prli_id = int(row.get('priceList')) if pd.notna(row.get('priceList')) else None
                existente.mla_id = row.get('ML_id')

                total_actualizados += 1
            else:
                # Crear nuevo
                metrica = MLVentaMetrica(
                    id_operacion=row['ID_de_Operación'],
                    ml_order_id=row.get('ML_id'),
                    pack_id=int(row.get('ML_pack_id')) if pd.notna(row.get('ML_pack_id')) and str(row.get('ML_pack_id')).replace('.','').isdigit() else None,
                    item_id=int(row.get('item_id')) if pd.notna(row.get('item_id')) else None,
                    codigo=row.get('Código_Item'),
                    descripcion=row.get('Descripción'),
                    marca=row.get('Marca'),
                    categoria=row.get('Categoría'),
                    subcategoria=row.get('SubCategoría'),
                    fecha_venta=fecha_venta,
                    fecha_calculo=date.today(),
                    cantidad=cantidad,
                    monto_unitario=Decimal(str(round(monto_unitario, 2))),
                    monto_total=Decimal(str(round(monto_total, 2))),
                    cotizacion_dolar=Decimal(str(round(cotizacion_dolar, 4))),
                    costo_unitario_sin_iva=Decimal(str(round(costo_sin_iva, 6))),
                    costo_total_sin_iva=Decimal(str(round(costo_total_sin_iva, 2))),
                    moneda_costo=moneda_costo,
                    tipo_lista=row.get('priceList'),
                    porcentaje_comision_ml=Decimal(str(round(porcentaje_comision_ml, 2))),
                    comision_ml=Decimal(str(round(comision_ml, 2))),
                    costo_envio_ml=Decimal(str(round(costo_envio_ml, 2))),
                    tipo_logistica=tipo_logistica,
                    monto_limpio=Decimal(str(round(monto_limpio, 2))),
                    costo_total=Decimal(str(round(costo_total_sin_iva, 2))),
                    ganancia=Decimal(str(round(ganancia, 2))),
                    markup_porcentaje=Decimal(str(round(markup_porcentaje, 2))),
                    prli_id=int(row.get('priceList')) if pd.notna(row.get('priceList')) else None,
                    mla_id=row.get('ML_id')
                )
                db.add(metrica)
                total_insertados += 1

            # Commit cada 50 registros (más frecuente para script incremental)
            if (total_insertados + total_actualizados) % 50 == 0:
                db.commit()

        except Exception as e:
            print(f"  ❌ Error procesando registro {idx}: {str(e)}")
            total_errores += 1
            continue

    # Commit final
    try:
        db.commit()
    except Exception as e:
        print(f"  ❌ Error en commit final: {str(e)}")
        db.rollback()

    print(f"✅ Completado - Nuevos: {total_insertados} | Actualizados: {total_actualizados} | Errores: {total_errores}")


def main():
    # Calcular rango de últimos 10 minutos
    to_datetime = datetime.now()
    from_datetime = to_datetime - timedelta(minutes=10)

    print(f"{'='*60}")
    print(f"MÉTRICAS ML INCREMENTAL - Últimos 10 minutos")
    print(f"{'='*60}")
    print(f"Ejecutado: {to_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Rango: {from_datetime.strftime('%H:%M:%S')} a {to_datetime.strftime('%H:%M:%S')}")
    print()

    # Fetch data from SQL Server
    df = fetch_data_from_sql_server(from_datetime, to_datetime)

    if df.empty:
        print("No hay datos para procesar")
        return

    # Process and insert
    db = SessionLocal()
    try:
        process_and_insert(db, df)
    finally:
        db.close()


if __name__ == "__main__":
    main()
