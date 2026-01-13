"""
Script para agregar métricas de ventas de Tienda Nube - INCREMENTAL
Versión incremental que procesa los últimos N minutos de datos
Diseñado para ejecutarse cada 5 minutos en cron

Ejecutar:
    python -m app.scripts.agregar_metricas_tienda_nube
    python -m app.scripts.agregar_metricas_tienda_nube --full  # Para reprocesar todo
    python -m app.scripts.agregar_metricas_tienda_nube --days 30  # Últimos 30 días
"""
import sys
import argparse
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_

from app.core.database import SessionLocal
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.models.pricing_constants import PricingConstants


# Constantes de filtrado para Tienda Nube
SD_VENTAS = [1, 4, 21, 56]
SD_DEVOLUCIONES = [3, 6, 23, 66]
SD_TODOS = SD_VENTAS + SD_DEVOLUCIONES
SD_IDS_STR = ','.join(map(str, SD_TODOS))

# df_id de facturas de Tienda Nube
DF_TIENDA_NUBE = [113, 114]
DF_IDS_STR = ','.join(map(str, DF_TIENDA_NUBE))

CLIENTES_EXCLUIDOS = [11, 3900]
CLIENTES_EXCLUIDOS_STR = ','.join(map(str, CLIENTES_EXCLUIDOS))

ITEMS_EXCLUIDOS = [16, 460]
ITEMS_EXCLUIDOS_STR = ','.join(map(str, ITEMS_EXCLUIDOS))


def get_comision_tienda_nube(db: Session, fecha: date = None) -> float:
    """Obtiene la comisión de Tienda Nube vigente para una fecha"""
    if fecha is None:
        fecha = date.today()

    constants = db.query(PricingConstants).filter(
        and_(
            PricingConstants.fecha_desde <= fecha,
            or_(
                PricingConstants.fecha_hasta.is_(None),
                PricingConstants.fecha_hasta >= fecha
            )
        )
    ).order_by(PricingConstants.fecha_desde.desc()).first()

    if constants and constants.comision_tienda_nube is not None:
        return float(constants.comision_tienda_nube)
    return 1.0  # Default 1%


