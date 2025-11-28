"""
Script para agregar métricas de ventas ML - INCREMENTAL
Versión incremental que procesa los últimos 10 minutos de datos
Diseñado para ejecutarse cada 5 minutos en cron

Ejecutar:
    python app/scripts/agregar_metricas_ml_incremental.py
"""
import sys
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
from sqlalchemy import text, and_, func, case, desc

from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.notificacion import Notificacion
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario, RolUsuario
from app.utils.ml_metrics_calculator import calcular_metricas_ml


def calcular_metricas_locales(db: Session, from_date: date, to_date: date):
    """
    Consulta las tablas locales de PostgreSQL para calcular métricas
    Replica la query del ERP pero usando tablas tb_* locales
    """

    print(f"\n🔍 Consultando tablas locales PostgreSQL...")
    print(f"   Rango: {from_date} a {to_date}")

    # Query complejo que replica la lógica del ERP
    query = text("""
    WITH sales_data AS (
        SELECT DISTINCT ON (tmlod.mlo_id)
            tmlod.mlo_id as id_operacion,
            tmlod.item_id,
            tct.ct_transaction,
            tmloh.mlo_cd as fecha_venta,
            tb.brand_desc as marca,
            tc.cat_desc as categoria,
            tsc.subcat_desc as subcategoria,
            ti.item_code as codigo,
            UPPER(ti.item_desc) as descripcion,
            tmlod.mlo_quantity as cantidad,
            tmlod.mlo_unit_price as monto_unitario,
            tmlod.mlo_unit_price * tmlod.mlo_quantity as monto_total,

            -- Costo: buscar el último costo antes de la fecha de venta
            (
                SELECT iclh.curr_id
                FROM tb_item_cost_list_history iclh
                WHERE iclh.item_id = tmlod.item_id
                  AND iclh.iclh_cd <= tmloh.mlo_cd
                  AND iclh.coslis_id = 1
                ORDER BY iclh.iclh_id DESC
                LIMIT 1
            ) as moneda_costo,

            -- Costo sin IVA en PESOS (convierte USD a ARS usando tipo de cambio)
            COALESCE(
                (
                    SELECT CASE
                        WHEN iclh.curr_id = 2 THEN  -- USD
                            CASE
                                WHEN iclh.iclh_price = 0 THEN ticl.coslis_price * (
                                    SELECT ceh.ceh_exchange
                                    FROM tb_cur_exch_history ceh
                                    WHERE ceh.ceh_cd <= tmloh.mlo_cd
                                    ORDER BY ceh.ceh_cd DESC
                                    LIMIT 1
                                )
                                ELSE iclh.iclh_price * (
                                    SELECT ceh.ceh_exchange
                                    FROM tb_cur_exch_history ceh
                                    WHERE ceh.ceh_cd <= tmloh.mlo_cd
                                    ORDER BY ceh.ceh_cd DESC
                                    LIMIT 1
                                )
                            END
                        ELSE  -- ARS
                            CASE
                                WHEN iclh.iclh_price = 0 THEN ticl.coslis_price
                                ELSE iclh.iclh_price
                            END
                    END
                    FROM tb_item_cost_list_history iclh
                    LEFT JOIN tb_item_cost_list ticl
                        ON ticl.item_id = iclh.item_id
                        AND ticl.coslis_id = 1
                    WHERE iclh.item_id = tmlod.item_id
                      AND iclh.iclh_cd <= tmloh.mlo_cd
                      AND iclh.coslis_id = 1
                    ORDER BY iclh.iclh_id DESC
                    LIMIT 1
                ),
                (
                    SELECT CASE
                        WHEN ticl.curr_id = 2 THEN  -- USD
                            ticl.coslis_price * (
                                SELECT ceh.ceh_exchange
                                FROM tb_cur_exch_history ceh
                                WHERE ceh.ceh_cd <= tmloh.mlo_cd
                                ORDER BY ceh.ceh_cd DESC
                                LIMIT 1
                            )
                        ELSE  -- ARS
                            ticl.coslis_price
                    END
                    FROM tb_item_cost_list ticl
                    WHERE ticl.item_id = tmlod.item_id
                      AND ticl.coslis_id = 1
                ),
                0
            ) as costo_sin_iva,

            COALESCE(ttn.tax_percentage, 21.0) as iva,

            -- Tipo de cambio al momento de la venta
            (
                SELECT ceh.ceh_exchange
                FROM tb_cur_exch_history ceh
                WHERE ceh.ceh_cd <= tmloh.mlo_cd
                ORDER BY ceh.ceh_cd DESC
                LIMIT 1
            ) as cambio_momento,

            tmlos.ml_logistic_type as tipo_logistica,
            tmloh.ml_id,
            tmloh.ml_pack_id as pack_id,
            tmloh.mlshippingid as shipping_id,
            -- REGLA: Si monto_unitario < monto_tier3, NO se resta costo de envío
            --        Si monto_unitario >= monto_tier3, SÍ se resta costo de envío
            CASE
                WHEN tmlod.mlo_unit_price < (
                    SELECT monto_tier3
                    FROM pricing_constants
                    WHERE fecha_desde <= tmloh.mlo_cd::date
                    ORDER BY fecha_desde DESC
                    LIMIT 1
                )
                THEN NULL  -- No restar envío
                ELSE COALESCE(tmlip.mlp_price4freeshipping, tmlos.mlshippmentcost4seller)
            END as costo_envio_ml,
            tmlip.mlp_price4freeshipping as precio_envio_gratis,
            tmlos.mlshippmentcost4seller as costo_envio_sin_iva_orig,

            -- Obtener el porcentaje de comisión base para que el helper lo calcule
            COALESCE(
                -- Prioridad 1: Comisión específica por pricelist + grupo
                (
                    SELECT clg.comision_porcentaje
                    FROM subcategorias_grupos sg
                    JOIN comisiones_lista_grupo clg ON clg.grupo_id = sg.grupo_id
                    WHERE sg.subcat_id = tsc.subcat_id
                      AND clg.pricelist_id = COALESCE(
                          tsoh.prli_id,
                          CASE
                              WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop
                              ELSE tmlip.prli_id
                          END
                      )
                      AND clg.activo = TRUE
                    LIMIT 1
                ),
                -- Fallback: Comisión base por grupo (versionada por fecha)
                (
                    SELECT cb.comision_base
                    FROM subcategorias_grupos sg
                    JOIN comisiones_base cb ON cb.grupo_id = sg.grupo_id
                    JOIN comisiones_versiones cv ON cv.id = cb.version_id
                    WHERE sg.subcat_id = tsc.subcat_id
                      AND tmloh.mlo_cd::date BETWEEN cv.fecha_desde AND COALESCE(cv.fecha_hasta, '9999-12-31'::date)
                      AND cv.activo = TRUE
                    LIMIT 1
                ),
                -- Fallback final: 12% (comisión mínima de ML)
                12.0
            ) as comision_base_porcentaje,

            tsc.subcat_id,

            -- Price list: Prioridad 1: SaleOrderHeader, Fallback: ML Items Publicados
            COALESCE(
                tsoh.prli_id,
                CASE
                    WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop
                    ELSE tmlip.prli_id
                END
            ) as pricelist_id

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
            AND ticl.coslis_id = 1

        WHERE tmlod.item_id NOT IN (460, 3042)
          AND tmloh.mlo_cd BETWEEN :from_date AND :to_date
          AND tmloh.mlo_status <> 'cancelled'
    )
    SELECT * FROM sales_data
    ORDER BY fecha_venta, id_operacion
    """)

    result = db.execute(query, {
        'from_date': from_date,
        'to_date': to_date
    })

    rows = result.fetchall()
    print(f"  ✓ Obtenidos {len(rows)} registros de tablas locales")

    return rows


