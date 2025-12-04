from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text
from typing import List, Optional
from datetime import date, datetime, timedelta
from pydantic import BaseModel

from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.offset_ganancia import OffsetGanancia
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
    # Parsear filtros múltiples
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split(',')] if subcategorias else []
    lista_productos = [int(p.strip()) for p in productos.split(',') if p.strip().isdigit()] if productos else []

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

    # Calcular acumulados por grupo/offset para verificar límites
    # Los límites son OR: si se cumple max_unidades O max_monto_usd, el offset deja de aplicar
    acumulados_grupo = {}  # grupo_id -> {'unidades': X, 'monto_usd': Y}
    acumulados_offset = {}  # offset_id -> {'unidades': X, 'monto_usd': Y}

    # Obtener unidades vendidas y monto para cada offset con límites
    for offset in offsets:
        if offset.max_unidades is None and offset.max_monto_usd is None:
            continue  # Sin límites, no necesita tracking

        # Determinar qué item_ids aplican a este offset
        items_aplicables = []
        if offset.item_id:
            items_aplicables = [offset.item_id]
        elif offset.subcategoria_id:
            items_aplicables = [
                d.item_id for d in db.query(MLVentaMetrica.item_id).filter(
                    MLVentaMetrica.subcategoria == str(offset.subcategoria_id),
                    MLVentaMetrica.fecha_venta >= fecha_desde_dt,
                    MLVentaMetrica.fecha_venta < fecha_hasta_dt
                ).distinct().all()
            ]
        elif offset.categoria:
            items_aplicables = [
                d.item_id for d in db.query(MLVentaMetrica.item_id).filter(
                    MLVentaMetrica.categoria == offset.categoria,
                    MLVentaMetrica.fecha_venta >= fecha_desde_dt,
                    MLVentaMetrica.fecha_venta < fecha_hasta_dt
                ).distinct().all()
            ]
        elif offset.marca:
            items_aplicables = [
                d.item_id for d in db.query(MLVentaMetrica.item_id).filter(
                    MLVentaMetrica.marca == offset.marca,
                    MLVentaMetrica.fecha_venta >= fecha_desde_dt,
                    MLVentaMetrica.fecha_venta < fecha_hasta_dt
                ).distinct().all()
            ]

        # Calcular unidades y monto para estos items
        if items_aplicables:
            acum = db.query(
                func.count(MLVentaMetrica.id).label('unidades'),
                func.sum(MLVentaMetrica.monto_total).label('monto')
            ).filter(
                MLVentaMetrica.item_id.in_(items_aplicables),
                MLVentaMetrica.fecha_venta >= fecha_desde_dt,
                MLVentaMetrica.fecha_venta < fecha_hasta_dt
            ).first()

            unidades = acum.unidades or 0
            monto = float(acum.monto or 0)
            # Convertir monto a USD si hay tipo de cambio
            monto_usd = monto / float(offset.tipo_cambio) if offset.tipo_cambio and offset.tipo_cambio > 0 else monto

            if offset.grupo_id:
                # Acumular en el grupo
                if offset.grupo_id not in acumulados_grupo:
                    acumulados_grupo[offset.grupo_id] = {'unidades': 0, 'monto_usd': 0}
                acumulados_grupo[offset.grupo_id]['unidades'] += unidades
                acumulados_grupo[offset.grupo_id]['monto_usd'] += monto_usd
            else:
                # Acumular en el offset individual
                acumulados_offset[offset.id] = {'unidades': unidades, 'monto_usd': monto_usd}

    def verificar_limite_alcanzado(offset):
        """
        Verifica si el offset ya alcanzó alguno de sus límites (condición OR).
        Retorna True si ya NO debe aplicar más.
        """
        if offset.max_unidades is None and offset.max_monto_usd is None:
            return False  # Sin límites

        # Obtener acumulados
        if offset.grupo_id and offset.grupo_id in acumulados_grupo:
            acum = acumulados_grupo[offset.grupo_id]
        elif offset.id in acumulados_offset:
            acum = acumulados_offset[offset.id]
        else:
            return False  # No hay datos acumulados

        # Verificar límites con condición OR
        if offset.max_unidades is not None and acum['unidades'] >= offset.max_unidades:
            return True
        if offset.max_monto_usd is not None and acum['monto_usd'] >= offset.max_monto_usd:
            return True

        return False

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
        """
        offset_total = 0.0
        desglose = []

        for offset in offsets:
            valor_offset = 0.0
            aplica = False
            nivel_offset, nombre_nivel = get_offset_nivel_nombre(offset)

            if nivel == "marca":
                # Offset directo por marca
                if offset.marca and offset.marca == card_nombre and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
                    aplica = True
                # Offsets de categorías dentro de esta marca
                elif offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    # Sumar ventas de productos de esta marca en esa categoría
                    for item_id, detalle in productos_detalle.items():
                        if detalle['marca'] == card_nombre and detalle['categoria'] == offset.categoria:
                            valor_offset += calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                    if valor_offset > 0:
                        aplica = True
                        nombre_nivel = f"Cat: {offset.categoria}"
                # Offsets de productos dentro de esta marca
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['marca'] == card_nombre:
                        valor_offset = calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                        aplica = True
                        nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "categoria":
                # Offset directo por categoría
                if offset.categoria and offset.categoria == card_nombre and not offset.subcategoria_id and not offset.item_id:
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
                    aplica = True
                # Offset de marca que aplica a esta categoría
                elif offset.marca and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    # Sumar ventas de productos de esa marca en esta categoría
                    for item_id, detalle in productos_detalle.items():
                        if detalle['categoria'] == card_nombre and detalle['marca'] == offset.marca:
                            valor_offset += calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                    if valor_offset > 0:
                        aplica = True
                        nombre_nivel = f"Marca: {offset.marca}"
                # Offsets de productos dentro de esta categoría
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['categoria'] == card_nombre:
                        valor_offset = calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                        aplica = True
                        nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "subcategoria":
                # Offset directo por subcategoría
                if offset.subcategoria_id and str(offset.subcategoria_id) == str(card_identificador):
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
                    aplica = True
                # Offset de marca que aplica a esta subcategoría
                elif offset.marca and not offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    for item_id, detalle in productos_detalle.items():
                        if detalle['subcategoria'] == card_nombre and detalle['marca'] == offset.marca:
                            valor_offset += calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                    if valor_offset > 0:
                        aplica = True
                        nombre_nivel = f"Marca: {offset.marca}"
                # Offset de categoría que aplica a esta subcategoría
                elif offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    for item_id, detalle in productos_detalle.items():
                        if detalle['subcategoria'] == card_nombre and detalle['categoria'] == offset.categoria:
                            valor_offset += calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                    if valor_offset > 0:
                        aplica = True
                        nombre_nivel = f"Cat: {offset.categoria}"
                # Offsets de productos dentro de esta subcategoría
                elif offset.item_id:
                    detalle = productos_detalle.get(offset.item_id)
                    if detalle and detalle['subcategoria'] == card_nombre:
                        valor_offset = calcular_valor_offset(offset, detalle['cantidad'], detalle['costo'])
                        aplica = True
                        nombre_nivel = f"Prod: {offset.item_id}"

            elif nivel == "producto":
                # Solo offsets directos del producto o de sus niveles superiores
                if offset.item_id and str(offset.item_id) == str(card_identificador):
                    valor_offset = calcular_valor_offset(offset, cantidad_vendida, costo_total)
                    aplica = True

            # Verificar si el offset ya alcanzó alguno de sus límites (OR)
            if aplica and valor_offset > 0:
                if verificar_limite_alcanzado(offset):
                    # Límite alcanzado, agregar al desglose con monto 0 y nota
                    desglose.append(DesgloseOffset(
                        descripcion=f"{offset.descripcion or f'Offset {offset.id}'} (LÍMITE ALCANZADO)",
                        nivel=nivel_offset,
                        nombre_nivel=nombre_nivel,
                        tipo_offset=offset.tipo_offset or 'monto_fijo',
                        monto=0
                    ))
                else:
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

    # Calcular totales
    total_ganancia_con_offset = total_ganancia + total_offset
    total_markup = ((total_ganancia / total_costo) * 100) if total_costo > 0 else 0
    total_markup_con_offset = ((total_ganancia_con_offset / total_costo) * 100) if total_costo > 0 else 0

    # Agrupar desglose de offsets totales por descripción
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
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split(',')] if subcategorias else []

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
