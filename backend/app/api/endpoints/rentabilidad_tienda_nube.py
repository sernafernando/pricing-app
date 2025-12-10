"""
Endpoints para rentabilidad de ventas de Tienda Nube
Incluye soporte para offsets con límites acumulativos (sumando ML + fuera_ml + tienda_nube)
Incluye comisión de Tienda Nube configurable desde admin
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text
from typing import List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal
from pydantic import BaseModel

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.pricing_constants import PricingConstants
from app.models.usuario import Usuario
from app.api.deps import get_current_user

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

DF_TIENDA_NUBE = [113, 114]
SD_VENTAS = [1, 4, 21, 56]
SD_DEVOLUCIONES = [3, 6, 23, 66]
SD_TODOS = SD_VENTAS + SD_DEVOLUCIONES
ITEMS_EXCLUIDOS = [16, 460]
CLIENTES_EXCLUIDOS = [11, 3900]

DF_IDS_STR = ','.join(map(str, DF_TIENDA_NUBE))
SD_IDS_STR = ','.join(map(str, SD_TODOS))
ITEMS_EXCLUIDOS_STR = ','.join(map(str, ITEMS_EXCLUIDOS))
CLIENTES_EXCLUIDOS_STR = ','.join(map(str, CLIENTES_EXCLUIDOS))


# ============================================================================
# Schemas
# ============================================================================

class DesgloseOffset(BaseModel):
    """Desglose de un offset aplicado"""
    descripcion: str
    nivel: str
    nombre_nivel: str
    tipo_offset: str
    monto: float


class DesgloseMarca(BaseModel):
    """Desglose por marca dentro de una card"""
    marca: str
    monto_venta: float
    ganancia: float
    markup_promedio: float


class CardRentabilidad(BaseModel):
    """Card de rentabilidad para mostrar en el dashboard"""
    nombre: str
    tipo: str
    identificador: Optional[str] = None

    total_ventas: int
    monto_venta: float
    comision_tn: float  # Comisión de Tienda Nube
    monto_limpio: float  # Monto venta - comisión
    costo_total: float
    ganancia: float  # Monto limpio - costo
    markup_promedio: float

    offset_total: float
    ganancia_con_offset: float
    markup_con_offset: float

    desglose_offsets: Optional[List[DesgloseOffset]] = None
    desglose_marcas: Optional[List[DesgloseMarca]] = None


class RentabilidadResponse(BaseModel):
    cards: List[CardRentabilidad]
    totales: CardRentabilidad
    filtros_aplicados: dict


# ============================================================================
# Helpers
# ============================================================================

def get_ventas_tienda_nube_base_query():
    """Query base para obtener ventas de Tienda Nube desde tabla de métricas pre-calculadas"""
    return """
    SELECT
        it_transaction as id_operacion,
        item_id,
        codigo,
        descripcion,
        marca,
        categoria,
        subcategoria,
        subcat_id,
        cantidad * signo as cantidad,
        monto_total * signo as monto_total,
        costo_total * signo as costo_total,
        comision_monto * signo as comision_monto,
        ganancia * signo as ganancia,
        signo
    FROM ventas_tienda_nube_metricas
    WHERE fecha_venta BETWEEN :from_date AND :to_date
    """


@router.get("/rentabilidad-tienda-nube", response_model=RentabilidadResponse)
async def obtener_rentabilidad_tienda_nube(
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
    Obtiene métricas de rentabilidad de Tienda Nube agrupadas según los filtros.
    Los offsets son ACUMULATIVOS: los límites suman ML + fuera_ml + tienda_nube.
    Incluye comisión de Tienda Nube configurable desde admin.
    """
    # Obtener comisión de TN vigente
    comision_tn_pct = get_comision_tienda_nube(db, fecha_desde)

    # Parsear filtros
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

    # Convertir fechas
    fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
    fecha_hasta_dt = datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time())

    # Construir filtros SQL
    filtros_sql = []
    if lista_marcas:
        marcas_str = "','".join(lista_marcas)
        filtros_sql.append(f"marca IN ('{marcas_str}')")
    if lista_categorias:
        categorias_str = "','".join(lista_categorias)
        filtros_sql.append(f"categoria IN ('{categorias_str}')")
    if lista_subcategorias:
        subcategorias_str = "','".join(lista_subcategorias)
        filtros_sql.append(f"subcategoria IN ('{subcategorias_str}')")
    if lista_productos:
        productos_str = ','.join(map(str, lista_productos))
        filtros_sql.append(f"item_id IN ({productos_str})")

    filtros_where = " AND " + " AND ".join(filtros_sql) if filtros_sql else ""

    # Query para obtener datos agrupados
    if nivel == "marca":
        group_by = "marca"
        select_nombre = "marca"
        select_identificador = "marca"
    elif nivel == "categoria":
        group_by = "categoria"
        select_nombre = "categoria"
        select_identificador = "categoria"
    elif nivel == "subcategoria":
        group_by = "subcategoria, subcat_id"
        select_nombre = "subcategoria"
        select_identificador = "subcat_id::text"
    else:  # producto
        group_by = "item_id, codigo, descripcion"
        select_nombre = "COALESCE(codigo || ' - ' || descripcion, descripcion)"
        select_identificador = "item_id::text"

    query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_base_query()}
    )
    SELECT
        {select_nombre} as nombre,
        {select_identificador} as identificador,
        COUNT(*) as total_ventas,
        COALESCE(SUM(monto_total), 0) as monto_venta,
        COALESCE(SUM(costo_total), 0) as costo_total,
        COALESCE(SUM(cantidad), 0) as cantidad_total
    FROM ventas
    WHERE {select_nombre} IS NOT NULL {filtros_where}
    GROUP BY {group_by}
    ORDER BY monto_venta DESC
    """

    resultados = db.execute(
        text(query),
        {"from_date": fecha_desde.isoformat(), "to_date": fecha_hasta.isoformat() + " 23:59:59"}
    ).fetchall()

    # Obtener offsets vigentes que aplican a Tienda Nube
    offsets = db.query(OffsetGanancia).filter(
        OffsetGanancia.fecha_desde <= fecha_hasta,
        or_(
            OffsetGanancia.fecha_hasta.is_(None),
            OffsetGanancia.fecha_hasta >= fecha_desde
        ),
        OffsetGanancia.aplica_tienda_nube == True
    ).all()

    # Obtener filtros de grupo para todos los grupos con offsets
    grupo_ids = list(set(o.grupo_id for o in offsets if o.grupo_id))
    filtros_por_grupo = {}  # grupo_id -> [filtros]
    if grupo_ids:
        filtros_grupo = db.query(OffsetGrupoFiltro).filter(
            OffsetGrupoFiltro.grupo_id.in_(grupo_ids)
        ).all()
        for filtro in filtros_grupo:
            if filtro.grupo_id not in filtros_por_grupo:
                filtros_por_grupo[filtro.grupo_id] = []
            filtros_por_grupo[filtro.grupo_id].append(filtro)

    # Función para calcular consumo ACUMULADO de un grupo (ML + fuera_ml + tienda_nube)
    # NO filtramos por tipo_venta para que sume todas las ventas
    def calcular_consumo_grupo_acumulado(grupo_id, desde_dt, hasta_dt):
        """Calcula consumo acumulado de TODAS las ventas (ML + fuera_ml + tienda_nube)"""
        consumo = db.query(
            func.sum(OffsetGrupoConsumo.cantidad).label('total_unidades'),
            func.sum(OffsetGrupoConsumo.monto_offset_aplicado).label('total_monto_ars'),
            func.sum(OffsetGrupoConsumo.monto_offset_usd).label('total_monto_usd')
        ).filter(
            OffsetGrupoConsumo.grupo_id == grupo_id,
            OffsetGrupoConsumo.fecha_venta >= desde_dt,
            OffsetGrupoConsumo.fecha_venta < hasta_dt
            # NO filtramos por tipo_venta - suma ML + fuera_ml + tienda_nube
        ).first()

        return (
            int(consumo.total_unidades or 0),
            float(consumo.total_monto_ars or 0),
            float(consumo.total_monto_usd or 0)
        )

    def calcular_consumo_individual_acumulado(offset_id, desde_dt, hasta_dt):
        """Calcula consumo acumulado de un offset individual"""
        consumo = db.query(
            func.sum(OffsetIndividualConsumo.cantidad).label('total_unidades'),
            func.sum(OffsetIndividualConsumo.monto_offset_aplicado).label('total_monto_ars'),
            func.sum(OffsetIndividualConsumo.monto_offset_usd).label('total_monto_usd')
        ).filter(
            OffsetIndividualConsumo.offset_id == offset_id,
            OffsetIndividualConsumo.fecha_venta >= desde_dt,
            OffsetIndividualConsumo.fecha_venta < hasta_dt
        ).first()

        return (
            int(consumo.total_unidades or 0),
            float(consumo.total_monto_ars or 0),
            float(consumo.total_monto_usd or 0)
        )

    # Pre-calcular offsets de grupo con límites
    offsets_grupo_calculados = {}

    for offset in offsets:
        if not offset.grupo_id:
            continue

        if offset.grupo_id not in offsets_grupo_calculados:
            tc = float(offset.tipo_cambio) if offset.tipo_cambio else 1.0

            resumen = db.query(OffsetGrupoResumen).filter(
                OffsetGrupoResumen.grupo_id == offset.grupo_id
            ).first()

            offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())

            if resumen:
                acum_unidades = resumen.total_unidades or 0
                acum_offset_ars = float(resumen.total_monto_ars or 0)

                # Consumo previo al período filtrado
                consumo_previo_unidades = 0
                consumo_previo_offset = 0.0
                if offset_inicio_dt < fecha_desde_dt:
                    consumo_previo_unidades, consumo_previo_offset, _ = calcular_consumo_grupo_acumulado(
                        offset.grupo_id, offset_inicio_dt, fecha_desde_dt
                    )

                # Consumo del período filtrado (solo desde que el offset aplica)
                periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)
                periodo_unidades, periodo_offset, _ = calcular_consumo_grupo_acumulado(
                    offset.grupo_id, periodo_inicio_dt, fecha_hasta_dt
                )

                # Verificar límites
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
                    'max_monto_usd': offset.max_monto_usd
                }
            else:
                offsets_grupo_calculados[offset.grupo_id] = {
                    'offset_total': 0.0,
                    'descripcion': offset.descripcion or f"Grupo {offset.grupo_id}",
                    'limite_aplicado': False,
                    'limite_agotado_previo': False,
                    'max_unidades': offset.max_unidades,
                    'max_monto_usd': offset.max_monto_usd,
                    'sin_recalcular': True
                }

    # Pre-calcular offsets individuales con límites
    offsets_individuales_calculados = {}

    for offset in offsets:
        if offset.grupo_id is not None:
            continue
        if not offset.max_unidades and not offset.max_monto_usd:
            continue

        tc = float(offset.tipo_cambio) if offset.tipo_cambio else 1.0

        resumen = db.query(OffsetIndividualResumen).filter(
            OffsetIndividualResumen.offset_id == offset.id
        ).first()

        offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())

        if resumen:
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
                'max_monto_usd': float(offset.max_monto_usd) if offset.max_monto_usd else None
            }
        else:
            offsets_individuales_calculados[offset.id] = {
                'offset_total': 0.0,
                'descripcion': offset.descripcion or f"Offset {offset.id}",
                'limite_aplicado': False,
                'limite_agotado_previo': False,
                'max_unidades': offset.max_unidades,
                'max_monto_usd': float(offset.max_monto_usd) if offset.max_monto_usd else None,
                'sin_recalcular': True
            }

    # Obtener detalle de productos para propagar offsets
    productos_detalle = {}
    if nivel in ["marca", "categoria", "subcategoria"]:
        detalle_query = f"""
        WITH ventas AS (
            {get_ventas_tienda_nube_base_query()}
        )
        SELECT
            item_id,
            marca,
            categoria,
            subcategoria,
            COUNT(*) as cantidad,
            COALESCE(SUM(costo_total), 0) as costo
        FROM ventas
        WHERE item_id IS NOT NULL {filtros_where}
        GROUP BY item_id, marca, categoria, subcategoria
        """
        for d in db.execute(text(detalle_query), {"from_date": fecha_desde.isoformat(), "to_date": fecha_hasta.isoformat() + " 23:59:59"}).fetchall():
            productos_detalle[d.item_id] = {
                'marca': d.marca,
                'categoria': d.categoria,
                'subcategoria': d.subcategoria,
                'cantidad': d.cantidad,
                'costo': float(d.costo or 0)
            }

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
        else:
            return float(offset.monto or 0)

    def get_offset_nivel_nombre(offset):
        """Obtiene el nivel y nombre del offset"""
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
        """Calcula offsets aplicables a una card"""
        offset_total = 0.0
        desglose = []
        grupos_procesados = set()

        for offset in offsets:
            valor_offset = 0.0
            aplica = False
            nivel_offset, nombre_nivel = get_offset_nivel_nombre(offset)

            # Offsets de grupo
            if offset.grupo_id and offset.grupo_id in offsets_grupo_calculados:
                if offset.grupo_id in grupos_procesados:
                    continue

                aplica_a_card = False

                if nivel == "marca":
                    if offset.marca and offset.marca == card_nombre:
                        aplica_a_card = True
                    elif offset.item_id:
                        detalle = productos_detalle.get(offset.item_id)
                        if detalle and detalle['marca'] == card_nombre:
                            aplica_a_card = True
                elif nivel == "categoria":
                    if offset.categoria and offset.categoria == card_nombre:
                        aplica_a_card = True
                    elif offset.item_id:
                        detalle = productos_detalle.get(offset.item_id)
                        if detalle and detalle['categoria'] == card_nombre:
                            aplica_a_card = True
                elif nivel == "subcategoria":
                    if offset.subcategoria_id and str(offset.subcategoria_id) == str(card_identificador):
                        aplica_a_card = True
                    elif offset.item_id:
                        detalle = productos_detalle.get(offset.item_id)
                        if detalle and detalle['subcategoria'] == card_nombre:
                            aplica_a_card = True
                elif nivel == "producto":
                    if offset.item_id and str(offset.item_id) == str(card_identificador):
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

                    if nivel == "producto":
                        desglose.append(DesgloseOffset(
                            descripcion=f"{grupo_info['descripcion']}{limite_texto} (ver total)",
                            nivel="grupo",
                            nombre_nivel=f"Grupo {offset.grupo_id}",
                            tipo_offset=offset.tipo_offset or 'monto_fijo',
                            monto=0
                        ))
                    else:
                        desglose.append(DesgloseOffset(
                            descripcion=f"{grupo_info['descripcion']}{limite_texto}",
                            nivel="grupo",
                            nombre_nivel=f"Grupo {offset.grupo_id}",
                            tipo_offset=offset.tipo_offset or 'monto_fijo',
                            monto=grupo_info['offset_total']
                        ))
                        offset_total += grupo_info['offset_total']

                continue

            # Offsets individuales pre-calculados
            if offset.id in offsets_individuales_calculados:
                offset_info = offsets_individuales_calculados[offset.id]
                aplica_a_card = False

                if nivel == "marca":
                    if offset.marca and offset.marca == card_nombre:
                        aplica_a_card = True
                    elif offset.item_id:
                        detalle = productos_detalle.get(offset.item_id)
                        if detalle and detalle['marca'] == card_nombre:
                            aplica_a_card = True
                elif nivel == "categoria":
                    if offset.categoria and offset.categoria == card_nombre:
                        aplica_a_card = True
                    elif offset.item_id:
                        detalle = productos_detalle.get(offset.item_id)
                        if detalle and detalle['categoria'] == card_nombre:
                            aplica_a_card = True
                elif nivel == "subcategoria":
                    if offset.subcategoria_id and str(offset.subcategoria_id) == str(card_identificador):
                        aplica_a_card = True
                    elif offset.item_id:
                        detalle = productos_detalle.get(offset.item_id)
                        if detalle and detalle['subcategoria'] == card_nombre:
                            aplica_a_card = True
                elif nivel == "producto":
                    if offset.item_id and str(offset.item_id) == str(card_identificador):
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

            # Offsets sin grupo y sin límites
            if nivel == "marca":
                if offset.marca and offset.marca == card_nombre and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
                    aplica = True
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['marca'] == card_nombre:
                        valor_offset = calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                        aplica = True
                        nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "categoria":
                if offset.categoria and offset.categoria == card_nombre and not offset.subcategoria_id and not offset.item_id:
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
                    aplica = True
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['categoria'] == card_nombre:
                        valor_offset = calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                        aplica = True
                        nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "subcategoria":
                if offset.subcategoria_id and str(offset.subcategoria_id) == str(card_identificador):
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
                    aplica = True
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['subcategoria'] == card_nombre:
                        valor_offset = calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                        aplica = True
                        nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "producto":
                if offset.item_id and str(offset.item_id) == str(card_identificador):
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
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

    # Construir cards
    cards = []
    total_ventas = 0
    total_monto_venta = 0.0
    total_comision_tn = 0.0
    total_monto_limpio = 0.0
    total_costo = 0.0
    total_ganancia = 0.0
    total_offset = 0.0
    total_desglose = []

    for r in resultados:
        cantidad_vendida = r.total_ventas
        costo_total_item = float(r.costo_total or 0)

        offset_aplicable, desglose_offsets = calcular_offsets_para_card(
            r.nombre,
            r.identificador,
            cantidad_vendida,
            costo_total_item
        )

        monto_venta = float(r.monto_venta or 0)
        costo_total = float(r.costo_total or 0)

        # Calcular comisión de TN y monto limpio
        comision_tn = monto_venta * (comision_tn_pct / 100)
        monto_limpio = monto_venta - comision_tn
        ganancia = monto_limpio - costo_total

        markup_promedio = ((ganancia / costo_total) * 100) if costo_total > 0 else 0
        ganancia_con_offset = ganancia + offset_aplicable
        markup_con_offset = ((ganancia_con_offset / costo_total) * 100) if costo_total > 0 else 0

        cards.append(CardRentabilidad(
            nombre=r.nombre or "Sin nombre",
            tipo=nivel,
            identificador=str(r.identificador) if r.identificador else None,
            total_ventas=r.total_ventas,
            monto_venta=monto_venta,
            comision_tn=comision_tn,
            monto_limpio=monto_limpio,
            costo_total=costo_total,
            ganancia=ganancia,
            markup_promedio=markup_promedio,
            offset_total=offset_aplicable,
            ganancia_con_offset=ganancia_con_offset,
            markup_con_offset=markup_con_offset,
            desglose_offsets=desglose_offsets
        ))

        total_ventas += r.total_ventas
        total_monto_venta += monto_venta
        total_comision_tn += comision_tn
        total_monto_limpio += monto_limpio
        total_costo += costo_total
        total_ganancia += ganancia
        total_offset += offset_aplicable
        if desglose_offsets:
            total_desglose.extend(desglose_offsets)

    # Ordenar por monto de venta descendente
    cards.sort(key=lambda c: c.monto_venta, reverse=True)

    # Agregar offsets de grupo al total (solo a nivel producto)
    if nivel == "producto":
        for grupo_id, grupo_info in offsets_grupo_calculados.items():
            grupo_aplica = False
            for offset in offsets:
                if offset.grupo_id == grupo_id:
                    if offset.item_id:
                        for r in resultados:
                            if str(r.identificador) == str(offset.item_id):
                                grupo_aplica = True
                                break
                if grupo_aplica:
                    break

            if grupo_aplica:
                total_offset += grupo_info['offset_total']
                limite_texto = ""
                if grupo_info['limite_aplicado']:
                    if grupo_info.get('max_monto_usd'):
                        limite_texto = f" (máx USD {grupo_info['max_monto_usd']:,.0f})"
                    elif grupo_info.get('max_unidades'):
                        limite_texto = f" (máx {grupo_info['max_unidades']} un.)"

                total_desglose.append(DesgloseOffset(
                    descripcion=f"{grupo_info['descripcion']}{limite_texto}",
                    nivel="grupo",
                    nombre_nivel=f"Grupo {grupo_id}",
                    tipo_offset="monto_por_unidad",
                    monto=grupo_info['offset_total']
                ))

    # Calcular totales
    total_ganancia_con_offset = total_ganancia + total_offset
    total_markup = ((total_ganancia / total_costo) * 100) if total_costo > 0 else 0
    total_markup_con_offset = ((total_ganancia_con_offset / total_costo) * 100) if total_costo > 0 else 0

    # Agrupar desglose de offsets totales
    desglose_agrupado = {}
    for d in total_desglose:
        if d.nivel == "grupo" and d.monto == 0:
            continue
        key = (d.descripcion, d.nivel, d.nombre_nivel, d.tipo_offset)
        if key not in desglose_agrupado:
            desglose_agrupado[key] = DesgloseOffset(
                descripcion=d.descripcion,
                nivel=d.nivel,
                nombre_nivel=d.nombre_nivel,
                tipo_offset=d.tipo_offset,
                monto=0
            )
        desglose_agrupado[key].monto += d.monto

    totales = CardRentabilidad(
        nombre="TOTAL",
        tipo="total",
        identificador=None,
        total_ventas=total_ventas,
        monto_venta=total_monto_venta,
        comision_tn=total_comision_tn,
        monto_limpio=total_monto_limpio,
        costo_total=total_costo,
        ganancia=total_ganancia,
        markup_promedio=total_markup,
        offset_total=total_offset,
        ganancia_con_offset=total_ganancia_con_offset,
        markup_con_offset=total_markup_con_offset,
        desglose_offsets=list(desglose_agrupado.values()) if desglose_agrupado else None
    )

    return RentabilidadResponse(
        cards=cards,
        totales=totales,
        filtros_aplicados={
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "marcas": lista_marcas,
            "categorias": lista_categorias,
            "subcategorias": lista_subcategorias,
            "productos": lista_productos,
            "nivel_agrupacion": nivel,
            "comision_tn_porcentaje": comision_tn_pct
        }
    )


@router.get("/rentabilidad-tienda-nube/filtros")
async def obtener_filtros_tienda_nube(
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    marcas: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    subcategorias: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los valores disponibles para los filtros de Tienda Nube.
    """
    lista_marcas = [m.strip() for m in marcas.split('|')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split('|')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split('|')] if subcategorias else []

    base_query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_base_query()}
    )
    """

    # Marcas
    marcas_filter = ""
    if lista_categorias:
        categorias_str = "','".join(lista_categorias)
        marcas_filter += f" AND categoria IN ('{categorias_str}')"
    if lista_subcategorias:
        subcategorias_str = "','".join(lista_subcategorias)
        marcas_filter += f" AND subcategoria IN ('{subcategorias_str}')"

    marcas_query = f"""
    {base_query}
    SELECT DISTINCT marca FROM ventas WHERE marca IS NOT NULL {marcas_filter} ORDER BY marca
    """
    marcas_result = db.execute(
        text(marcas_query),
        {"from_date": fecha_desde.isoformat(), "to_date": fecha_hasta.isoformat() + " 23:59:59"}
    ).fetchall()

    # Categorías
    categorias_filter = ""
    if lista_marcas:
        marcas_str = "','".join(lista_marcas)
        categorias_filter += f" AND marca IN ('{marcas_str}')"
    if lista_subcategorias:
        subcategorias_str = "','".join(lista_subcategorias)
        categorias_filter += f" AND subcategoria IN ('{subcategorias_str}')"

    categorias_query = f"""
    {base_query}
    SELECT DISTINCT categoria FROM ventas WHERE categoria IS NOT NULL {categorias_filter} ORDER BY categoria
    """
    categorias_result = db.execute(
        text(categorias_query),
        {"from_date": fecha_desde.isoformat(), "to_date": fecha_hasta.isoformat() + " 23:59:59"}
    ).fetchall()

    # Subcategorías
    subcategorias_filter = ""
    if lista_marcas:
        marcas_str = "','".join(lista_marcas)
        subcategorias_filter += f" AND marca IN ('{marcas_str}')"
    if lista_categorias:
        categorias_str = "','".join(lista_categorias)
        subcategorias_filter += f" AND categoria IN ('{categorias_str}')"

    subcategorias_query = f"""
    {base_query}
    SELECT DISTINCT subcategoria FROM ventas WHERE subcategoria IS NOT NULL {subcategorias_filter} ORDER BY subcategoria
    """
    subcategorias_result = db.execute(
        text(subcategorias_query),
        {"from_date": fecha_desde.isoformat(), "to_date": fecha_hasta.isoformat() + " 23:59:59"}
    ).fetchall()

    return {
        "marcas": [m[0] for m in marcas_result if m[0]],
        "categorias": [c[0] for c in categorias_result if c[0]],
        "subcategorias": [s[0] for s in subcategorias_result if s[0]]
    }


class ProductoBusqueda(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str] = None
    categoria: Optional[str] = None


@router.get("/rentabilidad-tienda-nube/buscar-productos", response_model=List[ProductoBusqueda])
async def buscar_productos_tienda_nube(
    q: str = Query(..., min_length=2, description="Término de búsqueda"),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Busca productos por código o descripción que tengan ventas en Tienda Nube.
    """
    query = f"""
    WITH ventas AS (
        {get_ventas_tienda_nube_base_query()}
    )
    SELECT DISTINCT
        item_id,
        codigo,
        descripcion,
        marca,
        categoria
    FROM ventas
    WHERE item_id IS NOT NULL
      AND (codigo ILIKE :search OR descripcion ILIKE :search)
    LIMIT 50
    """

    resultados = db.execute(
        text(query),
        {
            "from_date": fecha_desde.isoformat(),
            "to_date": fecha_hasta.isoformat() + " 23:59:59",
            "search": f"%{q}%"
        }
    ).fetchall()

    return [
        ProductoBusqueda(
            item_id=r.item_id,
            codigo=r.codigo or "",
            descripcion=r.descripcion or "",
            marca=r.marca,
            categoria=r.categoria
        )
        for r in resultados if r.item_id
    ]