def calcular_metricas_adicionales(row, count_per_pack, db_session):
    """
    Calcula las métricas usando helper centralizado
    El helper calcula la comisión dinámicamente usando subcat_id y pricelist_id
    """
    # IMPORTANTE: Determinamos si el costo_envio_ml ya tiene IVA o no
    # - Si viene de mlp_price4freeshipping: YA tiene IVA → pasar directo
    # - Si viene de mlshippmentcost4seller: NO tiene IVA → multiplicar por 1.21
    costo_envio_para_helper = None
    if row.costo_envio_ml:
        # Si precio_envio_gratis existe y es igual a costo_envio_ml, ya tiene IVA
        if row.precio_envio_gratis and abs(float(row.precio_envio_gratis) - float(row.costo_envio_ml)) < 0.01:
            # Ya tiene IVA, pasar directo
            costo_envio_para_helper = float(row.costo_envio_ml)
        else:
            # No tiene IVA, multiplicar por 1.21
            costo_envio_para_helper = float(row.costo_envio_ml) * 1.21

    # Llamar al helper centralizado - ahora calcula la comisión dinámicamente
    metricas = calcular_metricas_ml(
        monto_unitario=float(row.monto_unitario or 0),
        cantidad=float(row.cantidad or 1),
        iva_porcentaje=float(row.iva or 0),
        costo_unitario_sin_iva=float(row.costo_sin_iva or 0),
        costo_envio_ml=costo_envio_para_helper,
        count_per_pack=count_per_pack,
        # Parámetros para calcular comisión dinámicamente
        subcat_id=row.subcat_id,
        pricelist_id=row.pricelist_id,
        fecha_venta=row.fecha_venta,
        comision_base_porcentaje=float(row.comision_base_porcentaje or 12.0),
        db_session=db_session  # Pasar sesión para obtener pricing_constants
    )

    return {
        'costo_total_sin_iva': metricas['costo_total_sin_iva'],
        'comision_ml': metricas['comision_ml'],  # Ahora viene del helper
        'costo_envio': metricas['costo_envio'],
        'monto_limpio': metricas['monto_limpio'],
        'ganancia': metricas['ganancia'],
        'markup_porcentaje': metricas['markup_porcentaje']
    }


