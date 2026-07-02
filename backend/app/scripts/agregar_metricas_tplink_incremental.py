"""
Script for adding TP-Link sales metrics (store 2645, coslis_id=8) — INCREMENTAL.
Incremental version that processes the last 10 minutes of data.
Designed to run every 5 minutes via cron.

Clone of agregar_metricas_ml_incremental.py with targeted changes:
  1. Write target: TplinkVentaMetrica instead of MLVentaMetrica.
  2. All 5 coslis_id literals in SQL replaced with ':coslis_id' bind (TPLINK_COSLIS_ID=8).
  3. Added 'AND tmlip.mlp_official_store_id = :store_id' WHERE filter (TPLINK_STORE_ID=2645).
  4. STRIPPED: registrar_consumo_grupo_offset, registrar_consumo_offset_individual,
     crear_notificacion_markup_bajo — ML incremental already owns these for store-2645
     orders; calling them here would double-count offset consumo and duplicate notifications.
  5. Missing-cost logging after fetchall.

ML model/jobs are byte-for-byte unmodified.

Cron (mirror ML's 5-min cadence):
    */5 * * * * cd /var/www/html/pricing-app/backend && \\
        /var/www/html/pricing-app/backend/venv/bin/python \\
        app/scripts/agregar_metricas_tplink_incremental.py \\
        >> /var/log/pricing-app/tplink_metricas_incremental.log 2>&1
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, func

from app.core.database import SessionLocal
from app.models.tplink_venta_metrica import TplinkVentaMetrica
from app.models.producto import ProductoERP
from app.utils.ml_metrics_calculator import calcular_metricas_ml

# Module-level constants — kept identical to the full job
TPLINK_STORE_ID: int = 2645
TPLINK_COSLIS_ID: int = 8


def calcular_metricas_locales(db: Session, from_date: date, to_date: date):
    """
    Queries local PostgreSQL tables to calculate TP-Link metrics.
    Replicates ML incremental logic scoped to store 2645 and coslis_id=8.

    Key differences from ML incremental:
    - coslis_id literal replaced with :coslis_id bind (resolves to TPLINK_COSLIS_ID=8)
    - Added AND tmlip.mlp_official_store_id = :store_id filter (TPLINK_STORE_ID=2645)
    """

    print("\nConsultando tablas locales PostgreSQL (TP-Link)...")
    print(f"   Rango: {from_date} a {to_date}")

    query = text("""
    WITH sales_data AS (
        SELECT DISTINCT ON (tmlod.mlo_id)
            tmlod.mlo_id as id_operacion,
            tmlod.item_id,
            tct.ct_transaction,
            tmloh.mlo_cd as fecha_venta,
            COALESCE(tb.brand_desc, pe.marca) as marca,
            COALESCE(tc.cat_desc, pe.categoria) as categoria,
            COALESCE(tsc.subcat_desc, (SELECT s.subcat_desc FROM tb_subcategory s WHERE s.subcat_id = pe.subcategoria_id LIMIT 1)) as subcategoria,
            COALESCE(ti.item_code, pe.codigo) as codigo,
            COALESCE(UPPER(ti.item_desc), UPPER(pe.descripcion)) as descripcion,
            tmlod.mlo_quantity as cantidad,
            tmlod.mlo_unit_price as monto_unitario,
            tmlod.mlo_unit_price * tmlod.mlo_quantity as monto_total,

            -- Cost: uses :coslis_id bind (=8 for TP-Link, never list 1)
            -- FIRST history, FALLBACK current cost without date validation
            COALESCE(
                (
                    SELECT iclh.curr_id
                    FROM tb_item_cost_list_history iclh
                    WHERE iclh.item_id = tmlod.item_id
                      AND iclh.iclh_cd <= tmloh.mlo_cd
                      AND iclh.coslis_id = :coslis_id
                    ORDER BY iclh.iclh_id DESC
                    LIMIT 1
                ),
                (
                    SELECT ticl.curr_id
                    FROM tb_item_cost_list ticl
                    WHERE ticl.item_id = tmlod.item_id
                      AND ticl.coslis_id = :coslis_id
                )
            ) as moneda_costo,

            -- Cost without VAT in ARS — uses :coslis_id bind
            COALESCE(
                (
                    SELECT CASE
                        WHEN iclh.curr_id = 2 THEN  -- USD
                            iclh.iclh_price * COALESCE(
                                (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tmloh.mlo_cd::date ORDER BY tc.fecha DESC LIMIT 1),
                                (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tmloh.mlo_cd ORDER BY ceh.ceh_cd DESC LIMIT 1)
                            )
                        ELSE  -- ARS
                            iclh.iclh_price
                    END
                    FROM tb_item_cost_list_history iclh
                    WHERE iclh.item_id = tmlod.item_id
                      AND iclh.iclh_cd <= tmloh.mlo_cd
                      AND iclh.coslis_id = :coslis_id
                      AND iclh.iclh_price > 0
                    ORDER BY iclh.iclh_id DESC
                    LIMIT 1
                ),
                (
                    SELECT CASE
                        WHEN ticl.curr_id = 2 THEN  -- USD
                            ticl.coslis_price * COALESCE(
                                (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tmloh.mlo_cd::date ORDER BY tc.fecha DESC LIMIT 1),
                                (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tmloh.mlo_cd ORDER BY ceh.ceh_cd DESC LIMIT 1)
                            )
                        ELSE  -- ARS
                            ticl.coslis_price
                    END
                    FROM tb_item_cost_list ticl
                    WHERE ticl.item_id = tmlod.item_id
                      AND ticl.coslis_id = :coslis_id
                ),
                0
            ) as costo_sin_iva,

            -- VAT: always from productos_erp
            pe.iva as iva,

            -- Exchange rate at sale time
            COALESCE(
                (
                    SELECT tc.venta
                    FROM tipo_cambio tc
                    WHERE tc.moneda = 'USD'
                      AND tc.fecha <= tmloh.mlo_cd::date
                    ORDER BY tc.fecha DESC
                    LIMIT 1
                ),
                (
                    SELECT ceh.ceh_exchange
                    FROM tb_cur_exch_history ceh
                    WHERE ceh.ceh_cd <= tmloh.mlo_cd
                    ORDER BY ceh.ceh_cd DESC
                    LIMIT 1
                )
            ) as cambio_momento,

            COALESCE(tmlos.ml_logistic_type, tmlos.mllogistic_type) as tipo_logistica,
            tmloh.ml_id,
            tmloh.ml_pack_id as pack_id,
            tmloh.mlshippingid as shipping_id,
            pe.envio as envio_producto,
            COALESCE(tmlos.mlshippmentcost4seller, 0) as seller_shipping_cost,

            COALESCE(
                (SELECT SUM(od2.mlo_unit_price * od2.mlo_quantity)
                 FROM tb_mercadolibre_orders_detail od2
                 JOIN tb_mercadolibre_orders_header oh2 ON oh2.mlo_id = od2.mlo_id
                 WHERE oh2.mlshippingid = tmloh.mlshippingid
                ), tmlod.mlo_unit_price * tmlod.mlo_quantity
            ) as shipment_total,

            -- Commission percentage (versioned)
            COALESCE(
                (
                    SELECT
                        cb.comision_base + COALESCE(
                            (
                                SELECT cac.adicional
                                FROM comisiones_adicionales_cuota cac
                                WHERE cac.version_id = cv.id
                                  AND cac.cuotas = CASE
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (17, 18) THEN 3
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (14, 19) THEN 6
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (13, 20) THEN 9
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (23, 21) THEN 12
                                      ELSE NULL
                                  END
                                LIMIT 1
                            ),
                            0
                        )
                    FROM subcategorias_grupos sg
                    JOIN comisiones_base cb ON cb.grupo_id = sg.grupo_id
                    JOIN comisiones_versiones cv ON cv.id = cb.version_id
                    WHERE sg.subcat_id = COALESCE(tsc.subcat_id, pe.subcategoria_id)
                      AND tmloh.mlo_cd::date BETWEEN cv.fecha_desde AND COALESCE(cv.fecha_hasta, '9999-12-31'::date)
                      AND cv.activo = TRUE
                    LIMIT 1
                ),
                12.0
            ) as comision_base_porcentaje,

            COALESCE(tsc.subcat_id, pe.subcategoria_id) as subcat_id,

            COALESCE(
                tsoh.prli_id,
                CASE
                    WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop
                    ELSE tmlip.prli_id
                END
            ) as pricelist_id,

            tmlod.mlp_id as mlp_id,
            tmlip.mlp_official_store_id as mlp_official_store_id

        FROM tb_mercadolibre_orders_detail tmlod

        LEFT JOIN tb_mercadolibre_orders_header tmloh
            ON tmloh.comp_id = tmlod.comp_id
            AND tmloh.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_sale_order_header tsoh
            ON tsoh.comp_id = tmlod.comp_id
            AND tsoh.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_item ti
            ON ti.comp_id = tmlod.comp_id
            AND ti.item_id = tmlod.item_id

        LEFT JOIN productos_erp pe
            ON pe.item_id = tmlod.item_id

        LEFT JOIN tb_mercadolibre_items_publicados tmlip
            ON tmlip.comp_id = tmlod.comp_id
            AND tmlip.mlp_id = tmlod.mlp_id

        LEFT JOIN tb_mercadolibre_orders_shipping tmlos
            ON tmlos.comp_id = tmlod.comp_id
            AND tmlos.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_commercial_transactions tct
            ON tct.comp_id = tmlod.comp_id
            AND tct.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_category tc
            ON tc.comp_id = tmlod.comp_id
            AND tc.cat_id = ti.cat_id

        LEFT JOIN tb_subcategory tsc
            ON tsc.comp_id = tmlod.comp_id
            AND tsc.cat_id = ti.cat_id
            AND tsc.subcat_id = ti.subcat_id

        LEFT JOIN tb_brand tb
            ON tb.comp_id = tmlod.comp_id
            AND tb.brand_id = ti.brand_id

        LEFT JOIN tb_item_taxes tit
            ON ti.comp_id = tit.comp_id
            AND ti.item_id = tit.item_id

        LEFT JOIN tb_tax_name ttn
            ON ttn.comp_id = ti.comp_id
            AND ttn.tax_id = tit.tax_id

        LEFT JOIN tb_item_cost_list ticl
            ON ticl.comp_id = tmlod.comp_id
            AND ticl.item_id = tmlod.item_id
            AND ticl.coslis_id = :coslis_id

        WHERE tmlod.item_id NOT IN (460, 3042)
          AND tmloh.mlo_cd BETWEEN :from_date AND :to_date
          AND tmloh.mlo_status <> 'cancelled'
          AND tmlip.mlp_official_store_id = :store_id
    )
    SELECT * FROM sales_data
    ORDER BY fecha_venta, id_operacion
    """)

    result = db.execute(
        query,
        {
            "from_date": from_date,
            "to_date": to_date,
            "coslis_id": TPLINK_COSLIS_ID,
            "store_id": TPLINK_STORE_ID,
        },
    )

    rows = result.fetchall()
    print(f"  Obtenidos {len(rows)} registros (store {TPLINK_STORE_ID}, coslis_id={TPLINK_COSLIS_ID})")

    # Missing-cost logging after fetchall
    missing_count = sum(1 for row in rows if not row.costo_sin_iva or float(row.costo_sin_iva) == 0)
    if missing_count > 0:
        sample_codes = [row.codigo for row in rows if not row.costo_sin_iva or float(row.costo_sin_iva) == 0][:10]
        print(f"  AVISO: {missing_count} items sin costo lista {TPLINK_COSLIS_ID}. Muestra codigos: {sample_codes}")

    return rows


def calcular_metricas_adicionales(row, count_per_pack, db_session):
    """
    Calculates metrics using the centralized helper.
    Identical logic to ML incremental — commission computed dynamically.
    """
    costo_envio_producto = None
    if row.envio_producto:
        costo_envio_producto = float(row.envio_producto)

    from app.services.pricing_calculator import obtener_comision_versionada, obtener_grupo_subcategoria

    comision_porcentaje = None
    if db_session and row.subcat_id and row.pricelist_id:
        grupo_id = obtener_grupo_subcategoria(db_session, row.subcat_id)
        if grupo_id:
            fecha_venta = row.fecha_venta.date() if hasattr(row.fecha_venta, "date") else row.fecha_venta
            comision_porcentaje = obtener_comision_versionada(db_session, grupo_id, row.pricelist_id, fecha_venta)

    if comision_porcentaje is None:
        comision_porcentaje = float(row.comision_base_porcentaje or 12.0)

    metricas = calcular_metricas_ml(
        monto_unitario=float(row.monto_unitario or 0),
        cantidad=float(row.cantidad or 1),
        iva_porcentaje=float(row.iva or 0),
        costo_unitario_sin_iva=float(row.costo_sin_iva or 0),
        costo_envio_ml=costo_envio_producto,
        count_per_pack=count_per_pack,
        subcat_id=row.subcat_id,
        pricelist_id=row.pricelist_id,
        fecha_venta=row.fecha_venta,
        comision_base_porcentaje=comision_porcentaje,
        db_session=db_session,
        ml_logistic_type=row.tipo_logistica,
        seller_shipping_cost=float(row.seller_shipping_cost)
        if hasattr(row, "seller_shipping_cost") and row.seller_shipping_cost
        else None,
        shipment_total=float(row.shipment_total) if hasattr(row, "shipment_total") and row.shipment_total else None,
    )

    return {
        "costo_total_sin_iva": metricas["costo_total_sin_iva"],
        "comision_ml": metricas["comision_ml"],
        "costo_envio": metricas["costo_envio"],
        "monto_limpio": metricas["monto_limpio"],
        "ganancia": metricas["ganancia"],
        "markup_porcentaje": metricas["markup_porcentaje"],
        "offset_flex": metricas["offset_flex"],
    }


def process_and_insert(db: Session, rows) -> tuple[int, int, int]:
    """
    Processes rows and inserts/updates into tplink_ventas_metricas.

    Side effects deliberately NOT included vs ML incremental:
    The three ML global side-effect helpers (offset consumo grupo, offset consumo individual,
    and markup notification) are excluded because the ML incremental already runs them for
    store-2645 orders. Including them here would double-count offset consumo and duplicate
    markup notifications.
    """
    if not rows:
        print("  No hay datos para procesar")
        return 0, 0, 0

    print(f"\nProcesando {len(rows)} registros (TP-Link)...")

    # Calculate count_per_pack
    pack_counts = {}
    for row in rows:
        pack_id = row.pack_id
        if pack_id:
            pack_counts[pack_id] = pack_counts.get(pack_id, 0) + 1

    total_insertados = 0
    total_actualizados = 0
    total_errores = 0

    fecha_calculo = date.today()

    for row in rows:
        try:
            existente = db.query(TplinkVentaMetrica).filter(TplinkVentaMetrica.id_operacion == row.id_operacion).first()

            count_per_pack = pack_counts.get(row.pack_id, 1)
            metricas = calcular_metricas_adicionales(row, count_per_pack, db)

            data = {
                "id_operacion": row.id_operacion,
                "ml_order_id": str(row.ml_id) if row.ml_id else None,
                "pack_id": row.pack_id,
                "item_id": row.item_id,
                "codigo": row.codigo,
                "descripcion": row.descripcion,
                "marca": row.marca,
                "categoria": row.categoria,
                "subcategoria": row.subcategoria,
                "fecha_venta": row.fecha_venta,
                "fecha_calculo": fecha_calculo,
                "cantidad": row.cantidad,
                "monto_unitario": Decimal(str(row.monto_unitario)) if row.monto_unitario else Decimal("0"),
                "monto_total": Decimal(str(row.monto_total)) if row.monto_total else Decimal("0"),
                "costo_unitario_sin_iva": Decimal(str(row.costo_sin_iva)) if row.costo_sin_iva else Decimal("0"),
                "costo_total_sin_iva": Decimal(str(metricas["costo_total_sin_iva"])),
                "comision_ml": Decimal(str(metricas["comision_ml"])),
                "costo_envio_ml": Decimal(str(metricas["costo_envio"])),
                "tipo_logistica": row.tipo_logistica,
                "monto_limpio": Decimal(str(metricas["monto_limpio"])),
                "ganancia": Decimal(str(metricas["ganancia"])),
                "markup_porcentaje": Decimal(str(metricas["markup_porcentaje"])),
                "mla_id": str(row.mlp_id) if hasattr(row, "mlp_id") and row.mlp_id else None,
                "mlp_official_store_id": TPLINK_STORE_ID,  # Always 2645 for TP-Link
                "offset_flex": Decimal(str(metricas["offset_flex"])),
            }

            if existente:
                for key, value in data.items():
                    if key != "id_operacion":
                        setattr(existente, key, value)
                total_actualizados += 1
            else:
                nueva_metrica = TplinkVentaMetrica(**data)
                db.add(nueva_metrica)
                total_insertados += 1

            # Commit every 100 records
            if (total_insertados + total_actualizados) % 100 == 0:
                db.commit()
                print(f"  Progreso: {total_insertados + total_actualizados}/{len(rows)}")

        except Exception as e:
            total_errores += 1
            print(f"  Error procesando operacion {row.id_operacion}: {str(e)}")
            db.rollback()
            continue

    db.commit()

    return total_insertados, total_actualizados, total_errores


def main() -> None:
    # INCREMENTAL: process last 10 minutes (mirror ML incremental window)
    now = datetime.now()
    from_datetime = now - timedelta(minutes=10)
    to_datetime = now

    print("=" * 60)
    print(f"METRICAS TP-LINK INCREMENTAL (store {TPLINK_STORE_ID}, coslis_id={TPLINK_COSLIS_ID})")
    print("=" * 60)
    print(f"Ejecutado: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Rango: {from_datetime.strftime('%Y-%m-%d %H:%M:%S')} a {to_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

    db = SessionLocal()

    try:
        rows = calcular_metricas_locales(db, from_datetime, to_datetime)
        insertados, actualizados, errores = process_and_insert(db, rows)

        print("\n" + "=" * 60)
        print("COMPLETADO")
        print("=" * 60)
        print(f"Insertados: {insertados}")
        print(f"Actualizados: {actualizados}")
        print(f"Errores: {errores}")
        print()

    except Exception as e:
        print(f"\nError critico: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
