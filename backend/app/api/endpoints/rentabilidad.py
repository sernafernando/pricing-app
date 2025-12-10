from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text
from typing import List, Optional
from datetime import date, datetime, timedelta
from pydantic import BaseModel

from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


class DesgloseMarca(BaseModel):
    """Desglose por marca dentro de una card"""
    marca: str
    monto_venta: float
    ganancia: float
    markup_promedio: float


class DesgloseOffset(BaseModel):
    """Desglose de un offset aplicado"""
    descripcion: str
    nivel: str  # marca, categoria, subcategoria, producto
    nombre_nivel: str  # ej: "LENOVO", "Notebooks", etc.
    tipo_offset: str  # monto_fijo, monto_por_unidad, porcentaje_costo
    monto: float


class CardRentabilidad(BaseModel):
    """Card de rentabilidad para mostrar en el dashboard"""
    nombre: str
    tipo: str  # marca, categoria, subcategoria, producto
    identificador: Optional[str] = None

    # Métricas
    total_ventas: int
    monto_venta: float
    monto_limpio: float
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


class RentabilidadResponse(BaseModel):
    cards: List[CardRentabilidad]
    totales: CardRentabilidad
    filtros_aplicados: dict


@router.get("/rentabilidad", response_model=RentabilidadResponse)
async def obtener_rentabilidad(
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
    Obtiene métricas de rentabilidad agrupadas según los filtros.
    Los filtros son independientes y se pueden combinar libremente.
    El nivel de agrupación se determina por la cantidad de filtros aplicados.
    """
    # Parsear filtros múltiples (usar | como separador para evitar conflictos con comas en nombres)
    lista_marcas = [m.strip() for m in marcas.split('|')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split('|')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split('|')] if subcategorias else []
    lista_productos = [int(p.strip()) for p in productos.split('|') if p.strip().isdigit()] if productos else []

    # Determinar nivel de agrupación basado en los filtros seleccionados
    # La lógica es: agrupar por la dimensión que NO está filtrada para hacer drill-down
    if lista_productos:
        # Si hay productos específicos, mostrar cada producto
        nivel = "producto"
    elif lista_subcategorias:
        # Si hay subcategorías, mostrar productos
        nivel = "producto"
    elif lista_marcas and lista_categorias:
        # Marca + Categoría -> Subcategorías
        nivel = "subcategoria"
    elif lista_marcas:
        # Solo marca -> Categorías de esa marca
        nivel = "categoria"
    elif lista_categorias:
        # Solo categoría -> Marcas de esa categoría (drill-down inverso)
        nivel = "marca"
    else:
        # Sin filtros -> Marcas
        nivel = "marca"

    # Convertir fechas a datetime para comparación correcta con campo DateTime(timezone=True)
    # El campo fecha_venta es timestamp with timezone, comparar con date puede dar problemas
    fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
    fecha_hasta_dt = datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time())

    # Filtros base comunes
    def aplicar_filtros_base(query):
        query = query.filter(
            MLVentaMetrica.fecha_venta >= fecha_desde_dt,
            MLVentaMetrica.fecha_venta < fecha_hasta_dt
        )
        if lista_productos:
            query = query.filter(MLVentaMetrica.item_id.in_(lista_productos))
        if lista_marcas:
            query = query.filter(MLVentaMetrica.marca.in_(lista_marcas))
        if lista_categorias:
            query = query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
        if lista_subcategorias:
            query = query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
        return query

    # Query según nivel de agrupación
    # NOTA: No usamos avg(markup_porcentaje) porque promediar porcentajes es incorrecto.
    # El markup se calcula después: (ganancia / costo) * 100
    if nivel == "marca":
        query = db.query(
            MLVentaMetrica.marca.label('nombre'),
            MLVentaMetrica.marca.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia')
        )
        query = aplicar_filtros_base(query)
        query = query.filter(MLVentaMetrica.marca.isnot(None)).group_by(MLVentaMetrica.marca)

    elif nivel == "categoria":
        query = db.query(
            MLVentaMetrica.categoria.label('nombre'),
            MLVentaMetrica.categoria.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia')
        )
        query = aplicar_filtros_base(query)
        query = query.filter(MLVentaMetrica.categoria.isnot(None)).group_by(MLVentaMetrica.categoria)

    elif nivel == "subcategoria":
        query = db.query(
            MLVentaMetrica.subcategoria.label('nombre'),
            MLVentaMetrica.subcategoria.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia')
        )
        query = aplicar_filtros_base(query)
        query = query.filter(MLVentaMetrica.subcategoria.isnot(None)).group_by(MLVentaMetrica.subcategoria)

    else:  # producto
        query = db.query(
            func.concat(MLVentaMetrica.codigo, ' - ', MLVentaMetrica.descripcion).label('nombre'),
            MLVentaMetrica.item_id.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia')
        )
        query = aplicar_filtros_base(query)
        query = query.group_by(MLVentaMetrica.item_id, MLVentaMetrica.codigo, MLVentaMetrica.descripcion)

    resultados = query.all()

    # Obtener offsets vigentes para el período (solo los que aplican a ML)
    offsets = db.query(OffsetGanancia).filter(
        OffsetGanancia.fecha_desde <= fecha_hasta,
        or_(
            OffsetGanancia.fecha_hasta.is_(None),
            OffsetGanancia.fecha_hasta >= fecha_desde
        ),
        OffsetGanancia.aplica_ml == True
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

    # Función auxiliar para verificar si un producto matchea con los filtros de un grupo
    def producto_matchea_filtros_grupo(grupo_id, marca=None, categoria=None, subcategoria=None, item_id=None):
        """
        Verifica si un producto matchea con al menos un filtro del grupo.
        Si el grupo no tiene filtros, retorna False (debe matchear por offset individual).
        """
        filtros = filtros_por_grupo.get(grupo_id, [])
        if not filtros:
            return False

        for filtro in filtros:
            matchea = True
            # Todos los campos del filtro que no son None deben coincidir
            if filtro.marca and (not marca or filtro.marca != marca):
                matchea = False
            if filtro.categoria and (not categoria or filtro.categoria != categoria):
                matchea = False
            if filtro.subcategoria_id and (not subcategoria or str(filtro.subcategoria_id) != str(subcategoria)):
                matchea = False
            if filtro.item_id and (not item_id or filtro.item_id != item_id):
                matchea = False

            if matchea:
                return True

        return False

    # Calcular el offset total por grupo/offset CON límites aplicados
    # IMPORTANTE: El límite se calcula sobre el ACUMULADO desde que empezó el offset,
    # no solo sobre el período filtrado. Usamos la tabla offset_grupo_resumen para esto.
    offsets_grupo_calculados = {}  # grupo_id -> {'offset_total': X, 'descripcion': Y, 'limite_aplicado': bool, 'limite_agotado': bool}

    # Función auxiliar para calcular consumo de un grupo en un rango de fechas DESDE LA TABLA DE CONSUMO
    def calcular_consumo_grupo_desde_tabla(grupo_id, desde_dt, hasta_dt):
        """Calcula unidades y monto offset para un grupo en un rango de fechas desde la tabla de consumo"""
        consumo = db.query(
            func.sum(OffsetGrupoConsumo.cantidad).label('total_unidades'),
            func.sum(OffsetGrupoConsumo.monto_offset_aplicado).label('total_monto_ars'),
            func.sum(OffsetGrupoConsumo.monto_offset_usd).label('total_monto_usd')
        ).filter(
            OffsetGrupoConsumo.grupo_id == grupo_id,
            OffsetGrupoConsumo.fecha_venta >= desde_dt,
            OffsetGrupoConsumo.fecha_venta < hasta_dt
        ).first()

        return (
            int(consumo.total_unidades or 0),
            float(consumo.total_monto_ars or 0),
            float(consumo.total_monto_usd or 0)
        )

    # Pre-calcular offsets por grupo para aplicar límites a nivel grupo
    for offset in offsets:
        if not offset.grupo_id:
            continue  # Los offsets sin grupo se calculan individualmente

        if offset.grupo_id not in offsets_grupo_calculados:
            tc = float(offset.tipo_cambio) if offset.tipo_cambio else 1.0

            # Primero intentamos usar la tabla de resumen para obtener el consumo total
            resumen = db.query(OffsetGrupoResumen).filter(
                OffsetGrupoResumen.grupo_id == offset.grupo_id
            ).first()

            # Fecha inicio del offset (desde cuando empezó a correr)
            offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())

            # Si hay resumen, lo usamos para el límite total
            if resumen:
                # Consumo total acumulado desde la tabla de resumen
                acum_unidades = resumen.total_unidades or 0
                acum_offset_usd = float(resumen.total_monto_usd or 0)
                acum_offset_ars = float(resumen.total_monto_ars or 0)

                # Calcular consumo ANTES del período filtrado (lo que ya se consumió)
                consumo_previo_unidades = 0
                consumo_previo_offset = 0.0
                if offset_inicio_dt < fecha_desde_dt:
                    consumo_previo_unidades, consumo_previo_offset, _ = calcular_consumo_grupo_desde_tabla(
                        offset.grupo_id, offset_inicio_dt, fecha_desde_dt
                    )

                # Calcular consumo del período filtrado
                # IMPORTANTE: Solo contar ventas desde que el offset empezó a aplicar
                # Si el offset empieza después del inicio del filtro, usar la fecha del offset
                periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)
                periodo_unidades, periodo_offset, _ = calcular_consumo_grupo_desde_tabla(
                    offset.grupo_id, periodo_inicio_dt, fecha_hasta_dt
                )

                # Verificar si el límite ya se agotó
                limite_agotado_previo = False
                limite_aplicado = False
                max_monto_ars = (offset.max_monto_usd * tc) if offset.max_monto_usd else None

                # Si el resumen ya indica límite alcanzado, verificar si fue antes del período
                if resumen.limite_alcanzado:
                    if offset.max_unidades is not None and consumo_previo_unidades >= offset.max_unidades:
                        limite_agotado_previo = True
                    if max_monto_ars is not None and consumo_previo_offset >= max_monto_ars:
                        limite_agotado_previo = True

                # Calcular el offset aplicable al período filtrado
                if limite_agotado_previo:
                    grupo_offset_total = 0.0
                    limite_aplicado = True
                else:
                    grupo_offset_total = periodo_offset

                    # Aplicar límite de unidades
                    if offset.max_unidades is not None:
                        unidades_disponibles = offset.max_unidades - consumo_previo_unidades
                        if periodo_unidades >= unidades_disponibles:
                            if offset.tipo_offset == 'monto_por_unidad':
                                monto_base = float(offset.monto or 0)
                                if offset.moneda == 'USD' and offset.tipo_cambio:
                                    monto_base *= float(offset.tipo_cambio)
                                grupo_offset_total = monto_base * max(0, unidades_disponibles)
                            limite_aplicado = True

                    # Aplicar límite de monto
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
                    'consumo_previo_offset': consumo_previo_offset,
                    'consumo_acumulado_offset': acum_offset_ars,
                    'consumo_acumulado_usd': acum_offset_usd
                }
            else:
                # No hay resumen todavía - grupo sin consumo registrado o sin recalcular
                # El offset aplica completo para el período
                offsets_grupo_calculados[offset.grupo_id] = {
                    'offset_total': 0.0,  # Se calculará en calcular_offsets_para_card
                    'descripcion': offset.descripcion or f"Grupo {offset.grupo_id}",
                    'limite_aplicado': False,
                    'limite_agotado_previo': False,
                    'max_unidades': offset.max_unidades,
                    'max_monto_usd': offset.max_monto_usd,
                    'consumo_previo_offset': 0.0,
                    'consumo_acumulado_offset': 0.0,
                    'sin_recalcular': True  # Flag para indicar que falta recalcular
                }

    # Pre-calcular offsets INDIVIDUALES (sin grupo) con límites
    offsets_individuales_calculados = {}  # offset_id -> {'offset_total': X, 'limite_aplicado': bool, etc}

    def calcular_consumo_individual_desde_tabla(offset_id, desde_dt, hasta_dt):
        """Calcula unidades y monto para un offset individual en un rango de fechas"""
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

    for offset in offsets:
        # Solo procesar offsets individuales (sin grupo) que tengan límites
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
            acum_unidades = resumen.total_unidades or 0
            acum_offset_usd = float(resumen.total_monto_usd or 0)
            acum_offset_ars = float(resumen.total_monto_ars or 0)

            # Consumo previo al período filtrado
            consumo_previo_unidades = 0
            consumo_previo_offset = 0.0
            if offset_inicio_dt < fecha_desde_dt:
                consumo_previo_unidades, consumo_previo_offset, _ = calcular_consumo_individual_desde_tabla(
                    offset.id, offset_inicio_dt, fecha_desde_dt
                )

            # Consumo del período filtrado
            # IMPORTANTE: Solo contar ventas desde que el offset empezó a aplicar
            # Si el offset empieza después del inicio del filtro, usar la fecha del offset
            periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)
            periodo_unidades, periodo_offset, _ = calcular_consumo_individual_desde_tabla(
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
                'consumo_previo_offset': consumo_previo_offset,
                'consumo_acumulado_offset': acum_offset_ars
            }
        else:
            # Sin resumen - offset sin consumo registrado
            offsets_individuales_calculados[offset.id] = {
                'offset_total': 0.0,
                'descripcion': offset.descripcion or f"Offset {offset.id}",
                'limite_aplicado': False,
                'limite_agotado_previo': False,
                'max_unidades': offset.max_unidades,
                'max_monto_usd': float(offset.max_monto_usd) if offset.max_monto_usd else None,
                'consumo_previo_offset': 0.0,
                'consumo_acumulado_offset': 0.0,
                'sin_recalcular': True
            }

    # Para propagar offsets de niveles inferiores, necesitamos saber qué productos
    # pertenecen a cada marca/categoría/subcategoría
    # Obtenemos una query detallada a nivel producto con sus atributos
    productos_detalle = {}
    if nivel in ["marca", "categoria", "subcategoria"]:
        detalle_query = db.query(
            MLVentaMetrica.item_id,
            MLVentaMetrica.marca,
            MLVentaMetrica.categoria,
            MLVentaMetrica.subcategoria,
            func.count(MLVentaMetrica.id).label('cantidad'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo')
        ).filter(
            MLVentaMetrica.fecha_venta >= fecha_desde_dt,
            MLVentaMetrica.fecha_venta < fecha_hasta_dt
        )
        detalle_query = aplicar_filtros_base(detalle_query)
        detalle_query = detalle_query.group_by(
            MLVentaMetrica.item_id,
            MLVentaMetrica.marca,
            MLVentaMetrica.categoria,
            MLVentaMetrica.subcategoria
        )
        for d in detalle_query.all():
            productos_detalle[d.item_id] = {
                'marca': d.marca,
                'categoria': d.categoria,
                'subcategoria': d.subcategoria,
                'cantidad': d.cantidad,
                'costo': float(d.costo or 0)
            }

    # Si hay múltiples marcas y estamos en nivel categoría o subcategoría, obtener desglose por marca
    desglose_por_item = {}
    if len(lista_marcas) > 1 and nivel in ["categoria", "subcategoria"]:
        # Query para desglose por marca
        campo_agrupacion = MLVentaMetrica.categoria if nivel == "categoria" else MLVentaMetrica.subcategoria
        desglose_query = db.query(
            campo_agrupacion.label('item'),
            MLVentaMetrica.marca.label('marca'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total')
        ).filter(
            MLVentaMetrica.fecha_venta >= fecha_desde_dt,
            MLVentaMetrica.fecha_venta < fecha_hasta_dt,
            MLVentaMetrica.marca.in_(lista_marcas),
            campo_agrupacion.isnot(None)
        )
        if lista_categorias and nivel == "subcategoria":
            desglose_query = desglose_query.filter(MLVentaMetrica.categoria.in_(lista_categorias))

        desglose_resultados = desglose_query.group_by(campo_agrupacion, MLVentaMetrica.marca).all()

        for d in desglose_resultados:
            if d.item not in desglose_por_item:
                desglose_por_item[d.item] = []
            ganancia = float(d.ganancia or 0)
            costo = float(d.costo_total or 0)
            markup = ((ganancia / costo) * 100) if costo > 0 else 0
            desglose_por_item[d.item].append(DesgloseMarca(
                marca=d.marca,
                monto_venta=float(d.monto_venta or 0),
                ganancia=ganancia,
                markup_promedio=markup
            ))

        # Ordenar cada desglose por monto descendente
        for item in desglose_por_item:
            desglose_por_item[item].sort(key=lambda x: x.monto_venta, reverse=True)

    # Función auxiliar para calcular el valor de un offset según su tipo
    def calcular_valor_offset(offset, cantidad_vendida, costo_total):
        """
        Calcula el valor del offset según su tipo:
        - monto_fijo: usa el monto directamente
        - monto_por_unidad: monto * cantidad * tipo_cambio (si USD)
        - porcentaje_costo: porcentaje * costo_total / 100
        """
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

    # Función para obtener cantidad/costo de ventas en el período efectivo del offset
    def obtener_ventas_periodo_offset(offset, filtro_condicion, filtro_valor=None):
        """
        Obtiene cantidad y costo de ventas para un offset, considerando su fecha_desde.
        Solo cuenta ventas desde max(fecha_desde_filtro, fecha_desde_offset).

        filtro_condicion puede ser:
        - Un campo de SQLAlchemy (ej: MLVentaMetrica.marca) con filtro_valor como valor
        - Una condición SQLAlchemy compuesta (ej: and_(...)) cuando filtro_valor es True
        """
        offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())
        periodo_inicio = max(fecha_desde_dt, offset_inicio_dt)

        # Si el offset empieza después del período filtrado, no hay ventas aplicables
        if periodo_inicio >= fecha_hasta_dt:
            return 0, 0.0

        query = db.query(
            func.count(MLVentaMetrica.id).label('cantidad'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo')
        ).filter(
            MLVentaMetrica.fecha_venta >= periodo_inicio,
            MLVentaMetrica.fecha_venta < fecha_hasta_dt
        )

        # Aplicar filtros de la selección del usuario
        if lista_productos:
            query = query.filter(MLVentaMetrica.item_id.in_(lista_productos))
        if lista_marcas:
            query = query.filter(MLVentaMetrica.marca.in_(lista_marcas))
        if lista_categorias:
            query = query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
        if lista_subcategorias:
            query = query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))

        # Aplicar filtro específico del offset (marca, categoría, item, etc.)
        if filtro_valor is True:
            # filtro_condicion es una condición compuesta (and_, or_, etc.)
            query = query.filter(filtro_condicion)
        elif filtro_condicion is not None and filtro_valor is not None:
            # filtro_condicion es un campo, filtro_valor es el valor
            query = query.filter(filtro_condicion == filtro_valor)

        result = query.first()
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
        """
        Calcula todos los offsets aplicables a una card, incluyendo propagación
        de niveles inferiores. Retorna (total, lista_desglose)

        Para offsets con grupo_id:
        - Se muestra UN solo desglose por grupo (no por producto)
        - El monto es el total del grupo (con límites aplicados)
        - Solo se muestra en la primera card que lo use
        """
        offset_total = 0.0
        desglose = []
        grupos_procesados_en_card = set()  # Track grupos ya procesados en esta card

        for offset in offsets:
            valor_offset = 0.0
            aplica = False
            nivel_offset, nombre_nivel = get_offset_nivel_nombre(offset)

            # Si el offset tiene grupo, usar el valor pre-calculado del grupo
            # El offset de grupo es UN SOLO MONTO para toda la campaña, no se reparte por producto
            if offset.grupo_id and offset.grupo_id in offsets_grupo_calculados:
                # Skip si ya procesamos este grupo para esta card
                if offset.grupo_id in grupos_procesados_en_card:
                    continue

                # Solo procesar si este offset aplica a la card actual
                aplica_a_card = False

                # PRIMERO: Verificar si la card matchea con los filtros del grupo
                if offset.grupo_id in filtros_por_grupo and filtros_por_grupo[offset.grupo_id]:
                    # El grupo tiene filtros, verificar si la card matchea
                    if nivel == "marca":
                        # Para card de marca, verificar si algún filtro matchea esta marca
                        for filtro in filtros_por_grupo[offset.grupo_id]:
                            if filtro.marca and filtro.marca == card_nombre:
                                aplica_a_card = True
                                break
                    elif nivel == "categoria":
                        # Para card de categoría, verificar si algún filtro matchea esta categoría
                        for filtro in filtros_por_grupo[offset.grupo_id]:
                            if filtro.categoria and filtro.categoria == card_nombre:
                                aplica_a_card = True
                                break
                    elif nivel == "subcategoria":
                        # Para card de subcategoría
                        for filtro in filtros_por_grupo[offset.grupo_id]:
                            if filtro.subcategoria_id and str(filtro.subcategoria_id) == str(card_identificador):
                                aplica_a_card = True
                                break
                    elif nivel == "producto":
                        # Para card de producto, verificar si matchea con filtros
                        detalle = productos_detalle.get(int(card_identificador)) if card_identificador else None
                        if detalle:
                            for filtro in filtros_por_grupo[offset.grupo_id]:
                                matchea = True
                                if filtro.marca and filtro.marca != detalle.get('marca'):
                                    matchea = False
                                if filtro.categoria and filtro.categoria != detalle.get('categoria'):
                                    matchea = False
                                if filtro.item_id and filtro.item_id != int(card_identificador):
                                    matchea = False
                                if matchea:
                                    aplica_a_card = True
                                    break

                # SEGUNDO: Si no matcheó por filtros, verificar por offset individual (lógica original)
                if not aplica_a_card:
                    if nivel == "marca":
                        if offset.marca and offset.marca == card_nombre:
                            aplica_a_card = True
                        elif offset.item_id:
                            detalle = productos_detalle.get(offset.item_id)
                            if detalle and detalle['marca'] == card_nombre:
                                aplica_a_card = True
                        elif offset.categoria:
                            for item_id, detalle in productos_detalle.items():
                                if detalle['marca'] == card_nombre and detalle['categoria'] == offset.categoria:
                                    aplica_a_card = True
                                    break
                    elif nivel == "categoria":
                        if offset.categoria and offset.categoria == card_nombre:
                            aplica_a_card = True
                        elif offset.item_id:
                            detalle = productos_detalle.get(offset.item_id)
                            if detalle and detalle['categoria'] == card_nombre:
                                aplica_a_card = True
                        elif offset.marca:
                            for item_id, detalle in productos_detalle.items():
                                if detalle['categoria'] == card_nombre and detalle['marca'] == offset.marca:
                                    aplica_a_card = True
                                    break
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
                    # Marcar grupo como procesado para esta card
                    grupos_procesados_en_card.add(offset.grupo_id)

                    grupo_info = offsets_grupo_calculados[offset.grupo_id]

                    # Agregar al desglose para que se muestre la info del grupo
                    limite_texto = ""
                    if grupo_info['limite_aplicado']:
                        if grupo_info.get('max_monto_usd'):
                            limite_texto = f" (máx USD {grupo_info['max_monto_usd']:,.0f})"
                        elif grupo_info.get('max_unidades'):
                            limite_texto = f" (máx {grupo_info['max_unidades']} un.)"

                    # En cards individuales de producto, NO sumamos el offset del grupo
                    # porque el offset del grupo es por CAMPAÑA, no por producto
                    # Solo mostramos que participa del grupo (monto 0 para la card)
                    # El total se suma UNA sola vez en los totales globales
                    if nivel == "producto":
                        # Mostrar que el producto participa del grupo pero sin sumar
                        desglose.append(DesgloseOffset(
                            descripcion=f"{grupo_info['descripcion']}{limite_texto} (ver total)",
                            nivel="grupo",
                            nombre_nivel=f"Grupo {offset.grupo_id}",
                            tipo_offset=offset.tipo_offset or 'monto_fijo',
                            monto=0  # No sumar a nivel producto
                        ))
                    else:
                        # Para niveles agregados (marca, categoria, subcategoria)
                        # mostramos el total del grupo
                        desglose.append(DesgloseOffset(
                            descripcion=f"{grupo_info['descripcion']}{limite_texto}",
                            nivel="grupo",
                            nombre_nivel=f"Grupo {offset.grupo_id}",
                            tipo_offset=offset.tipo_offset or 'monto_fijo',
                            monto=grupo_info['offset_total']
                        ))
                        offset_total += grupo_info['offset_total']

                continue  # Skip normal processing for grouped offsets

            # Si el offset individual tiene límites y ya lo pre-calculamos, usar ese valor
            if offset.id in offsets_individuales_calculados:
                offset_info = offsets_individuales_calculados[offset.id]

                # Verificar si aplica a esta card
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

                continue  # Skip normal processing for pre-calculated individual offsets

            # Offsets SIN grupo y SIN límites - procesar normalmente
            # IMPORTANTE: Usar la fecha de inicio del offset para calcular cantidad/costo
            # Solo se cuentan ventas desde max(fecha_filtro, fecha_offset)
            if nivel == "marca":
                # Offset directo por marca
                if offset.marca and offset.marca == card_nombre and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    # Obtener cantidad/costo solo para el período donde aplica el offset
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.marca, card_nombre)
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                # Offsets de categorías dentro de esta marca
                elif offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    # Obtener ventas de esta marca + categoría del offset, solo en período aplicable
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(
                        offset,
                        and_(MLVentaMetrica.marca == card_nombre, MLVentaMetrica.categoria == offset.categoria),
                        True  # dummy value since we use compound filter
                    )
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                        nombre_nivel = f"Cat: {offset.categoria}"
                # Offsets de productos dentro de esta marca
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['marca'] == card_nombre:
                        cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.item_id, offset.item_id)
                        if cant_offset > 0:
                            valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                            aplica = True
                            nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "categoria":
                # Offset directo por categoría
                if offset.categoria and offset.categoria == card_nombre and not offset.subcategoria_id and not offset.item_id:
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.categoria, card_nombre)
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                # Offset de marca que aplica a esta categoría
                elif offset.marca and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    # Obtener ventas de esta categoría + marca del offset
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(
                        offset,
                        and_(MLVentaMetrica.categoria == card_nombre, MLVentaMetrica.marca == offset.marca),
                        True
                    )
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                        nombre_nivel = f"Marca: {offset.marca}"
                # Offsets de productos dentro de esta categoría
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['categoria'] == card_nombre:
                        cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.item_id, offset.item_id)
                        if cant_offset > 0:
                            valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                            aplica = True
                            nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "subcategoria":
                # Offset directo por subcategoría
                if offset.subcategoria_id and str(offset.subcategoria_id) == str(card_identificador):
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.subcategoria, card_nombre)
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                # Offset de marca que aplica a esta subcategoría
                elif offset.marca and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(
                        offset,
                        and_(MLVentaMetrica.subcategoria == card_nombre, MLVentaMetrica.marca == offset.marca),
                        True
                    )
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                        nombre_nivel = f"Marca: {offset.marca}"
                # Offset de categoría que aplica a esta subcategoría
                elif offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(
                        offset,
                        and_(MLVentaMetrica.subcategoria == card_nombre, MLVentaMetrica.categoria == offset.categoria),
                        True
                    )
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                        nombre_nivel = f"Cat: {offset.categoria}"
                # Offsets de productos dentro de esta subcategoría
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['subcategoria'] == card_nombre:
                        cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.item_id, offset.item_id)
                        if cant_offset > 0:
                            valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                            aplica = True
                            nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "producto":
                # Solo offsets directos del producto o de sus niveles superiores
                if offset.item_id and str(offset.item_id) == str(card_identificador):
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.item_id, int(card_identificador))
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
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
    total_monto_limpio = 0.0
    total_costo = 0.0
    total_ganancia = 0.0
    total_offset = 0.0
    total_desglose_offsets = []

    for r in resultados:
        cantidad_vendida = r.total_ventas
        costo_total_item = float(r.costo_total or 0)

        # Calcular offsets con desglose
        offset_aplicable, desglose_offsets = calcular_offsets_para_card(
            r.nombre,
            r.identificador,
            cantidad_vendida,
            costo_total_item
        )

        monto_venta = float(r.monto_venta or 0)
        monto_limpio = float(r.monto_limpio or 0)
        costo_total = float(r.costo_total or 0)
        ganancia = float(r.ganancia or 0)

        # Calcular markup a partir de ganancia/costo (no promediar porcentajes)
        markup_promedio = ((ganancia / costo_total) * 100) if costo_total > 0 else 0

        ganancia_con_offset = ganancia + offset_aplicable
        markup_con_offset = ((ganancia_con_offset / costo_total) * 100) if costo_total > 0 else 0

        # Obtener desglose de marcas si existe
        desglose = desglose_por_item.get(r.nombre) if r.nombre in desglose_por_item else None

        cards.append(CardRentabilidad(
            nombre=r.nombre or "Sin nombre",
            tipo=nivel,
            identificador=str(r.identificador) if r.identificador else None,
            total_ventas=r.total_ventas,
            monto_venta=monto_venta,
            monto_limpio=monto_limpio,
            costo_total=costo_total,
            ganancia=ganancia,
            markup_promedio=markup_promedio,
            offset_total=offset_aplicable,
            ganancia_con_offset=ganancia_con_offset,
            markup_con_offset=markup_con_offset,
            desglose_offsets=desglose_offsets,
            desglose_marcas=desglose
        ))

        # Acumular totales
        total_ventas += r.total_ventas
        total_monto_venta += monto_venta
        total_monto_limpio += monto_limpio
        total_costo += costo_total
        total_ganancia += ganancia
        total_offset += offset_aplicable
        if desglose_offsets:
            total_desglose_offsets.extend(desglose_offsets)

    # Ordenar por monto de venta descendente
    cards.sort(key=lambda c: c.monto_venta, reverse=True)

    # Agregar offsets de grupos al total (una sola vez por grupo)
    # Solo cuando estamos a nivel producto, porque en niveles agregados ya se sumó en calcular_offsets_para_card
    if nivel == "producto":
        for grupo_id, grupo_info in offsets_grupo_calculados.items():
            # Verificar si algún producto del grupo está en los resultados
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

                total_desglose_offsets.append(DesgloseOffset(
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

    # Agrupar desglose de offsets totales por descripción
    # Filtrar los de grupo con monto=0 (que vienen de las cards de producto individuales)
    desglose_totales_agrupado = {}
    for d in total_desglose_offsets:
        # Skip entries de grupo con monto=0 (vienen de cards individuales de producto)
        if d.nivel == "grupo" and d.monto == 0:
            continue
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

    totales = CardRentabilidad(
        nombre="TOTAL",
        tipo="total",
        identificador=None,
        total_ventas=total_ventas,
        monto_venta=total_monto_venta,
        monto_limpio=total_monto_limpio,
        costo_total=total_costo,
        ganancia=total_ganancia,
        markup_promedio=total_markup,
        offset_total=total_offset,
        ganancia_con_offset=total_ganancia_con_offset,
        markup_con_offset=total_markup_con_offset,
        desglose_offsets=list(desglose_totales_agrupado.values()) if desglose_totales_agrupado else None
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
            "nivel_agrupacion": nivel
        }
    )


class ProductoBusqueda(BaseModel):
    """Producto encontrado en búsqueda"""
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str] = None
    categoria: Optional[str] = None


@router.get("/rentabilidad/buscar-productos", response_model=List[ProductoBusqueda])
async def buscar_productos(
    q: str = Query(..., min_length=2, description="Término de búsqueda"),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Busca productos por código o descripción que tengan ventas en el período.
    """
    # Convertir fechas a datetime para comparación correcta
    fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
    fecha_hasta_dt = datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time())

    # Buscar productos con ventas en el período
    query = db.query(
        MLVentaMetrica.item_id,
        MLVentaMetrica.codigo,
        MLVentaMetrica.descripcion,
        MLVentaMetrica.marca,
        MLVentaMetrica.categoria
    ).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        or_(
            MLVentaMetrica.codigo.ilike(f"%{q}%"),
            MLVentaMetrica.descripcion.ilike(f"%{q}%")
        )
    ).distinct().limit(50)

    resultados = query.all()

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