def crear_notificacion_markup_bajo(db: Session, row, metricas, producto_erp):
    """
    Crea una notificación si el markup real es NEGATIVO y está por debajo del markup_calculado
    Solo alerta ventas en pérdida que están peor de lo esperado
    """
    if not producto_erp:
        return False

    # Buscar el pricing del producto para obtener el markup_calculado como referencia
    try:
        producto_pricing = db.query(ProductoPricing).filter(
            ProductoPricing.item_id == row.item_id
        ).first()

        if not producto_pricing or producto_pricing.markup_calculado is None:
            return False

        markup_calculado = float(producto_pricing.markup_calculado)
        markup_real = float(metricas['markup_porcentaje'])

        # Solo notificar si:
        # 1. El markup real es NEGATIVO (venta en pérdida)
        # 2. Y está por debajo del markup_calculado (peor de lo esperado)
        # 3. Con una diferencia significativa (> 0.5%)
        diferencia = markup_calculado - markup_real

        if markup_real < 0 and markup_real < markup_calculado and diferencia > 0.5:
            # Obtener TODOS los usuarios activos para notificar
            usuarios_notificar = db.query(Usuario).filter(
                Usuario.activo == True
            ).all()

            if not usuarios_notificar:
                return False

            mensaje = (
                f"⚠️ VENTA EN PÉRDIDA - Markup negativo peor de lo esperado. "
                f"Esperado: {markup_calculado:.2f}%, Real: {markup_real:.2f}% "
                f"(diferencia: {diferencia:.2f}%). "
                f"Venta: ${float(row.monto_total):,.2f}"
            )

            notificaciones_creadas = 0
            for usuario in usuarios_notificar:
                # Verificar si ya existe una notificación para esta operación y usuario
                existe_notif = db.query(Notificacion).filter(
                    Notificacion.id_operacion == row.id_operacion,
                    Notificacion.tipo == 'markup_bajo',
                    Notificacion.user_id == usuario.id
                ).first()

                if not existe_notif:
                    # Obtener costo actual del producto desde ProductoERP
                    costo_actual = None
                    try:
                        producto_actual = db.query(ProductoERP).filter(
                            ProductoERP.item_id == row.item_id
                        ).first()
                        if producto_actual and producto_actual.costo is not None:
                            # Convertir a ARS si está en USD
                            if producto_actual.moneda_costo == 'USD':
                                # Obtener último tipo de cambio
                                from sqlalchemy import text
                                tc_query = text("""
                                    SELECT ceh_exchange
                                    FROM tb_cur_exch_history
                                    ORDER BY ceh_cd DESC
                                    LIMIT 1
                                """)
                                tc_result = db.execute(tc_query).fetchone()
                                tipo_cambio = float(tc_result[0]) if tc_result else 1.0
                                costo_actual = float(producto_actual.costo) * tipo_cambio
                            else:
                                costo_actual = float(producto_actual.costo)
                    except:
                        pass

                    # Obtener porcentaje de comisión base (solo para el frontend)
                    comision_porcentaje = None
                    if row.comision_base_porcentaje is not None:
                        comision_porcentaje = float(row.comision_base_porcentaje)

                    # Obtener nombre de pricelist para tipo_publicacion
                    tipo_publicacion = None
                    if row.pricelist_id:
                        pricelist_names = {
                            4: "Clásica",
                            12: "Clásica",
                            17: "3 Cuotas",
                            18: "3 Cuotas",
                            14: "6 Cuotas",
                            19: "6 Cuotas",
                            13: "9 Cuotas",
                            20: "9 Cuotas",
                            23: "12 Cuotas",
                            21: "12 Cuotas"
                        }
                        tipo_publicacion = pricelist_names.get(row.pricelist_id, f"Lista {row.pricelist_id}")

                    # Obtener PM asignado a la marca del producto
                    from app.models.marca_pm import MarcaPM
                    pm_nombre = None
                    if row.marca:
                        marca_pm = db.query(MarcaPM).filter(MarcaPM.marca == row.marca).first()
                        if marca_pm and marca_pm.usuario:
                            pm_nombre = marca_pm.usuario.nombre

                    # Calcular costo total de la operación (unitario × cantidad)
                    costo_total_operacion = None
                    if row.costo_sin_iva is not None and row.cantidad:
                        costo_total_operacion = float(row.costo_sin_iva) * float(row.cantidad)

                    notificacion = Notificacion(
                        user_id=usuario.id,
                        tipo='markup_bajo',
                        item_id=row.item_id,
                        id_operacion=row.id_operacion,
                        ml_id=row.ml_id,
                        pack_id=row.pack_id,
                        codigo_producto=row.codigo,
                        descripcion_producto=row.descripcion[:500] if row.descripcion else None,
                        mensaje=mensaje,
                        markup_real=Decimal(str(markup_real)),
                        markup_objetivo=Decimal(str(markup_calculado)),
                        monto_venta=Decimal(str(row.monto_total)),
                        fecha_venta=row.fecha_venta,
                        # Campos adicionales
                        pm=pm_nombre,
                        costo_operacion=Decimal(str(costo_total_operacion)) if costo_total_operacion is not None else None,
                        costo_actual=Decimal(str(costo_actual)) if costo_actual is not None else None,
                        precio_venta_unitario=Decimal(str(row.monto_unitario)) if row.monto_unitario is not None else None,
                        precio_publicacion=None,  # TODO: obtener de ML si está disponible
                        tipo_publicacion=tipo_publicacion,
                        comision_ml=Decimal(str(comision_porcentaje)) if comision_porcentaje is not None else None,  # Guardar el % para mostrar
                        iva_porcentaje=Decimal(str(row.iva)) if row.iva is not None else None,
                        cantidad=int(row.cantidad) if row.cantidad else None,
                        costo_envio=Decimal(str(metricas['costo_envio'])) if metricas.get('costo_envio') else None,
                        leida=False
                    )
                    db.add(notificacion)
                    notificaciones_creadas += 1

            return notificaciones_creadas > 0

    except Exception as e:
        # Si hay error, simplemente no crear notificación (silencioso)
        return False

    return False


