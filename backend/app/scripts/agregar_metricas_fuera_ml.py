"""
Script para agregar métricas de ventas fuera de ML - INCREMENTAL
Versión incremental que procesa los últimos N minutos de datos
Diseñado para ejecutarse cada 5 minutos en cron

Ejecutar:
    python app/scripts/agregar_metricas_fuera_ml.py
    python app/scripts/agregar_metricas_fuera_ml.py --full  # Para reprocesar todo
    python app/scripts/agregar_metricas_fuera_ml.py --days 30  # Últimos 30 días
"""

import sys
import argparse
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
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica


# Constantes de filtrado (igual que en ventas_fuera_ml.py)
SD_VENTAS = [1, 4, 21, 56]
SD_DEVOLUCIONES = [3, 6, 23, 66]
SD_TODOS = SD_VENTAS + SD_DEVOLUCIONES

DF_PERMITIDOS = [
    1,
    2,
    3,
    4,
    5,
    6,
    63,
    85,
    86,
    87,
    65,
    67,
    68,
    69,
    70,
    71,
    72,
    73,
    74,
    81,
    103,
    105,
    106,
    109,
    111,
    115,
    116,
    117,
    118,
    122,
    124,
    125,
    126,
    127,
]

CLIENTES_EXCLUIDOS = [11, 3900]

ITEMS_EXCLUIDOS = [16, 460]

VENDEDORES_EXCLUIDOS_DEFAULT = [10, 11, 12]


def get_vendedores_excluidos_str(db: Session) -> str:
    """Obtiene vendedores excluidos de BD + default"""
    from app.models.vendedor_excluido import VendedorExcluido

    excluidos_bd = db.query(VendedorExcluido.sm_id).all()
    excluidos_ids = {e.sm_id for e in excluidos_bd}
    todos_excluidos = excluidos_ids.union(set(VENDEDORES_EXCLUIDOS_DEFAULT))

    if not todos_excluidos:
        return "0"
    return ",".join(map(str, sorted(todos_excluidos)))


def obtener_ventas_fuera_ml(db: Session, from_date, to_date):
    """
    Obtiene todas las ventas fuera de ML con métricas ya calculadas
    """
    vendedores_excluidos_str = get_vendedores_excluidos_str(db)
    vendedores_excluidos = [int(x) for x in vendedores_excluidos_str.split(",")]

    query = text("""
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
        GROUP BY tit.it_isassociationgroup, tit.ct_transaction
    )
    SELECT
        tit.it_transaction,
        tit.ct_transaction,
        COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice) as item_id,
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
        AND tct.df_id = ANY(:df_ids)
        AND (tit.item_id != ALL(:items_excluidos) OR tit.item_id IS NULL)
        AND tct.cust_id != ALL(:clientes_excluidos)
        AND tct.sm_id != ALL(:vendedores_excluidos)
        AND tit.it_qty <> 0
        AND tct.sd_id = ANY(:sd_ids)
        -- Excluir items "Envio" (lógica igual a query original)
        AND NOT (
            CASE
                WHEN tit.item_id IS NULL AND tit.it_item_id_origin IS NULL
                THEN COALESCE(titd.itm_desc, '')
                ELSE COALESCE(ti.item_desc, '')
            END ILIKE '%envio%'
        )
        -- Excluir componentes de combos (solo mostrar el item principal)
        AND NOT (
            COALESCE(tit.it_isassociation, false) = true
            AND COALESCE(tit.it_order, 1) <> 1
            AND tit.it_isassociationgroup IS NOT NULL
        )
    ORDER BY tct.ct_date, tit.it_transaction
    """)

    result = db.execute(
        query,
        {
            "from_date": from_date,
            "to_date": to_date,
            "df_ids": DF_PERMITIDOS,
            "items_excluidos": ITEMS_EXCLUIDOS,
            "clientes_excluidos": CLIENTES_EXCLUIDOS,
            "vendedores_excluidos": vendedores_excluidos,
            "sd_ids": SD_TODOS,
        },
    )

    return result.fetchall()


