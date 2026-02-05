"""
Endpoints para métricas de ventas por fuera de MercadoLibre
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.core.database import get_db
from app.api.deps import get_current_user

router = APIRouter()


# ============================================================================
# Schemas
# ============================================================================

class VentaFueraMLResponse(BaseModel):
    """Respuesta detallada de una venta por fuera de ML"""
    id_operacion: int
    metrica_id: Optional[int] = None  # ID en tabla de métricas para edición
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

    model_config = ConfigDict(from_attributes=True)


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


class OperacionFueraMLResponse(BaseModel):
    """Respuesta de operación desde métricas (para detalle de operaciones con paginación)"""
    metrica_id: int
    id_operacion: int
    sucursal: Optional[str]
    cliente: Optional[str]
    vendedor: Optional[str]
    fecha: Optional[datetime]
    tipo_comprobante: Optional[str]
    numero_comprobante: Optional[str]
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria: Optional[str]
    codigo_item: Optional[str]
    descripcion: Optional[str]
    cantidad: float
    precio_unitario_sin_iva: float
    iva_porcentaje: float
    precio_final_sin_iva: float
    monto_iva: float
    precio_final_con_iva: float
    costo_unitario: float
    costo_pesos_sin_iva: float
    markup: Optional[float]
    ganancia: float
    signo: int


class CountResponse(BaseModel):
    """Response para endpoints de conteo (usado en paginación)"""
    total: int


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
# Facturas en dólares: 103, 122, 124, 125, 126, 127
# Excluimos: 107, 110 (Remitos), 112 (Recibos), 113, 114 (TN), 129-132 (MercadoLibre)
DF_PERMITIDOS = [1, 2, 3, 4, 5, 6, 63, 85, 86, 87, 65, 67, 68, 69, 70, 71, 72, 73, 74, 81,
                 103, 105, 106, 109, 111, 115, 116, 117, 118, 122, 124, 125, 126, 127]

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
                        (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tct.ct_date::date ORDER BY tc.fecha DESC LIMIT 1),
                        (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tct.ct_date ORDER BY ceh.ceh_cd DESC LIMIT 1),
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
            WHEN tct.sd_id IN (3, 6, 23, 66) THEN NULL  -- No calcular markup para devoluciones
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
        AND tc.cust_id = COALESCE(tct.cust_id, tct.ws_cust_id)

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
        AND COALESCE(tct.cust_id, tct.ws_cust_id) NOT IN ({CLIENTES_EXCLUIDOS_STR})
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

@router.get("/ventas-fuera-ml/operaciones", response_model=List[OperacionFueraMLResponse])
async def get_operaciones_desde_metricas(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    sucursal: Optional[str] = Query(None, description="Filtrar por sucursal"),
    vendedor: Optional[str] = Query(None, description="Filtrar por vendedor"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    solo_sin_costo: bool = Query(False, description="Solo mostrar operaciones sin costo"),
    search: Optional[str] = Query(None, description="Buscar en código, descripción o cliente"),
    limit: int = Query(1000, le=50000, description="Límite de resultados"),
    offset: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene operaciones desde la tabla de métricas pre-calculadas.
    Más rápido que el endpoint original y devuelve metrica_id para edición.
    Soporta paginación server-side con limit/offset.
    """
    # Construir query con filtros opcionales
    where_clauses = ["m.fecha_venta BETWEEN :from_date AND :to_date"]
    params = {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit, "offset": offset}

    if sucursal:
        sucursales = [s.strip() for s in sucursal.split(',') if s.strip()]
        if sucursales:
            sucursales_escaped = [s.replace("'", "''") for s in sucursales]
            sucursales_quoted = "','".join(sucursales_escaped)
            where_clauses.append(f"m.sucursal IN ('{sucursales_quoted}')")
    if vendedor:
        vendedores = [v.strip() for v in vendedor.split(',') if v.strip()]
        if vendedores:
            vendedores_escaped = [v.replace("'", "''") for v in vendedores]
            vendedores_quoted = "','".join(vendedores_escaped)
            where_clauses.append(f"m.vendedor IN ('{vendedores_quoted}')")
    if marca:
        where_clauses.append("m.marca = :marca")
        params["marca"] = marca
    if solo_sin_costo:
        where_clauses.append("(m.costo_total IS NULL OR m.costo_total = 0)")
    if search:
        # Buscar en código, descripción o cliente (case-insensitive)
        where_clauses.append("""(
            LOWER(COALESCE(o.codigo, m.codigo)) LIKE LOWER(:search) OR
            LOWER(COALESCE(o.descripcion, m.descripcion)) LIKE LOWER(:search) OR
            LOWER(COALESCE(o.cliente, tc.cust_name, m.cliente)) LIKE LOWER(:search)
        )""")
        params["search"] = f"%{search}%"

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT
        m.id as metrica_id,
        m.it_transaction as id_operacion,
        m.sucursal,
        COALESCE(o.cliente, tc.cust_name, m.cliente) as cliente,
        m.vendedor,
        m.fecha_venta as fecha,
        m.tipo_comprobante,
        m.numero_comprobante,
        COALESCE(o.marca, m.marca) as marca,
        COALESCE(o.categoria, m.categoria) as categoria,
        COALESCE(o.subcategoria, m.subcategoria) as subcategoria,
        COALESCE(o.codigo, m.codigo) as codigo,
        COALESCE(o.descripcion, m.descripcion) as descripcion,
        COALESCE(o.cantidad, m.cantidad) as cantidad,
        COALESCE(o.precio_unitario, m.monto_unitario) as precio_unitario_sin_iva,
        m.iva_porcentaje,
        COALESCE(o.precio_unitario * COALESCE(o.cantidad, m.cantidad), m.monto_total) as precio_final_sin_iva,
        m.monto_iva,
        m.monto_con_iva as precio_final_con_iva,
        COALESCE(o.costo_unitario, m.costo_unitario) as costo_unitario,
        COALESCE(o.costo_unitario * COALESCE(o.cantidad, m.cantidad), m.costo_total) as costo_pesos_sin_iva,
        m.markup_porcentaje as markup,
        m.ganancia,
        m.signo
    FROM ventas_fuera_ml_metricas m
    LEFT JOIN tb_customer tc ON tc.cust_id = m.cust_id AND tc.comp_id = 1
    LEFT JOIN ventas_fuera_ml_override o ON o.it_transaction = m.it_transaction
    WHERE {where_sql}
    ORDER BY m.fecha_venta DESC, m.it_transaction
    LIMIT :limit OFFSET :offset
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
            "markup": float(r.markup) / 100 if r.markup else None,  # Convertir a decimal (0.15 en lugar de 15%)
            "ganancia": float(r.ganancia) if r.ganancia else 0,
            "signo": r.signo
        }
        for r in result
    ]


