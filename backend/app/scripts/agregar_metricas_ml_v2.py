"""
Script para agregar métricas de ventas ML - Versión 2
Usa el mismo endpoint que st_app para obtener los datos ya procesados
Inserta directamente en ml_ventas_metricas

Ejecutar:
    python app/scripts/agregar_metricas_ml_v2.py --from-date 2025-01-01 --to-date 2025-11-14
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import requests
import argparse
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from decimal import Decimal
import pandas as pd

from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.utils.ml_metrics_calculator import calcular_metricas_ml


def fetch_data_from_api(from_date: date, to_date: date) -> pd.DataFrame:
    """Obtiene datos del mismo endpoint que usa st_app"""
    url = f"http://localhost:8002/api/gbp-parser?strScriptLabel=scriptDashboard&fromDate={from_date}&toDate={to_date}"

    print(f"🌐 Consultando API: {url}")

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.json()

        df = pd.DataFrame(data)
        print(f"  ✓ Obtenidos {len(df)} registros desde la API")
        return df

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error consultando API: {e}")
        return pd.DataFrame()


def process_and_insert(db: Session, df: pd.DataFrame):
    """Procesa el DataFrame y lo inserta en ml_ventas_metricas"""

    if df.empty:
        print("  ⚠️  DataFrame vacío, nada que procesar")
        return

    print(f"\n📊 Procesando {len(df)} registros...")

    # Calcular contar_si (items por MLShippingID / pack)
    # Esto es equivalente a lo que hace st_app en línea 601
    df["contar_si"] = df.groupby("MLShippingID")["MLShippingID"].transform("count")

    total_insertados = 0
    total_actualizados = 0
    total_errores = 0

    for idx, row in df.iterrows():
        try:
            # Verificar si ya existe
            existente = (
                db.query(MLVentaMetrica).filter(MLVentaMetrica.id_operacion == row.get("ID_de_Operación")).first()
            )

            # Extraer datos
            fecha_venta = pd.to_datetime(row.get("Fecha"))
            cantidad = int(row.get("Cantidad", 1))
            monto_unitario = float(row.get("Monto_Unitario", 0))
            monto_total = float(row.get("Monto_Total", 0))

            # Costo
            costo_sin_iva = float(row.get("Costo_sin_IVA", 0)) if pd.notna(row.get("Costo_sin_IVA")) else 0.0
            costo_total_sin_iva = costo_sin_iva * cantidad
            moneda_costo = row.get("Moneda_Costo", "ARS")

            # Costo de envío
            costo_envio_ml = (
                float(row.get("mlp_price4FreeShipping", 0)) if pd.notna(row.get("mlp_price4FreeShipping")) else 0.0
            )

            # Tipo de logística
            tipo_logistica_raw = row.get("ML_logistic_type")
            if pd.isna(tipo_logistica_raw) or tipo_logistica_raw == "NaN":
                tipo_logistica = None
            else:
                tipo_logistica = str(tipo_logistica_raw) if tipo_logistica_raw else None

            # Datos para calcular comisión dinámicamente
            subcat_id = int(row.get("subcat_id")) if pd.notna(row.get("subcat_id")) else None
            pricelist_id = int(row.get("priceList")) if pd.notna(row.get("priceList")) else None
            comision_base_porcentaje = (
                float(row.get("Comisión_base_%", 15.5)) if pd.notna(row.get("Comisión_base_%")) else 15.5
            )

            # Usar helper centralizado para calcular métricas
            contar_si = row.get("contar_si", 1)
            metricas = calcular_metricas_ml(
                monto_unitario=monto_unitario,
                cantidad=cantidad,
                iva_porcentaje=21.0,  # IVA hardcoded a 21% en este script
                costo_unitario_sin_iva=costo_sin_iva,
                costo_envio_ml=costo_envio_ml if pd.notna(row.get("MLShippingID")) else None,
                count_per_pack=contar_si,
                # Calcular comisión dinámicamente
                subcat_id=subcat_id,
                pricelist_id=pricelist_id,
                fecha_venta=fecha_venta,
                comision_base_porcentaje=comision_base_porcentaje,
                db_session=db,
                ml_logistic_type=tipo_logistica,
            )

            monto_limpio = metricas["monto_limpio"]
            ganancia = metricas["ganancia"]
            markup_porcentaje = metricas["markup_porcentaje"]
            costo_envio_prorrateado = metricas["costo_envio"]
            comision_ml = metricas["comision_ml"]  # Comisión calculada por el helper
            monto_total_sin_iva = monto_total / 1.21

            # Porcentaje de comisión
            porcentaje_comision_ml = (comision_ml / monto_total_sin_iva * 100) if monto_total_sin_iva > 0 else 0.0

            # Cotización dólar
            cotizacion_dolar = float(row.get("Cambio_al_Momento", 0)) if pd.notna(row.get("Cambio_al_Momento")) else 0.0

            if existente:
                # Actualizar
                existente.ml_order_id = row.get("ML_id")
                existente.pack_id = (
                    int(row.get("ML_pack_id"))
                    if pd.notna(row.get("ML_pack_id")) and str(row.get("ML_pack_id")).isdigit()
                    else None
                )
                existente.item_id = int(row.get("item_id")) if pd.notna(row.get("item_id")) else None
                existente.codigo = row.get("Código_Item")
                existente.descripcion = row.get("Descripción")
                existente.marca = row.get("Marca")
                existente.categoria = row.get("Categoría")
                existente.subcategoria = row.get("SubCategoría")
                existente.fecha_venta = fecha_venta
                existente.fecha_calculo = date.today()
                existente.cantidad = cantidad
                existente.monto_unitario = Decimal(str(round(monto_unitario, 2)))
                existente.monto_total = Decimal(str(round(monto_total, 2)))
                existente.cotizacion_dolar = Decimal(str(round(cotizacion_dolar, 4)))
                existente.costo_unitario_sin_iva = Decimal(str(round(costo_sin_iva, 6)))
                existente.costo_total_sin_iva = Decimal(str(round(costo_total_sin_iva, 2)))
                existente.moneda_costo = moneda_costo
                existente.tipo_lista = row.get("priceList")
                existente.porcentaje_comision_ml = Decimal(str(round(porcentaje_comision_ml, 2)))
                existente.comision_ml = Decimal(str(round(comision_ml, 2)))
                existente.costo_envio_ml = Decimal(str(round(costo_envio_ml, 2)))
                existente.tipo_logistica = tipo_logistica
                existente.monto_limpio = Decimal(str(round(monto_limpio, 2)))
                existente.costo_total = Decimal(str(round(costo_total_sin_iva, 2)))
                existente.ganancia = Decimal(str(round(ganancia, 2)))
                existente.markup_porcentaje = Decimal(str(round(markup_porcentaje, 2)))
                existente.offset_flex = Decimal(str(round(metricas["offset_flex"], 2)))
                existente.prli_id = int(row.get("priceList")) if pd.notna(row.get("priceList")) else None
                existente.mla_id = row.get("ML_id")

                total_actualizados += 1
            else:
                # Crear nuevo
                metrica = MLVentaMetrica(
                    id_operacion=row.get("ID_de_Operación"),
                    ml_order_id=row.get("ML_id"),
                    pack_id=int(row.get("ML_pack_id"))
                    if pd.notna(row.get("ML_pack_id")) and str(row.get("ML_pack_id")).isdigit()
                    else None,
                    item_id=int(row.get("item_id")) if pd.notna(row.get("item_id")) else None,
                    codigo=row.get("Código_Item"),
                    descripcion=row.get("Descripción"),
                    marca=row.get("Marca"),
                    categoria=row.get("Categoría"),
                    subcategoria=row.get("SubCategoría"),
                    fecha_venta=fecha_venta,
                    fecha_calculo=date.today(),
                    cantidad=cantidad,
                    monto_unitario=Decimal(str(round(monto_unitario, 2))),
                    monto_total=Decimal(str(round(monto_total, 2))),
                    cotizacion_dolar=Decimal(str(round(cotizacion_dolar, 4))),
                    costo_unitario_sin_iva=Decimal(str(round(costo_sin_iva, 6))),
                    costo_total_sin_iva=Decimal(str(round(costo_total_sin_iva, 2))),
                    moneda_costo=moneda_costo,
                    tipo_lista=row.get("priceList"),
                    porcentaje_comision_ml=Decimal(str(round(porcentaje_comision_ml, 2))),
                    comision_ml=Decimal(str(round(comision_ml, 2))),
                    costo_envio_ml=Decimal(str(round(costo_envio_ml, 2))),
                    tipo_logistica=tipo_logistica,
                    monto_limpio=Decimal(str(round(monto_limpio, 2))),
                    costo_total=Decimal(str(round(costo_total_sin_iva, 2))),
                    ganancia=Decimal(str(round(ganancia, 2))),
                    markup_porcentaje=Decimal(str(round(markup_porcentaje, 2))),
                    offset_flex=Decimal(str(round(metricas["offset_flex"], 2))),
                    prli_id=int(row.get("priceList")) if pd.notna(row.get("priceList")) else None,
                    mla_id=row.get("ML_id"),
                )
                db.add(metrica)
                total_insertados += 1

            # Commit cada 100 registros
            if (total_insertados + total_actualizados) % 100 == 0:
                db.commit()
                print(
                    f"  Procesados: {total_insertados + total_actualizados} | Nuevos: {total_insertados} | Actualizados: {total_actualizados}"
                )

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

    print()
    print(f"{'=' * 60}")
    print("✅ COMPLETADO")
    print(f"{'=' * 60}")
    print(f"Insertados: {total_insertados}")
    print(f"Actualizados: {total_actualizados}")
    print(f"Errores: {total_errores}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    args = parser.parse_args()

    from_date = datetime.strptime(args.from_date, "%Y-%m-%d").date()
    to_date = datetime.strptime(args.to_date, "%Y-%m-%d").date()

    print(f"\n{'=' * 60}")
    print("AGREGACIÓN DE MÉTRICAS ML (v2 - usando API)")
    print(f"{'=' * 60}")
    print(f"Rango: {from_date} a {to_date}")
    print()

    # Fetch data from API
    df = fetch_data_from_api(from_date, to_date)

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
