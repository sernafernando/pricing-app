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
from app.models.usuario import Usuario, RolUsuario
from app.models.marca_pm import MarcaPM
from app.api.deps import get_current_user

router = APIRouter()


def aplicar_filtro_marcas_pm(query, usuario: Usuario, db: Session, pm_ids: Optional[str] = None):
    """
    Aplica filtro de marcas del PM a una query de MLVentaMetrica.
    
    Si pm_ids está presente (usuario admin seleccionó PMs específicos), filtra por esos PMs.
    Si pm_ids NO está presente, aplica el filtro del usuario actual (comportamiento original).
    """
    # Si el usuario admin pasó pm_ids, usar esos en lugar del usuario actual
    if pm_ids:
        pm_ids_list = [int(id.strip()) for id in pm_ids.split(',') if id.strip().isdigit()]
        if pm_ids_list:
            # Obtener marcas de los PMs seleccionados
            marcas_pms = db.query(MarcaPM.marca).filter(
                MarcaPM.usuario_id.in_(pm_ids_list)
            ).distinct().all()
            marcas_filtradas = [m[0] for m in marcas_pms] if marcas_pms else []
            
            if len(marcas_filtradas) == 0:
                query = query.filter(MLVentaMetrica.marca == '__NINGUNA__')
            else:
                query = query.filter(MLVentaMetrica.marca.in_(marcas_filtradas))
            return query
    
    # Comportamiento original: filtrar por marcas del usuario actual
    roles_completos = [RolUsuario.SUPERADMIN, RolUsuario.ADMIN, RolUsuario.GERENTE]

    if usuario.rol in roles_completos:
        return query  # No filtrar

    marcas = db.query(MarcaPM.marca).filter(MarcaPM.usuario_id == usuario.id).all()
    marcas_usuario = [m[0] for m in marcas] if marcas else []

    if len(marcas_usuario) == 0:
        query = query.filter(MLVentaMetrica.marca == '__NINGUNA__')
    else:
        query = query.filter(MLVentaMetrica.marca.in_(marcas_usuario))

    return query