@router.get("/ventas-fuera-ml/operaciones/count", response_model=CountResponse)
async def get_operaciones_count(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    sucursal: Optional[str] = Query(None, description="Filtrar por sucursal"),
    vendedor: Optional[str] = Query(None, description="Filtrar por vendedor"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    solo_sin_costo: bool = Query(False, description="Solo mostrar operaciones sin costo"),
    search: Optional[str] = Query(None, description="Buscar en código, descripción o cliente"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Cuenta el total de operaciones que coinciden con los filtros.
    Usado para paginación clásica.
    """
    # Construir query con filtros opcionales (misma lógica que get_operaciones)
    where_clauses = ["m.fecha_venta BETWEEN :from_date AND :to_date"]
    params = {"from_date": from_date, "to_date": to_date + " 23:59:59"}

    if sucursal:
        sucursales = [s.strip() for s in sucursal.split(',') if s.strip()]
        if sucursales:
            sucursales_escaped = [s.replace("'", "''") for s in sucursales]
            sucursales_quoted = "','".join(sucursales_escaped)
            where_clauses.append(f"m.sucursal IN ('{sucursales_quoted}')")
    if vendedor:
        vendedores = [v.strip() for v in vendedor.split(',') if v.strip()]
        if vendedores:
            vendedores_escaped = [v.replace("'", "''") for v in vendedores]
            vendedores_quoted = "','".join(vendedores_escaped)
            where_clauses.append(f"m.vendedor IN ('{vendedores_quoted}')")
    if marca:
        where_clauses.append("m.marca = :marca")
        params["marca"] = marca
    if solo_sin_costo:
        where_clauses.append("(m.costo_total IS NULL OR m.costo_total = 0)")
    if search:
        where_clauses.append("""(
            LOWER(COALESCE(o.codigo, m.codigo)) LIKE LOWER(:search) OR
            LOWER(COALESCE(o.descripcion, m.descripcion)) LIKE LOWER(:search) OR
            LOWER(COALESCE(o.cliente, tc.cust_name, m.cliente)) LIKE LOWER(:search)
        )""")
        params["search"] = f"%{search}%"

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT COUNT(*) as total
    FROM ventas_fuera_ml_metricas m
    LEFT JOIN tb_customer tc ON tc.cust_id = m.cust_id AND tc.comp_id = 1
    LEFT JOIN ventas_fuera_ml_override o ON o.it_transaction = m.it_transaction
    WHERE {where_sql}
    """

    result = db.execute(text(query), params).fetchone()
    return {"total": result.total if result else 0}


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
    sucursal: Optional[str] = Query(None, description="Filtrar por sucursales (separadas por coma)"),
    vendedor: Optional[str] = Query(None, description="Filtrar por vendedores (separados por coma)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene estadísticas agregadas de ventas por fuera de ML.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    Una sola query con GROUPING SETS para calcular todo de una vez.
    """
    # Construir cláusula WHERE dinámica
    where_clause = "WHERE fecha_venta BETWEEN :from_date AND :to_date"
    params = {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    
    if sucursal:
        sucursales = [s.strip() for s in sucursal.split(',') if s.strip()]
        if sucursales:
            sucursales_quoted = "','".join(sucursales)
            where_clause += f" AND sucursal IN ('{sucursales_quoted}')"
    
    if vendedor:
        vendedores = [v.strip() for v in vendedor.split(',') if v.strip()]
        if vendedores:
            vendedores_quoted = "','".join(vendedores)
            where_clause += f" AND vendedor IN ('{vendedores_quoted}')"
    
    # Query única con GROUPING SETS para stats totales, por sucursal y por vendedor
    combined_query = f"""
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
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_total * signo ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_con_iva * signo ELSE 0 END), 0) as monto_con_costo_con_iva,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN costo_total * signo ELSE 0 END), 0) as costo_con_costo
    FROM ventas_fuera_ml_metricas
    {where_clause}
    GROUP BY GROUPING SETS (
        (),
        (sucursal),
        (vendedor)
    )
    """

    results = db.execute(text(combined_query), params).fetchall()

    # Inicializar variables
    total_ventas = 0
    productos_sin_costo = 0
    total_unidades = 0.0
    monto_con_costo = 0.0
    monto_con_costo_con_iva = 0.0
    costo_con_costo = 0.0
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

    # Calcular markup promedio
    markup_promedio = None
    if monto_con_costo > 0 and costo_con_costo > 0:
        markup_promedio = (monto_con_costo / costo_con_costo) - 1

    # Obtener listas completas de sucursales y vendedores disponibles (sin filtro)
    sucursales_disponibles_query = """
    SELECT DISTINCT sucursal
    FROM ventas_fuera_ml_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
        AND sucursal IS NOT NULL
    ORDER BY sucursal
    """
    sucursales_disponibles = [r.sucursal for r in db.execute(
        text(sucursales_disponibles_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()]

    vendedores_disponibles_query = """
    SELECT DISTINCT vendedor
    FROM ventas_fuera_ml_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
        AND vendedor IS NOT NULL
    ORDER BY vendedor
    """
    vendedores_disponibles = [r.vendedor for r in db.execute(
        text(vendedores_disponibles_query),
        {"from_date": from_date, "to_date": to_date + " 23:59:59"}
    ).fetchall()]

    return {
        "total_ventas": total_ventas,
        "total_unidades": total_unidades,
        "monto_total_sin_iva": monto_con_costo,
        "monto_total_con_iva": monto_con_costo_con_iva,
        "costo_total": costo_con_costo,
        "markup_promedio": markup_promedio,
        "productos_sin_costo": productos_sin_costo,
        "por_sucursal": sucursales_dict,
        "por_vendedor": vendedores_dict,
        "sucursales_disponibles": sucursales_disponibles,
        "vendedores_disponibles": vendedores_disponibles
    }


@router.get("/ventas-fuera-ml/por-marca", response_model=List[VentaFueraMLPorMarcaResponse])
async def get_ventas_fuera_ml_por_marca(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(50, le=200, description="Límite de resultados"),
    sucursal: Optional[str] = Query(None, description="Filtrar por sucursales (separadas por coma)"),
    vendedor: Optional[str] = Query(None, description="Filtrar por vendedores (separados por coma)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por marca.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    # Construir cláusula WHERE dinámica
    where_clause = "WHERE fecha_venta BETWEEN :from_date AND :to_date"
    params = {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    
    if sucursal:
        sucursales = [s.strip() for s in sucursal.split(',') if s.strip()]
        if sucursales:
            # Escapar comillas simples en los nombres para evitar SQL injection
            sucursales_escaped = [s.replace("'", "''") for s in sucursales]
            sucursales_quoted = "','".join(sucursales_escaped)
            where_clause += f" AND sucursal IN ('{sucursales_quoted}')"
    
    if vendedor:
        vendedores = [v.strip() for v in vendedor.split(',') if v.strip()]
        if vendedores:
            # Escapar comillas simples en los nombres para evitar SQL injection
            vendedores_escaped = [v.replace("'", "''") for v in vendedores]
            vendedores_quoted = "','".join(vendedores_escaped)
            where_clause += f" AND vendedor IN ('{vendedores_quoted}')"
    
    # Query rápida desde tabla de métricas pre-calculadas
    query = f"""
    SELECT
        marca,
        COUNT(*) as total_ventas,
        COALESCE(SUM(cantidad * signo), 0) as unidades_vendidas,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN monto_total * signo ELSE 0 END), 0) as monto_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN costo_total * signo ELSE 0 END), 0) as costo_con_costo,
        COALESCE(SUM(CASE WHEN costo_total > 0 THEN ganancia * signo ELSE 0 END), 0) as ganancia_con_costo
    FROM ventas_fuera_ml_metricas
    {where_clause}
    GROUP BY marca
    ORDER BY monto_con_costo DESC
    LIMIT :limit
    """

    result = db.execute(text(query), params).fetchall()

    # Calcular markup desde totales: ganancia / costo
    marcas = []
    for r in result:
        monto_con_costo = float(r.monto_con_costo or 0)
        costo_con_costo = float(r.costo_con_costo or 0)
        ganancia_con_costo = float(r.ganancia_con_costo or 0)
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


@router.get("/ventas-fuera-ml/top-productos")
async def get_top_productos_fuera_ml(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(20, le=100, description="Límite de resultados"),
    sucursal: Optional[str] = Query(None, description="Filtrar por sucursales (separadas por coma)"),
    vendedor: Optional[str] = Query(None, description="Filtrar por vendedores (separados por coma)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene los productos más vendidos por fuera de ML.
    Usa la tabla de métricas pre-calculadas para mayor performance.
    """
    # Construir cláusula WHERE dinámica
    where_clause = "WHERE fecha_venta BETWEEN :from_date AND :to_date"
    params = {"from_date": from_date, "to_date": to_date + " 23:59:59", "limit": limit}
    
    if sucursal:
        sucursales = [s.strip() for s in sucursal.split(',') if s.strip()]
        if sucursales:
            # Escapar comillas simples en los nombres para evitar SQL injection
            sucursales_escaped = [s.replace("'", "''") for s in sucursales]
            sucursales_quoted = "','".join(sucursales_escaped)
            where_clause += f" AND sucursal IN ('{sucursales_quoted}')"
    
    if vendedor:
        vendedores = [v.strip() for v in vendedor.split(',') if v.strip()]
        if vendedores:
            # Escapar comillas simples en los nombres para evitar SQL injection
            vendedores_escaped = [v.replace("'", "''") for v in vendedores]
            vendedores_quoted = "','".join(vendedores_escaped)
            where_clause += f" AND vendedor IN ('{vendedores_quoted}')"

    # Query rápida desde tabla de métricas pre-calculadas
    query = f"""
    SELECT
        item_id,
        codigo,
        descripcion,
        marca,
        COALESCE(SUM(cantidad * signo), 0) as unidades_vendidas,
        COALESCE(SUM(monto_total * signo), 0) as monto_total,
        COUNT(*) as cantidad_operaciones
    FROM ventas_fuera_ml_metricas
    {where_clause}
    GROUP BY item_id, codigo, descripcion, marca
    ORDER BY unidades_vendidas DESC
    LIMIT :limit
    """

    result = db.execute(text(query), params).fetchall()

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