def obtener_ventas_tienda_nube(db: Session, from_date, to_date):
    """
    Obtiene todas las ventas de Tienda Nube con métricas ya calculadas
    """
    query = text(f"""
    WITH combo_precios AS (
        -- Precio total del combo por transacción
        SELECT
            tit.it_isassociationgroup AS group_id,
            tit.ct_transaction,
            SUM(tit.it_price * tit.it_qty) AS precio_combo
        FROM tb_item_transactions tit
        INNER JOIN tb_commercial_transactions tct
            ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
        WHERE tit.it_isassociationgroup IS NOT NULL
          AND tit.it_price IS NOT NULL AND tit.it_price > 0
          AND tct.ct_date BETWEEN :from_date AND :to_date
          AND tct.df_id IN ({DF_IDS_STR})
        GROUP BY tit.it_isassociationgroup, tit.ct_transaction
    ),
    combo_costos AS (
        -- Costo total del combo por transacción (con multiplicador 1.065)
        SELECT
            tit.it_isassociationgroup AS group_id,
            tit.ct_transaction,
            SUM(
                COALESCE(
                    CASE
                        WHEN COALESCE(iclh.curr_id, 1) = 1 THEN iclh.iclh_price
                        ELSE iclh.iclh_price * COALESCE(ceh.ceh_exchange, 1)
                    END,
                    0
                ) * 1.065 * tit.it_qty
            ) AS costo_combo
        FROM tb_item_transactions tit
        INNER JOIN tb_commercial_transactions tct
            ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
        LEFT JOIN LATERAL (
            SELECT iclh_price, curr_id
            FROM tb_item_cost_list_history
            WHERE item_id = tit.item_id AND iclh_cd <= tct.ct_date AND coslis_id = 1
            ORDER BY iclh_id DESC LIMIT 1
        ) iclh ON true
        LEFT JOIN LATERAL (
            -- TC: Primero tipo_cambio, fallback tb_cur_exch_history
            SELECT COALESCE(
                (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tct.ct_date::date ORDER BY tc.fecha DESC LIMIT 1),
                (SELECT ceh_exchange FROM tb_cur_exch_history WHERE ceh_cd <= tct.ct_date ORDER BY ceh_cd DESC LIMIT 1)
            ) as ceh_exchange
        ) ceh ON true
        WHERE tit.it_isassociationgroup IS NOT NULL
          AND tct.ct_date BETWEEN :from_date AND :to_date
          AND tct.df_id IN ({DF_IDS_STR})
        GROUP BY tit.it_isassociationgroup, tit.ct_transaction
    )
    SELECT
        tit.it_transaction,
        tit.ct_transaction,
        tit.item_id,
        ti.item_code as codigo,
        COALESCE(ti.item_desc, titd.itm_desc) as descripcion,
        tbd.brand_desc as marca,
        tcc.cat_desc as categoria,
        tsc.subcat_desc as subcategoria,
        tct.bra_id,
        tb.bra_desc as sucursal,
        tct.sm_id,
        tsm.sm_name as vendedor,
        tct.cust_id,
        tc.cust_name as cliente,
        tct.df_id,
        tdf.df_desc as tipo_comprobante,
        tct.ct_docnumber as numero_comprobante,
        tct.ct_date as fecha_venta,
        tct.sd_id,
        CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as signo,

        -- Cantidad
        tit.it_qty as cantidad,

        -- IVA
        -- IVA: Primero tb_tax_name, fallback productos_erp
        COALESCE(ttn.tax_percentage, pe.iva, 21.0) as iva_porcentaje,

        -- Es combo?
        CASE WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN true ELSE false END as es_combo,
        tit.it_isassociationgroup as combo_group_id,

        -- Monto unitario (para combos usa precio_combo)
        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN cp.precio_combo / NULLIF(tit.it_qty, 0)
            ELSE tit.it_price
        END as monto_unitario,

        -- Monto total
        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN cp.precio_combo
            ELSE tit.it_price * tit.it_qty
        END as monto_total,

        -- Costo unitario (convertido a pesos, con multiplicador 1.065)
        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN
                COALESCE(ccb.costo_combo, 0) / NULLIF(tit.it_qty, 0)
            ELSE
                CASE
                    WHEN COALESCE(iclh.curr_id, 1) = 1 THEN COALESCE(iclh.iclh_price, 0) * 1.065
                    ELSE COALESCE(iclh.iclh_price, 0) * COALESCE(ceh.ceh_exchange, 1) * 1.065
                END
        END as costo_unitario,

        -- Costo total (con multiplicador 1.065)
        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN COALESCE(ccb.costo_combo, 0)
            ELSE
                CASE
                    WHEN COALESCE(iclh.curr_id, 1) = 1 THEN COALESCE(iclh.iclh_price, 0) * 1.065 * tit.it_qty
                    ELSE COALESCE(iclh.iclh_price, 0) * COALESCE(ceh.ceh_exchange, 1) * 1.065 * tit.it_qty
                END
        END as costo_total,

        -- Moneda y cotización
        CASE WHEN COALESCE(iclh.curr_id, 1) = 2 THEN 'USD' ELSE 'ARS' END as moneda_costo,
        ceh.ceh_exchange as cotizacion_dolar

    FROM tb_item_transactions tit
    INNER JOIN tb_commercial_transactions tct
        ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_item ti
        ON ti.comp_id = tit.comp_id AND ti.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
    LEFT JOIN productos_erp pe
        ON pe.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
    LEFT JOIN tb_item_transaction_details titd
        ON titd.comp_id = tit.comp_id AND titd.bra_id = tit.bra_id AND titd.it_transaction = tit.it_transaction
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN tb_category tcc ON tcc.comp_id = ti.comp_id AND tcc.cat_id = ti.cat_id
    LEFT JOIN tb_subcategory tsc ON tsc.comp_id = ti.comp_id AND tsc.cat_id = ti.cat_id AND tsc.subcat_id = ti.subcat_id
    LEFT JOIN tb_branch tb ON tb.comp_id = tit.comp_id AND tb.bra_id = tct.bra_id
    LEFT JOIN tb_salesman tsm ON tsm.sm_id = tct.sm_id
    LEFT JOIN tb_customer tc ON tc.comp_id = tct.comp_id AND tc.cust_id = tct.cust_id
    LEFT JOIN tb_document_file tdf ON tdf.comp_id = tct.comp_id AND tdf.bra_id = tct.bra_id AND tdf.df_id = tct.df_id
    LEFT JOIN tb_item_taxes titx ON titx.comp_id = tit.comp_id AND titx.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
    LEFT JOIN tb_tax_name ttn ON ttn.comp_id = tit.comp_id AND ttn.tax_id = titx.tax_id
    LEFT JOIN combo_precios cp ON cp.group_id = tit.it_isassociationgroup AND cp.ct_transaction = tit.ct_transaction
    LEFT JOIN combo_costos ccb ON ccb.group_id = tit.it_isassociationgroup AND ccb.ct_transaction = tit.ct_transaction
    LEFT JOIN LATERAL (
        SELECT iclh_price, curr_id
        FROM tb_item_cost_list_history
        WHERE item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
          AND iclh_cd <= tct.ct_date AND coslis_id = 1
        ORDER BY iclh_id DESC LIMIT 1
    ) iclh ON true
    LEFT JOIN LATERAL (
        -- TC: Primero tipo_cambio, fallback tb_cur_exch_history
        SELECT COALESCE(
            (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tct.ct_date::date ORDER BY tc.fecha DESC LIMIT 1),
            (SELECT ceh_exchange FROM tb_cur_exch_history WHERE ceh_cd <= tct.ct_date ORDER BY ceh_cd DESC LIMIT 1)
        ) as ceh_exchange
    ) ceh ON true

    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN ({DF_IDS_STR})
        AND (tit.item_id NOT IN ({ITEMS_EXCLUIDOS_STR}) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN ({CLIENTES_EXCLUIDOS_STR})
        AND tit.it_qty <> 0
        AND tct.sd_id IN ({SD_IDS_STR})
        -- Excluir items "Envio"
        AND NOT (
            CASE
                WHEN tit.item_id IS NULL AND tit.it_item_id_origin IS NULL
                THEN COALESCE(titd.itm_desc, '')
                ELSE COALESCE(ti.item_desc, '')
            END ILIKE '%envio%'
        )
        -- Excluir componentes de combos
        AND NOT (
            COALESCE(tit.it_isassociation, false) = true
            AND COALESCE(tit.it_order, 1) <> 1
            AND tit.it_isassociationgroup IS NOT NULL
        )
    ORDER BY tct.ct_date, tit.it_transaction
    """)

    result = db.execute(query, {
        'from_date': from_date,
        'to_date': to_date
    })

    return result.fetchall()


