"""
Endpoints para métricas de rentabilidad de ventas por fuera de MercadoLibre
Replica la funcionalidad de rentabilidad.py pero usando datos del ERP directamente
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, or_, func, and_
from typing import List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal
from pydantic import BaseModel

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
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


class DesgloseOffset(BaseModel):
    """Desglose de un offset aplicado"""
    descripcion: str
    nivel: str  # marca, categoria, subcategoria, producto, grupo
    nombre_nivel: str
    tipo_offset: str  # monto_fijo, monto_por_unidad, porcentaje_costo
    monto: float


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

    # Desglose de offsets aplicados
    desglose_offsets: Optional[List[DesgloseOffset]] = None

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

# df_id permitidos para ventas (facturas, NC, ND, etc.)
# Sucursal 45 (Grupo Gauss): 105, 106, 109, 111, 115, 116, 117, 118, 124
# Facturas en dólares: 103, 122, 124, 125, 126, 127
# Excluimos: 107, 110 (Remitos), 112 (Recibos), 113, 114 (TN), 129-132 (MercadoLibre)
DF_PERMITIDOS = [1, 2, 3, 4, 5, 6, 63, 85, 86, 87, 65, 67, 68, 69, 70, 71, 72, 73, 74, 81,
                 103, 105, 106, 109, 111, 115, 116, 117, 118, 122, 124, 125, 126, 127]

# Exclusiones
CLIENTES_EXCLUIDOS = [11, 3900]
VENDEDORES_EXCLUIDOS_DEFAULT = [10, 11, 12]
ITEMS_EXCLUIDOS = [16, 460]


def get_vendedores_excluidos_str(db) -> str:
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
        return '0'

    return ','.join(map(str, sorted(todos_excluidos)))


# ============================================================================
# Query base
# ============================================================================

def get_base_ventas_query(grupo_by: str, filtros_extra: str = "", vendedores_excluidos_str: str = "10,11,12") -> str:
    """
    Query base para obtener ventas agrupadas por el nivel especificado.
    grupo_by puede ser: 'marca', 'categoria', 'subcategoria', 'producto'
    """

    if grupo_by == 'marca':
        select_campos = "marca as nombre, marca as identificador"
        group_by = "marca"
        where_not_null = "marca IS NOT NULL"
    elif grupo_by == 'categoria':
        select_campos = "categoria as nombre, categoria as identificador"
        group_by = "categoria"
        where_not_null = "categoria IS NOT NULL"
    elif grupo_by == 'subcategoria':
        select_campos = "subcategoria as nombre, subcategoria as identificador"
        group_by = "subcategoria"
        where_not_null = "subcategoria IS NOT NULL"
    else:  # producto
        select_campos = "CONCAT(item_code, ' - ', item_desc) as nombre, item_id::text as identificador"
        group_by = "item_id, item_code, item_desc"
        where_not_null = "item_id IS NOT NULL"

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
            AND tct.sm_id NOT IN ({vendedores_excluidos_str})
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

        -- Monto solo de productos CON costo (para calcular markup)
        SUM(
            CASE WHEN costo_unitario > 0 THEN
                it_price * it_qty *
                CASE WHEN bra_id = 35 THEN (1 + iva_porcentaje / 100) ELSE 1 END *
                CASE WHEN sd_id IN ({','.join(map(str, SD_DEVOLUCIONES))}) THEN -1 ELSE 1 END
            ELSE 0 END
        ) as monto_con_costo,

        -- Costo solo de productos CON costo (para calcular markup)
        SUM(
            CASE WHEN costo_unitario > 0 THEN
                CASE
                    WHEN costo_moneda = 1 THEN costo_unitario * it_qty
                    ELSE costo_unitario * tipo_cambio * it_qty
                END *
                CASE WHEN sd_id IN ({','.join(map(str, SD_DEVOLUCIONES))}) THEN -1 ELSE 1 END
            ELSE 0 END
        ) as costo_con_costo

    FROM costo_venta
    WHERE {where_not_null}
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
    marcas: Optional[str] = Query(None, description="Marcas separadas por |"),
    categorias: Optional[str] = Query(None, description="Categorías separadas por |"),
    subcategorias: Optional[str] = Query(None, description="Subcategorías separadas por |"),
    productos: Optional[str] = Query(None, description="Item IDs separados por |"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene métricas de rentabilidad para ventas fuera de ML agrupadas según los filtros.
    Los límites de offsets son ACUMULATIVOS con ventas ML.
    """
    # Parsear filtros (usar | como separador para evitar conflictos con comas en nombres)
    lista_marcas = [m.strip() for m in marcas.split('|')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split('|')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split('|')] if subcategorias else []
    lista_productos = [int(p.strip()) for p in productos.split('|') if p.strip().isdigit()] if productos else []

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

    # Convertir fechas a datetime para comparaciones
    fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
    fecha_hasta_dt = datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time())

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

    # Obtener vendedores excluidos dinámicamente
    vendedores_excluidos = get_vendedores_excluidos_str(db)

    # Ejecutar query
    query_str = get_base_ventas_query(nivel, filtros_extra, vendedores_excluidos)
    result = db.execute(text(query_str), params)
    resultados = result.fetchall()

    # Obtener offsets vigentes (solo los que NO son exclusivos de ML)
    offsets = db.query(OffsetGanancia).filter(
        OffsetGanancia.fecha_desde <= fecha_hasta,
        or_(
            OffsetGanancia.fecha_hasta.is_(None),
            OffsetGanancia.fecha_hasta >= fecha_desde
        ),
        # Excluir offsets que solo aplican a ML
        or_(
            OffsetGanancia.aplica_ml.is_(None),
            OffsetGanancia.aplica_ml == False,
            # Si aplica_ml es True pero no hay campo exclusivo, incluir
            and_(OffsetGanancia.aplica_ml == True, OffsetGanancia.grupo_id.isnot(None))
        )
    ).all()

    # ========================================================================
    # FUNCIONES AUXILIARES PARA CONSUMO ACUMULATIVO (ML + FUERA_ML)
    # ========================================================================

    def calcular_consumo_grupo_acumulado(grupo_id, desde_dt, hasta_dt):
        """
        Calcula unidades y monto para un grupo en un rango de fechas.
        ACUMULATIVO: suma tanto ventas ML como fuera de ML.
        """
        consumo = db.query(
            func.sum(OffsetGrupoConsumo.cantidad).label('total_unidades'),
            func.sum(OffsetGrupoConsumo.monto_offset_aplicado).label('total_monto_ars'),
            func.sum(OffsetGrupoConsumo.monto_offset_usd).label('total_monto_usd')
        ).filter(
            OffsetGrupoConsumo.grupo_id == grupo_id,
            OffsetGrupoConsumo.fecha_venta >= desde_dt,
            OffsetGrupoConsumo.fecha_venta < hasta_dt
            # NO filtramos por tipo_venta, así suma ML + fuera_ml
        ).first()

        return (
            int(consumo.total_unidades or 0),
            float(consumo.total_monto_ars or 0),
            float(consumo.total_monto_usd or 0)
        )

    def calcular_consumo_individual_acumulado(offset_id, desde_dt, hasta_dt):
        """
        Calcula unidades y monto para un offset individual en un rango de fechas.
        ACUMULATIVO: suma tanto ventas ML como fuera de ML.
        """
        consumo = db.query(
            func.sum(OffsetIndividualConsumo.cantidad).label('total_unidades'),
            func.sum(OffsetIndividualConsumo.monto_offset_aplicado).label('total_monto_ars'),
            func.sum(OffsetIndividualConsumo.monto_offset_usd).label('total_monto_usd')
        ).filter(
            OffsetIndividualConsumo.offset_id == offset_id,
            OffsetIndividualConsumo.fecha_venta >= desde_dt,
            OffsetIndividualConsumo.fecha_venta < hasta_dt
            # NO filtramos por tipo_venta, así suma ML + fuera_ml
        ).first()

        return (
            int(consumo.total_unidades or 0),
            float(consumo.total_monto_ars or 0),
            float(consumo.total_monto_usd or 0)
        )

    # ========================================================================
    # PRE-CÁLCULO DE OFFSETS DE GRUPO CON LÍMITES
    # ========================================================================
    offsets_grupo_calculados = {}

    for offset in offsets:
        if not offset.grupo_id:
            continue

        if offset.grupo_id not in offsets_grupo_calculados:
            tc = float(offset.tipo_cambio) if offset.tipo_cambio else 1.0
            offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())

            resumen = db.query(OffsetGrupoResumen).filter(
                OffsetGrupoResumen.grupo_id == offset.grupo_id
            ).first()

            if resumen:
                acum_unidades = resumen.total_unidades or 0
                acum_offset_usd = float(resumen.total_monto_usd or 0)
                acum_offset_ars = float(resumen.total_monto_ars or 0)

                # Consumo ANTES del período filtrado
                consumo_previo_unidades = 0
                consumo_previo_offset = 0.0
                if offset_inicio_dt < fecha_desde_dt:
                    consumo_previo_unidades, consumo_previo_offset, _ = calcular_consumo_grupo_acumulado(
                        offset.grupo_id, offset_inicio_dt, fecha_desde_dt
                    )

                # Consumo del período filtrado (desde max(filtro, offset_inicio))
                periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)
                periodo_unidades, periodo_offset, _ = calcular_consumo_grupo_acumulado(
                    offset.grupo_id, periodo_inicio_dt, fecha_hasta_dt
                )

                limite_agotado_previo = False
                limite_aplicado = False
                max_monto_ars = (offset.max_monto_usd * tc) if offset.max_monto_usd else None

                if resumen.limite_alcanzado:
                    if offset.max_unidades is not None and consumo_previo_unidades >= offset.max_unidades:
                        limite_agotado_previo = True
                    if max_monto_ars is not None and consumo_previo_offset >= max_monto_ars:
                        limite_agotado_previo = True

                if limite_agotado_previo:
                    grupo_offset_total = 0.0
                    limite_aplicado = True
                else:
                    grupo_offset_total = periodo_offset

                    if offset.max_unidades is not None:
                        unidades_disponibles = offset.max_unidades - consumo_previo_unidades
                        if periodo_unidades >= unidades_disponibles:
                            if offset.tipo_offset == 'monto_por_unidad':
                                monto_base = float(offset.monto or 0)
                                if offset.moneda == 'USD' and offset.tipo_cambio:
                                    monto_base *= float(offset.tipo_cambio)
                                grupo_offset_total = monto_base * max(0, unidades_disponibles)
                            limite_aplicado = True

                    if max_monto_ars is not None:
                        monto_disponible = max_monto_ars - consumo_previo_offset
                        if grupo_offset_total >= monto_disponible:
                            grupo_offset_total = max(0, monto_disponible)
                            limite_aplicado = True

                offsets_grupo_calculados[offset.grupo_id] = {
                    'offset_total': grupo_offset_total,
                    'descripcion': offset.descripcion or f"Grupo {offset.grupo_id}",
                    'limite_aplicado': limite_aplicado,
                    'limite_agotado_previo': limite_agotado_previo,
                    'max_unidades': offset.max_unidades,
                    'max_monto_usd': offset.max_monto_usd,
                    'consumo_previo_offset': consumo_previo_offset
                }
            else:
                offsets_grupo_calculados[offset.grupo_id] = {
                    'offset_total': 0.0,
                    'descripcion': offset.descripcion or f"Grupo {offset.grupo_id}",
                    'limite_aplicado': False,
                    'limite_agotado_previo': False,
                    'max_unidades': offset.max_unidades,
                    'max_monto_usd': offset.max_monto_usd,
                    'consumo_previo_offset': 0.0,
                    'sin_recalcular': True
                }

    # ========================================================================
    # PRE-CÁLCULO DE OFFSETS INDIVIDUALES CON LÍMITES
    # ========================================================================
    offsets_individuales_calculados = {}

    for offset in offsets:
        if offset.grupo_id is not None:
            continue
        if not offset.max_unidades and not offset.max_monto_usd:
            continue

        tc = float(offset.tipo_cambio) if offset.tipo_cambio else 1.0
        offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())

        resumen = db.query(OffsetIndividualResumen).filter(
            OffsetIndividualResumen.offset_id == offset.id
        ).first()

        if resumen:
            acum_unidades = resumen.total_unidades or 0
            acum_offset_usd = float(resumen.total_monto_usd or 0)
            acum_offset_ars = float(resumen.total_monto_ars or 0)

            consumo_previo_unidades = 0
            consumo_previo_offset = 0.0
            if offset_inicio_dt < fecha_desde_dt:
                consumo_previo_unidades, consumo_previo_offset, _ = calcular_consumo_individual_acumulado(
                    offset.id, offset_inicio_dt, fecha_desde_dt
                )

            periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)
            periodo_unidades, periodo_offset, _ = calcular_consumo_individual_acumulado(
                offset.id, periodo_inicio_dt, fecha_hasta_dt
            )

            limite_agotado_previo = False
            limite_aplicado = False
            max_monto_ars = (float(offset.max_monto_usd) * tc) if offset.max_monto_usd else None

            if resumen.limite_alcanzado:
                if offset.max_unidades is not None and consumo_previo_unidades >= offset.max_unidades:
                    limite_agotado_previo = True
                if max_monto_ars is not None and consumo_previo_offset >= max_monto_ars:
                    limite_agotado_previo = True

            if limite_agotado_previo:
                offset_total = 0.0
                limite_aplicado = True
            else:
                offset_total = periodo_offset

                if offset.max_unidades is not None:
                    unidades_disponibles = offset.max_unidades - consumo_previo_unidades
                    if periodo_unidades >= unidades_disponibles:
                        if offset.tipo_offset == 'monto_por_unidad':
                            monto_base = float(offset.monto or 0)
                            if offset.moneda == 'USD' and offset.tipo_cambio:
                                monto_base *= float(offset.tipo_cambio)
                            offset_total = monto_base * max(0, unidades_disponibles)
                        limite_aplicado = True

                if max_monto_ars is not None:
                    monto_disponible = max_monto_ars - consumo_previo_offset
                    if offset_total >= monto_disponible:
                        offset_total = max(0, monto_disponible)
                        limite_aplicado = True

            offsets_individuales_calculados[offset.id] = {
                'offset_total': offset_total,
                'descripcion': offset.descripcion or f"Offset {offset.id}",
                'limite_aplicado': limite_aplicado,
                'limite_agotado_previo': limite_agotado_previo,
                'max_unidades': offset.max_unidades,
                'max_monto_usd': float(offset.max_monto_usd) if offset.max_monto_usd else None,
                'consumo_previo_offset': consumo_previo_offset
            }
        else:
            offsets_individuales_calculados[offset.id] = {
                'offset_total': 0.0,
                'descripcion': offset.descripcion or f"Offset {offset.id}",
                'limite_aplicado': False,
                'limite_agotado_previo': False,
                'max_unidades': offset.max_unidades,
                'max_monto_usd': float(offset.max_monto_usd) if offset.max_monto_usd else None,
                'consumo_previo_offset': 0.0,
                'sin_recalcular': True
            }

    # ========================================================================
    # FUNCIONES PARA CÁLCULO DE OFFSETS
    # ========================================================================

    def calcular_valor_offset(offset, cantidad_vendida, costo_total):
        """Calcula el valor del offset según su tipo"""
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

    def obtener_ventas_periodo_offset_fuera(offset, filtro_sql_extra=""):
        """
        Obtiene cantidad y costo de ventas FUERA de ML para un offset,
        considerando su fecha_desde.
        """
        offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())
        periodo_inicio = max(fecha_desde_dt, offset_inicio_dt)

        if periodo_inicio >= fecha_hasta_dt:
            return 0, 0.0

        query_ventas = f"""
        SELECT
            COUNT(*) as cantidad,
            SUM(
                CASE
                    WHEN iclh.curr_id = 1 THEN iclh.iclh_price * tit.it_qty
                    ELSE iclh.iclh_price * COALESCE(ceh.ceh_exchange, 1) * tit.it_qty
                END *
                CASE WHEN tct.sd_id IN ({','.join(map(str, SD_DEVOLUCIONES))}) THEN -1 ELSE 1 END
            ) as costo
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
        WHERE tct.ct_date >= :periodo_inicio AND tct.ct_date < :periodo_fin
            AND tct.df_id IN ({','.join(map(str, DF_PERMITIDOS))})
            AND tct.cust_id NOT IN ({','.join(map(str, CLIENTES_EXCLUIDOS))})
            AND tct.sm_id NOT IN ({vendedores_excluidos})
            AND tct.sd_id IN ({','.join(map(str, SD_TODOS))})
            {filtros_extra}
            {filtro_sql_extra}
        """

        result = db.execute(text(query_ventas), {
            "periodo_inicio": periodo_inicio.date().isoformat(),
            "periodo_fin": fecha_hasta_dt.date().isoformat()
        }).first()

        return int(result.cantidad or 0), float(result.costo or 0)

    def get_offset_nivel_nombre(offset):
        """Obtiene el nivel y nombre del offset para el desglose"""
        if offset.item_id:
            return "producto", f"Producto {offset.item_id}"
        elif offset.subcategoria_id:
            return "subcategoria", f"Subcat {offset.subcategoria_id}"
        elif offset.categoria:
            return "categoria", offset.categoria
        elif offset.marca:
            return "marca", offset.marca
        return "otro", "Offset"

    def calcular_offsets_para_card(card_nombre, card_identificador, cantidad_vendida, costo_total):
        """Calcula todos los offsets aplicables a una card"""
        offset_total = 0.0
        desglose = []
        grupos_procesados = set()

        for offset in offsets:
            valor_offset = 0.0
            aplica = False
            nivel_offset, nombre_nivel = get_offset_nivel_nombre(offset)

            # Offsets de grupo con límites pre-calculados
            if offset.grupo_id and offset.grupo_id in offsets_grupo_calculados:
                if offset.grupo_id in grupos_procesados:
                    continue

                aplica_a_card = False
                if nivel == "marca" and offset.marca == card_nombre:
                    aplica_a_card = True
                elif nivel == "categoria" and offset.categoria == card_nombre:
                    aplica_a_card = True
                elif nivel == "producto" and offset.item_id and str(offset.item_id) == str(card_identificador):
                    aplica_a_card = True

                if aplica_a_card:
                    grupos_procesados.add(offset.grupo_id)
                    grupo_info = offsets_grupo_calculados[offset.grupo_id]

                    limite_texto = ""
                    if grupo_info['limite_aplicado']:
                        if grupo_info.get('max_monto_usd'):
                            limite_texto = f" (máx USD {grupo_info['max_monto_usd']:,.0f})"
                        elif grupo_info.get('max_unidades'):
                            limite_texto = f" (máx {grupo_info['max_unidades']} un.)"

                    desglose.append(DesgloseOffset(
                        descripcion=f"{grupo_info['descripcion']}{limite_texto}",
                        nivel="grupo",
                        nombre_nivel=f"Grupo {offset.grupo_id}",
                        tipo_offset=offset.tipo_offset or 'monto_fijo',
                        monto=grupo_info['offset_total']
                    ))
                    offset_total += grupo_info['offset_total']
                continue

            # Offsets individuales con límites pre-calculados
            if offset.id in offsets_individuales_calculados:
                offset_info = offsets_individuales_calculados[offset.id]

                aplica_a_card = False
                if nivel == "marca" and offset.marca == card_nombre:
                    aplica_a_card = True
                elif nivel == "categoria" and offset.categoria == card_nombre:
                    aplica_a_card = True
                elif nivel == "producto" and offset.item_id and str(offset.item_id) == str(card_identificador):
                    aplica_a_card = True

                if aplica_a_card:
                    limite_texto = ""
                    if offset_info['limite_aplicado']:
                        if offset_info.get('max_monto_usd'):
                            limite_texto = f" (máx USD {offset_info['max_monto_usd']:,.0f})"
                        elif offset_info.get('max_unidades'):
                            limite_texto = f" (máx {offset_info['max_unidades']} un.)"

                    desglose.append(DesgloseOffset(
                        descripcion=f"{offset_info['descripcion']}{limite_texto}",
                        nivel=nivel_offset,
                        nombre_nivel=nombre_nivel,
                        tipo_offset=offset.tipo_offset or 'monto_fijo',
                        monto=offset_info['offset_total']
                    ))
                    offset_total += offset_info['offset_total']
                continue

            # Offsets sin grupo y sin límites - usar fecha de inicio del offset
            if nivel == "marca" and offset.marca == card_nombre and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                cant, costo = obtener_ventas_periodo_offset_fuera(offset, f" AND tbd.brand_desc = '{card_nombre}'")
                if cant > 0:
                    valor_offset = calcular_valor_offset(offset, cant, costo)
                    aplica = True
            elif nivel == "categoria" and offset.categoria == card_nombre and not offset.subcategoria_id and not offset.item_id:
                cant, costo = obtener_ventas_periodo_offset_fuera(offset, f" AND tcc.cat_desc = '{card_nombre}'")
                if cant > 0:
                    valor_offset = calcular_valor_offset(offset, cant, costo)
                    aplica = True
            elif nivel == "producto" and offset.item_id and str(offset.item_id) == str(card_identificador):
                cant, costo = obtener_ventas_periodo_offset_fuera(offset, f" AND ti.item_id = {offset.item_id}")
                if cant > 0:
                    valor_offset = calcular_valor_offset(offset, cant, costo)
                    aplica = True

            if aplica and valor_offset > 0:
                offset_total += valor_offset
                desglose.append(DesgloseOffset(
                    descripcion=offset.descripcion or f"Offset {offset.id}",
                    nivel=nivel_offset,
                    nombre_nivel=nombre_nivel,
                    tipo_offset=offset.tipo_offset or 'monto_fijo',
                    monto=valor_offset
                ))

        return offset_total, desglose if desglose else None

    # ========================================================================
    # CONSTRUIR CARDS
    # ========================================================================
    cards = []
    total_ventas = 0
    total_monto_venta = 0.0
    total_costo = 0.0
    total_ganancia = 0.0
    total_offset = 0.0
    total_desglose_offsets = []

    for r in resultados:
        cantidad_vendida = r.total_ventas
        costo_total_item = float(r.costo_con_costo or 0)

        # Calcular offsets con desglose
        offset_aplicable, desglose_offsets = calcular_offsets_para_card(
            r.nombre,
            r.identificador,
            cantidad_vendida,
            costo_total_item
        )

        monto_con_costo = float(r.monto_con_costo or 0)
        costo_con_costo = float(r.costo_con_costo or 0)
        ganancia_con_costo = monto_con_costo - costo_con_costo

        markup_promedio = ((ganancia_con_costo / costo_con_costo) * 100) if costo_con_costo > 0 else 0

        ganancia_con_offset = ganancia_con_costo + offset_aplicable
        markup_con_offset = ((ganancia_con_offset / costo_con_costo) * 100) if costo_con_costo > 0 else 0

        cards.append(CardRentabilidadFuera(
            nombre=r.nombre or "Sin nombre",
            tipo=nivel,
            identificador=str(r.identificador) if r.identificador else None,
            total_ventas=r.total_ventas,
            monto_venta=monto_con_costo,
            costo_total=costo_con_costo,
            ganancia=ganancia_con_costo,
            markup_promedio=markup_promedio,
            offset_total=offset_aplicable,
            ganancia_con_offset=ganancia_con_offset,
            markup_con_offset=markup_con_offset,
            desglose_offsets=desglose_offsets
        ))

        total_ventas += r.total_ventas
        total_monto_venta += monto_con_costo
        total_costo += costo_con_costo
        total_ganancia += ganancia_con_costo
        total_offset += offset_aplicable
        if desglose_offsets:
            total_desglose_offsets.extend(desglose_offsets)

    cards.sort(key=lambda c: c.monto_venta, reverse=True)

    # Agrupar desglose de offsets totales
    desglose_totales_agrupado = {}
    for d in total_desglose_offsets:
        key = (d.descripcion, d.nivel, d.nombre_nivel, d.tipo_offset)
        if key not in desglose_totales_agrupado:
            desglose_totales_agrupado[key] = DesgloseOffset(
                descripcion=d.descripcion,
                nivel=d.nivel,
                nombre_nivel=d.nombre_nivel,
                tipo_offset=d.tipo_offset,
                monto=0
            )
        desglose_totales_agrupado[key].monto += d.monto

    total_markup = ((total_ganancia / total_costo) * 100) if total_costo > 0 else 0
    total_ganancia_con_offset = total_ganancia + total_offset
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
        markup_con_offset=total_markup_con_offset,
        desglose_offsets=list(desglose_totales_agrupado.values()) if desglose_totales_agrupado else None
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
    vendedores_excluidos = get_vendedores_excluidos_str(db)

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
        AND tct.sm_id NOT IN ({vendedores_excluidos})
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

    vendedores_excluidos = get_vendedores_excluidos_str(db)

    params = {
        "from_date": fecha_desde.isoformat(),
        "to_date": (fecha_hasta + timedelta(days=1)).isoformat()
    }

    base_where = f"""
        WHERE tct.ct_date BETWEEN :from_date AND :to_date
            AND tct.df_id IN ({','.join(map(str, DF_PERMITIDOS))})
            AND tct.cust_id NOT IN ({','.join(map(str, CLIENTES_EXCLUIDOS))})
            AND tct.sm_id NOT IN ({vendedores_excluidos})
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
