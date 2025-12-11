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
from sqlalchemy import text, and_, or_, func, case, desc

from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.notificacion import Notificacion
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario, RolUsuario
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.cur_exch_history import CurExchHistory
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
            COALESCE(tb.brand_desc, pe.marca) as marca,
            COALESCE(tc.cat_desc, pe.categoria) as categoria,
            COALESCE(tsc.subcat_desc, (SELECT s.subcat_desc FROM tb_subcategory s WHERE s.subcat_id = pe.subcategoria_id LIMIT 1)) as subcategoria,
            COALESCE(ti.item_code, pe.codigo) as codigo,
            COALESCE(UPPER(ti.item_desc), UPPER(pe.descripcion)) as descripcion,
            tmlod.mlo_quantity as cantidad,
            tmlod.mlo_unit_price as monto_unitario,
            tmlod.mlo_unit_price * tmlod.mlo_quantity as monto_total,

            -- Costo: Primero verificar si fecha_venta >= coslis_cd de tb_item_cost_list
            -- Si es así, usar ese costo. Si no, buscar en histórico.
            COALESCE(
                -- Opción 1: Si fecha_venta >= coslis_cd, usar costo actual
                (
                    SELECT ticl.curr_id
                    FROM tb_item_cost_list ticl
                    WHERE ticl.item_id = tmlod.item_id
                      AND ticl.coslis_id = 1
                      AND ticl.coslis_cd IS NOT NULL
                      AND tmloh.mlo_cd >= ticl.coslis_cd
                ),
                -- Opción 2: Buscar en histórico
                (
                    SELECT iclh.curr_id
                    FROM tb_item_cost_list_history iclh
                    WHERE iclh.item_id = tmlod.item_id
                      AND iclh.iclh_cd <= tmloh.mlo_cd
                      AND iclh.coslis_id = 1
                    ORDER BY iclh.iclh_id DESC
                    LIMIT 1
                ),
                -- Fallback: costo actual sin verificar fecha
                (
                    SELECT ticl.curr_id
                    FROM tb_item_cost_list ticl
                    WHERE ticl.item_id = tmlod.item_id
                      AND ticl.coslis_id = 1
                )
            ) as moneda_costo,

            -- Costo sin IVA en PESOS (convierte USD a ARS usando tipo de cambio)
            -- Lógica: Si fecha_venta >= coslis_cd -> usar tb_item_cost_list
            --         Si no -> buscar en tb_item_cost_list_history
            -- TC: Primero tipo_cambio, fallback tb_cur_exch_history
            COALESCE(
                -- Opción 1: Si fecha_venta >= coslis_cd, usar costo actual
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
                      AND ticl.coslis_id = 1
                      AND ticl.coslis_cd IS NOT NULL
                      AND tmloh.mlo_cd >= ticl.coslis_cd
                ),
                -- Opción 2: Buscar en histórico el último costo antes de la venta
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
                      AND iclh.coslis_id = 1
                      AND iclh.iclh_price > 0
                    ORDER BY iclh.iclh_id DESC
                    LIMIT 1
                ),
                -- Fallback: costo actual sin verificar fecha
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
                      AND ticl.coslis_id = 1
                ),
                0
            ) as costo_sin_iva,

            COALESCE(ttn.tax_percentage, 21.0) as iva,

            -- Tipo de cambio al momento de la venta (primero tipo_cambio, fallback tb_cur_exch_history)
            COALESCE(
                -- Opción 1: Buscar en tabla tipo_cambio por fecha de venta
                (
                    SELECT tc.venta
                    FROM tipo_cambio tc
                    WHERE tc.moneda = 'USD'
                      AND tc.fecha <= tmloh.mlo_cd::date
                    ORDER BY tc.fecha DESC
                    LIMIT 1
                ),
                -- Fallback: tb_cur_exch_history
                (
                    SELECT ceh.ceh_exchange
                    FROM tb_cur_exch_history ceh
                    WHERE ceh.ceh_cd <= tmloh.mlo_cd
                    ORDER BY ceh.ceh_cd DESC
                    LIMIT 1
                )
            ) as cambio_momento,

            tmlos.ml_logistic_type as tipo_logistica,
            tmloh.ml_id,
            tmloh.ml_pack_id as pack_id,
            tmloh.mlshippingid as shipping_id,
            -- Costo de envío del producto (viene con IVA)
            pe.envio as envio_producto,

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
    # Usar el costo de envío del PRODUCTO (productos_erp.envio)
    # Ya viene con IVA, el helper lo multiplica por cantidad y le resta el IVA
    costo_envio_producto = None
    if row.envio_producto:
        costo_envio_producto = float(row.envio_producto)

    # Obtener comisión usando el sistema versionado (igual que pricing)
    from app.services.pricing_calculator import obtener_comision_versionada, obtener_grupo_subcategoria

    comision_porcentaje = None
    if db_session and row.subcat_id and row.pricelist_id:
        grupo_id = obtener_grupo_subcategoria(db_session, row.subcat_id)
        if grupo_id:
            fecha_venta = row.fecha_venta.date() if hasattr(row.fecha_venta, 'date') else row.fecha_venta
            comision_porcentaje = obtener_comision_versionada(db_session, grupo_id, row.pricelist_id, fecha_venta)

    # Fallback al valor de la query si no se pudo obtener del sistema versionado
    if comision_porcentaje is None:
        comision_porcentaje = float(row.comision_base_porcentaje or 12.0)

    # Llamar al helper centralizado - ahora calcula la comisión dinámicamente
    metricas = calcular_metricas_ml(
        monto_unitario=float(row.monto_unitario or 0),
        cantidad=float(row.cantidad or 1),
        iva_porcentaje=float(row.iva or 0),
        costo_unitario_sin_iva=float(row.costo_sin_iva or 0),
        costo_envio_ml=costo_envio_producto,
        count_per_pack=count_per_pack,
        # Parámetros para calcular comisión dinámicamente
        subcat_id=row.subcat_id,
        pricelist_id=row.pricelist_id,
        fecha_venta=row.fecha_venta,
        comision_base_porcentaje=comision_porcentaje,
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
                f"⚠️ Markup: {markup_real:.2f}% (esperado {markup_calculado:.2f}%) - "
                f"${float(row.monto_total):,.2f}"
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
                    # DEBUG: Ver qué valores vienen
                    print(f"DEBUG item_id={row.item_id}: moneda_costo={row.moneda_costo} (type={type(row.moneda_costo)}), cambio_momento={row.cambio_momento}")

                    # Obtener TC usado para la operación (de cambio_momento de la query)
                    # Solo se usa si el costo está en USD (curr_id = 2)
                    # Convertir a int para comparación segura (puede venir como Decimal)
                    es_usd = row.moneda_costo is not None and int(row.moneda_costo) == 2

                    tc_operacion = None
                    if es_usd and row.cambio_momento:
                        tc_operacion = float(row.cambio_momento)

                    print(f"DEBUG: es_usd={es_usd}, tc_operacion={tc_operacion}")

                    # Obtener costo actual del producto desde ProductoERP
                    costo_actual = None
                    tc_actual = None  # TC usado para costo actual
                    try:
                        producto_actual = db.query(ProductoERP).filter(
                            ProductoERP.item_id == row.item_id
                        ).first()
                        if producto_actual and producto_actual.costo is not None:
                            # Convertir a ARS si está en USD (curr_id = 2)
                            if es_usd:
                                # Usar tabla tipo_cambio (TC actual del día)
                                from app.models.tipo_cambio import TipoCambio
                                tc = db.query(TipoCambio).filter(
                                    TipoCambio.moneda == "USD"
                                ).order_by(TipoCambio.fecha.desc()).first()
                                if tc and tc.venta:
                                    tc_actual = float(tc.venta)
                                else:
                                    # Fallback a tb_cur_exch_history
                                    tc_query = text("""
                                        SELECT ceh_exchange FROM tb_cur_exch_history ORDER BY ceh_cd DESC LIMIT 1
                                    """)
                                    tc_result = db.execute(tc_query).fetchone()
                                    tc_actual = float(tc_result[0]) if tc_result else 1.0
                                costo_actual = float(producto_actual.costo) * tc_actual
                            else:
                                costo_actual = float(producto_actual.costo)
                    except:
                        pass

                    # Obtener precio_lista_ml del producto
                    precio_lista_ml = None
                    try:
                        if producto_actual and producto_actual.precio_lista_ml is not None:
                            precio_lista_ml = float(producto_actual.precio_lista_ml)
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

                    # Intentar con marca de tb_brand primero
                    if row.marca:
                        marca_pm = db.query(MarcaPM).filter(MarcaPM.marca == row.marca).first()
                        if marca_pm and marca_pm.usuario:
                            pm_nombre = marca_pm.usuario.nombre

                    # Si no encontró PM, intentar con marca de productos_erp como fallback
                    if not pm_nombre and producto_actual and producto_actual.marca:
                        marca_pm = db.query(MarcaPM).filter(MarcaPM.marca == producto_actual.marca).first()
                        if marca_pm and marca_pm.usuario:
                            pm_nombre = marca_pm.usuario.nombre

                    # Calcular costo total de la operación (unitario × cantidad)
                    costo_total_operacion = None
                    if row.costo_sin_iva is not None and row.cantidad:
                        costo_total_operacion = float(row.costo_sin_iva) * float(row.cantidad)

                    # Obtener código y descripción del producto
                    codigo_prod = row.codigo
                    descripcion_prod = row.descripcion

                    # Si no vienen de tb_item, buscar en productos_erp como fallback
                    if not codigo_prod or not descripcion_prod:
                        producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == row.item_id).first()
                        if producto_erp:
                            if not codigo_prod:
                                codigo_prod = producto_erp.codigo
                            if not descripcion_prod:
                                descripcion_prod = producto_erp.descripcion

                    notificacion = Notificacion(
                        user_id=usuario.id,
                        tipo='markup_bajo',
                        item_id=row.item_id,
                        id_operacion=row.id_operacion,
                        ml_id=row.ml_id,
                        pack_id=row.pack_id,
                        codigo_producto=codigo_prod,
                        descripcion_producto=descripcion_prod[:500] if descripcion_prod else None,
                        mensaje=mensaje,
                        markup_real=Decimal(str(markup_real)),
                        markup_objetivo=Decimal(str(markup_calculado)),
                        monto_venta=Decimal(str(row.monto_total)),
                        fecha_venta=row.fecha_venta,
                        # Campos adicionales
                        pm=pm_nombre,
                        costo_operacion=Decimal(str(costo_total_operacion)) if costo_total_operacion is not None else None,
                        costo_actual=Decimal(str(costo_actual)) if costo_actual is not None else None,
                        tipo_cambio_operacion=Decimal(str(tc_operacion)) if tc_operacion is not None else None,
                        tipo_cambio_actual=Decimal(str(tc_actual)) if tc_actual is not None else None,
                        precio_venta_unitario=Decimal(str(row.monto_unitario)) if row.monto_unitario is not None else None,
                        precio_publicacion=Decimal(str(precio_lista_ml)) if precio_lista_ml is not None else None,
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


def registrar_consumo_grupo_offset(db: Session, row, es_nuevo: bool):
    """
    Registra el consumo de offset de grupo para una venta ML.
    Solo registra si el item pertenece a un grupo con límites.

    Args:
        db: Sesión de base de datos
        row: Datos de la venta
        es_nuevo: True si es una nueva venta, False si es actualización

    Returns:
        True si se registró consumo, False si no
    """
    try:
        # Buscar si el item tiene un offset con grupo que tiene límites
        offset = db.query(OffsetGanancia).filter(
            OffsetGanancia.item_id == row.item_id,
            OffsetGanancia.grupo_id.isnot(None),
            OffsetGanancia.aplica_ml == True,
            OffsetGanancia.fecha_desde <= row.fecha_venta.date() if hasattr(row.fecha_venta, 'date') else row.fecha_venta,
            or_(
                OffsetGanancia.fecha_hasta.is_(None),
                OffsetGanancia.fecha_hasta >= row.fecha_venta.date() if hasattr(row.fecha_venta, 'date') else row.fecha_venta
            ),
            or_(
                OffsetGanancia.max_unidades.isnot(None),
                OffsetGanancia.max_monto_usd.isnot(None)
            )
        ).first()

        if not offset:
            return False

        # Verificar si ya existe un registro de consumo para esta operación
        consumo_existente = db.query(OffsetGrupoConsumo).filter(
            OffsetGrupoConsumo.id_operacion == row.id_operacion
        ).first()

        if consumo_existente:
            # Si existe y no es nuevo, actualizar si cambió la cantidad
            if not es_nuevo and consumo_existente.cantidad != row.cantidad:
                # Recalcular monto
                cotizacion = float(row.cambio_momento) if row.cambio_momento else 1000.0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(
                    offset, row.cantidad, row.costo_sin_iva, cotizacion
                )

                # Actualizar resumen (restar viejo, sumar nuevo)
                actualizar_resumen_grupo(
                    db, offset.grupo_id,
                    consumo_existente.cantidad, float(consumo_existente.monto_offset_aplicado or 0),
                    float(consumo_existente.monto_offset_usd or 0),
                    restar=True
                )

                consumo_existente.cantidad = row.cantidad
                consumo_existente.monto_offset_aplicado = monto_offset_ars
                consumo_existente.monto_offset_usd = monto_offset_usd
                consumo_existente.cotizacion_dolar = cotizacion

                actualizar_resumen_grupo(
                    db, offset.grupo_id,
                    row.cantidad, monto_offset_ars, monto_offset_usd,
                    restar=False
                )
            return True

        # Calcular monto del offset
        cotizacion = float(row.cambio_momento) if row.cambio_momento else 1000.0
        monto_offset_ars, monto_offset_usd = calcular_monto_offset(
            offset, row.cantidad, row.costo_sin_iva, cotizacion
        )

        # Crear registro de consumo
        consumo = OffsetGrupoConsumo(
            grupo_id=offset.grupo_id,
            id_operacion=row.id_operacion,
            tipo_venta='ml',
            fecha_venta=row.fecha_venta,
            item_id=row.item_id,
            cantidad=row.cantidad,
            offset_id=offset.id,
            monto_offset_aplicado=monto_offset_ars,
            monto_offset_usd=monto_offset_usd,
            cotizacion_dolar=cotizacion
        )
        db.add(consumo)

        # Actualizar resumen del grupo
        actualizar_resumen_grupo(
            db, offset.grupo_id,
            row.cantidad, monto_offset_ars, monto_offset_usd,
            restar=False, offset=offset
        )

        return True

    except Exception as e:
        # No fallar el proceso principal por error en consumo
        print(f"  ⚠️  Error registrando consumo offset para op {row.id_operacion}: {e}")
        return False


def calcular_monto_offset(offset, cantidad, costo_sin_iva, cotizacion):
    """Calcula el monto del offset en ARS y USD"""
    costo = float(costo_sin_iva) if costo_sin_iva else 0

    if offset.tipo_offset == 'monto_fijo':
        monto_offset = float(offset.monto or 0)
        if offset.moneda == 'USD':
            monto_offset_ars = monto_offset * cotizacion
            monto_offset_usd = monto_offset
        else:
            monto_offset_ars = monto_offset
            monto_offset_usd = monto_offset / cotizacion if cotizacion > 0 else 0
    elif offset.tipo_offset == 'monto_por_unidad':
        monto_por_u = float(offset.monto or 0)
        if offset.moneda == 'USD':
            monto_offset_ars = monto_por_u * cantidad * cotizacion
            monto_offset_usd = monto_por_u * cantidad
        else:
            monto_offset_ars = monto_por_u * cantidad
            monto_offset_usd = monto_por_u * cantidad / cotizacion if cotizacion > 0 else 0
    elif offset.tipo_offset == 'porcentaje_costo':
        porcentaje = float(offset.porcentaje or 0)
        monto_offset_ars = costo * cantidad * (porcentaje / 100)
        monto_offset_usd = monto_offset_ars / cotizacion if cotizacion > 0 else 0
    else:
        monto_offset_ars = 0
        monto_offset_usd = 0

    return monto_offset_ars, monto_offset_usd


def actualizar_resumen_grupo(db: Session, grupo_id: int, cantidad: int,
                              monto_ars: float, monto_usd: float,
                              restar: bool = False, offset=None):
    """Actualiza o crea el resumen del grupo"""
    resumen = db.query(OffsetGrupoResumen).filter(
        OffsetGrupoResumen.grupo_id == grupo_id
    ).first()

    factor = -1 if restar else 1

    if resumen:
        resumen.total_unidades = (resumen.total_unidades or 0) + (cantidad * factor)
        resumen.total_monto_ars = float(resumen.total_monto_ars or 0) + (monto_ars * factor)
        resumen.total_monto_usd = float(resumen.total_monto_usd or 0) + (monto_usd * factor)
        resumen.cantidad_ventas = (resumen.cantidad_ventas or 0) + factor
        resumen.ultima_venta_fecha = datetime.now()

        # Verificar límites si se está sumando
        if not restar and offset:
            if offset.max_unidades and resumen.total_unidades >= offset.max_unidades:
                if not resumen.limite_alcanzado:
                    resumen.limite_alcanzado = 'unidades'
                    resumen.fecha_limite_alcanzado = datetime.now()
            elif offset.max_monto_usd and resumen.total_monto_usd >= offset.max_monto_usd:
                if not resumen.limite_alcanzado:
                    resumen.limite_alcanzado = 'monto'
                    resumen.fecha_limite_alcanzado = datetime.now()
    else:
        # Crear nuevo resumen
        resumen = OffsetGrupoResumen(
            grupo_id=grupo_id,
            total_unidades=cantidad,
            total_monto_ars=monto_ars,
            total_monto_usd=monto_usd,
            cantidad_ventas=1,
            ultima_venta_fecha=datetime.now()
        )
        db.add(resumen)

        # Verificar límites
        if offset:
            if offset.max_unidades and cantidad >= offset.max_unidades:
                resumen.limite_alcanzado = 'unidades'
                resumen.fecha_limite_alcanzado = datetime.now()
            elif offset.max_monto_usd and monto_usd >= offset.max_monto_usd:
                resumen.limite_alcanzado = 'monto'
                resumen.fecha_limite_alcanzado = datetime.now()


def registrar_consumo_offset_individual(db: Session, row, es_nuevo: bool):
    """
    Registra el consumo de offsets individuales (sin grupo) con límites.
    Aplica a offsets por producto, marca, categoría, subcategoría.

    Args:
        db: Sesión de base de datos
        row: Datos de la venta
        es_nuevo: True si es una nueva venta, False si es actualización

    Returns:
        int: Cantidad de consumos registrados
    """
    try:
        fecha_venta = row.fecha_venta.date() if hasattr(row.fecha_venta, 'date') else row.fecha_venta

        # Buscar offsets individuales (sin grupo) con límites que apliquen a esta venta
        # Puede haber múltiples offsets aplicables (por producto, marca, categoría, etc.)
        offsets = db.query(OffsetGanancia).filter(
            OffsetGanancia.grupo_id.is_(None),  # Sin grupo
            OffsetGanancia.aplica_ml == True,
            OffsetGanancia.fecha_desde <= fecha_venta,
            or_(
                OffsetGanancia.fecha_hasta.is_(None),
                OffsetGanancia.fecha_hasta >= fecha_venta
            ),
            or_(
                OffsetGanancia.max_unidades.isnot(None),
                OffsetGanancia.max_monto_usd.isnot(None)
            ),
            # Filtrar por criterios que apliquen a esta venta
            or_(
                OffsetGanancia.item_id == row.item_id,  # Por producto
                and_(
                    OffsetGanancia.marca == row.marca,
                    OffsetGanancia.item_id.is_(None),
                    OffsetGanancia.categoria.is_(None),
                    OffsetGanancia.subcategoria_id.is_(None)
                ),  # Por marca (sin producto específico)
                and_(
                    OffsetGanancia.categoria == row.categoria,
                    OffsetGanancia.item_id.is_(None),
                    OffsetGanancia.marca.is_(None),
                    OffsetGanancia.subcategoria_id.is_(None)
                ),  # Por categoría
                and_(
                    OffsetGanancia.subcategoria_id == row.subcat_id,
                    OffsetGanancia.item_id.is_(None)
                )  # Por subcategoría
            )
        ).all()

        if not offsets:
            return 0

        cotizacion = float(row.cambio_momento) if row.cambio_momento else 1000.0
        consumos_registrados = 0

        for offset in offsets:
            # Verificar si ya existe un registro de consumo para esta operación y offset
            consumo_existente = db.query(OffsetIndividualConsumo).filter(
                OffsetIndividualConsumo.id_operacion == row.id_operacion,
                OffsetIndividualConsumo.offset_id == offset.id
            ).first()

            if consumo_existente:
                # Si existe y no es nuevo, actualizar si cambió la cantidad
                if not es_nuevo and consumo_existente.cantidad != row.cantidad:
                    monto_offset_ars, monto_offset_usd = calcular_monto_offset(
                        offset, row.cantidad, row.costo_sin_iva, cotizacion
                    )

                    # Actualizar resumen (restar viejo, sumar nuevo)
                    actualizar_resumen_offset_individual(
                        db, offset.id,
                        consumo_existente.cantidad, float(consumo_existente.monto_offset_aplicado or 0),
                        float(consumo_existente.monto_offset_usd or 0),
                        restar=True
                    )

                    consumo_existente.cantidad = row.cantidad
                    consumo_existente.monto_offset_aplicado = monto_offset_ars
                    consumo_existente.monto_offset_usd = monto_offset_usd
                    consumo_existente.cotizacion_dolar = cotizacion

                    actualizar_resumen_offset_individual(
                        db, offset.id,
                        row.cantidad, monto_offset_ars, monto_offset_usd,
                        restar=False, offset=offset
                    )
                continue

            # Calcular monto del offset
            monto_offset_ars, monto_offset_usd = calcular_monto_offset(
                offset, row.cantidad, row.costo_sin_iva, cotizacion
            )

            # Crear registro de consumo
            consumo = OffsetIndividualConsumo(
                offset_id=offset.id,
                id_operacion=row.id_operacion,
                tipo_venta='ml',
                fecha_venta=row.fecha_venta,
                item_id=row.item_id,
                cantidad=row.cantidad,
                monto_offset_aplicado=monto_offset_ars,
                monto_offset_usd=monto_offset_usd,
                cotizacion_dolar=cotizacion
            )
            db.add(consumo)

            # Actualizar resumen del offset
            actualizar_resumen_offset_individual(
                db, offset.id,
                row.cantidad, monto_offset_ars, monto_offset_usd,
                restar=False, offset=offset
            )

            consumos_registrados += 1

        return consumos_registrados

    except Exception as e:
        print(f"  ⚠️  Error registrando consumo offset individual para op {row.id_operacion}: {e}")
        return 0


def actualizar_resumen_offset_individual(db: Session, offset_id: int, cantidad: int,
                                          monto_ars: float, monto_usd: float,
                                          restar: bool = False, offset=None):
    """Actualiza o crea el resumen del offset individual"""
    resumen = db.query(OffsetIndividualResumen).filter(
        OffsetIndividualResumen.offset_id == offset_id
    ).first()

    factor = -1 if restar else 1

    if resumen:
        resumen.total_unidades = (resumen.total_unidades or 0) + (cantidad * factor)
        resumen.total_monto_ars = float(resumen.total_monto_ars or 0) + (monto_ars * factor)
        resumen.total_monto_usd = float(resumen.total_monto_usd or 0) + (monto_usd * factor)
        resumen.cantidad_ventas = (resumen.cantidad_ventas or 0) + factor
        resumen.ultima_venta_fecha = datetime.now()

        # Verificar límites si se está sumando
        if not restar and offset:
            if offset.max_unidades and resumen.total_unidades >= offset.max_unidades:
                if not resumen.limite_alcanzado:
                    resumen.limite_alcanzado = 'unidades'
                    resumen.fecha_limite_alcanzado = datetime.now()
            elif offset.max_monto_usd and resumen.total_monto_usd >= offset.max_monto_usd:
                if not resumen.limite_alcanzado:
                    resumen.limite_alcanzado = 'monto'
                    resumen.fecha_limite_alcanzado = datetime.now()
    else:
        # Crear nuevo resumen
        resumen = OffsetIndividualResumen(
            offset_id=offset_id,
            total_unidades=cantidad,
            total_monto_ars=monto_ars,
            total_monto_usd=monto_usd,
            cantidad_ventas=1,
            ultima_venta_fecha=datetime.now()
        )
        db.add(resumen)

        # Verificar límites
        if offset:
            if offset.max_unidades and cantidad >= offset.max_unidades:
                resumen.limite_alcanzado = 'unidades'
                resumen.fecha_limite_alcanzado = datetime.now()
            elif offset.max_monto_usd and monto_usd >= offset.max_monto_usd:
                resumen.limite_alcanzado = 'monto'
                resumen.fecha_limite_alcanzado = datetime.now()


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

            # Registrar consumo de offsets (si aplica)
            es_nuevo = not existente
            registrar_consumo_grupo_offset(db, row, es_nuevo)  # Offsets de grupo
            registrar_consumo_offset_individual(db, row, es_nuevo)  # Offsets individuales

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

    print("=" * 60)
    print("MÉTRICAS ML INCREMENTAL - Últimos 10 minutos")
    print("=" * 60)
    print(f"Ejecutado: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Rango: {from_datetime.strftime('%Y-%m-%d %H:%M:%S')} a {to_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

    db = SessionLocal()

    try:
        # Obtener datos de tablas locales - pasar datetime completo, no solo date
        rows = calcular_metricas_locales(db, from_datetime, to_datetime)

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