# ============================================================================
# Endpoint para actualizar costo manual de una operación
# ============================================================================

class ActualizarCostoRequest(BaseModel):
    """Request para actualizar el costo de una operación"""
    costo_unitario: float


class ActualizarMetricaRequest(BaseModel):
    """Request para actualizar campos de una métrica"""
    costo_unitario: Optional[float] = None
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None
    descripcion: Optional[str] = None
    codigo: Optional[str] = None


@router.put("/ventas-fuera-ml/metricas/{metrica_id}/costo")
async def actualizar_costo_operacion(
    metrica_id: int,
    request: ActualizarCostoRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Actualiza el costo unitario de una operación en la tabla de métricas.
    Recalcula automáticamente: costo_total, ganancia, markup_porcentaje.
    """
    from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica

    # Buscar la métrica
    metrica = db.query(VentaFueraMLMetrica).filter(
        VentaFueraMLMetrica.id == metrica_id
    ).first()

    if not metrica:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Operación no encontrada")

    # Actualizar costo unitario
    costo_unitario = Decimal(str(request.costo_unitario))
    cantidad = metrica.cantidad or Decimal('1')
    monto_total = metrica.monto_total or Decimal('0')

    # Calcular costo total
    costo_total = costo_unitario * cantidad

    # Calcular ganancia
    ganancia = monto_total - costo_total

    # Calcular markup
    markup_porcentaje = None
    if costo_total > 0:
        markup_porcentaje = ((monto_total / costo_total) - 1) * 100

    # Actualizar campos
    metrica.costo_unitario = costo_unitario
    metrica.costo_total = costo_total
    metrica.ganancia = ganancia
    metrica.markup_porcentaje = Decimal(str(markup_porcentaje)) if markup_porcentaje is not None else None
    metrica.moneda_costo = 'ARS'  # Costo manual siempre en ARS

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


@router.patch("/ventas-fuera-ml/metricas/{metrica_id}")
async def actualizar_metrica(
    metrica_id: int,
    request: ActualizarMetricaRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Actualiza campos de una métrica de venta por fuera de ML.
    Permite actualizar: costo_unitario, marca, categoria, subcategoria, descripcion, codigo.
    Si se actualiza el costo, recalcula automáticamente: costo_total, ganancia, markup_porcentaje.
    """
    from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
    from fastapi import HTTPException

    metrica = db.query(VentaFueraMLMetrica).filter(
        VentaFueraMLMetrica.id == metrica_id
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

        costo_total = costo_unitario * cantidad
        ganancia = monto_total - costo_total

        markup_porcentaje = None
        if costo_total > 0:
            markup_porcentaje = ((monto_total / costo_total) - 1) * 100

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


@router.get("/ventas-fuera-ml/metricas/{metrica_id}")
async def get_metrica_detalle(
    metrica_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene el detalle de una métrica específica.
    """
    from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica

    metrica = db.query(VentaFueraMLMetrica).filter(
        VentaFueraMLMetrica.id == metrica_id
    ).first()

    if not metrica:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Operación no encontrada")

    return {
        "id": metrica.id,
        "it_transaction": metrica.it_transaction,
        "item_id": metrica.item_id,
        "codigo": metrica.codigo,
        "descripcion": metrica.descripcion,
        "marca": metrica.marca,
        "cantidad": float(metrica.cantidad) if metrica.cantidad else 0,
        "monto_unitario": float(metrica.monto_unitario) if metrica.monto_unitario else 0,
        "monto_total": float(metrica.monto_total) if metrica.monto_total else 0,
        "costo_unitario": float(metrica.costo_unitario) if metrica.costo_unitario else 0,
        "costo_total": float(metrica.costo_total) if metrica.costo_total else 0,
        "ganancia": float(metrica.ganancia) if metrica.ganancia else 0,
        "markup_porcentaje": float(metrica.markup_porcentaje) if metrica.markup_porcentaje else None,
        "moneda_costo": metrica.moneda_costo,
        "fecha_venta": metrica.fecha_venta.isoformat() if metrica.fecha_venta else None
    }


# ============================================================================
# Endpoints para Overrides manuales de marca/categoría/subcategoría
# Estos datos NO se sobreescriben cuando se recalculan las métricas
# ============================================================================

class VentaFueraOverrideRequest(BaseModel):
    """Request para crear/actualizar override de datos"""
    it_transaction: int
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None
    cliente: Optional[str] = None
    cantidad: Optional[Decimal] = None
    precio_unitario: Optional[Decimal] = None
    costo_unitario: Optional[Decimal] = None


class VentaFueraOverrideResponse(BaseModel):
    """Response de override"""
    it_transaction: int
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria: Optional[str] = None
    cliente: Optional[str] = None
    cantidad: Optional[Decimal] = None
    precio_unitario: Optional[Decimal] = None
    costo_unitario: Optional[Decimal] = None


@router.get("/ventas-fuera-ml/overrides")
async def get_overrides_fuera_ml(
    from_date: str = Query(...),
    to_date: str = Query(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene todos los overrides de ventas fuera ML para un rango de fechas.
    Devuelve un diccionario con it_transaction como clave.
    """
    from app.models.venta_override import VentaFueraMLOverride

    # Primero obtener los it_transaction del período
    query = text("""
        SELECT DISTINCT it_transaction
        FROM ventas_fuera_ml_metricas
        WHERE fecha_venta >= :from_date AND fecha_venta <= :to_date
    """)

    result = db.execute(query, {"from_date": from_date, "to_date": to_date}).fetchall()
    it_transactions = [r[0] for r in result]

    if not it_transactions:
        return {}

    # Obtener overrides
    overrides = db.query(VentaFueraMLOverride).filter(
        VentaFueraMLOverride.it_transaction.in_(it_transactions)
    ).all()

    return {
        o.it_transaction: {
            "codigo": o.codigo,
            "descripcion": o.descripcion,
            "marca": o.marca,
            "categoria": o.categoria,
            "subcategoria": o.subcategoria,
            "cliente": o.cliente,
            "cantidad": float(o.cantidad) if o.cantidad else None,
            "precio_unitario": float(o.precio_unitario) if o.precio_unitario else None,
            "costo_unitario": float(o.costo_unitario) if o.costo_unitario else None
        }
        for o in overrides
    }


@router.post("/ventas-fuera-ml/override")
async def set_override_fuera_ml(
    request: VentaFueraOverrideRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Guarda o actualiza el override de datos para una venta fuera ML.
    Usa UPSERT para manejar concurrencia cuando se hacen múltiples llamadas simultáneas.
    """
    from sqlalchemy.dialects.postgresql import insert
    from app.models.venta_override import VentaFueraMLOverride

    usuario_id = current_user.id if hasattr(current_user, 'id') else None

    # Helper para limpiar strings vacíos
    def clean_str(val):
        if val is None or val == '':
            return None
        return val

    # Preparar valores para el upsert
    valores_insert = {
        'it_transaction': request.it_transaction,
        'codigo': clean_str(request.codigo),
        'descripcion': clean_str(request.descripcion),
        'marca': clean_str(request.marca),
        'categoria': clean_str(request.categoria),
        'subcategoria': clean_str(request.subcategoria),
        'cliente': clean_str(request.cliente),
        'cantidad': request.cantidad,
        'precio_unitario': request.precio_unitario,
        'costo_unitario': request.costo_unitario,
        'usuario_id': usuario_id
    }

    # Preparar valores para update (solo campos que vinieron en el request)
    valores_update = {'usuario_id': usuario_id}

    # Campos de texto
    for campo in ['codigo', 'descripcion', 'marca', 'categoria', 'subcategoria', 'cliente']:
        val = getattr(request, campo)
        if val is not None:
            valores_update[campo] = clean_str(val)

    # Campos numéricos
    for campo in ['cantidad', 'precio_unitario', 'costo_unitario']:
        val = getattr(request, campo)
        if val is not None:
            valores_update[campo] = val

    # UPSERT: INSERT ... ON CONFLICT DO UPDATE
    stmt = insert(VentaFueraMLOverride).values(**valores_insert)
    stmt = stmt.on_conflict_do_update(
        index_elements=['it_transaction'],
        set_=valores_update
    )

    db.execute(stmt)
    db.commit()

    return {
        "success": True,
        "it_transaction": request.it_transaction
    }


@router.delete("/ventas-fuera-ml/override/{it_transaction}")
async def delete_override_fuera_ml(
    it_transaction: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Elimina un override de venta fuera ML."""
    from app.models.venta_override import VentaFueraMLOverride
    from fastapi import HTTPException

    override = db.query(VentaFueraMLOverride).filter(
        VentaFueraMLOverride.it_transaction == it_transaction
    ).first()

    if not override:
        raise HTTPException(status_code=404, detail="Override no encontrado")

    db.delete(override)
    db.commit()

    return {"success": True, "it_transaction": it_transaction}


@router.get("/ventas-fuera-ml/jerarquia-productos")
async def get_jerarquia_productos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Devuelve la jerarquía de marca -> categorías -> subcategorías
    basada en los productos existentes en el ERP.
    """
    from collections import defaultdict

    # Obtener combinaciones únicas de marca, categoría, subcategoría
    # productos_erp tiene subcategoria_id (integer), necesitamos JOIN con tb_subcategory
    query = text("""
        SELECT DISTINCT
            pe.marca,
            pe.categoria,
            ts.subcat_desc as subcategoria
        FROM productos_erp pe
        LEFT JOIN tb_subcategory ts ON pe.subcategoria_id = ts.subcat_id
        WHERE pe.marca IS NOT NULL
          AND pe.categoria IS NOT NULL
        ORDER BY pe.marca, pe.categoria, ts.subcat_desc
    """)

    result = db.execute(query).fetchall()

    # Construir jerarquía
    jerarquia = defaultdict(lambda: defaultdict(set))

    for row in result:
        marca = row.marca
        categoria = row.categoria
        subcategoria = row.subcategoria

        if marca and categoria:
            if subcategoria:
                jerarquia[marca][categoria].add(subcategoria)
            else:
                # Asegurar que la categoría exista aunque no tenga subcategorías
                if categoria not in jerarquia[marca]:
                    jerarquia[marca][categoria] = set()

    # Convertir a formato serializable
    return {
        marca: {
            cat: sorted(list(subcats)) if subcats else []
            for cat, subcats in cats.items()
        }
        for marca, cats in sorted(jerarquia.items())
    }