def process_and_insert(db: Session, rows):
    """Procesa los registros y los inserta en ventas_tienda_nube_metricas"""

    if not rows:
        print("  No hay datos para procesar")
        return 0, 0, 0

    print(f"\n  Procesando {len(rows)} registros...")
    
    # PASO 1: Deduplicar resultados de la query (la query puede traer duplicados por los JOINs)
    seen_it_transactions = set()
    rows_deduplicated = []
    duplicados_query = 0
    
    for row in rows:
        if row.it_transaction not in seen_it_transactions:
            seen_it_transactions.add(row.it_transaction)
            rows_deduplicated.append(row)
        else:
            duplicados_query += 1
    
    if duplicados_query > 0:
        print(f"  ⚠️  Detectados {duplicados_query} duplicados en la query (se ignoran)")
    
    print(f"  Registros únicos a procesar: {len(rows_deduplicated)}")
    
    # PASO 2: Bulk fetch - Traer todos los it_transaction existentes de una vez (evita N+1)
    incoming_ids = [row.it_transaction for row in rows_deduplicated]
    
    existing_records = db.query(VentaTiendaNubeMetrica).filter(
        VentaTiendaNubeMetrica.it_transaction.in_(incoming_ids)
    ).all()
    
    # Crear mapa it_transaction → registro para lookup O(1)
    existing_map = {record.it_transaction: record for record in existing_records}
    print(f"  Encontrados {len(existing_map)} registros existentes en DB")

    total_insertados = 0
    total_actualizados = 0
    total_errores = 0
    fecha_calculo = date.today()

    # Obtener comisión de TN (usamos la vigente hoy, pero idealmente debería ser por fecha de venta)
    comision_tn_pct = get_comision_tienda_nube(db, fecha_calculo)
    print(f"  Comision TN: {comision_tn_pct}%")

    for row in rows_deduplicated:
        try:
            # Buscar en el mapa (O(1) lookup, no query a DB)
            existente = existing_map.get(row.it_transaction)

            # Calcular valores derivados
            monto_total = float(row.monto_total or 0)
            costo_total = float(row.costo_total or 0)
            iva_porcentaje = float(row.iva_porcentaje or 21)
            signo = row.signo

            monto_iva = monto_total * (iva_porcentaje / 100)
            monto_con_iva = monto_total * (1 + iva_porcentaje / 100)

            # Calcular comisión de Tienda Nube
            comision_monto = monto_total * (comision_tn_pct / 100)

            # Ganancia = monto - costo - comisión
            ganancia = monto_total - costo_total - comision_monto

            # Markup = (monto / (costo + comisión)) - 1 (solo si hay costo)
            markup_porcentaje = None
            base_costo = costo_total + comision_monto
            if base_costo > 0 and signo > 0:  # Solo para ventas, no devoluciones
                markup_porcentaje = ((monto_total / base_costo) - 1) * 100
                # Limitar a rango válido
                if markup_porcentaje > 99999999.99:
                    markup_porcentaje = 99999999.99
                elif markup_porcentaje < -99999999.99:
                    markup_porcentaje = -99999999.99

            data = {
                'it_transaction': row.it_transaction,
                'ct_transaction': row.ct_transaction,
                'item_id': row.item_id,
                'codigo': row.codigo,
                'descripcion': row.descripcion[:500] if row.descripcion else None,
                'marca': row.marca,
                'categoria': row.categoria,
                'subcategoria': row.subcategoria,
                'bra_id': row.bra_id,
                'sucursal': row.sucursal,
                'sm_id': row.sm_id,
                'vendedor': row.vendedor,
                'cust_id': row.cust_id,
                'cliente': row.cliente,
                'df_id': row.df_id,
                'tipo_comprobante': row.tipo_comprobante,
                'numero_comprobante': row.numero_comprobante,
                'fecha_venta': row.fecha_venta,
                'fecha_calculo': fecha_calculo,
                'sd_id': row.sd_id,
                'signo': signo,
                'cantidad': Decimal(str(row.cantidad or 0)),
                'monto_unitario': Decimal(str(row.monto_unitario or 0)),
                'monto_total': Decimal(str(monto_total)),
                'iva_porcentaje': Decimal(str(iva_porcentaje)),
                'monto_iva': Decimal(str(monto_iva)),
                'monto_con_iva': Decimal(str(monto_con_iva)),
                'costo_unitario': Decimal(str(row.costo_unitario or 0)),
                'costo_total': Decimal(str(costo_total)),
                'moneda_costo': row.moneda_costo,
                'cotizacion_dolar': Decimal(str(row.cotizacion_dolar)) if row.cotizacion_dolar else None,
                'comision_porcentaje': Decimal(str(comision_tn_pct)),
                'comision_monto': Decimal(str(comision_monto)),
                'ganancia': Decimal(str(ganancia)),
                'markup_porcentaje': Decimal(str(markup_porcentaje)) if markup_porcentaje is not None else None,
                'es_combo': bool(row.es_combo) if row.es_combo is not None else False,
                'combo_group_id': int(row.combo_group_id) if row.combo_group_id else None
            }

            if existente:
                for key, value in data.items():
                    if key != 'it_transaction':
                        setattr(existente, key, value)
                total_actualizados += 1
            else:
                nueva_metrica = VentaTiendaNubeMetrica(**data)
                db.add(nueva_metrica)
                total_insertados += 1

            # Commit cada 500 registros
            if (total_insertados + total_actualizados) % 500 == 0:
                db.commit()
                print(f"    Progreso: {total_insertados + total_actualizados}/{len(rows)}")

        except Exception as e:
            total_errores += 1
            print(f"    Error procesando transaccion {row.it_transaction}: {str(e)}")
            db.rollback()
            continue

    # Commit final
    db.commit()

    return total_insertados, total_actualizados, total_errores