def process_and_insert(db: Session, rows):
    """Procesa los registros y los inserta en ventas_fuera_ml_metricas"""

    if not rows:
        print("  ⚠️  No hay datos para procesar")
        return 0, 0, 0

    print(f"\n📊 Procesando {len(rows)} registros...")

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

    existing_records = db.query(VentaFueraMLMetrica).filter(VentaFueraMLMetrica.it_transaction.in_(incoming_ids)).all()

    # Crear mapa it_transaction → registro para lookup O(1)
    existing_map = {record.it_transaction: record for record in existing_records}
    print(f"  Encontrados {len(existing_map)} registros existentes en DB")

    total_insertados = 0
    total_actualizados = 0
    total_errores = 0
    fecha_calculo = date.today()

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
            ganancia = monto_total - costo_total

            # Markup = (monto / costo) - 1 (solo si hay costo)
            markup_porcentaje = None
            if costo_total > 0:
                markup_porcentaje = ((monto_total / costo_total) - 1) * 100
                # Limitar a rango válido
                if markup_porcentaje > 99999999.99:
                    markup_porcentaje = 99999999.99
                elif markup_porcentaje < -99999999.99:
                    markup_porcentaje = -99999999.99

            data = {
                "it_transaction": row.it_transaction,
                "ct_transaction": row.ct_transaction,
                "item_id": row.item_id,
                "codigo": row.codigo,
                "descripcion": row.descripcion[:500] if row.descripcion else None,
                "marca": row.marca,
                "categoria": row.categoria,
                "subcategoria": row.subcategoria,
                "bra_id": row.bra_id,
                "sucursal": row.sucursal,
                "sm_id": row.sm_id,
                "vendedor": row.vendedor,
                "cust_id": row.cust_id,
                "cliente": row.cliente,
                "df_id": row.df_id,
                "tipo_comprobante": row.tipo_comprobante,
                "numero_comprobante": row.numero_comprobante,
                "fecha_venta": row.fecha_venta,
                "fecha_calculo": fecha_calculo,
                "sd_id": row.sd_id,
                "signo": signo,
                "cantidad": Decimal(str(row.cantidad or 0)),
                "monto_unitario": Decimal(str(row.monto_unitario or 0)),
                "monto_total": Decimal(str(monto_total)),
                "iva_porcentaje": Decimal(str(iva_porcentaje)),
                "monto_iva": Decimal(str(monto_iva)),
                "monto_con_iva": Decimal(str(monto_con_iva)),
                "costo_unitario": Decimal(str(row.costo_unitario or 0)),
                "costo_total": Decimal(str(costo_total)),
                "moneda_costo": row.moneda_costo,
                "cotizacion_dolar": Decimal(str(row.cotizacion_dolar)) if row.cotizacion_dolar else None,
                "ganancia": Decimal(str(ganancia)),
                "markup_porcentaje": Decimal(str(markup_porcentaje)) if markup_porcentaje is not None else None,
                "es_combo": bool(row.es_combo) if row.es_combo is not None else False,
                "combo_group_id": int(row.combo_group_id) if row.combo_group_id else None,
            }

            if existente:
                for key, value in data.items():
                    if key != "it_transaction":
                        setattr(existente, key, value)
                total_actualizados += 1
            else:
                nueva_metrica = VentaFueraMLMetrica(**data)
                db.add(nueva_metrica)
                total_insertados += 1

            # Commit cada 500 registros
            if (total_insertados + total_actualizados) % 500 == 0:
                db.commit()
                print(f"  📊 Progreso: {total_insertados + total_actualizados}/{len(rows)}")

        except Exception as e:
            total_errores += 1
            print(f"  ⚠️  Error procesando transacción {row.it_transaction}: {str(e)}")
            db.rollback()
            continue

    # Commit final
    db.commit()

    return total_insertados, total_actualizados, total_errores


def main():
    parser = argparse.ArgumentParser(description="Agregar métricas de ventas fuera de ML")
    parser.add_argument("--full", action="store_true", help="Reprocesar todo (último año)")
    parser.add_argument("--days", type=int, default=None, help="Procesar últimos N días")
    parser.add_argument("--minutes", type=int, default=10, help="Minutos hacia atrás (modo incremental)")
    parser.add_argument("--from-date", type=str, default=None, help="Fecha desde (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, default=None, help="Fecha hasta (YYYY-MM-DD)")
    args = parser.parse_args()

    now = datetime.now()

    if args.from_date and args.to_date:
        # Modo fecha específica
        from_date = args.from_date
        to_date = args.to_date + " 23:59:59"
        mode = "PERÍODO ESPECÍFICO"
    elif args.full:
        # Modo completo: último año
        from_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d 23:59:59")
        mode = "COMPLETO (último año)"
    elif args.days:
        # Modo días específicos
        from_date = (now - timedelta(days=args.days)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d 23:59:59")
        mode = f"ÚLTIMOS {args.days} DÍAS"
    else:
        # Modo incremental (default)
        from_date = (now - timedelta(minutes=args.minutes)).strftime("%Y-%m-%d %H:%M:%S")
        to_date = now.strftime("%Y-%m-%d %H:%M:%S")
        mode = f"INCREMENTAL (últimos {args.minutes} minutos)"

    print("=" * 60)
    print(f"MÉTRICAS VENTAS FUERA ML - {mode}")
    print("=" * 60)
    print(f"Ejecutado: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Rango: {from_date} a {to_date}")

    db = SessionLocal()

    try:
        # Obtener datos
        print("\n🔍 Consultando ventas fuera de ML...")
        rows = obtener_ventas_fuera_ml(db, from_date, to_date)
        print(f"  ✓ Obtenidos {len(rows)} registros")

        # Procesar e insertar
        insertados, actualizados, errores = process_and_insert(db, rows)

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