def aplicar_filtro_tienda_oficial(query, tiendas_oficiales: Optional[str], db: Session):
    """
    Aplica filtro de tiendas oficiales por mlp_official_store_id.
    Soporta múltiples tiendas separadas por coma.
    
    Tiendas disponibles:
    - 57997: Gauss
    - 2645: TP-Link
    - 144: Forza/Verbatim
    - 191942: Multi-marca (Epson, Logitech, MGN, Razer)
    """
    if tiendas_oficiales:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
        from sqlalchemy import cast, String
        
        # Parsear múltiples tiendas
        store_ids = [int(id.strip()) for id in tiendas_oficiales.split(',') if id.strip().isdigit()]
        
        if store_ids:
            # Subquery para obtener mlp_ids de tiendas oficiales
            mlas_tienda_oficial = db.query(
                cast(MercadoLibreItemPublicado.mlp_id, String)
            ).filter(
                MercadoLibreItemPublicado.mlp_official_store_id.in_(store_ids)
            ).distinct()
            
            query = query.filter(MLVentaMetrica.mla_id.in_(mlas_tienda_oficial))
    return query


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
    tiendas_oficiales: Optional[str] = Query(None, description="IDs de tiendas oficiales separados por coma"),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene métricas de rentabilidad agrupadas según los filtros.
    Los filtros son independientes y se pueden combinar libremente.
    El nivel de agrupación se determina por la cantidad de filtros aplicados.
    Soporta filtros de PMs y múltiples tiendas oficiales.
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
        query = aplicar_filtro_tienda_oficial(query, tiendas_oficiales, db)
        query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)
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
        query = query.filter(MLVentaMetrica.item_id.isnot(None))
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
    def calcular_consumo_grupo_desde_tabla(grupo_id, desde_dt, hasta_dt, tienda_oficial_filtro=None):
        """Calcula unidades y monto offset para un grupo en un rango de fechas desde la tabla de consumo"""
        query = db.query(
            func.sum(OffsetGrupoConsumo.cantidad).label('total_unidades'),
            func.sum(OffsetGrupoConsumo.monto_offset_aplicado).label('total_monto_ars'),
            func.sum(OffsetGrupoConsumo.monto_offset_usd).label('total_monto_usd')
        ).filter(
            OffsetGrupoConsumo.grupo_id == grupo_id,
            OffsetGrupoConsumo.fecha_venta >= desde_dt,
            OffsetGrupoConsumo.fecha_venta < hasta_dt
        )
        
        # Filtrar por tienda oficial si aplica
        if tienda_oficial_filtro and tienda_oficial_filtro.isdigit():
            query = query.filter(OffsetGrupoConsumo.tienda_oficial == tienda_oficial_filtro)
        
        consumo = query.first()

        return (
            int(consumo.total_unidades or 0),
            float(consumo.total_monto_ars or 0),
            float(consumo.total_monto_usd or 0)
        )

    # Función para calcular el offset de un grupo EN TIEMPO REAL desde las ventas
    # Se usa cuando el grupo tiene filtros pero no hay datos precalculados
    def calcular_offset_grupo_en_tiempo_real(grupo_id, offset, desde_dt, hasta_dt, tc, tienda_oficial_filtro=None):
        """
        Calcula el offset de un grupo sumando las ventas que matchean sus filtros.
        Retorna (total_unidades, total_offset_ars, total_offset_usd)
        """
        filtros = filtros_por_grupo.get(grupo_id, [])
        if not filtros:
            return 0, 0.0, 0.0

        # Construir condiciones para los filtros
        condiciones_filtro = []
        for f in filtros:
            conds = []
            if f.marca:
                conds.append(f"marca = '{f.marca}'")
            if f.categoria:
                conds.append(f"categoria = '{f.categoria}'")
            if f.item_id:
                conds.append(f"item_id = {f.item_id}")
            if conds:
                condiciones_filtro.append(f"({' AND '.join(conds)})")

        if not condiciones_filtro:
            return 0, 0.0, 0.0

        where_filtros = " OR ".join(condiciones_filtro)
        
        # Filtro de tienda oficial (usar parámetro preparado para evitar SQL injection)
        filtro_tienda = ""
        params_ml = {"desde": desde_dt, "hasta": hasta_dt}
        if tienda_oficial_filtro and tienda_oficial_filtro.isdigit():
            filtro_tienda = "AND mlp_official_store_id = :tienda_oficial"
            params_ml["tienda_oficial"] = int(tienda_oficial_filtro)

        # Sumar ventas de ML
        query_ml = text(f"""
            SELECT
                COALESCE(SUM(cantidad), 0) as total_unidades,
                COALESCE(SUM(costo_total_sin_iva), 0) as total_costo
            FROM ml_ventas_metricas
            WHERE ({where_filtros})
            AND fecha_venta >= :desde AND fecha_venta < :hasta
            {filtro_tienda}
        """)
        result_ml = db.execute(query_ml, params_ml).first()

        # Sumar ventas fuera de ML (estas no tienen tienda oficial, se incluyen siempre)
        query_fuera = text(f"""
            SELECT
                COALESCE(SUM(cantidad), 0) as total_unidades,
                COALESCE(SUM(costo_total), 0) as total_costo
            FROM ventas_fuera_ml_metricas
            WHERE ({where_filtros})
            AND fecha_venta >= :desde AND fecha_venta < :hasta
        """)
        result_fuera = db.execute(query_fuera, {"desde": desde_dt, "hasta": hasta_dt}).first()

        total_unidades = int(result_ml.total_unidades or 0) + int(result_fuera.total_unidades or 0)
        total_costo = float(result_ml.total_costo or 0) + float(result_fuera.total_costo or 0)

        # Calcular el monto del offset según su tipo
        if offset.tipo_offset == 'monto_fijo':
            monto_offset = float(offset.monto or 0)
            if offset.moneda == 'USD':
                return total_unidades, monto_offset * tc, monto_offset
            else:
                return total_unidades, monto_offset, monto_offset / tc if tc > 0 else 0
        elif offset.tipo_offset == 'monto_por_unidad':
            monto_por_u = float(offset.monto or 0)
            if offset.moneda == 'USD':
                return total_unidades, monto_por_u * total_unidades * tc, monto_por_u * total_unidades
            else:
                return total_unidades, monto_por_u * total_unidades, monto_por_u * total_unidades / tc if tc > 0 else 0
        elif offset.tipo_offset == 'porcentaje_costo':
            porcentaje = float(offset.porcentaje or 0)
            monto_ars = total_costo * (porcentaje / 100)
            return total_unidades, monto_ars, monto_ars / tc if tc > 0 else 0

        return 0, 0.0, 0.0

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
                # IMPORTANTE: Este consumo previo es GLOBAL (sin filtro de tienda) para calcular límites correctamente
                consumo_previo_unidades = 0
                consumo_previo_offset = 0.0
                if offset_inicio_dt < fecha_desde_dt:
                    consumo_previo_unidades, consumo_previo_offset, _ = calcular_consumo_grupo_desde_tabla(
                        offset.grupo_id, offset_inicio_dt, fecha_desde_dt, tienda_oficial_filtro=None
                    )

                # Calcular consumo del período filtrado
                # IMPORTANTE: Solo contar ventas desde que el offset empezó a aplicar
                # Si el offset empieza después del inicio del filtro, usar la fecha del offset
                # Aquí SÍ aplicamos el filtro de tienda oficial para mostrar solo esa tienda
                periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)
                periodo_unidades, periodo_offset, _ = calcular_consumo_grupo_desde_tabla(
                    offset.grupo_id, periodo_inicio_dt, fecha_hasta_dt, tienda_oficial_filtro=tiendas_oficiales
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
                # No hay resumen todavía - calcular EN TIEMPO REAL desde las ventas
                # Fecha inicio del offset
                offset_inicio_dt = datetime.combine(offset.fecha_desde, datetime.min.time())
                periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)

                # Calcular el offset sumando ventas que matchean los filtros
                # Aplicar filtro de tienda oficial para mostrar solo esa tienda
                total_unidades, total_offset_ars, total_offset_usd = calcular_offset_grupo_en_tiempo_real(
                    offset.grupo_id, offset, periodo_inicio_dt, fecha_hasta_dt, tc, tienda_oficial_filtro=tiendas_oficiales
                )

                offsets_grupo_calculados[offset.grupo_id] = {
                    'offset_total': total_offset_ars,
                    'descripcion': offset.descripcion or f"Grupo {offset.grupo_id}",
                    'limite_aplicado': False,
                    'limite_agotado_previo': False,
                    'max_unidades': offset.max_unidades,
                    'max_monto_usd': offset.max_monto_usd,
                    'consumo_previo_offset': 0.0,
                    'consumo_acumulado_offset': total_offset_ars,
                    'consumo_acumulado_usd': total_offset_usd,
                    'calculado_en_tiempo_real': True
                }

    # Pre-calcular offsets INDIVIDUALES (sin grupo) con límites
    offsets_individuales_calculados = {}  # offset_id -> {'offset_total': X, 'limite_aplicado': bool, etc}

    def calcular_consumo_individual_desde_tabla(offset_id, desde_dt, hasta_dt, tienda_oficial_filtro=None):
        """Calcula unidades y monto para un offset individual en un rango de fechas"""
        query = db.query(
            func.sum(OffsetIndividualConsumo.cantidad).label('total_unidades'),
            func.sum(OffsetIndividualConsumo.monto_offset_aplicado).label('total_monto_ars'),
            func.sum(OffsetIndividualConsumo.monto_offset_usd).label('total_monto_usd')
        ).filter(
            OffsetIndividualConsumo.offset_id == offset_id,
            OffsetIndividualConsumo.fecha_venta >= desde_dt,
            OffsetIndividualConsumo.fecha_venta < hasta_dt
        )
        
        # Filtrar por tienda oficial si aplica
        if tienda_oficial_filtro and tienda_oficial_filtro.isdigit():
            query = query.filter(OffsetIndividualConsumo.tienda_oficial == tienda_oficial_filtro)
        
        consumo = query.first()

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
            # IMPORTANTE: Este consumo previo es GLOBAL (sin filtro de tienda) para calcular límites correctamente
            consumo_previo_unidades = 0
            consumo_previo_offset = 0.0
            if offset_inicio_dt < fecha_desde_dt:
                consumo_previo_unidades, consumo_previo_offset, _ = calcular_consumo_individual_desde_tabla(
                    offset.id, offset_inicio_dt, fecha_desde_dt, tienda_oficial_filtro=None
                )

            # Consumo del período filtrado
            # IMPORTANTE: Solo contar ventas desde que el offset empezó a aplicar
            # Si el offset empieza después del inicio del filtro, usar la fecha del offset
            # Aquí SÍ aplicamos el filtro de tienda oficial para mostrar solo esa tienda
            periodo_inicio_dt = max(fecha_desde_dt, offset_inicio_dt)
            periodo_unidades, periodo_offset, _ = calcular_consumo_individual_desde_tabla(
                offset.id, periodo_inicio_dt, fecha_hasta_dt, tienda_oficial_filtro=tienda_oficial
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
        
        # Aplicar filtro de tienda oficial
        query = aplicar_filtro_tienda_oficial(query, tiendas_oficiales, db)

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
                        # IMPORTANTE: Si el filtro tiene marca+categoría, solo debe matchear si ambas coinciden
                        for filtro in filtros_por_grupo[offset.grupo_id]:
                            if filtro.marca and filtro.marca == card_nombre:
                                # Si el filtro tiene categoría, verificar que existan productos que cumplan ambas
                                if filtro.categoria:
                                    # Verificar si hay productos de esta marca+categoría en las ventas
                                    for item_id, detalle in productos_detalle.items():
                                        if detalle['marca'] == card_nombre and detalle['categoria'] == filtro.categoria:
                                            aplica_a_card = True
                                            break
                                else:
                                    # Filtro solo por marca
                                    aplica_a_card = True
                                if aplica_a_card:
                                    break
                    elif nivel == "categoria":
                        # Para card de categoría, verificar si algún filtro matchea esta categoría
                        # IMPORTANTE: Si el filtro tiene marca+categoría, solo debe matchear si ambas coinciden
                        for filtro in filtros_por_grupo[offset.grupo_id]:
                            if filtro.categoria and filtro.categoria == card_nombre:
                                # Si el filtro tiene marca, verificar que existan productos que cumplan ambas
                                if filtro.marca:
                                    # Verificar si hay productos de esta categoría+marca en las ventas
                                    for item_id, detalle in productos_detalle.items():
                                        if detalle['categoria'] == card_nombre and detalle['marca'] == filtro.marca:
                                            aplica_a_card = True
                                            break
                                else:
                                    # Filtro solo por categoría
                                    aplica_a_card = True
                                if aplica_a_card:
                                    break
                    elif nivel == "subcategoria":
                        # Para card de subcategoría, verificar filtros del grupo
                        for filtro in filtros_por_grupo[offset.grupo_id]:
                            # Match directo por subcategoria_id
                            if filtro.subcategoria_id and str(filtro.subcategoria_id) == str(card_identificador):
                                aplica_a_card = True
                                break
                            # Si el filtro tiene marca/categoría, verificar si la subcat tiene productos que cumplan
                            elif filtro.marca or filtro.categoria:
                                for item_id, detalle in productos_detalle.items():
                                    if detalle.get('subcategoria') != card_nombre:
                                        continue
                                    # Validar que el producto cumpla TODOS los criterios del filtro
                                    cumple = True
                                    if filtro.marca and detalle.get('marca') != filtro.marca:
                                        cumple = False
                                    if filtro.categoria and detalle.get('categoria') != filtro.categoria:
                                        cumple = False
                                    if cumple:
                                        aplica_a_card = True
                                        break
                                if aplica_a_card:
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
                        elif offset.categoria and not offset.marca:
                            # Solo si el offset NO tiene marca específica (solo categoría)
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
                        elif offset.marca and not offset.categoria:
                            # Solo si el offset NO tiene categoría específica (solo marca)
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
                        # Offsets de marca/categoría aplican si los filtros del usuario coinciden
                        elif offset.marca or offset.categoria:
                            # Buscar productos de esta subcategoría que cumplan los filtros del offset
                            for item_id, detalle in productos_detalle.items():
                                if detalle.get('subcategoria') != card_nombre:
                                    continue
                                # Validar que el producto cumpla TODOS los criterios del offset
                                cumple = True
                                if offset.marca and detalle.get('marca') != offset.marca:
                                    cumple = False
                                if offset.categoria and detalle.get('categoria') != offset.categoria:
                                    cumple = False
                                if cumple:
                                    aplica_a_card = True
                                    break
                    elif nivel == "producto":
                        if offset.item_id and str(offset.item_id) == str(card_identificador):
                            aplica_a_card = True
                        # Offsets de marca/categoría aplican si el producto cumple los criterios
                        elif offset.marca or offset.categoria:
                            detalle = productos_detalle.get(int(card_identificador)) if card_identificador else None
                            if detalle:
                                cumple = True
                                if offset.marca and detalle.get('marca') != offset.marca:
                                    cumple = False
                                if offset.categoria and detalle.get('categoria') != offset.categoria:
                                    cumple = False
                                if cumple:
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

                    # En cards individuales de producto/subcategoría, NO mostramos el offset
                    # porque el offset del grupo es por CAMPAÑA, no por item individual
                    # El total se suma UNA sola vez en los totales globales (sección posterior del código)
                    #
                    # Criterio para NO mostrar en la card:
                    # - Nivel producto: siempre (no mostrar)
                    # - Nivel subcategoría con filtros: siempre (no mostrar, se suma en totales)
                    # - Nivel marca/categoria: SÍ mostrar y sumar
                    es_nivel_detalle = (
                        nivel == "producto" or 
                        (nivel == "subcategoria" and (lista_marcas or lista_categorias))
                    )
                    
                    if not es_nivel_detalle:
                        # Solo para niveles agregados (marca, categoria sin filtros previos)
                        # mostramos el total del grupo en cada card
                        desglose.append(DesgloseOffset(
                            descripcion=f"{grupo_info['descripcion']}{limite_texto}",
                            nivel="grupo",
                            nombre_nivel=f"Grupo {offset.grupo_id}",
                            tipo_offset=offset.tipo_offset or 'monto_fijo',
                            monto=grupo_info['offset_total']
                        ))
                        offset_total += grupo_info['offset_total']
                    # Si es nivel de detalle, NO agregamos nada al desglose de la card
                    # El offset se agregará al total global en la sección posterior del código

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
                    # IMPORTANTE: Si el offset tiene marca + categoría, solo aplica si la marca coincide
                    # Si el offset tiene solo categoría (sin marca), aplica a todas las marcas de esa categoría
                    if offset.marca and offset.marca != card_nombre:
                        # El offset tiene marca específica que no coincide con esta card
                        pass
                    else:
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
                elif offset.marca and not offset.subcategoria_id and not offset.item_id:
                    # CAMBIO: Ahora soporta offsets con marca sola O marca+categoría
                    # Si el offset tiene marca+categoría, debe coincidir la categoría con la card
                    if offset.categoria and offset.categoria != card_nombre:
                        # El offset tiene categoría específica que no coincide con esta card
                        pass
                    else:
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
                # Offset de marca+categoría que aplica a esta subcategoría
                elif offset.marca and offset.categoria and not offset.subcategoria_id and not offset.item_id:
                    # Validar que la subcategoría tenga productos que cumplan marca+categoría
                    # Primero verificar si hay productos en productos_detalle que cumplan
                    tiene_productos_validos = False
                    for item_id, detalle in productos_detalle.items():
                        if (detalle.get('subcategoria') == card_nombre and 
                            detalle.get('marca') == offset.marca and 
                            detalle.get('categoria') == offset.categoria):
                            tiene_productos_validos = True
                            break
                    
                    if tiene_productos_validos:
                        # Buscar ventas de esta subcategoría que cumplan marca+categoría del offset
                        cant_offset, costo_offset = obtener_ventas_periodo_offset(
                            offset,
                            and_(
                                MLVentaMetrica.subcategoria == card_nombre,
                                MLVentaMetrica.marca == offset.marca,
                                MLVentaMetrica.categoria == offset.categoria
                            ),
                            True
                        )
                        if cant_offset > 0:
                            valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                            aplica = True
                            nombre_nivel = f"{offset.marca} + {offset.categoria}"
                # Offset de marca sola que aplica a esta subcategoría
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
                # Offset de categoría sola que aplica a esta subcategoría
                elif offset.categoria and not offset.marca and not offset.subcategoria_id and not offset.item_id:
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
                # Offset directo por producto
                if offset.item_id and str(offset.item_id) == str(card_identificador):
                    cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.item_id, int(card_identificador))
                    if cant_offset > 0:
                        valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                        aplica = True
                # Offsets de niveles superiores (marca, categoría, subcategoría) que aplican a este producto
                elif not offset.item_id:
                    detalle = productos_detalle.get(int(card_identificador)) if card_identificador else None
                    if detalle:
                        # Verificar si el producto cumple TODOS los criterios del offset
                        cumple = True
                        if offset.marca and detalle.get('marca') != offset.marca:
                            cumple = False
                        if offset.categoria and detalle.get('categoria') != offset.categoria:
                            cumple = False
                        if offset.subcategoria_id and detalle.get('subcategoria_id') != offset.subcategoria_id:
                            cumple = False
                        
                        if cumple:
                            cant_offset, costo_offset = obtener_ventas_periodo_offset(offset, MLVentaMetrica.item_id, int(card_identificador))
                            if cant_offset > 0:
                                valor_offset = calcular_valor_offset(offset, cant_offset, costo_offset)
                                aplica = True
                                # Nombre descriptivo según qué criterios tiene el offset
                                if offset.marca and offset.categoria:
                                    nombre_nivel = f"{offset.marca} + {offset.categoria}"
                                elif offset.marca:
                                    nombre_nivel = f"Marca: {offset.marca}"
                                elif offset.categoria:
                                    nombre_nivel = f"Cat: {offset.categoria}"
                                elif offset.subcategoria_id:
                                    nombre_nivel = f"Subcat: {offset.subcategoria_id}"

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
    # Solo cuando estamos a nivel de detalle (producto o subcategoría con filtros),
    # porque en niveles agregados ya se sumó en calcular_offsets_para_card
    if nivel == "producto" or (nivel == "subcategoria" and (lista_marcas or lista_categorias)):
        for grupo_id, grupo_info in offsets_grupo_calculados.items():
            # Verificar si el grupo aplica a algún item en los resultados
            grupo_aplica = False
            
            if nivel == "producto":
                # Para productos: verificar si hay offsets del grupo por item_id
                for offset in offsets:
                    if offset.grupo_id == grupo_id and offset.item_id:
                        for r in resultados:
                            if str(r.identificador) == str(offset.item_id):
                                grupo_aplica = True
                                break
                    if grupo_aplica:
                        break
            elif nivel == "subcategoria":
                # Para subcategorías: verificar si el grupo tiene filtros que matchean
                # con los filtros del usuario (marca/categoría)
                if grupo_id in filtros_por_grupo and filtros_por_grupo[grupo_id]:
                    for filtro in filtros_por_grupo[grupo_id]:
                        # Si el filtro del grupo matchea con los filtros del usuario, aplica
                        matchea = True
                        if filtro.marca and lista_marcas and filtro.marca not in lista_marcas:
                            matchea = False
                        if filtro.categoria and lista_categorias and filtro.categoria not in lista_categorias:
                            matchea = False
                        if matchea:
                            grupo_aplica = True
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
            "tiendas_oficiales": tiendas_oficiales,
            "pm_ids": pm_ids,
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
    tiendas_oficiales: Optional[str] = Query(None, description="IDs de tiendas oficiales separados por coma"),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Busca productos por código o descripción que tengan ventas en el período.
    Soporta filtros de PMs y múltiples tiendas oficiales.
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
    )
    
    query = aplicar_filtro_tienda_oficial(query, tiendas_oficiales, db)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)
    query = query.distinct().limit(50)

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
    tiendas_oficiales: Optional[str] = Query(None, description="IDs de tiendas oficiales separados por coma"),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los valores disponibles para los filtros basado en los datos del período.
    Los filtros se retroalimentan entre sí (bidireccional).
    Soporta filtros de PMs y múltiples tiendas oficiales.
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
    marcas_query = aplicar_filtro_tienda_oficial(marcas_query, tiendas_oficiales, db)
    marcas_query = aplicar_filtro_marcas_pm(marcas_query, current_user, db, pm_ids)
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
    cat_query = aplicar_filtro_tienda_oficial(cat_query, tiendas_oficiales, db)
    cat_query = aplicar_filtro_marcas_pm(cat_query, current_user, db, pm_ids)
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
    subcat_query = aplicar_filtro_tienda_oficial(subcat_query, tiendas_oficiales, db)
    subcat_query = aplicar_filtro_marcas_pm(subcat_query, current_user, db, pm_ids)
    subcategorias_disponibles = subcat_query.distinct().order_by(MLVentaMetrica.subcategoria).all()

    return {
        "marcas": [m[0] for m in marcas_disponibles if m[0]],
        "categorias": [c[0] for c in categorias_disponibles if c[0]],
        "subcategorias": [s[0] for s in subcategorias_disponibles if s[0]]
    }
