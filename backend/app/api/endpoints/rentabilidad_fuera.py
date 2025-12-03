"""
Endpoints para métricas de rentabilidad de ventas por fuera de MercadoLibre
Replica la funcionalidad de rentabilidad.py pero usando datos del ERP directamente
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, or_
from typing import List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal
from pydantic import BaseModel

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


# ============================================================================
# Schemas
# ============================================================================

class DesgloseMarca(BaseModel):
    """Desglose por marca dentro de una card"""
    marca: str
    monto_venta: float
    ganancia: float
    markup_promedio: float


class CardRentabilidadFuera(BaseModel):
    """Card de rentabilidad para ventas fuera de ML"""
    nombre: str
    tipo: str  # marca, categoria, subcategoria, producto
    identificador: Optional[str] = None

    # Métricas
    total_ventas: int
    monto_venta: float
    costo_total: float
    ganancia: float
    markup_promedio: float

    # Offsets aplicados
    offset_total: float
    ganancia_con_offset: float
    markup_con_offset: float

    # Desglose por marca (cuando hay múltiples marcas seleccionadas)
    desglose_marcas: Optional[List[DesgloseMarca]] = None


class RentabilidadFueraResponse(BaseModel):
    cards: List[CardRentabilidadFuera]
    totales: CardRentabilidadFuera
    filtros_aplicados: dict


class ProductoBusquedaFuera(BaseModel):
    """Producto encontrado en búsqueda"""
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str] = None
    categoria: Optional[str] = None


# ============================================================================
# Constantes
# ============================================================================

# Mapeo de sd_id para PlusOrMinus
SD_VENTAS = [1, 4, 21, 56]
SD_DEVOLUCIONES = [3, 6, 23, 66]
SD_TODOS = SD_VENTAS + SD_DEVOLUCIONES

# df_id permitidos para ventas (facturas, remitos, etc.)
# Sucursal 45 (Grupo Gauss): 105-118, 124
# Excluimos: 113, 114 (TN), 129-132 (MercadoLibre)
DF_PERMITIDOS = [1, 2, 3, 4, 5, 6, 63, 85, 86, 87, 65, 67, 68, 69, 70, 71, 72, 73, 74, 81,
                 105, 106, 107, 109, 110, 111, 112, 115, 116, 117, 118, 124]

# Exclusiones
CLIENTES_EXCLUIDOS = [11, 3900]
VENDEDORES_EXCLUIDOS = [10, 11, 12]
ITEMS_EXCLUIDOS = [16, 460]


# ============================================================================
# Query base
# ============================================================================

def get_base_ventas_query(grupo_by: str, filtros_extra: str = "") -> str:
    """
    Query base para obtener ventas agrupadas por el nivel especificado.
    grupo_by puede ser: 'marca', 'categoria', 'subcategoria', 'producto'
    """

    if grupo_by == 'marca':
        select_campos = "tbd.brand_desc as nombre, tbd.brand_desc as identificador"
        group_by = "tbd.brand_desc"
    elif grupo_by == 'categoria':
        select_campos = "tcc.cat_desc as nombre, tcc.cat_desc as identificador"
        group_by = "tcc.cat_desc"
    elif grupo_by == 'subcategoria':
        select_campos = "tsc.subcat_desc as nombre, tsc.subcat_desc as identificador"
        group_by = "tsc.subcat_desc"
    else:  # producto
        select_campos = "CONCAT(ti.item_code, ' - ', ti.item_desc) as nombre, ti.item_id::text as identificador"
        group_by = "ti.item_id, ti.item_code, ti.item_desc"

    return f"""
    WITH costo_venta AS (
        SELECT
            tit.it_transaction,
            tit.item_id,
            tct.ct_date,
            tit.it_qty,
            tit.it_price,
            tct.sd_id,
            tct.bra_id,
            tbd.brand_desc as marca,
            tcc.cat_desc as categoria,
            tsc.subcat_desc as subcategoria,
            ti.item_code,
            ti.item_desc,
            COALESCE(ttn.tax_percentage, 21.0) as iva_porcentaje,

            -- Costo histórico
            COALESCE(iclh.iclh_price, 0) as costo_unitario,
            COALESCE(iclh.curr_id, 1) as costo_moneda,
            COALESCE(ceh.ceh_exchange, 1) as tipo_cambio

        FROM tb_item ti

        LEFT JOIN tb_item_transactions tit
            ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id

        LEFT JOIN tb_commercial_transactions tct
            ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction

        LEFT JOIN tb_brand tbd
            ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id

        LEFT JOIN tb_category tcc
            ON tcc.comp_id = ti.comp_id AND tcc.cat_id = ti.cat_id

        LEFT JOIN tb_subcategory tsc
            ON tsc.comp_id = ti.comp_id AND tsc.cat_id = ti.cat_id AND tsc.subcat_id = ti.subcat_id

        LEFT JOIN tb_item_taxes titx
            ON titx.comp_id = ti.comp_id AND titx.item_id = ti.item_id

        LEFT JOIN tb_tax_name ttn
            ON ttn.comp_id = ti.comp_id AND ttn.tax_id = titx.tax_id

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
            AND tct.df_id IN ({','.join(map(str, DF_PERMITIDOS))})
            AND (tit.item_id NOT IN ({','.join(map(str, ITEMS_EXCLUIDOS))}) OR tit.item_id IS NULL)
            AND tct.cust_id NOT IN ({','.join(map(str, CLIENTES_EXCLUIDOS))})
            AND tct.sm_id NOT IN ({','.join(map(str, VENDEDORES_EXCLUIDOS))})
            AND tit.it_price <> 0
            AND tit.it_qty <> 0
            AND tct.sd_id IN ({','.join(map(str, SD_TODOS))})
            {filtros_extra}
    )
    SELECT
        {select_campos},
        COUNT(*) as total_ventas,

        -- Monto venta (sin IVA, con signo)
        SUM(
            it_price * it_qty *
            CASE WHEN bra_id = 35 THEN (1 + iva_porcentaje / 100) ELSE 1 END *
            CASE WHEN sd_id IN ({','.join(map(str, SD_DEVOLUCIONES))}) THEN -1 ELSE 1 END
        ) as monto_venta,

        -- Costo total
        SUM(
            CASE
                WHEN costo_moneda = 1 THEN costo_unitario * it_qty
                ELSE costo_unitario * tipo_cambio * it_qty
            END *
            CASE WHEN sd_id IN ({','.join(map(str, SD_DEVOLUCIONES))}) THEN -1 ELSE 1 END
        ) as costo_total,

        -- Ganancia simple (monto - costo)
        SUM(
            it_price * it_qty *
            CASE WHEN bra_id = 35 THEN (1 + iva_porcentaje / 100) ELSE 1 END *
            CASE WHEN sd_id IN ({','.join(map(str, SD_DEVOLUCIONES))}) THEN -1 ELSE 1 END
        ) - SUM(
            CASE
                WHEN costo_moneda = 1 THEN costo_unitario * it_qty
                ELSE costo_unitario * tipo_cambio * it_qty
            END *
            CASE WHEN sd_id IN ({','.join(map(str, SD_DEVOLUCIONES))}) THEN -1 ELSE 1 END
        ) as ganancia,

        -- Markup promedio: ((precio_venta / costo) - 1) * 100
        AVG(
            CASE
                WHEN costo_unitario = 0 THEN NULL
                ELSE (
                    (it_price * CASE WHEN bra_id = 35 THEN (1 + iva_porcentaje / 100) ELSE 0.95 END) /
                    CASE
                        WHEN costo_moneda = 1 THEN costo_unitario
                        ELSE costo_unitario * tipo_cambio
                    END - 1
                ) * 100
            END
        ) as markup_promedio

    FROM costo_venta
    WHERE nombre IS NOT NULL
    GROUP BY {group_by}
    ORDER BY monto_venta DESC
    """


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/rentabilidad-fuera", response_model=RentabilidadFueraResponse)
async def obtener_rentabilidad_fuera(
    fecha_desde: date = Query(..., description="Fecha inicio del período"),
    fecha_hasta: date = Query(..., description="Fecha fin del período"),
    marcas: Optional[str] = Query(None, description="Marcas separadas por coma"),
    categorias: Optional[str] = Query(None, description="Categorías separadas por coma"),
    subcategorias: Optional[str] = Query(None, description="Subcategorías separadas por coma"),
    productos: Optional[str] = Query(None, description="Item IDs separados por coma"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene métricas de rentabilidad para ventas fuera de ML agrupadas según los filtros.
    """
    # Parsear filtros
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split(',')] if subcategorias else []
    lista_productos = [int(p.strip()) for p in productos.split(',') if p.strip().isdigit()] if productos else []

    # Determinar nivel de agrupación
    if lista_productos:
        nivel = "producto"
    elif lista_subcategorias:
        nivel = "producto"
    elif lista_marcas and lista_categorias:
        nivel = "subcategoria"
    elif lista_marcas:
        nivel = "categoria"
    elif lista_categorias:
        nivel = "marca"
    else:
        nivel = "marca"

    # Construir filtros SQL
    filtros_extra = ""
    params = {
        "from_date": fecha_desde.isoformat(),
        "to_date": (fecha_hasta + timedelta(days=1)).isoformat()
    }

    if lista_productos:
        filtros_extra += f" AND ti.item_id IN ({','.join(map(str, lista_productos))})"
    if lista_marcas:
        marcas_quoted = "','".join(lista_marcas)
        filtros_extra += f" AND tbd.brand_desc IN ('{marcas_quoted}')"
    if lista_categorias:
        cats_quoted = "','".join(lista_categorias)
        filtros_extra += f" AND tcc.cat_desc IN ('{cats_quoted}')"
    if lista_subcategorias:
        subcats_quoted = "','".join(lista_subcategorias)
        filtros_extra += f" AND tsc.subcat_desc IN ('{subcats_quoted}')"

    # Ejecutar query
    query_str = get_base_ventas_query(nivel, filtros_extra)
    result = db.execute(text(query_str), params)
    resultados = result.fetchall()

    # Obtener offsets vigentes
    offsets = db.query(OffsetGanancia).filter(
        OffsetGanancia.fecha_desde <= fecha_hasta,
        or_(
            OffsetGanancia.fecha_hasta.is_(None),
            OffsetGanancia.fecha_hasta >= fecha_desde
        )
    ).all()

    # Función para calcular offset
    def calcular_valor_offset(offset, cantidad_vendida, costo_total):
        tipo = offset.tipo_offset or 'monto_fijo'
        if tipo == 'monto_fijo':
            return float(offset.monto or 0)
        elif tipo == 'monto_por_unidad':
            monto_base = float(offset.monto or 0)
            if offset.moneda == 'USD' and offset.tipo_cambio:
                monto_base *= float(offset.tipo_cambio)
            return monto_base * cantidad_vendida
        elif tipo == 'porcentaje_costo':
            return (float(offset.porcentaje or 0) / 100) * costo_total
        return float(offset.monto or 0)

    # Construir cards
    cards = []
    total_ventas = 0
    total_monto_venta = 0.0
    total_costo = 0.0
    total_ganancia = 0.0
    total_offset = 0.0

    for r in resultados:
        # Calcular offset aplicable
        offset_aplicable = 0.0
        cantidad_vendida = r.total_ventas
        costo_total_item = float(r.costo_total or 0)

        for offset in offsets:
            if nivel == "marca" and offset.marca == r.nombre:
                offset_aplicable += calcular_valor_offset(offset, cantidad_vendida, costo_total_item)
            elif nivel == "categoria" and offset.categoria == r.nombre:
                offset_aplicable += calcular_valor_offset(offset, cantidad_vendida, costo_total_item)
            elif nivel == "subcategoria" and offset.subcategoria_id and str(offset.subcategoria_id) == str(r.identificador):
                offset_aplicable += calcular_valor_offset(offset, cantidad_vendida, costo_total_item)
            elif nivel == "producto" and offset.item_id and str(offset.item_id) == str(r.identificador):
                offset_aplicable += calcular_valor_offset(offset, cantidad_vendida, costo_total_item)

        monto_venta = float(r.monto_venta or 0)
        costo_total = float(r.costo_total or 0)
        ganancia = float(r.ganancia or 0)
        markup_promedio = float(r.markup_promedio or 0)

        ganancia_con_offset = ganancia + offset_aplicable
        markup_con_offset = ((ganancia_con_offset / costo_total) * 100) if costo_total > 0 else 0

        cards.append(CardRentabilidadFuera(
            nombre=r.nombre or "Sin nombre",
            tipo=nivel,
            identificador=str(r.identificador) if r.identificador else None,
            total_ventas=r.total_ventas,
            monto_venta=monto_venta,
            costo_total=costo_total,
            ganancia=ganancia,
            markup_promedio=markup_promedio,
            offset_total=offset_aplicable,
            ganancia_con_offset=ganancia_con_offset,
            markup_con_offset=markup_con_offset
        ))

        # Acumular totales
        total_ventas += r.total_ventas
        total_monto_venta += monto_venta
        total_costo += costo_total
        total_ganancia += ganancia
        total_offset += offset_aplicable

    # Ordenar por monto de venta descendente
    cards.sort(key=lambda c: c.monto_venta, reverse=True)

    # Calcular totales
    total_ganancia_con_offset = total_ganancia + total_offset
    total_markup = ((total_ganancia / total_costo) * 100) if total_costo > 0 else 0
    total_markup_con_offset = ((total_ganancia_con_offset / total_costo) * 100) if total_costo > 0 else 0

    totales = CardRentabilidadFuera(
        nombre="TOTAL",
        tipo="total",
        identificador=None,
        total_ventas=total_ventas,
        monto_venta=total_monto_venta,
        costo_total=total_costo,
        ganancia=total_ganancia,
        markup_promedio=total_markup,
        offset_total=total_offset,
        ganancia_con_offset=total_ganancia_con_offset,
        markup_con_offset=total_markup_con_offset
    )

    return RentabilidadFueraResponse(
        cards=cards,
        totales=totales,
        filtros_aplicados={
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "marcas": lista_marcas,
            "categorias": lista_categorias,
            "subcategorias": lista_subcategorias,
            "productos": lista_productos,
            "nivel_agrupacion": nivel
        }
    )