def process_and_insert(db: Session, rows):
    """Procesa los registros y los inserta en ml_ventas_metricas"""

    if not rows:
        print("  ⚠️  No hay datos para procesar")
        return 0, 0, 0, 0

    print(f"\n📊 Procesando {len(rows)} registros...")

    # Calcular count_per_pack (cuántos items por paquete)
    pack_counts = {}
    for row in rows:
        pack_id = row.pack_id
        if pack_id:
            pack_counts[pack_id] = pack_counts.get(pack_id, 0) + 1

    total_insertados = 0
    total_actualizados = 0
    total_errores = 0
    total_notificaciones = 0

    fecha_calculo = date.today()

    for row in rows:
        try:
            # Verificar si ya existe
            existente = db.query(MLVentaMetrica).filter(
                MLVentaMetrica.id_operacion == row.id_operacion
            ).first()

            # Calcular métricas adicionales
            count_per_pack = pack_counts.get(row.pack_id, 1)
            metricas = calcular_metricas_adicionales(row, count_per_pack, db)

            # Preparar datos
            data = {
                'id_operacion': row.id_operacion,
                'ml_order_id': str(row.ml_id) if row.ml_id else None,
                'pack_id': row.pack_id,
                'item_id': row.item_id,
                'codigo': row.codigo,
                'descripcion': row.descripcion,
                'marca': row.marca,
                'categoria': row.categoria,
                'subcategoria': row.subcategoria,
                'fecha_venta': row.fecha_venta,
                'fecha_calculo': fecha_calculo,
                'cantidad': row.cantidad,
                'monto_unitario': Decimal(str(row.monto_unitario)) if row.monto_unitario else Decimal('0'),
                'monto_total': Decimal(str(row.monto_total)) if row.monto_total else Decimal('0'),
                'costo_unitario_sin_iva': Decimal(str(row.costo_sin_iva)) if row.costo_sin_iva else Decimal('0'),
                'costo_total_sin_iva': Decimal(str(metricas['costo_total_sin_iva'])),
                'comision_ml': Decimal(str(metricas['comision_ml'])),
                'costo_envio_ml': Decimal(str(metricas['costo_envio'])),
                'tipo_logistica': row.tipo_logistica,
                'monto_limpio': Decimal(str(metricas['monto_limpio'])),
                'ganancia': Decimal(str(metricas['ganancia'])),
                'markup_porcentaje': Decimal(str(metricas['markup_porcentaje']))
            }

            if existente:
                # Actualizar
                for key, value in data.items():
                    if key != 'id_operacion':  # No actualizar PK
                        setattr(existente, key, value)
                total_actualizados += 1
            else:
                # Insertar nuevo
                nueva_metrica = MLVentaMetrica(**data)
                db.add(nueva_metrica)
                total_insertados += 1

            # Verificar markup y crear notificación si es necesario
            # NOTA: Requiere que tb_cur_exch_history esté sincronizado con el ERP
            # Ejecutar: python app/scripts/sync_cur_exch_history.py
            producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == row.item_id).first()
            if crear_notificacion_markup_bajo(db, row, metricas, producto_erp):
                total_notificaciones += 1

            # Commit cada 100 registros
            if (total_insertados + total_actualizados) % 100 == 0:
                db.commit()
                print(f"  📊 Progreso: {total_insertados + total_actualizados}/{len(rows)} | Notificaciones: {total_notificaciones}")

        except Exception as e:
            total_errores += 1
            print(f"  ⚠️  Error procesando operación {row.id_operacion}: {str(e)}")
            db.rollback()  # Rollback para continuar con los demás
            continue

    # Commit final
    db.commit()

    return total_insertados, total_actualizados, total_errores, total_notificaciones


def main():
    # INCREMENTAL: Procesar últimos 10 minutos
    now = datetime.now()
    from_datetime = now - timedelta(minutes=10)
    to_datetime = now

    from_date = from_datetime.date()
    to_date = to_datetime.date()

    print("=" * 60)
    print("MÉTRICAS ML INCREMENTAL - Últimos 10 minutos")
    print("=" * 60)
    print(f"Ejecutado: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Rango: {from_datetime.strftime('%H:%M:%S')} a {to_datetime.strftime('%H:%M:%S')}")

    db = SessionLocal()

    try:
        # Obtener datos de tablas locales
        rows = calcular_metricas_locales(db, from_date, to_date)

        # Procesar e insertar
        insertados, actualizados, errores, notificaciones = process_and_insert(db, rows)

        print("\n" + "=" * 60)
        print("✅ COMPLETADO")
        print("=" * 60)
        print(f"Insertados: {insertados}")
        print(f"Actualizados: {actualizados}")
        print(f"Errores: {errores}")
        print(f"🔔 Notificaciones creadas: {notificaciones}")
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
