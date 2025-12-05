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
    Calcula directamente desde la query base.
    """
    # Query para stats agregadas
    stats_query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_query()}
    )
    SELECT
        COUNT(*) as total_ventas,
        COUNT(*) FILTER (WHERE costo_pesos_sin_iva = 0 OR costo_pesos_sin_iva IS NULL) as productos_sin_costo,
        COALESCE(SUM(cantidad), 0) as total_unidades,
        COALESCE(SUM(precio_final_sin_iva), 0) as monto_total_sin_iva,
        COALESCE(SUM(precio_final_con_iva), 0) as monto_total_con_iva,
        COALESCE(SUM(costo_pesos_sin_iva), 0) as costo_total,
        COALESCE(SUM(CASE WHEN costo_pesos_sin_iva > 0 THEN precio_final_sin_iva ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_pesos_sin_iva > 0 THEN costo_pesos_sin_iva ELSE 0 END), 0) as costo_con_costo
    FROM ventas
    """

    result = db.execute(
        text(stats_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).first()

    # Stats por sucursal
    sucursal_query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_query()}
    )
    SELECT
        sucursal,
        COUNT(*) as ventas,
        COALESCE(SUM(cantidad), 0) as unidades,
        COALESCE(SUM(precio_final_sin_iva), 0) as monto
    FROM ventas
    WHERE sucursal IS NOT NULL
    GROUP BY sucursal
    """

    sucursales = db.execute(
        text(sucursal_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()

    sucursales_dict = {
        r.sucursal: {
            "ventas": r.ventas,
            "unidades": float(r.unidades or 0),
            "monto": float(r.monto or 0)
        }
        for r in sucursales
    }

    # Stats por vendedor
    vendedor_query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_query()}
    )
    SELECT
        vendedor,
        COUNT(*) as ventas,
        COALESCE(SUM(cantidad), 0) as unidades,
        COALESCE(SUM(precio_final_sin_iva), 0) as monto
    FROM ventas
    WHERE vendedor IS NOT NULL
    GROUP BY vendedor
    """

    vendedores = db.execute(
        text(vendedor_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()

    vendedores_dict = {
        r.vendedor: {
            "ventas": r.ventas,
            "unidades": float(r.unidades or 0),
            "monto": float(r.monto or 0)
        }
        for r in vendedores
    }

    # Obtener comisión de TN vigente
    fecha_desde = datetime.strptime(from_date, "%Y-%m-%d").date()
    comision_tn_pct = get_comision_tienda_nube(db, fecha_desde)

    # Calcular métricas con comisión
    monto_con_costo = float(result.monto_con_costo or 0)
    costo_con_costo = float(result.costo_con_costo or 0)

    # Comisión de TN sobre el monto total
    comision_tn_total = monto_con_costo * (comision_tn_pct / 100)
    monto_limpio_total = monto_con_costo - comision_tn_total
    ganancia_total = monto_limpio_total - costo_con_costo

    # Markup calculado sobre ganancia / costo
    markup_promedio = ((ganancia_total / costo_con_costo)) if costo_con_costo > 0 else None

    return {
        "total_ventas": result.total_ventas or 0,
        "total_unidades": float(result.total_unidades or 0),
        "monto_total_sin_iva": monto_con_costo,
        "monto_total_con_iva": float(result.monto_total_con_iva or 0),
        "comision_tn_porcentaje": comision_tn_pct,
        "comision_tn_total": comision_tn_total,
        "monto_limpio_total": monto_limpio_total,
        "costo_total": costo_con_costo,
        "ganancia_total": ganancia_total,
        "markup_promedio": markup_promedio,
        "productos_sin_costo": result.productos_sin_costo or 0,
        "por_sucursal": sucursales_dict,
        "por_vendedor": vendedores_dict
    }


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
    """
    query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_query()}
    )
    SELECT
        marca,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad), 0) as unidades_vendidas,
        COALESCE(SUM(CASE WHEN costo_pesos_sin_iva > 0 THEN precio_final_sin_iva ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_pesos_sin_iva > 0 THEN costo_pesos_sin_iva ELSE 0 END), 0) as costo_con_costo
    FROM ventas
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
        markup = ((monto_con_costo / costo_con_costo) - 1) if costo_con_costo > 0 else None
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
    """
    query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_query()}
    )
    SELECT
        item_id,
        codigo_item as codigo,
        descripcion,
        marca,
        COALESCE(SUM(cantidad), 0) as unidades_vendidas,
        COALESCE(SUM(precio_final_sin_iva), 0) as monto_total,
        COUNT(*) as cantidad_operaciones
    FROM ventas
    WHERE item_id IS NOT NULL
    GROUP BY item_id, codigo_item, descripcion, marca
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
    """
    query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_query()}
    )
    SELECT
        categoria,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad), 0) as unidades_vendidas,
        COALESCE(SUM(precio_final_sin_iva), 0) as monto_total,
        COALESCE(SUM(costo_pesos_sin_iva), 0) as costo_total
    FROM ventas
    WHERE categoria IS NOT NULL
    GROUP BY categoria
    ORDER BY monto_total DESC
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
            "monto_total": float(r.monto_total or 0),
            "costo_total": float(r.costo_total or 0),
            "markup": ((float(r.monto_total or 0) / float(r.costo_total)) - 1) if float(r.costo_total or 0) > 0 else None
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
    """
    categoria_filter = ""
    if categoria:
        categoria_filter = f"AND categoria = '{categoria}'"

    query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_query()}
    )
    SELECT
        subcategoria,
        subcat_id,
        categoria,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad), 0) as unidades_vendidas,
        COALESCE(SUM(precio_final_sin_iva), 0) as monto_total,
        COALESCE(SUM(costo_pesos_sin_iva), 0) as costo_total
    FROM ventas
    WHERE subcategoria IS NOT NULL {categoria_filter}
    GROUP BY subcategoria, subcat_id, categoria
    ORDER BY monto_total DESC
    LIMIT :limit
    """

    result = db.execute(
        text(query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    ).fetchall()

    return [
        {
            "subcategoria": r.subcategoria,
            "subcat_id": r.subcat_id,
            "categoria": r.categoria,
            "total_ventas": r.total_ventas,
            "unidades_vendidas": float(r.unidades_vendidas or 0),
            "monto_total": float(r.monto_total or 0),
            "costo_total": float(r.costo_total or 0),
            "markup": ((float(r.monto_total or 0) / float(r.costo_total)) - 1) if float(r.costo_total or 0) > 0 else None
        }
        for r in result
    ]