@router.get("/rentabilidad-fuera/buscar-productos", response_model=List[ProductoBusquedaFuera])
async def buscar_productos_fuera(
    q: str = Query(..., min_length=2, description="Término de búsqueda"),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Busca productos por código o descripción que tengan ventas en el período.
    """
    search_term = f"%{q}%"

    query = f"""
    SELECT DISTINCT
        ti.item_id,
        ti.item_code as codigo,
        ti.item_desc as descripcion,
        tbd.brand_desc as marca,
        tcc.cat_desc as categoria
    FROM tb_item ti
    LEFT JOIN tb_item_transactions tit
        ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
    LEFT JOIN tb_commercial_transactions tct
        ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_brand tbd
        ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN tb_category tcc
        ON tcc.comp_id = ti.comp_id AND tcc.cat_id = ti.cat_id
    WHERE tct.ct_date BETWEEN :from_date AND :to_date
        AND tct.df_id IN ({','.join(map(str, DF_PERMITIDOS))})
        AND tct.cust_id NOT IN ({','.join(map(str, CLIENTES_EXCLUIDOS))})
        AND tct.sm_id NOT IN ({','.join(map(str, VENDEDORES_EXCLUIDOS))})
        AND tct.sd_id IN ({','.join(map(str, SD_TODOS))})
        AND (ti.item_code ILIKE :search OR ti.item_desc ILIKE :search)
    LIMIT 50
    """

    result = db.execute(
        text(query),
        {
            "from_date": fecha_desde.isoformat(),
            "to_date": (fecha_hasta + timedelta(days=1)).isoformat(),
            "search": search_term
        }
    )

    return [
        ProductoBusquedaFuera(
            item_id=r.item_id,
            codigo=r.codigo or "",
            descripcion=r.descripcion or "",
            marca=r.marca,
            categoria=r.categoria
        )
        for r in result if r.item_id
    ]


@router.get("/rentabilidad-fuera/filtros")
async def obtener_filtros_disponibles_fuera(
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    marcas: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    subcategorias: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los valores disponibles para los filtros basado en los datos del período.
    """
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split(',')] if subcategorias else []

    params = {
        "from_date": fecha_desde.isoformat(),
        "to_date": (fecha_hasta + timedelta(days=1)).isoformat()
    }

    base_where = f"""
        WHERE tct.ct_date BETWEEN :from_date AND :to_date
            AND tct.df_id IN ({','.join(map(str, DF_PERMITIDOS))})
            AND tct.cust_id NOT IN ({','.join(map(str, CLIENTES_EXCLUIDOS))})
            AND tct.sm_id NOT IN ({','.join(map(str, VENDEDORES_EXCLUIDOS))})
            AND tct.sd_id IN ({','.join(map(str, SD_TODOS))})
    """

    # Marcas
    marcas_where = base_where
    if lista_categorias:
        cats_quoted = "','".join(lista_categorias)
        marcas_where += f" AND tcc.cat_desc IN ('{cats_quoted}')"
    if lista_subcategorias:
        subcats_quoted = "','".join(lista_subcategorias)
        marcas_where += f" AND tsc.subcat_desc IN ('{subcats_quoted}')"

    marcas_query = f"""
    SELECT DISTINCT tbd.brand_desc as marca
    FROM tb_item ti
    LEFT JOIN tb_item_transactions tit ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN tb_category tcc ON tcc.comp_id = ti.comp_id AND tcc.cat_id = ti.cat_id
    LEFT JOIN tb_subcategory tsc ON tsc.comp_id = ti.comp_id AND tsc.cat_id = ti.cat_id AND tsc.subcat_id = ti.subcat_id
    {marcas_where}
        AND tbd.brand_desc IS NOT NULL
    ORDER BY tbd.brand_desc
    """
    marcas_result = db.execute(text(marcas_query), params).fetchall()

    # Categorías
    cats_where = base_where
    if lista_marcas:
        marcas_quoted = "','".join(lista_marcas)
        cats_where += f" AND tbd.brand_desc IN ('{marcas_quoted}')"
    if lista_subcategorias:
        subcats_quoted = "','".join(lista_subcategorias)
        cats_where += f" AND tsc.subcat_desc IN ('{subcats_quoted}')"

    cats_query = f"""
    SELECT DISTINCT tcc.cat_desc as categoria
    FROM tb_item ti
    LEFT JOIN tb_item_transactions tit ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN tb_category tcc ON tcc.comp_id = ti.comp_id AND tcc.cat_id = ti.cat_id
    LEFT JOIN tb_subcategory tsc ON tsc.comp_id = ti.comp_id AND tsc.cat_id = ti.cat_id AND tsc.subcat_id = ti.subcat_id
    {cats_where}
        AND tcc.cat_desc IS NOT NULL
    ORDER BY tcc.cat_desc
    """
    cats_result = db.execute(text(cats_query), params).fetchall()

    # Subcategorías
    subcats_where = base_where
    if lista_marcas:
        marcas_quoted = "','".join(lista_marcas)
        subcats_where += f" AND tbd.brand_desc IN ('{marcas_quoted}')"
    if lista_categorias:
        cats_quoted = "','".join(lista_categorias)
        subcats_where += f" AND tcc.cat_desc IN ('{cats_quoted}')"

    subcats_query = f"""
    SELECT DISTINCT tsc.subcat_desc as subcategoria
    FROM tb_item ti
    LEFT JOIN tb_item_transactions tit ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
    LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tit.comp_id AND tct.ct_transaction = tit.ct_transaction
    LEFT JOIN tb_brand tbd ON tbd.comp_id = ti.comp_id AND tbd.brand_id = ti.brand_id
    LEFT JOIN tb_category tcc ON tcc.comp_id = ti.comp_id AND tcc.cat_id = ti.cat_id
    LEFT JOIN tb_subcategory tsc ON tsc.comp_id = ti.comp_id AND tsc.cat_id = ti.cat_id AND tsc.subcat_id = ti.subcat_id
    {subcats_where}
        AND tsc.subcat_desc IS NOT NULL
    ORDER BY tsc.subcat_desc
    """
    subcats_result = db.execute(text(subcats_query), params).fetchall()

    return {
        "marcas": [m[0] for m in marcas_result if m[0]],
        "categorias": [c[0] for c in cats_result if c[0]],
        "subcategorias": [s[0] for s in subcats_result if s[0]]
    }