def main():
    parser = argparse.ArgumentParser(description='Agregar metricas de ventas Tienda Nube')
    parser.add_argument('--full', action='store_true', help='Reprocesar todo (ultimo año)')
    parser.add_argument('--days', type=int, default=None, help='Procesar ultimos N dias')
    parser.add_argument('--minutes', type=int, default=10, help='Minutos hacia atras (modo incremental)')
    parser.add_argument('--from-date', type=str, default=None, help='Fecha desde (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, default=None, help='Fecha hasta (YYYY-MM-DD)')
    args = parser.parse_args()

    now = datetime.now()

    if args.from_date and args.to_date:
        # Modo fecha específica
        from_date = args.from_date
        to_date = args.to_date + ' 23:59:59'
        mode = f"PERIODO ESPECIFICO"
    elif args.full:
        # Modo completo: último año
        from_date = (now - timedelta(days=365)).strftime('%Y-%m-%d')
        to_date = now.strftime('%Y-%m-%d 23:59:59')
        mode = "COMPLETO (ultimo año)"
    elif args.days:
        # Modo días específicos
        from_date = (now - timedelta(days=args.days)).strftime('%Y-%m-%d')
        to_date = now.strftime('%Y-%m-%d 23:59:59')
        mode = f"ULTIMOS {args.days} DIAS"
    else:
        # Modo incremental (default)
        from_date = (now - timedelta(minutes=args.minutes)).strftime('%Y-%m-%d %H:%M:%S')
        to_date = now.strftime('%Y-%m-%d %H:%M:%S')
        mode = f"INCREMENTAL (ultimos {args.minutes} minutos)"

    print("=" * 60)
    print(f"METRICAS VENTAS TIENDA NUBE - {mode}")
    print("=" * 60)
    print(f"Ejecutado: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Rango: {from_date} a {to_date}")

    db = SessionLocal()

    try:
        # Obtener datos
        print(f"\n  Consultando ventas de Tienda Nube...")
        rows = obtener_ventas_tienda_nube(db, from_date, to_date)
        print(f"  Obtenidos {len(rows)} registros")

        # Procesar e insertar
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
