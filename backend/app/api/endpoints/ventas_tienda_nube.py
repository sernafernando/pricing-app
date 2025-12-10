"""
Endpoints para métricas de ventas de Tienda Nube
Filtra específicamente por facturas de Tienda Nube (df_id 113, 114)
Incluye comisión configurable desde pricing_constants
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_
from typing import List, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal
from pydantic import BaseModel
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.pricing_constants import PricingConstants

router = APIRouter()


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
    return 1.0  # Default 1% (debe venir de constantes)


# ============================================================================
# Constantes para Tienda Nube
# ============================================================================

# df_id de facturas de Tienda Nube
DF_TIENDA_NUBE = [113, 114]

# sd_id para ventas y devoluciones
SD_VENTAS = [1, 4, 21, 56]
SD_DEVOLUCIONES = [3, 6, 23, 66]
SD_TODOS = SD_VENTAS + SD_DEVOLUCIONES

# Items excluidos
ITEMS_EXCLUIDOS = [16, 460]

# Clientes excluidos
CLIENTES_EXCLUIDOS = [11, 3900]

# Strings pre-generados para queries
DF_IDS_STR = ','.join(map(str, DF_TIENDA_NUBE))
SD_IDS_STR = ','.join(map(str, SD_TODOS))
ITEMS_EXCLUIDOS_STR = ','.join(map(str, ITEMS_EXCLUIDOS))
CLIENTES_EXCLUIDOS_STR = ','.join(map(str, CLIENTES_EXCLUIDOS))


# ============================================================================
# Schemas
# ============================================================================

class VentaTiendaNubeResponse(BaseModel):
    """Respuesta detallada de una venta de Tienda Nube"""
    id_operacion: int
    metrica_id: Optional[int] = None
    sucursal: Optional[str]
    cliente: Optional[str]
    clase_fiscal: Optional[str]
    tipo_documento: Optional[str]
    documento_numero: Optional[str]
    domicilio: Optional[str]
    ciudad: Optional[str]
    provincia: Optional[str]
    fecha: Optional[datetime]
    tipo_comprobante: Optional[str]
    clase: Optional[str]
    punto_de_venta: Optional[int]
    numero_comprobante: Optional[str]
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria: Optional[str]
    codigo_item: Optional[str]
    descripcion: Optional[str]
    cantidad: Optional[Decimal]
    precio_unitario_sin_iva: Optional[Decimal]
    iva_porcentaje: Optional[Decimal]
    cambio_al_momento: Optional[Decimal]
    precio_final_sin_iva: Optional[Decimal]
    monto_iva: Optional[Decimal]
    precio_final_con_iva: Optional[Decimal]
    costo_pesos_sin_iva: Optional[Decimal]
    comision_tn_porcentaje: Optional[Decimal]  # Comisión de Tienda Nube en %
    comision_tn_pesos: Optional[Decimal]  # Comisión de Tienda Nube en $
    monto_limpio: Optional[Decimal]  # Monto venta - comisión
    ganancia: Optional[Decimal]  # Monto limpio - costo
    markup: Optional[Decimal]
    vendedor: Optional[str]

    class Config:
        from_attributes = True


class VentaTiendaNubeStatsResponse(BaseModel):
    """Estadísticas agregadas de ventas de Tienda Nube"""
    total_ventas: int
    total_unidades: Decimal
    monto_total_sin_iva: Decimal
    monto_total_con_iva: Decimal
    comision_tn_total: Decimal  # Comisión total de Tienda Nube
    monto_limpio_total: Decimal  # Monto - comisión
    costo_total: Decimal
    ganancia_total: Decimal  # Monto limpio - costo
    markup_promedio: Optional[Decimal]
    por_sucursal: dict
    por_vendedor: dict


class VentaTiendaNubePorMarcaResponse(BaseModel):
    """Ventas agrupadas por marca"""
    marca: Optional[str]
    total_ventas: int
    unidades_vendidas: Decimal
    monto_sin_iva: Decimal
    costo_total: Decimal
    markup_promedio: Optional[Decimal]


# ============================================================================
# Helpers
# ============================================================================

def get_ventas_tienda_nube_query():
    """
    Query principal para obtener ventas de Tienda Nube.
    Similar a ventas_fuera_ml pero filtrando solo por df_id de TN.
    """
    return f"""
    WITH CostoCalculado AS (
        SELECT
            tit.it_transaction,
            tit.item_id,
            tit.it_qty,
            CASE
                WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
                WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
                ELSE 0
            END as plusorminus,
            tct.ct_date,
            tct.bra_id,
            (
                COALESCE(
                    (SELECT iclh.iclh_price
                     FROM tb_item_cost_list_history iclh
                     WHERE iclh.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
                       AND iclh.iclh_cd <= tct.ct_date AND iclh.coslis_id = 1
                     ORDER BY iclh.iclh_id DESC LIMIT 1),
                    (SELECT ticl.coslis_price
                     FROM tb_item_cost_list ticl
                     WHERE ticl.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
                       AND ticl.coslis_id = 1
                     ORDER BY ticl.coslis_cd DESC LIMIT 1),
                    0
                ) *
                CASE
                    WHEN COALESCE(
                        (SELECT iclh.curr_id FROM tb_item_cost_list_history iclh
                         WHERE iclh.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
                           AND iclh.iclh_cd <= tct.ct_date AND iclh.coslis_id = 1
                         ORDER BY iclh.iclh_id DESC LIMIT 1),
                        (SELECT ticl.curr_id FROM tb_item_cost_list ticl
                         WHERE ticl.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
                           AND ticl.coslis_id = 1
                         ORDER BY ticl.coslis_cd DESC LIMIT 1),
                        1
                    ) = 1 THEN 1
                    ELSE COALESCE(
                        (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh
                         WHERE ceh.ceh_cd <= tct.ct_date ORDER BY ceh.ceh_cd DESC LIMIT 1),
                        1
                    )
                END
            ) * 1.065 AS costo_unitario
        FROM tb_item_transactions tit
        LEFT JOIN tb_commercial_transactions tct ON tct.ct_transaction = tit.ct_transaction
        WHERE tct.ct_date BETWEEN :from_date AND :to_date
          AND tct.sd_id IN ({SD_IDS_STR})
          AND tct.df_id IN ({DF_IDS_STR})
    ),
    CTE_QtyDivisor AS (
        SELECT
            tit.it_isassociationgroup AS group_id,
            COALESCE(
                NULLIF(
                    (SELECT tit2.it_qty FROM tb_item_transactions tit2
                     WHERE tit2.item_id IS NULL AND tit2.it_isassociationgroup = tit.it_isassociationgroup
                     LIMIT 1),
                    0
                ),
                1
            ) AS qtydivisor
        FROM tb_item_transactions tit
        WHERE tit.it_isassociationgroup IS NOT NULL
        GROUP BY tit.it_isassociationgroup
    ),
    precio_venta AS (
        SELECT
            tit.it_isassociationgroup AS group_id,
            tit.ct_transaction,
            SUM(tit.it_price * tit.it_qty) AS precio_venta
        FROM tb_item_transactions tit
        WHERE tit.it_isassociationgroup IS NOT NULL
          AND tit.it_price IS NOT NULL
        GROUP BY tit.it_isassociationgroup, tit.ct_transaction
    ),
    costo_combo AS (
        SELECT
            tit.it_isassociationgroup AS group_id,
            tit.ct_transaction,
            SUM(cc.costo_unitario * tit.it_qty) AS costo_combo
        FROM tb_item_transactions tit
        LEFT JOIN CostoCalculado cc ON cc.it_transaction = tit.it_transaction
        WHERE tit.it_isassociationgroup IS NOT NULL
        GROUP BY tit.it_isassociationgroup, tit.ct_transaction
    )
    SELECT DISTINCT
        tit.it_transaction as id_operacion,
        tb.bra_desc as sucursal,
        tc.cust_name as cliente,
        tfc.fc_desc as clase_fiscal,
        ttnt.tnt_desc as tipo_documento,
        tc.cust_taxnumber as documento_numero,
        tc.cust_address as domicilio,
        tc.cust_city as ciudad,
        ts.state_desc as provincia,
        tct.ct_date as fecha,
        tdf.df_desc as tipo_comprobante,
        tct.ct_kindof as clase,
        tct.ct_pointofsale as punto_de_venta,
        tct.ct_docnumber as numero_comprobante,
        tbd.brand_desc as marca,
        tcc.cat_desc as categoria,
        tsc.subcat_desc as subcategoria,
        ti.item_code as codigo_item,
        COALESCE(ti.item_desc, titd.itm_desc) as descripcion,

        tit.it_qty * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as cantidad,

        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta
            ELSE tit.it_price
        END * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as precio_unitario_sin_iva,

        COALESCE(ttn.tax_percentage, 21.0) as iva_porcentaje,
        tct.ct_acurrencyexchange as cambio_al_momento,

        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta
            ELSE tit.it_price * tit.it_qty
        END * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as precio_final_sin_iva,

        (CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta
            ELSE tit.it_price * tit.it_qty
        END * COALESCE(ttn.tax_percentage, 21.0) / 100) * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as monto_iva,

        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta
            ELSE tit.it_price * tit.it_qty
        END * (1 + COALESCE(ttn.tax_percentage, 21.0) / 100) * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as precio_final_con_iva,

        tsm.sm_name as vendedor,

        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN COALESCE(ccb.costo_combo, 0)
            ELSE COALESCE(cc.costo_unitario, 0) * tit.it_qty
        END * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as costo_pesos_sin_iva,

        CASE
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN NULL  -- No calcular markup para devoluciones
            WHEN (CASE WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN COALESCE(ccb.costo_combo, 0) ELSE COALESCE(cc.costo_unitario, 0) * tit.it_qty END) = 0 THEN NULL
            ELSE (
                CASE WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta ELSE tit.it_price * tit.it_qty END
                / CASE WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN ccb.costo_combo ELSE cc.costo_unitario * tit.it_qty END
            ) - 1
        END as markup,

        ti.item_id,
        tsc.subcat_id

    FROM tb_item_transactions tit

    LEFT JOIN tb_commercial_transactions tct
        ON tct.comp_id = tit.comp_id
        AND tct.ct_transaction = tit.ct_transaction

    LEFT JOIN tb_item ti
        ON ti.comp_id = tit.comp_id
        AND ti.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)

    LEFT JOIN tb_customer tc
        ON tc.comp_id = tct.comp_id
        AND tc.cust_id = tct.cust_id

    LEFT JOIN tb_fiscal_class tfc
        ON tfc.fc_id = tc.fc_id

    LEFT JOIN tb_state ts
        ON ts.country_id = tc.country_id
        AND ts.state_id = tc.state_id

    LEFT JOIN tb_tax_number_type ttnt
        ON ttnt.tnt_id = tc.tnt_id

    LEFT JOIN tb_category tcc
        ON tcc.comp_id = ti.comp_id
        AND tcc.cat_id = ti.cat_id

    LEFT JOIN tb_subcategory tsc
        ON tsc.comp_id = ti.comp_id
        AND tsc.cat_id = ti.cat_id
        AND tsc.subcat_id = ti.subcat_id

    LEFT JOIN tb_brand tbd
        ON tbd.comp_id = ti.comp_id
        AND tbd.brand_id = ti.brand_id

    LEFT JOIN tb_document_file tdf
        ON tdf.comp_id = tct.comp_id
        AND tdf.bra_id = tct.bra_id
        AND tdf.df_id = tct.df_id

    LEFT JOIN tb_item_taxes titx
        ON titx.comp_id = tit.comp_id
        AND titx.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)

    LEFT JOIN tb_tax_name ttn
        ON ttn.comp_id = tit.comp_id
        AND ttn.tax_id = titx.tax_id

    LEFT JOIN tb_salesman tsm
        ON tsm.sm_id = tct.sm_id

    LEFT JOIN tb_branch tb
        ON tb.comp_id = tit.comp_id
        AND tb.bra_id = tct.bra_id

    LEFT JOIN tb_item_transaction_details titd
        ON titd.comp_id = tit.comp_id
        AND titd.bra_id = tit.bra_id
        AND titd.it_transaction = tit.it_transaction

    LEFT JOIN precio_venta pv
        ON pv.group_id = tit.it_isassociationgroup
        AND pv.ct_transaction = tit.ct_transaction

    LEFT JOIN CostoCalculado cc
        ON cc.it_transaction = tit.it_transaction

    LEFT JOIN costo_combo ccb
        ON ccb.group_id = tit.it_isassociationgroup
        AND ccb.ct_transaction = tit.ct_transaction

    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN ({DF_IDS_STR})
        AND (tit.item_id NOT IN ({ITEMS_EXCLUIDOS_STR}) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN ({CLIENTES_EXCLUIDOS_STR})
        AND tct.sd_id IN ({SD_IDS_STR})
        AND tit.it_qty <> 0
        AND NOT (
            CASE
                WHEN tit.item_id IS NULL AND tit.it_item_id_origin IS NULL
                THEN COALESCE(titd.itm_desc, '')
                ELSE COALESCE(ti.item_desc, '')
            END ILIKE '%envio%'
        )
        AND NOT (
            COALESCE(tit.it_isassociation, false) = true
            AND COALESCE(tit.it_order, 1) <> 1
            AND tit.it_isassociationgroup IS NOT NULL
        )

    ORDER BY tct.ct_date DESC, tit.it_transaction
    """


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/ventas-tienda-nube", response_model=List[VentaTiendaNubeResponse])
async def get_ventas_tienda_nube(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    sucursal: Optional[str] = Query(None, description="Filtrar por sucursal"),
    vendedor: Optional[str] = Query(None, description="Filtrar por vendedor"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    cliente: Optional[str] = Query(None, description="Filtrar por cliente"),
    limit: int = Query(1000, le=10000, description="Límite de resultados"),
    offset: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas de Tienda Nube con métricas calculadas.
    Filtra específicamente por facturas de Tienda Nube (df_id 113, 114).
    Incluye comisión de TN configurable desde admin.
    """
    # Obtener comisión de TN vigente
    fecha_desde = datetime.strptime(from_date, "%Y-%m-%d").date()
    comision_tn_pct = get_comision_tienda_nube(db, fecha_desde)

    query_str = get_ventas_tienda_nube_query()
    query_str += f"\nLIMIT {limit} OFFSET {offset}"

    result = db.execute(
        text(query_str),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    )

    rows = result.fetchall()
    columns = result.keys()

    ventas = []
    for row in rows:
        row_dict = dict(zip(columns, row))

        # Aplicar filtros opcionales
        if sucursal and row_dict.get('sucursal') != sucursal:
            continue
        if vendedor and row_dict.get('vendedor') != vendedor:
            continue
        if marca and row_dict.get('marca') != marca:
            continue
        if cliente and cliente.lower() not in (row_dict.get('cliente') or '').lower():
            continue

        # Calcular comisión de TN y ganancia
        precio_final = float(row_dict.get('precio_final_sin_iva') or 0)
        costo = float(row_dict.get('costo_pesos_sin_iva') or 0)

        comision_tn_pesos = precio_final * (comision_tn_pct / 100)
        monto_limpio = precio_final - comision_tn_pesos
        ganancia = monto_limpio - costo

        row_dict['comision_tn_porcentaje'] = comision_tn_pct
        row_dict['comision_tn_pesos'] = comision_tn_pesos
        row_dict['monto_limpio'] = monto_limpio
        row_dict['ganancia'] = ganancia

        ventas.append(row_dict)

    return ventas


@router.get("/ventas-tienda-nube/stats")
async def get_ventas_tienda_nube_stats(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene estadísticas agregadas de ventas de Tienda Nube.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    # Query única con GROUPING SETS para stats totales, por sucursal y por vendedor
    combined_query = """
    SELECT
        sucursal,
        vendedor,
        GROUPING(sucursal) as is_sucursal_total,
        GROUPING(vendedor) as is_vendedor_total,
        COUNT(*) as total_ventas,
        COUNT(*) FILTER (WHERE costo_total = 0 OR costo_total IS NULL) as productos_sin_costo,
        COALESCE(SUM(cantidad * signo), 0) as total_unidades,
        COALESCE(SUM(monto_total * signo), 0) as monto_total_sin_iva,
        COALESCE(SUM(monto_con_iva * signo), 0) as monto_total_con_iva,
        COALESCE(SUM(costo_total * signo), 0) as costo_total,
        COALESCE(SUM(comision_monto * signo), 0) as comision_total,
        COALESCE(SUM(ganancia * signo), 0) as ganancia_total,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_total * signo ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_con_iva * signo ELSE 0 END), 0) as monto_con_costo_con_iva,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN costo_total * signo ELSE 0 END), 0) as costo_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN comision_monto * signo ELSE 0 END), 0) as comision_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN ganancia * signo ELSE 0 END), 0) as ganancia_con_costo
    FROM ventas_tienda_nube_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
    GROUP BY GROUPING SETS (
        (),
        (sucursal),
        (vendedor)
    )
    """

    results = db.execute(
        text(combined_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()

    # Inicializar variables
    total_ventas = 0
    productos_sin_costo = 0
    total_unidades = 0.0
    monto_con_costo = 0.0
    monto_con_costo_con_iva = 0.0
    costo_con_costo = 0.0
    comision_con_costo = 0.0
    ganancia_con_costo = 0.0
    sucursales_dict = {}
    vendedores_dict = {}

    for row in results:
        # Row con ambos GROUPING = 1 es el total general
        if row.is_sucursal_total == 1 and row.is_vendedor_total == 1:
            total_ventas = row.total_ventas or 0
            productos_sin_costo = row.productos_sin_costo or 0
            total_unidades = float(row.total_unidades or 0)
            monto_con_costo = float(row.monto_con_costo or 0)
            monto_con_costo_con_iva = float(row.monto_con_costo_con_iva or 0)
            costo_con_costo = float(row.costo_con_costo or 0)
            comision_con_costo = float(row.comision_con_costo or 0)
            ganancia_con_costo = float(row.ganancia_con_costo or 0)
        # Row con is_sucursal_total = 0 es agrupado por sucursal
        elif row.is_sucursal_total == 0 and row.is_vendedor_total == 1:
            if row.sucursal:
                sucursales_dict[row.sucursal] = {
                    "ventas": row.total_ventas,
                    "unidades": float(row.total_unidades or 0),
                    "monto": float(row.monto_total_sin_iva or 0)
                }
        # Row con is_vendedor_total = 0 es agrupado por vendedor
        elif row.is_sucursal_total == 1 and row.is_vendedor_total == 0:
            if row.vendedor:
                vendedores_dict[row.vendedor] = {
                    "ventas": row.total_ventas,
                    "unidades": float(row.total_unidades or 0),
                    "monto": float(row.monto_total_sin_iva or 0)
                }

    # Calcular markup promedio: ganancia / costo
    markup_promedio = None
    if costo_con_costo > 0:
        markup_promedio = ganancia_con_costo / costo_con_costo

    # Obtener comisión de TN vigente (para mostrar el %)
    fecha_desde = datetime.strptime(from_date, "%Y-%m-%d").date()
    comision_tn_pct = get_comision_tienda_nube(db, fecha_desde)

    # Monto limpio = monto - comisión
    monto_limpio_total = monto_con_costo - comision_con_costo

    return {
        "total_ventas": total_ventas,
        "total_unidades": total_unidades,
        "monto_total_sin_iva": monto_con_costo,
        "monto_total_con_iva": monto_con_costo_con_iva,
        "comision_tn_porcentaje": comision_tn_pct,
        "comision_tn_total": comision_con_costo,
        "monto_limpio_total": monto_limpio_total,
        "costo_total": costo_con_costo,
        "ganancia_total": ganancia_con_costo,
        "markup_promedio": markup_promedio,
        "productos_sin_costo": productos_sin_costo,
        "por_sucursal": sucursales_dict,
        "por_vendedor": vendedores_dict
    }


@router.get("/ventas-tienda-nube/operaciones")
async def get_operaciones_tn_desde_metricas(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    sucursal: Optional[str] = Query(None, description="Filtrar por sucursal"),
    vendedor: Optional[str] = Query(None, description="Filtrar por vendedor"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    solo_sin_costo: bool = Query(False, description="Solo mostrar operaciones sin costo"),
    limit: int = Query(1000, le=10000, description="Límite de resultados"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene operaciones desde la tabla de métricas pre-calculadas.
    Más rápido que el endpoint original y devuelve metrica_id para edición.
    """
    # Construir query con filtros opcionales
    where_clauses = ["fecha_venta BETWEEN :from_date AND :to_date"]
    params = {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}

    if sucursal:
        where_clauses.append("sucursal = :sucursal")
        params["sucursal"] = sucursal
    if vendedor:
        where_clauses.append("vendedor = :vendedor")
        params["vendedor"] = vendedor
    if marca:
        where_clauses.append("marca = :marca")
        params["marca"] = marca
    if solo_sin_costo:
        where_clauses.append("(costo_total IS NULL OR costo_total = 0)")

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT
        id as metrica_id,
        it_transaction as id_operacion,
        sucursal,
        cliente,
        vendedor,
        fecha_venta as fecha,
        tipo_comprobante,
        numero_comprobante,
        marca,
        categoria,
        subcategoria,
        codigo,
        descripcion,
        cantidad,
        monto_unitario as precio_unitario_sin_iva,
        iva_porcentaje,
        monto_total as precio_final_sin_iva,
        monto_iva,
        monto_con_iva as precio_final_con_iva,
        costo_unitario,
        costo_total as costo_pesos_sin_iva,
        comision_porcentaje,
        comision_monto,
        markup_porcentaje as markup,
        ganancia,
        signo
    FROM ventas_tienda_nube_metricas
    WHERE {where_sql}
    ORDER BY fecha_venta DESC, it_transaction
    LIMIT :limit
    """

    result = db.execute(text(query), params).fetchall()

    return [
        {
            "metrica_id": r.metrica_id,
            "id_operacion": r.id_operacion,
            "sucursal": r.sucursal,
            "cliente": r.cliente,
            "vendedor": r.vendedor,
            "fecha": r.fecha.isoformat() if r.fecha else None,
            "tipo_comprobante": r.tipo_comprobante,
            "numero_comprobante": r.numero_comprobante,
            "marca": r.marca,
            "categoria": r.categoria,
            "subcategoria": r.subcategoria,
            "codigo_item": r.codigo,
            "descripcion": r.descripcion,
            "cantidad": float(r.cantidad) if r.cantidad else 0,
            "precio_unitario_sin_iva": float(r.precio_unitario_sin_iva) if r.precio_unitario_sin_iva else 0,
            "iva_porcentaje": float(r.iva_porcentaje) if r.iva_porcentaje else 21,
            "precio_final_sin_iva": float(r.precio_final_sin_iva) if r.precio_final_sin_iva else 0,
            "monto_iva": float(r.monto_iva) if r.monto_iva else 0,
            "precio_final_con_iva": float(r.precio_final_con_iva) if r.precio_final_con_iva else 0,
            "costo_unitario": float(r.costo_unitario) if r.costo_unitario else 0,
            "costo_pesos_sin_iva": float(r.costo_pesos_sin_iva) if r.costo_pesos_sin_iva else 0,
            "comision_tn_porcentaje": float(r.comision_porcentaje) if r.comision_porcentaje else 0,
            "comision_tn_pesos": float(r.comision_monto) if r.comision_monto else 0,
            "markup": float(r.markup) / 100 if r.markup else None,  # Convertir a decimal (0.15 en lugar de 15%)
            "ganancia": float(r.ganancia) if r.ganancia else 0,
            "signo": r.signo
        }
        for r in result
    ]


@router.get("/ventas-tienda-nube/por-marca", response_model=List[VentaTiendaNubePorMarcaResponse])
async def get_ventas_tienda_nube_por_marca(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(50, le=200, description="Límite de resultados"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas de Tienda Nube agrupadas por marca.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    query = """
    SELECT
        marca,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad * signo), 0) as unidades_vendidas,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_total * signo ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN costo_total * signo ELSE 0 END), 0) as costo_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN ganancia * signo ELSE 0 END), 0) as ganancia_con_costo
    FROM ventas_tienda_nube_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
    GROUP BY marca
    ORDER BY monto_con_costo DESC
    LIMIT :limit
    """

    result = db.execute(
        text(query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    ).fetchall()

    marcas = []
    for r in result:
        monto_con_costo = float(r.monto_con_costo or 0)
        costo_con_costo = float(r.costo_con_costo or 0)
        ganancia_con_costo = float(r.ganancia_con_costo or 0)
        # Markup = ganancia / costo
        markup = (ganancia_con_costo / costo_con_costo) if costo_con_costo > 0 else None
        marcas.append({
            "marca": r.marca,
            "total_ventas": r.total_ventas,
            "unidades_vendidas": Decimal(str(r.unidades_vendidas or 0)),
            "monto_sin_iva": Decimal(str(monto_con_costo)),
            "costo_total": Decimal(str(costo_con_costo)),
            "markup_promedio": Decimal(str(markup)) if markup is not None else None
        })
    return marcas


@router.get("/ventas-tienda-nube/top-productos")
async def get_top_productos_tienda_nube(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(20, le=100, description="Límite de resultados"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene los productos más vendidos en Tienda Nube.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    query = """
    SELECT
        item_id,
        codigo,
        descripcion,
        marca,
        COALESCE(SUM(cantidad * signo), 0) as unidades_vendidas,
        COALESCE(SUM(monto_total * signo), 0) as monto_total,
        COUNT(*) as cantidad_operaciones
    FROM ventas_tienda_nube_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
      AND item_id IS NOT NULL
    GROUP BY item_id, codigo, descripcion, marca
    ORDER BY unidades_vendidas DESC
    LIMIT :limit
    """

    result = db.execute(
        text(query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    ).fetchall()

    return [
        {
            "item_id": r.item_id,
            "codigo": r.codigo,
            "descripcion": r.descripcion,
            "marca": r.marca,
            "unidades_vendidas": float(r.unidades_vendidas or 0),
            "monto_total": float(r.monto_total or 0),
            "cantidad_operaciones": r.cantidad_operaciones
        }
        for r in result
    ]


@router.get("/ventas-tienda-nube/por-categoria")
async def get_ventas_tienda_nube_por_categoria(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(50, le=200, description="Límite de resultados"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas de Tienda Nube agrupadas por categoría.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    query = """
    SELECT
        categoria,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad * signo), 0) as unidades_vendidas,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_total * signo ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN costo_total * signo ELSE 0 END), 0) as costo_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN ganancia * signo ELSE 0 END), 0) as ganancia_con_costo
    FROM ventas_tienda_nube_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
      AND categoria IS NOT NULL
    GROUP BY categoria
    ORDER BY monto_con_costo DESC
    LIMIT :limit
    """

    result = db.execute(
        text(query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    ).fetchall()

    return [
        {
            "categoria": r.categoria,
            "total_ventas": r.total_ventas,
            "unidades_vendidas": float(r.unidades_vendidas or 0),
            "monto_total": float(r.monto_con_costo or 0),
            "costo_total": float(r.costo_con_costo or 0),
            "markup": (float(r.ganancia_con_costo or 0) / float(r.costo_con_costo)) if float(r.costo_con_costo or 0) > 0 else None
        }
        for r in result
    ]


@router.get("/ventas-tienda-nube/por-subcategoria")
async def get_ventas_tienda_nube_por_subcategoria(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    limit: int = Query(50, le=200, description="Límite de resultados"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas de Tienda Nube agrupadas por subcategoría.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    # Construir filtro de categoría de forma segura
    where_clauses = ["fecha_venta BETWEEN :from_date AND :to_date", "subcategoria IS NOT NULL"]
    params = {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}

    if categoria:
        where_clauses.append("categoria = :categoria")
        params["categoria"] = categoria

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT
        subcategoria,
        categoria,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad * signo), 0) as unidades_vendidas,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_total * signo ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN costo_total * signo ELSE 0 END), 0) as costo_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN ganancia * signo ELSE 0 END), 0) as ganancia_con_costo
    FROM ventas_tienda_nube_metricas
    WHERE {where_sql}
    GROUP BY subcategoria, categoria
    ORDER BY monto_con_costo DESC
    LIMIT :limit
    """

    result = db.execute(text(query), params).fetchall()

    return [
        {
            "subcategoria": r.subcategoria,
            "categoria": r.categoria,
            "total_ventas": r.total_ventas,
            "unidades_vendidas": float(r.unidades_vendidas or 0),
            "monto_total": float(r.monto_con_costo or 0),
            "costo_total": float(r.costo_con_costo or 0),
            "markup": (float(r.ganancia_con_costo or 0) / float(r.costo_con_costo)) if float(r.costo_con_costo or 0) > 0 else None
        }
        for r in result
    ]


# ============================================================================
# Endpoints para actualización de métricas
# ============================================================================

class ActualizarCostoTNRequest(BaseModel):
    """Request para actualizar el costo de una operación de TN"""
    costo_unitario: float


class ActualizarMetricaTNRequest(BaseModel):
    """Request para actualizar campos de una métrica de TN"""
    costo_unitario: Optional[float] = None
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None
    descripcion: Optional[str] = None
    codigo: Optional[str] = None


@router.put("/ventas-tienda-nube/metricas/{metrica_id}/costo")
async def actualizar_costo_operacion_tn(
    metrica_id: int,
    request: ActualizarCostoTNRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Actualiza el costo unitario de una operación de Tienda Nube.
    Recalcula automáticamente: costo_total, ganancia, markup_porcentaje.
    """
    from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
    from fastapi import HTTPException

    metrica = db.query(VentaTiendaNubeMetrica).filter(
        VentaTiendaNubeMetrica.id == metrica_id
    ).first()

    if not metrica:
        raise HTTPException(status_code=404, detail="Operación no encontrada")

    # Actualizar costo unitario
    costo_unitario = Decimal(str(request.costo_unitario))
    cantidad = metrica.cantidad or Decimal('1')
    monto_total = metrica.monto_total or Decimal('0')
    comision_monto = metrica.comision_monto or Decimal('0')

    # Calcular costo total
    costo_total = costo_unitario * cantidad

    # Ganancia = monto - costo - comisión
    ganancia = monto_total - costo_total - comision_monto

    # Markup = (monto / (costo + comisión)) - 1
    markup_porcentaje = None
    base_costo = costo_total + comision_monto
    if base_costo > 0:
        markup_porcentaje = ((monto_total / base_costo) - 1) * 100

    # Actualizar campos
    metrica.costo_unitario = costo_unitario
    metrica.costo_total = costo_total
    metrica.ganancia = ganancia
    metrica.markup_porcentaje = Decimal(str(markup_porcentaje)) if markup_porcentaje is not None else None
    metrica.moneda_costo = 'ARS'

    db.commit()
    db.refresh(metrica)

    return {
        "success": True,
        "id": metrica.id,
        "costo_unitario": float(metrica.costo_unitario),
        "costo_total": float(metrica.costo_total),
        "ganancia": float(metrica.ganancia),
        "markup_porcentaje": float(metrica.markup_porcentaje) if metrica.markup_porcentaje else None
    }


@router.patch("/ventas-tienda-nube/metricas/{metrica_id}")
async def actualizar_metrica_tn(
    metrica_id: int,
    request: ActualizarMetricaTNRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Actualiza campos de una métrica de venta de Tienda Nube.
    Permite actualizar: costo_unitario, marca, categoria, subcategoria, descripcion, codigo.
    Si se actualiza el costo, recalcula automáticamente: costo_total, ganancia, markup_porcentaje.
    """
    from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
    from fastapi import HTTPException

    metrica = db.query(VentaTiendaNubeMetrica).filter(
        VentaTiendaNubeMetrica.id == metrica_id
    ).first()

    if not metrica:
        raise HTTPException(status_code=404, detail="Operación no encontrada")

    campos_actualizados = []

    # Actualizar campos de texto si se proporcionan
    if request.marca is not None:
        metrica.marca = request.marca
        campos_actualizados.append("marca")

    if request.categoria is not None:
        metrica.categoria = request.categoria
        campos_actualizados.append("categoria")

    if request.subcategoria is not None:
        metrica.subcategoria = request.subcategoria
        campos_actualizados.append("subcategoria")

    if request.descripcion is not None:
        metrica.descripcion = request.descripcion
        campos_actualizados.append("descripcion")

    if request.codigo is not None:
        metrica.codigo = request.codigo
        campos_actualizados.append("codigo")

    # Actualizar costo y recalcular
    if request.costo_unitario is not None:
        costo_unitario = Decimal(str(request.costo_unitario))
        cantidad = metrica.cantidad or Decimal('1')
        monto_total = metrica.monto_total or Decimal('0')
        comision_monto = metrica.comision_monto or Decimal('0')

        costo_total = costo_unitario * cantidad
        ganancia = monto_total - costo_total - comision_monto

        markup_porcentaje = None
        base_costo = costo_total + comision_monto
        if base_costo > 0:
            markup_porcentaje = ((monto_total / base_costo) - 1) * 100

        metrica.costo_unitario = costo_unitario
        metrica.costo_total = costo_total
        metrica.ganancia = ganancia
        metrica.markup_porcentaje = Decimal(str(markup_porcentaje)) if markup_porcentaje is not None else None
        metrica.moneda_costo = 'ARS'
        campos_actualizados.append("costo_unitario")

    if not campos_actualizados:
        raise HTTPException(status_code=400, detail="No se proporcionaron campos para actualizar")

    db.commit()
    db.refresh(metrica)

    return {
        "success": True,
        "id": metrica.id,
        "campos_actualizados": campos_actualizados,
        "metrica": {
            "codigo": metrica.codigo,
            "descripcion": metrica.descripcion,
            "marca": metrica.marca,
            "categoria": metrica.categoria,
            "subcategoria": metrica.subcategoria,
            "costo_unitario": float(metrica.costo_unitario) if metrica.costo_unitario else None,
            "costo_total": float(metrica.costo_total) if metrica.costo_total else None,
            "ganancia": float(metrica.ganancia) if metrica.ganancia else None,
            "markup_porcentaje": float(metrica.markup_porcentaje) if metrica.markup_porcentaje else None
        }
    }


@router.get("/ventas-tienda-nube/metricas/{metrica_id}")
async def get_metrica_detalle_tn(
    metrica_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene el detalle de una métrica específica de Tienda Nube.
    """
    from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
    from fastapi import HTTPException

    metrica = db.query(VentaTiendaNubeMetrica).filter(
        VentaTiendaNubeMetrica.id == metrica_id
    ).first()

    if not metrica:
        raise HTTPException(status_code=404, detail="Operación no encontrada")

    return {
        "id": metrica.id,
        "it_transaction": metrica.it_transaction,
        "item_id": metrica.item_id,
        "codigo": metrica.codigo,
        "descripcion": metrica.descripcion,
        "marca": metrica.marca,
        "categoria": metrica.categoria,
        "subcategoria": metrica.subcategoria,
        "cantidad": float(metrica.cantidad) if metrica.cantidad else 0,
        "monto_unitario": float(metrica.monto_unitario) if metrica.monto_unitario else 0,
        "monto_total": float(metrica.monto_total) if metrica.monto_total else 0,
        "costo_unitario": float(metrica.costo_unitario) if metrica.costo_unitario else 0,
        "costo_total": float(metrica.costo_total) if metrica.costo_total else 0,
        "comision_porcentaje": float(metrica.comision_porcentaje) if metrica.comision_porcentaje else 0,
        "comision_monto": float(metrica.comision_monto) if metrica.comision_monto else 0,
        "ganancia": float(metrica.ganancia) if metrica.ganancia else 0,
        "markup_porcentaje": float(metrica.markup_porcentaje) if metrica.markup_porcentaje else None,
        "moneda_costo": metrica.moneda_costo,
        "fecha_venta": metrica.fecha_venta.isoformat() if metrica.fecha_venta else None
    }


# ============================================================================
# Endpoints para método de pago
# ============================================================================

class MetodoPagoRequest(BaseModel):
    it_transaction: int
    metodo_pago: str  # 'efectivo' o 'tarjeta'


class MetodoPagoBulkRequest(BaseModel):
    operaciones: List[MetodoPagoRequest]


@router.get("/ventas-tienda-nube/metodos-pago")
async def get_metodos_pago_tn(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene los métodos de pago guardados para operaciones TN en un período.
    Devuelve un diccionario con it_transaction como clave y metodo_pago como valor.
    """
    from app.models.metodo_pago_tn import MetodoPagoTN

    # Obtener it_transactions del período desde la tabla de métricas
    metricas_query = """
    SELECT it_transaction FROM ventas_tienda_nube_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
    """
    metricas_result = db.execute(
        text(metricas_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()

    it_transactions = [r.it_transaction for r in metricas_result]

    if not it_transactions:
        return {}

    # Obtener métodos de pago guardados
    metodos = db.query(MetodoPagoTN).filter(
        MetodoPagoTN.it_transaction.in_(it_transactions)
    ).all()

    return {m.it_transaction: m.metodo_pago for m in metodos}


@router.post("/ventas-tienda-nube/metodo-pago")
async def set_metodo_pago_tn(
    request: MetodoPagoRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Guarda o actualiza el método de pago para una operación TN.
    """
    from app.models.metodo_pago_tn import MetodoPagoTN
    from fastapi import HTTPException

    if request.metodo_pago not in ['efectivo', 'tarjeta']:
        raise HTTPException(status_code=400, detail="Método de pago debe ser 'efectivo' o 'tarjeta'")

    # Buscar si ya existe
    metodo_existente = db.query(MetodoPagoTN).filter(
        MetodoPagoTN.it_transaction == request.it_transaction
    ).first()

    if metodo_existente:
        metodo_existente.metodo_pago = request.metodo_pago
        metodo_existente.usuario_id = current_user.id if hasattr(current_user, 'id') else None
    else:
        nuevo_metodo = MetodoPagoTN(
            it_transaction=request.it_transaction,
            metodo_pago=request.metodo_pago,
            usuario_id=current_user.id if hasattr(current_user, 'id') else None
        )
        db.add(nuevo_metodo)

    db.commit()

    return {"success": True, "it_transaction": request.it_transaction, "metodo_pago": request.metodo_pago}


@router.post("/ventas-tienda-nube/metodos-pago/bulk")
async def set_metodos_pago_bulk_tn(
    request: MetodoPagoBulkRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Guarda o actualiza métodos de pago para múltiples operaciones TN.
    """
    from app.models.metodo_pago_tn import MetodoPagoTN
    from fastapi import HTTPException

    actualizados = 0
    creados = 0

    for op in request.operaciones:
        if op.metodo_pago not in ['efectivo', 'tarjeta']:
            continue

        metodo_existente = db.query(MetodoPagoTN).filter(
            MetodoPagoTN.it_transaction == op.it_transaction
        ).first()

        if metodo_existente:
            if metodo_existente.metodo_pago != op.metodo_pago:
                metodo_existente.metodo_pago = op.metodo_pago
                metodo_existente.usuario_id = current_user.id if hasattr(current_user, 'id') else None
                actualizados += 1
        else:
            nuevo_metodo = MetodoPagoTN(
                it_transaction=op.it_transaction,
                metodo_pago=op.metodo_pago,
                usuario_id=current_user.id if hasattr(current_user, 'id') else None
            )
            db.add(nuevo_metodo)
            creados += 1

    db.commit()

    return {"success": True, "actualizados": actualizados, "creados": creados}


def get_comision_tienda_nube_tarjeta(db: Session, fecha: date = None) -> float:
    """Obtiene la comisión de Tienda Nube para tarjeta vigente para una fecha"""
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

    if constants and constants.comision_tienda_nube_tarjeta is not None:
        return float(constants.comision_tienda_nube_tarjeta)
    return 3.0  # Default 3%
