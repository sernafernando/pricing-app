"""
Endpoints para métricas de ventas por fuera de MercadoLibre
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal
from pydantic import BaseModel
from app.core.database import get_db
from app.api.deps import get_current_user

router = APIRouter()


# ============================================================================
# Schemas
# ============================================================================

class VentaFueraMLResponse(BaseModel):
    """Respuesta detallada de una venta por fuera de ML"""
    id_operacion: int
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
    markup: Optional[Decimal]
    vendedor: Optional[str]

    class Config:
        from_attributes = True


class VentaFueraMLStatsResponse(BaseModel):
    """Estadísticas agregadas de ventas por fuera de ML"""
    total_ventas: int
    total_unidades: Decimal
    monto_total_sin_iva: Decimal
    monto_total_con_iva: Decimal
    costo_total: Decimal
    markup_promedio: Optional[Decimal]
    por_sucursal: dict
    por_vendedor: dict


class VentaFueraMLPorMarcaResponse(BaseModel):
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

# Mapeo de sd_id para PlusOrMinus
# sd_id IN (1, 4, 21, 56) => +1 (Ventas)
# sd_id IN (3, 6, 23, 66) => -1 (NC/Devoluciones)
SD_VENTAS = [1, 4, 21, 56]
SD_DEVOLUCIONES = [3, 6, 23, 66]

# df_id permitidos para ventas (facturas, remitos, etc.)
# Sucursal 45 (Grupo Gauss): 105-118, 124
# Excluimos: 113, 114 (TN), 129-132 (MercadoLibre)
DF_PERMITIDOS = [1, 2, 3, 4, 5, 6, 63, 85, 86, 87, 65, 67, 68, 69, 70, 71, 72, 73, 74, 81,
                 105, 106, 107, 109, 110, 111, 112, 115, 116, 117, 118, 124]

# Clientes excluidos
CLIENTES_EXCLUIDOS = [11, 3900]

# Vendedores excluidos (ML)
VENDEDORES_EXCLUIDOS = [10, 11, 12]

# Items excluidos
ITEMS_EXCLUIDOS = [16, 460]


def get_ventas_fuera_ml_query():
    """
    Query principal para obtener ventas por fuera de ML.
    Replica la lógica de la query SQL del ERP.
    """
    return """
    WITH costo_historico AS (
        -- Subconsulta para obtener el costo histórico más cercano a la fecha de venta
        SELECT DISTINCT ON (iclh.item_id, ct_date_trunc)
            iclh.item_id,
            DATE_TRUNC('day', ct.ct_date) as ct_date_trunc,
            iclh.iclh_price,
            iclh.curr_id as costo_curr_id
        FROM tb_item_cost_list_history iclh
        CROSS JOIN (
            SELECT DISTINCT DATE_TRUNC('day', ct_date) as ct_date
            FROM tb_commercial_transactions
            WHERE ct_date BETWEEN :from_date AND :to_date
        ) ct
        WHERE iclh.iclh_cd <= ct.ct_date
          AND iclh.coslis_id = 1
        ORDER BY iclh.item_id, ct_date_trunc, iclh.iclh_id DESC
    ),
    tc_historico AS (
        -- Subconsulta para obtener el tipo de cambio más cercano a la fecha de venta
        SELECT DISTINCT ON (ct_date_trunc)
            DATE_TRUNC('day', ct.ct_date) as ct_date_trunc,
            ceh.ceh_exchange
        FROM tb_cur_exch_history ceh
        CROSS JOIN (
            SELECT DISTINCT DATE_TRUNC('day', ct_date) as ct_date
            FROM tb_commercial_transactions
            WHERE ct_date BETWEEN :from_date AND :to_date
        ) ct
        WHERE ceh.ceh_cd <= ct.ct_date
        ORDER BY ct_date_trunc, ceh.ceh_cd DESC
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
        ti.item_desc as descripcion,

        -- Cantidad con signo (+ venta, - devolución)
        CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN tit.it_qty
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -tit.it_qty
            ELSE tit.it_qty
        END as cantidad,

        -- Precio unitario sin IVA con signo
        CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN tit.it_price
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -tit.it_price
            ELSE tit.it_price
        END as precio_unitario_sin_iva,

        COALESCE(ttn.tax_percentage, 21.0) as iva_porcentaje,

        -- Tipo de cambio al momento (de tb_commercial_transactions si existe, sino del histórico)
        COALESCE(tct.ct_acurrencyexchange, tch.ceh_exchange, 1) as cambio_al_momento,

        -- Precio final sin IVA (cantidad * precio unitario)
        -- Caso especial: sucursal 35 multiplica por (1 + IVA)
        CASE
            WHEN tct.bra_id = 35 THEN
                (tit.it_price * tit.it_qty * (1 + COALESCE(ttn.tax_percentage, 21.0) / 100)) *
                CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
            ELSE
                tit.it_price * tit.it_qty *
                CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
        END as precio_final_sin_iva,

        -- Monto IVA
        (tit.it_price * COALESCE(ttn.tax_percentage, 21.0) / 100) * tit.it_qty *
        CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END as monto_iva,

        -- Precio final con IVA
        (tit.it_price * tit.it_qty * (1 + COALESCE(ttn.tax_percentage, 21.0) / 100)) *
        CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END as precio_final_con_iva,

        -- Costo en pesos sin IVA
        CASE
            WHEN ch.costo_curr_id = 1 THEN  -- ARS
                COALESCE(ch.iclh_price, 0) * tit.it_qty *
                CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
            ELSE  -- USD u otra moneda
                COALESCE(ch.iclh_price, 0) * COALESCE(tch.ceh_exchange, 1) * tit.it_qty *
                CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
        END as costo_pesos_sin_iva,

        -- Markup: (precio_venta / costo) - 1
        CASE
            WHEN COALESCE(ch.iclh_price, 0) = 0 THEN NULL
            ELSE
                (
                    CASE
                        WHEN tct.bra_id = 35 THEN tit.it_price * (1 + COALESCE(ttn.tax_percentage, 21.0) / 100)
                        ELSE tit.it_price * 0.95  -- Descuento 5% para otras sucursales
                    END
                    /
                    CASE
                        WHEN ch.costo_curr_id = 1 THEN ch.iclh_price
                        ELSE ch.iclh_price * COALESCE(tch.ceh_exchange, 1)
                    END
                ) - 1
        END as markup,

        tsm.sm_name as vendedor

    FROM tb_item ti

    LEFT JOIN tb_item_transactions tit
        ON tit.comp_id = ti.comp_id
        AND tit.item_id = ti.item_id

    LEFT JOIN tb_commercial_transactions tct
        ON tct.comp_id = tit.comp_id
        AND tct.ct_transaction = tit.ct_transaction

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
        ON titx.comp_id = ti.comp_id
        AND titx.item_id = ti.item_id

    LEFT JOIN tb_tax_name ttn
        ON ttn.comp_id = ti.comp_id
        AND ttn.tax_id = titx.tax_id

    LEFT JOIN tb_salesman tsm
        ON tsm.sm_id = tct.sm_id

    LEFT JOIN tb_branch tb
        ON tb.comp_id = ti.comp_id
        AND tb.bra_id = tct.bra_id

    LEFT JOIN costo_historico ch
        ON ch.item_id = tit.item_id
        AND ch.ct_date_trunc = DATE_TRUNC('day', tct.ct_date)

    LEFT JOIN tc_historico tch
        ON tch.ct_date_trunc = DATE_TRUNC('day', tct.ct_date)

    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN (1,2,3,4,5,6,63,85,86,87,65,67,68,69,70,71,72,73,74,81)
        AND (tit.item_id NOT IN (16, 460) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN (11, 3900)
        AND tct.sm_id NOT IN (10, 11, 12)
        AND tit.it_price <> 0
        AND tit.it_qty <> 0
        AND tct.sd_id IN (1, 3, 4, 6, 21, 23, 56, 66)

    ORDER BY tct.ct_date DESC, tit.it_transaction
    """


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/ventas-fuera-ml", response_model=List[VentaFueraMLResponse])
async def get_ventas_fuera_ml(
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
    Obtiene ventas por fuera de MercadoLibre con métricas calculadas.
    Incluye: precio sin IVA, con IVA, costo, markup, datos del cliente, etc.
    """

    query_str = get_ventas_fuera_ml_query()

    # Agregar LIMIT y OFFSET
    query_str += f"\nLIMIT {limit} OFFSET {offset}"

    # Ejecutar query
    result = db.execute(
        text(query_str),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    )

    rows = result.fetchall()
    columns = result.keys()

    # Filtrar en Python si se especificaron filtros adicionales
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

        ventas.append(row_dict)

    return ventas


@router.get("/ventas-fuera-ml/stats")
async def get_ventas_fuera_ml_stats(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene estadísticas agregadas de ventas por fuera de ML.
    """

    stats_query = """
    WITH ventas AS (
        SELECT
            tit.it_transaction,
            tb.bra_desc as sucursal,
            tsm.sm_name as vendedor,

            -- Cantidad con signo
            CASE
                WHEN tct.sd_id IN (1, 4, 21, 56) THEN tit.it_qty
                WHEN tct.sd_id IN (3, 6, 23, 66) THEN -tit.it_qty
                ELSE tit.it_qty
            END as cantidad,

            -- Precio sin IVA con signo
            tit.it_price * tit.it_qty *
            CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END as precio_sin_iva,

            -- Precio con IVA
            tit.it_price * tit.it_qty * (1 + COALESCE(ttn.tax_percentage, 21.0) / 100) *
            CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END as precio_con_iva,

            -- Costo
            CASE
                WHEN iclh.curr_id = 1 THEN COALESCE(iclh.iclh_price, 0) * tit.it_qty
                ELSE COALESCE(iclh.iclh_price, 0) * COALESCE(ceh.ceh_exchange, 1) * tit.it_qty
            END * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END as costo,

            -- Markup
            CASE
                WHEN COALESCE(iclh.iclh_price, 0) = 0 THEN NULL
                ELSE (tit.it_price * 0.95 /
                    CASE
                        WHEN iclh.curr_id = 1 THEN iclh.iclh_price
                        ELSE iclh.iclh_price * COALESCE(ceh.ceh_exchange, 1)
                    END) - 1
            END as markup

        FROM tb_item ti
        LEFT JOIN tb_item_transactions tit ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
        LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
        LEFT JOIN tb_branch tb ON tb.comp_id = ti.comp_id AND tb.bra_id = tct.bra_id
        LEFT JOIN tb_salesman tsm ON tsm.sm_id = tct.sm_id
        LEFT JOIN tb_item_taxes titx ON titx.comp_id = ti.comp_id AND titx.item_id = ti.item_id
        LEFT JOIN tb_tax_name ttn ON ttn.comp_id = ti.comp_id AND ttn.tax_id = titx.tax_id
        LEFT JOIN LATERAL (
            SELECT iclh_price, curr_id
            FROM tb_item_cost_list_history
            WHERE item_id = tit.item_id AND iclh_cd <= tct.ct_date AND coslis_id = 1
            ORDER BY iclh_id DESC LIMIT 1
        ) iclh ON true
        LEFT JOIN LATERAL (
            SELECT ceh_exchange
            FROM tb_cur_exch_history
            WHERE ceh_cd <= tct.ct_date
            ORDER BY ceh_cd DESC LIMIT 1
        ) ceh ON true

        WHERE tct.ct_date BETWEEN :from_date AND :to_date
            AND tct.df_id IN (1,2,3,4,5,6,63,85,86,87,65,67,68,69,70,71,72,73,74,81)
            AND (tit.item_id NOT IN (16, 460) OR tit.item_id IS NULL)
            AND tct.cust_id NOT IN (11, 3900)
            AND tct.sm_id NOT IN (10, 11, 12)
            AND tit.it_price <> 0
            AND tit.it_qty <> 0
            AND tct.sd_id IN (1, 3, 4, 6, 21, 23, 56, 66)
    )
    SELECT
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad), 0) as total_unidades,
        COALESCE(SUM(precio_sin_iva), 0) as monto_total_sin_iva,
        COALESCE(SUM(precio_con_iva), 0) as monto_total_con_iva,
        COALESCE(SUM(costo), 0) as costo_total,
        AVG(markup) FILTER (WHERE markup IS NOT NULL) as markup_promedio
    FROM ventas
    """

    result = db.execute(
        text(stats_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchone()

    # Stats por sucursal
    sucursal_query = """
    SELECT
        tb.bra_desc as sucursal,
        COUNT(*) as total_ventas,
        SUM(tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as unidades,
        SUM(tit.it_price * tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as monto
    FROM tb_item_transactions tit
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_branch tb ON tb.comp_id = tit.comp_id AND tb.bra_id = tct.bra_id
    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN (1,2,3,4,5,6,63,85,86,87,65,67,68,69,70,71,72,73,74,81)
        AND (tit.item_id NOT IN (16, 460) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN (11, 3900)
        AND tct.sm_id NOT IN (10, 11, 12)
        AND tit.it_price <> 0
        AND tit.it_qty <> 0
        AND tct.sd_id IN (1, 3, 4, 6, 21, 23, 56, 66)
    GROUP BY tb.bra_desc
    ORDER BY monto DESC
    """

    sucursales = db.execute(
        text(sucursal_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()

    # Stats por vendedor
    vendedor_query = """
    SELECT
        tsm.sm_name as vendedor,
        COUNT(*) as total_ventas,
        SUM(tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as unidades,
        SUM(tit.it_price * tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as monto
    FROM tb_item_transactions tit
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_salesman tsm ON tsm.sm_id = tct.sm_id
    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN (1,2,3,4,5,6,63,85,86,87,65,67,68,69,70,71,72,73,74,81)
        AND (tit.item_id NOT IN (16, 460) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN (11, 3900)
        AND tct.sm_id NOT IN (10, 11, 12)
        AND tit.it_price <> 0
        AND tit.it_qty <> 0
        AND tct.sd_id IN (1, 3, 4, 6, 21, 23, 56, 66)
    GROUP BY tsm.sm_name
    ORDER BY monto DESC
    """

    vendedores = db.execute(
        text(vendedor_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()

    return {
        "total_ventas": result.total_ventas or 0,
        "total_unidades": float(result.total_unidades or 0),
        "monto_total_sin_iva": float(result.monto_total_sin_iva or 0),
        "monto_total_con_iva": float(result.monto_total_con_iva or 0),
        "costo_total": float(result.costo_total or 0),
        "markup_promedio": float(result.markup_promedio) if result.markup_promedio else None,
        "por_sucursal": {
            s.sucursal: {
                "ventas": s.total_ventas,
                "unidades": float(s.unidades or 0),
                "monto": float(s.monto or 0)
            }
            for s in sucursales if s.sucursal
        },
        "por_vendedor": {
            v.vendedor: {
                "ventas": v.total_ventas,
                "unidades": float(v.unidades or 0),
                "monto": float(v.monto or 0)
            }
            for v in vendedores if v.vendedor
        }
    }


@router.get("/ventas-fuera-ml/por-marca", response_model=List[VentaFueraMLPorMarcaResponse])
async def get_ventas_fuera_ml_por_marca(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(50, le=200, description="Límite de resultados"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por marca.
    """

    query = """
    SELECT
        tbd.brand_desc as marca,
        COUNT(*) as total_ventas,
        SUM(tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as unidades_vendidas,
        SUM(tit.it_price * tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as monto_sin_iva,
        SUM(
            CASE
                WHEN iclh.curr_id = 1 THEN COALESCE(iclh.iclh_price, 0) * tit.it_qty
                ELSE COALESCE(iclh.iclh_price, 0) * COALESCE(ceh.ceh_exchange, 1) * tit.it_qty
            END * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
        ) as costo_total,
        AVG(
            CASE
                WHEN COALESCE(iclh.iclh_price, 0) = 0 THEN NULL
                ELSE (tit.it_price * 0.95 /
                    CASE
                        WHEN iclh.curr_id = 1 THEN iclh.iclh_price
                        ELSE iclh.iclh_price * COALESCE(ceh.ceh_exchange, 1)
                    END) - 1
            END
        ) as markup_promedio

    FROM tb_item ti
    LEFT JOIN tb_item_transactions tit ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN LATERAL (
        SELECT iclh_price, curr_id
        FROM tb_item_cost_list_history
        WHERE item_id = tit.item_id AND iclh_cd <= tct.ct_date AND coslis_id = 1
        ORDER BY iclh_id DESC LIMIT 1
    ) iclh ON true
    LEFT JOIN LATERAL (
        SELECT ceh_exchange
        FROM tb_cur_exch_history
        WHERE ceh_cd <= tct.ct_date
        ORDER BY ceh_cd DESC LIMIT 1
    ) ceh ON true

    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN (1,2,3,4,5,6,63,85,86,87,65,67,68,69,70,71,72,73,74,81)
        AND (tit.item_id NOT IN (16, 460) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN (11, 3900)
        AND tct.sm_id NOT IN (10, 11, 12)
        AND tit.it_price <> 0
        AND tit.it_qty <> 0
        AND tct.sd_id IN (1, 3, 4, 6, 21, 23, 56, 66)

    GROUP BY tbd.brand_desc
    ORDER BY monto_sin_iva DESC
    LIMIT :limit
    """

    result = db.execute(
        text(query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    ).fetchall()

    return [
        {
            "marca": r.marca,
            "total_ventas": r.total_ventas,
            "unidades_vendidas": Decimal(str(r.unidades_vendidas or 0)),
            "monto_sin_iva": Decimal(str(r.monto_sin_iva or 0)),
            "costo_total": Decimal(str(r.costo_total or 0)),
            "markup_promedio": Decimal(str(r.markup_promedio)) if r.markup_promedio else None
        }
        for r in result
    ]


@router.get("/ventas-fuera-ml/top-productos")
async def get_top_productos_fuera_ml(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(20, le=100, description="Límite de resultados"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene los productos más vendidos por fuera de ML.
    """

    query = """
    SELECT
        ti.item_id,
        ti.item_code as codigo,
        ti.item_desc as descripcion,
        tbd.brand_desc as marca,
        SUM(tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as unidades_vendidas,
        SUM(tit.it_price * tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as monto_total,
        COUNT(DISTINCT tit.it_transaction) as cantidad_operaciones

    FROM tb_item ti
    LEFT JOIN tb_item_transactions tit ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id

    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN (1,2,3,4,5,6,63,85,86,87,65,67,68,69,70,71,72,73,74,81)
        AND tit.item_id NOT IN (16, 460)
        AND tct.cust_id NOT IN (11, 3900)
        AND tct.sm_id NOT IN (10, 11, 12)
        AND tit.it_price <> 0
        AND tit.it_qty <> 0
        AND tct.sd_id IN (1, 3, 4, 6, 21, 23, 56, 66)

    GROUP BY ti.item_id, ti.item_code, ti.item_desc, tbd.brand_desc
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
