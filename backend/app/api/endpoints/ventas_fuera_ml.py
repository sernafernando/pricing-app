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

# df_id permitidos para ventas (facturas, NC, ND, etc.)
# Sucursal 45 (Grupo Gauss): 105, 106, 109, 111, 115, 116, 117, 118, 124
# Excluimos: 107, 110 (Remitos), 112 (Recibos), 113, 114 (TN), 129-132 (MercadoLibre)
DF_PERMITIDOS = [1, 2, 3, 4, 5, 6, 63, 85, 86, 87, 65, 67, 68, 69, 70, 71, 72, 73, 74, 81,
                 105, 106, 109, 111, 115, 116, 117, 118, 124]

# Clientes excluidos
CLIENTES_EXCLUIDOS = [11, 3900]

# Vendedores excluidos por defecto (se combinan con los de la BD)
VENDEDORES_EXCLUIDOS_DEFAULT = [10, 11, 12]

# Items excluidos
ITEMS_EXCLUIDOS = [16, 460]

# Todos los sd_id permitidos
SD_TODOS = SD_VENTAS + SD_DEVOLUCIONES

# Strings pre-generados para usar en queries (excepto vendedores que son dinámicos)
DF_IDS_STR = ','.join(map(str, DF_PERMITIDOS))
SD_IDS_STR = ','.join(map(str, SD_TODOS))
ITEMS_EXCLUIDOS_STR = ','.join(map(str, ITEMS_EXCLUIDOS))
CLIENTES_EXCLUIDOS_STR = ','.join(map(str, CLIENTES_EXCLUIDOS))


def get_vendedores_excluidos_str(db: Session) -> str:
    """
    Obtiene los vendedores excluidos de la base de datos + los default.
    Retorna string para usar en SQL IN clause.
    """
    from app.models.vendedor_excluido import VendedorExcluido

    # Obtener de la BD
    excluidos_bd = db.query(VendedorExcluido.sm_id).all()
    excluidos_ids = {e.sm_id for e in excluidos_bd}

    # Combinar con los default
    todos_excluidos = excluidos_ids.union(set(VENDEDORES_EXCLUIDOS_DEFAULT))

    if not todos_excluidos:
        return '0'  # Para evitar errores de SQL si no hay ninguno

    return ','.join(map(str, sorted(todos_excluidos)))