@router.get("/rentabilidad/filtros")
async def obtener_filtros_disponibles(
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
    Los filtros se retroalimentan entre sí (bidireccional).
    """
    # Usar | como separador para evitar conflictos con comas en nombres
    lista_marcas = [m.strip() for m in marcas.split('|')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split('|')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split('|')] if subcategorias else []

    # Convertir fechas a datetime para comparación correcta
    fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
    fecha_hasta_dt = datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time())

    # Marcas disponibles (filtradas por categorías y subcategorías seleccionadas)
    marcas_query = db.query(MLVentaMetrica.marca).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        MLVentaMetrica.marca.isnot(None)
    )
    if lista_categorias:
        marcas_query = marcas_query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
    if lista_subcategorias:
        marcas_query = marcas_query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
    marcas_disponibles = marcas_query.distinct().order_by(MLVentaMetrica.marca).all()

    # Categorías disponibles (filtradas por marcas y subcategorías seleccionadas)
    cat_query = db.query(MLVentaMetrica.categoria).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        MLVentaMetrica.categoria.isnot(None)
    )
    if lista_marcas:
        cat_query = cat_query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    if lista_subcategorias:
        cat_query = cat_query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
    categorias_disponibles = cat_query.distinct().order_by(MLVentaMetrica.categoria).all()

    # Subcategorías disponibles (filtradas por marcas y categorías seleccionadas)
    subcat_query = db.query(MLVentaMetrica.subcategoria).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        MLVentaMetrica.subcategoria.isnot(None)
    )
    if lista_marcas:
        subcat_query = subcat_query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    if lista_categorias:
        subcat_query = subcat_query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
    subcategorias_disponibles = subcat_query.distinct().order_by(MLVentaMetrica.subcategoria).all()

    return {
        "marcas": [m[0] for m in marcas_disponibles if m[0]],
        "categorias": [c[0] for c in categorias_disponibles if c[0]],
        "subcategorias": [s[0] for s in subcategorias_disponibles if s[0]]
    }