def get_ventas_fuera_ml_query(vendedores_excluidos_str: str):
    """
    Query principal para obtener ventas por fuera de ML.
    Replica la lógica de la query SQL del ERP.

    Lógica clave:
    - PlusOrMinus calculado desde sd_id: +1 para ventas (1,4,21,56), -1 para NC (3,6,23,66)
    - Maneja combos/asociaciones con it_isassociationgroup
    - Calcula precio de venta del grupo (suma de componentes) para combos
    - Excluye componentes individuales de combos (solo muestra el combo principal)
    - Excluye items con descripción 'Envio'
    """
    return f"""
    WITH CostoCalculado AS (
        -- Costo unitario histórico para cada item/transacción
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
    ),
    CTE_QtyDivisor AS (
        -- Divisor de cantidad para combos (cuántas unidades del combo se vendieron)
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
        -- Precio total del grupo/combo (suma de precios de componentes) POR TRANSACCION
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
        -- Costo total del combo (suma de costos de componentes) POR TRANSACCION
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

        -- Cantidad ajustada por PlusOrMinus (basado en sd_id)
        tit.it_qty * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as cantidad,

        -- Precio unitario sin IVA (solo usa precio_venta del grupo si el item NO tiene precio propio)
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

        -- Precio final sin IVA
        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta
            ELSE tit.it_price * tit.it_qty
        END * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as precio_final_sin_iva,

        -- Monto IVA
        (CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta
            ELSE tit.it_price * tit.it_qty
        END * COALESCE(ttn.tax_percentage, 21.0) / 100) * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as monto_iva,

        -- Precio final con IVA
        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta
            ELSE tit.it_price * tit.it_qty
        END * (1 + COALESCE(ttn.tax_percentage, 21.0) / 100) * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as precio_final_con_iva,

        tsm.sm_name as vendedor,

        -- Costo en pesos sin IVA (solo usa costo_combo si el item NO tiene precio propio, es decir, es un combo)
        CASE
            WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN COALESCE(ccb.costo_combo, 0)
            ELSE COALESCE(cc.costo_unitario, 0) * tit.it_qty
        END * CASE
            WHEN tct.sd_id IN (1, 4, 21, 56) THEN 1
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1
            ELSE 1
        END as costo_pesos_sin_iva,

        -- Markup: (precio_venta / costo) - 1 (sin comisión porque es fuera de ML)
        CASE
            WHEN (CASE WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN COALESCE(ccb.costo_combo, 0) ELSE COALESCE(cc.costo_unitario, 0) * tit.it_qty END) = 0 THEN NULL
            ELSE (
                CASE WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN pv.precio_venta ELSE tit.it_price * tit.it_qty END
                / CASE WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN ccb.costo_combo ELSE cc.costo_unitario * tit.it_qty END
            ) - 1
        END as markup

    FROM tb_item_transactions tit

    LEFT JOIN tb_commercial_transactions tct
        ON tct.comp_id = tit.comp_id
        AND tct.ct_transaction = tit.ct_transaction

    -- JOIN a tb_item usando item_id, it_item_id_origin o item_idfrompreinvoice
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
        AND tct.sm_id NOT IN ({vendedores_excluidos_str})
        AND tct.sd_id IN ({SD_IDS_STR})
        AND tit.it_qty <> 0
        -- Excluir items "Envio"
        AND NOT (
            CASE
                WHEN tit.item_id IS NULL AND tit.it_item_id_origin IS NULL
                THEN COALESCE(titd.itm_desc, '')
                ELSE COALESCE(ti.item_desc, '')
            END ILIKE '%envio%'
        )
        -- Excluir componentes individuales de combos (solo mostrar el combo principal)
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
    # Obtener vendedores excluidos dinámicamente
    vendedores_excluidos = get_vendedores_excluidos_str(db)

    query_str = get_ventas_fuera_ml_query(vendedores_excluidos)

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
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    # Query ultra-rápida desde tabla de métricas pre-calculadas
    stats_query = """
    SELECT
        COUNT(*) as total_ventas,
        COUNT(*) FILTER (WHERE costo_total = 0 OR costo_total IS NULL) as productos_sin_costo,
        COALESCE(SUM(cantidad * signo), 0) as total_unidades,
        COALESCE(SUM(monto_total * signo), 0) as monto_total_sin_iva,
        COALESCE(SUM(monto_con_iva * signo), 0) as monto_total_con_iva,
        COALESCE(SUM(costo_total * signo), 0) as costo_total,
        -- Solo productos con costo
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_total * signo ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_con_iva * signo ELSE 0 END), 0) as monto_con_costo_con_iva,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN costo_total * signo ELSE 0 END), 0) as costo_con_costo
    FROM ventas_fuera_ml_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
    """

    result = db.execute(
        text(stats_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchone()

    # Extraer resultados
    total_ventas = result.total_ventas or 0
    productos_sin_costo = result.productos_sin_costo or 0
    total_unidades = float(result.total_unidades or 0)
    monto_con_costo = float(result.monto_con_costo or 0)
    monto_con_costo_con_iva = float(result.monto_con_costo_con_iva or 0)
    costo_con_costo = float(result.costo_con_costo or 0)

    # Por sucursal
    sucursal_query = """
    SELECT
        sucursal,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad * signo), 0) as unidades,
        COALESCE(SUM(monto_total * signo), 0) as monto
    FROM ventas_fuera_ml_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
    GROUP BY sucursal
    """
    sucursales_result = db.execute(text(sucursal_query), {"from_date": from_date, "to_date": to_date + " 23:59:59"}).fetchall()

    sucursales_dict = {}
    for s in sucursales_result:
        if s.sucursal:
            sucursales_dict[s.sucursal] = {"ventas": s.total_ventas, "unidades": float(s.unidades or 0), "monto": float(s.monto or 0)}

    # Por vendedor
    vendedor_query = """
    SELECT
        vendedor,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad * signo), 0) as unidades,
        COALESCE(SUM(monto_total * signo), 0) as monto
    FROM ventas_fuera_ml_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
    GROUP BY vendedor
    """
    vendedores_result = db.execute(text(vendedor_query), {"from_date": from_date, "to_date": to_date + " 23:59:59"}).fetchall()

    vendedores_dict = {}
    for v in vendedores_result:
        if v.vendedor:
            vendedores_dict[v.vendedor] = {"ventas": v.total_ventas, "unidades": float(v.unidades or 0), "monto": float(v.monto or 0)}

    # Calcular markup promedio
    markup_promedio = None
    if monto_con_costo > 0 and costo_con_costo > 0:
        markup_promedio = (monto_con_costo / costo_con_costo) - 1

    return {
        "total_ventas": total_ventas,
        "total_unidades": total_unidades,
        "monto_total_sin_iva": monto_con_costo,
        "monto_total_con_iva": monto_con_costo_con_iva,
        "costo_total": costo_con_costo,
        "markup_promedio": markup_promedio,
        "productos_sin_costo": productos_sin_costo,
        "por_sucursal": sucursales_dict,
        "por_vendedor": vendedores_dict
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
    # Obtener vendedores excluidos dinámicamente
    VENDEDORES_EXCLUIDOS_STR = get_vendedores_excluidos_str(db)

    # Query unificada que comienza desde tb_item_transactions
    query = f"""
    WITH combo_precios AS (
        SELECT tit.it_isassociationgroup as group_id, tit.ct_transaction,
            SUM(tit.it_price * tit.it_qty) as precio_combo
        FROM tb_item_transactions tit
        LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
        WHERE tit.it_isassociationgroup IS NOT NULL
          AND tit.it_price IS NOT NULL AND tit.it_price > 0
          AND tct.ct_date BETWEEN :from_date AND :to_date
        GROUP BY tit.it_isassociationgroup, tit.ct_transaction
    )
    SELECT
        tbd.brand_desc as marca,
        COUNT(*) as total_ventas,
        SUM(tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as unidades_vendidas,
        SUM(
            CASE
                WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN cp.precio_combo
                ELSE tit.it_price * tit.it_qty
            END * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
        ) as monto_sin_iva,
        SUM(
            CASE
                WHEN iclh.curr_id = 1 THEN COALESCE(iclh.iclh_price, 0) * tit.it_qty
                ELSE COALESCE(iclh.iclh_price, 0) * COALESCE(ceh.ceh_exchange, 1) * tit.it_qty
            END * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
        ) as costo_total,
        -- Monto solo de productos CON costo (para markup)
        SUM(
            CASE
                WHEN COALESCE(iclh.iclh_price, 0) > 0 THEN
                    CASE
                        WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN cp.precio_combo
                        ELSE tit.it_price * tit.it_qty
                    END * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
                ELSE 0
            END
        ) as monto_con_costo,
        -- Costo solo de productos CON costo (para markup)
        SUM(
            CASE
                WHEN COALESCE(iclh.iclh_price, 0) > 0 THEN
                    CASE
                        WHEN iclh.curr_id = 1 THEN iclh.iclh_price * tit.it_qty
                        ELSE iclh.iclh_price * COALESCE(ceh.ceh_exchange, 1) * tit.it_qty
                    END * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
                ELSE 0
            END
        ) as costo_con_costo

    FROM tb_item_transactions tit
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_item ti ON ti.comp_id = tit.comp_id AND ti.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN combo_precios cp ON cp.group_id = tit.it_isassociationgroup AND cp.ct_transaction = tit.ct_transaction
    LEFT JOIN LATERAL (
        SELECT iclh_price, curr_id
        FROM tb_item_cost_list_history
        WHERE item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice) AND iclh_cd <= tct.ct_date AND coslis_id = 1
        ORDER BY iclh_id DESC LIMIT 1
    ) iclh ON true
    LEFT JOIN LATERAL (
        SELECT ceh_exchange
        FROM tb_cur_exch_history
        WHERE ceh_cd <= tct.ct_date
        ORDER BY ceh_cd DESC LIMIT 1
    ) ceh ON true

    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN ({DF_IDS_STR})
        AND (tit.item_id NOT IN ({ITEMS_EXCLUIDOS_STR}) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN ({CLIENTES_EXCLUIDOS_STR})
        AND tct.sm_id NOT IN ({VENDEDORES_EXCLUIDOS_STR})
        AND tit.it_qty <> 0
        AND tct.sd_id IN ({SD_IDS_STR})
        AND COALESCE(ti.item_desc, '') NOT ILIKE '%envio%'
        -- Excluir componentes de combos
        AND NOT (
            COALESCE(tit.it_isassociation, false) = true
            AND COALESCE(tit.it_order, 1) <> 1
            AND tit.it_isassociationgroup IS NOT NULL
        )

    GROUP BY tbd.brand_desc
    ORDER BY monto_sin_iva DESC
    LIMIT :limit
    """

    result = db.execute(
        text(query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    ).fetchall()

    # Calcular markup desde totales (solo productos con costo, sin comisión ML porque es venta directa)
    marcas = []
    for r in result:
        # Para monto y costo: solo usar productos con costo
        monto_con_costo = float(r.monto_con_costo or 0)
        costo_con_costo = float(r.costo_con_costo or 0)
        # Markup = (monto / costo) - 1 (solo productos con costo)
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
    # Obtener vendedores excluidos dinámicamente
    VENDEDORES_EXCLUIDOS_STR = get_vendedores_excluidos_str(db)

    # Query unificada que comienza desde tb_item_transactions
    query = f"""
    WITH combo_precios AS (
        SELECT tit.it_isassociationgroup as group_id, tit.ct_transaction,
            SUM(tit.it_price * tit.it_qty) as precio_combo
        FROM tb_item_transactions tit
        LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
        WHERE tit.it_isassociationgroup IS NOT NULL
          AND tit.it_price IS NOT NULL AND tit.it_price > 0
          AND tct.ct_date BETWEEN :from_date AND :to_date
        GROUP BY tit.it_isassociationgroup, tit.ct_transaction
    )
    SELECT
        ti.item_id,
        ti.item_code as codigo,
        COALESCE(ti.item_desc, titd.itm_desc) as descripcion,
        tbd.brand_desc as marca,
        SUM(tit.it_qty * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END) as unidades_vendidas,
        SUM(
            CASE
                WHEN tit.it_price IS NULL OR tit.it_price = 0 THEN cp.precio_combo
                ELSE tit.it_price * tit.it_qty
            END * CASE WHEN tct.sd_id IN (3, 6, 23, 66) THEN -1 ELSE 1 END
        ) as monto_total,
        COUNT(DISTINCT tit.it_transaction) as cantidad_operaciones

    FROM tb_item_transactions tit
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_item ti ON ti.comp_id = tit.comp_id AND ti.item_id = COALESCE(tit.item_id, tit.it_item_id_origin, tit.item_idfrompreinvoice)
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN tb_item_transaction_details titd ON titd.comp_id = tit.comp_id AND titd.bra_id = tit.bra_id AND titd.it_transaction = tit.it_transaction
    LEFT JOIN combo_precios cp ON cp.group_id = tit.it_isassociationgroup AND cp.ct_transaction = tit.ct_transaction

    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN ({DF_IDS_STR})
        AND (tit.item_id NOT IN ({ITEMS_EXCLUIDOS_STR}) OR tit.item_id IS NULL)
        AND tct.cust_id NOT IN ({CLIENTES_EXCLUIDOS_STR})
        AND tct.sm_id NOT IN ({VENDEDORES_EXCLUIDOS_STR})
        AND tit.it_qty <> 0
        AND tct.sd_id IN ({SD_IDS_STR})
        AND COALESCE(ti.item_desc, titd.itm_desc, '') NOT ILIKE '%envio%'
        -- Excluir componentes de combos
        AND NOT (
            COALESCE(tit.it_isassociation, false) = true
            AND COALESCE(tit.it_order, 1) <> 1
            AND tit.it_isassociationgroup IS NOT NULL
        )

    GROUP BY ti.item_id, ti.item_code, COALESCE(ti.item_desc, titd.itm_desc), tbd.brand_desc
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
