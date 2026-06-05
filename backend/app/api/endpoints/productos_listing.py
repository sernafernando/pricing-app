from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_, select, tuple_
from typing import Optional
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from datetime import UTC, date
from app.api.deps import get_current_user
from app.services.envio_real_service import resolver_costos_envio_batch, resolver_costo_envio
import logging

from app.api.endpoints.productos_shared import (  # noqa: F401
    ProductoResponse,
    ProductoListResponse,
    ProductoTiendaResponse,
    ProductoTiendaListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/productos", response_model=ProductoListResponse)
def listar_productos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    orden_campos: Optional[str] = None,
    orden_direcciones: Optional[str] = None,
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    con_rebate: Optional[bool] = None,
    con_oferta: Optional[bool] = None,
    con_web_transf: Optional[bool] = None,
    tn_con_descuento: Optional[bool] = None,
    tn_sin_descuento: Optional[bool] = None,
    tn_no_publicado: Optional[bool] = None,
    markup_clasica_positivo: Optional[bool] = None,
    markup_rebate_positivo: Optional[bool] = None,
    markup_oferta_positivo: Optional[bool] = None,
    markup_web_transf_positivo: Optional[bool] = None,
    out_of_cards: Optional[bool] = None,
    colores: Optional[str] = None,
    pms: Optional[str] = None,
    con_mla: Optional[bool] = None,
    estado_mla: Optional[str] = None,
    nuevos_ultimos_7_dias: Optional[bool] = None,
    tienda_oficial: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

    # EXCLUIR PRODUCTOS BANEADOS
    from app.models.producto_banlist import ProductoBanlist

    # Obtener productos baneados por item_id
    productos_baneados_item_ids = (
        db.query(ProductoBanlist.item_id)
        .filter(ProductoBanlist.activo == True, ProductoBanlist.item_id.isnot(None))
        .all()
    )

    # Obtener productos baneados por EAN
    productos_baneados_eans = (
        db.query(ProductoBanlist.ean).filter(ProductoBanlist.activo == True, ProductoBanlist.ean.isnot(None)).all()
    )

    # Aplicar filtros de exclusión
    filtros_ban = []

    if productos_baneados_item_ids:
        banned_ids = [pid[0] for pid in productos_baneados_item_ids]
        filtros_ban.append(ProductoERP.item_id.in_(banned_ids))

    if productos_baneados_eans:
        banned_eans = [ean[0] for ean in productos_baneados_eans]
        # Solo excluir por EAN si el EAN coincide Y no está vacío/null
        filtros_ban.append(and_(ProductoERP.ean.in_(banned_eans), ProductoERP.ean.isnot(None), ProductoERP.ean != ""))

    if filtros_ban:
        query = query.filter(~or_(*filtros_ban))

    # FILTRADO POR AUDITORÍA
    if audit_usuarios or audit_tipos_accion or audit_fecha_desde or audit_fecha_hasta:
        from app.models.auditoria import Auditoria
        from datetime import datetime
        from sqlalchemy.sql import exists

        # Construir filtros de auditoría base
        filtros_audit = [Auditoria.item_id.isnot(None)]

        if audit_usuarios:
            usuarios_ids = [int(u) for u in audit_usuarios.split(",")]
            filtros_audit.append(Auditoria.usuario_id.in_(usuarios_ids))

        if audit_tipos_accion:
            tipos_list = audit_tipos_accion.split(",")
            filtros_audit.append(Auditoria.tipo_accion.in_(tipos_list))

        fecha_desde_dt = None
        if audit_fecha_desde:
            try:
                # Intentar con segundos
                fecha_desde_dt = datetime.strptime(audit_fecha_desde, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    # Intentar sin segundos (formato datetime-local de HTML5)
                    fecha_desde_dt = datetime.strptime(audit_fecha_desde, "%Y-%m-%d %H:%M")
                except ValueError:
                    try:
                        # Intentar solo fecha (poner hora en 00:00:00)
                        fecha_desde_dt = datetime.strptime(audit_fecha_desde, "%Y-%m-%d")
                    except ValueError:
                        # Si falla todo, usar fecha de hoy
                        from datetime import date

                        fecha_desde_dt = datetime.combine(date.today(), datetime.min.time())

            # Convertir de hora local (ART = UTC-3) a UTC sumando 3 horas
            from datetime import timedelta

            fecha_desde_dt = fecha_desde_dt + timedelta(hours=3)

            filtros_audit.append(Auditoria.fecha >= fecha_desde_dt)

        fecha_hasta_dt = None
        if audit_fecha_hasta:
            try:
                # Intentar con segundos
                fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    # Intentar sin segundos (formato datetime-local de HTML5)
                    fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, "%Y-%m-%d %H:%M")
                except ValueError:
                    try:
                        # Solo fecha: poner hora al final del día
                        fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, "%Y-%m-%d")
                        fecha_hasta_dt = fecha_hasta_dt.replace(hour=23, minute=59, second=59)
                    except ValueError:
                        from datetime import date

                        fecha_hasta_dt = datetime.combine(date.today(), datetime.max.time())

            # Convertir de hora local (ART = UTC-3) a UTC sumando 3 horas
            from datetime import timedelta

            fecha_hasta_dt = fecha_hasta_dt + timedelta(hours=3)

            filtros_audit.append(Auditoria.fecha <= fecha_hasta_dt)

        # Obtener productos que tienen auditorías cumpliendo los criterios
        audit_query = db.query(Auditoria.item_id).filter(and_(*filtros_audit))
        item_ids = [item_id for (item_id,) in audit_query.distinct().all()]

        if item_ids:
            query = query.filter(ProductoERP.item_id.in_(item_ids))
        else:
            return ProductoListResponse(total=0, page=page, page_size=page_size, productos=[])

    if search:
        # Parsear operadores de búsqueda
        search_filter = None
        logger.debug(f"Búsqueda recibida: '{search}'")

        # Detectar búsquedas literales: campo:valor
        if ":" in search and not search.startswith("*") and not search.endswith("*"):
            parts = search.split(":", 1)
            if len(parts) == 2:
                field, value = parts[0].strip().lower(), parts[1].strip()

                if field == "ean":
                    # EAN no está disponible en ProductoERP, buscar por código
                    logger.debug(f"Buscando EAN '{value}' en campo código")
                    search_filter = and_(
                        ProductoERP.codigo.isnot(None),
                        ProductoERP.codigo != "",
                        func.upper(ProductoERP.codigo) == value.upper(),
                    )
                elif field == "codigo":
                    # Búsqueda exacta por código (case insensitive)
                    search_filter = and_(
                        ProductoERP.codigo.isnot(None),
                        ProductoERP.codigo != "",
                        func.upper(ProductoERP.codigo) == value.upper(),
                    )
                elif field == "marca":
                    # Búsqueda exacta por marca (case insensitive)
                    search_filter = and_(
                        ProductoERP.marca.isnot(None),
                        ProductoERP.marca != "",
                        func.upper(ProductoERP.marca) == value.upper(),
                    )
                elif field == "desc" or field == "descripcion":
                    # Búsqueda por descripción (contiene)
                    value_normalized = value.replace("-", "").replace(" ", "").upper()
                    search_filter = and_(
                        ProductoERP.descripcion.isnot(None),
                        func.replace(func.replace(func.upper(ProductoERP.descripcion), "-", ""), " ", "").like(
                            f"%{value_normalized}%"
                        ),
                    )
                else:
                    # Si el campo no es reconocido, hacer búsqueda normal con el texto completo
                    search_normalized = search.replace("-", "").replace(" ", "").upper()
                    search_filter = or_(
                        func.replace(func.replace(func.upper(ProductoERP.descripcion), "-", ""), " ", "").like(
                            f"%{search_normalized}%"
                        ),
                        func.replace(func.replace(func.upper(ProductoERP.marca), "-", ""), " ", "").like(
                            f"%{search_normalized}%"
                        ),
                        func.replace(func.upper(ProductoERP.codigo), "-", "").like(f"%{search_normalized}%"),
                    )

        # Detectar wildcards: *valor (termina en) o valor* (comienza con)
        elif search.startswith("*") and not search.endswith("*"):
            # Termina en
            value = search[1:].upper()
            logger.debug(f"Filtrando por TERMINA EN: '{value}'")
            search_filter = or_(
                and_(ProductoERP.descripcion.isnot(None), func.upper(ProductoERP.descripcion).like(f"%{value}")),
                and_(ProductoERP.marca.isnot(None), func.upper(ProductoERP.marca).like(f"%{value}")),
                and_(ProductoERP.codigo.isnot(None), func.upper(ProductoERP.codigo).like(f"%{value}")),
            )
        elif search.endswith("*") and not search.startswith("*"):
            # Comienza con
            value = search[:-1].upper()
            search_filter = or_(
                and_(ProductoERP.descripcion.isnot(None), func.upper(ProductoERP.descripcion).like(f"{value}%")),
                and_(ProductoERP.marca.isnot(None), func.upper(ProductoERP.marca).like(f"{value}%")),
                and_(ProductoERP.codigo.isnot(None), func.upper(ProductoERP.codigo).like(f"{value}%")),
            )
        else:
            # Búsqueda normal (contiene)
            search_normalized = search.replace("-", "").replace(" ", "").upper()
            search_filter = or_(
                func.replace(func.replace(func.upper(ProductoERP.descripcion), "-", ""), " ", "").like(
                    f"%{search_normalized}%"
                ),
                func.replace(func.replace(func.upper(ProductoERP.marca), "-", ""), " ", "").like(
                    f"%{search_normalized}%"
                ),
                func.replace(func.upper(ProductoERP.codigo), "-", "").like(f"%{search_normalized}%"),
            )

        # Aplicar filtro de búsqueda
        if search_filter is not None:
            logger.debug("Aplicando filtro de búsqueda")
            query = query.filter(search_filter)
        else:
            logger.warning("⚠️ search_filter quedó en None! No se aplicó ningún filtro")

    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)

    if subcategorias:
        subcat_list = [int(s.strip()) for s in subcategorias.split(",")]
        query = query.filter(ProductoERP.subcategoria_id.in_(subcat_list))

    if marcas:
        marcas_list = [m.strip().upper() for m in marcas.split(",")]
        query = query.filter(func.upper(ProductoERP.marca).in_(marcas_list))

    # Filtro por PMs (Product Managers) - filtra por pares (marca, categoria)
    if pms:
        from app.models.marca_pm import MarcaPM

        pm_ids = [int(pm.strip()) for pm in pms.split(",")]

        # Obtener pares marca-categoría asignados a esos PMs
        pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids)).all()

        if pares_pm:
            pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
            query = query.filter(
                tuple_(func.upper(ProductoERP.marca), func.upper(ProductoERP.categoria)).in_(pares_upper)
            )
        else:
            # Si no hay marcas asignadas, retornar vacío
            return ProductoListResponse(total=0, page=page, page_size=page_size, productos=[])

    if con_stock is not None:
        query = query.filter(ProductoERP.stock > 0 if con_stock else ProductoERP.stock == 0)

    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(ProductoPricing.precio_lista_ml.is_(None))

    # Filtros de valores específicos
    if con_rebate is not None:
        if con_rebate:
            query = query.filter(ProductoPricing.participa_rebate == True)
        else:
            query = query.filter(
                or_(ProductoPricing.participa_rebate == False, ProductoPricing.participa_rebate.is_(None))
            )

    if con_web_transf is not None:
        if con_web_transf:
            query = query.filter(ProductoPricing.participa_web_transferencia == True)
        else:
            query = query.filter(
                or_(
                    ProductoPricing.participa_web_transferencia == False,
                    ProductoPricing.participa_web_transferencia.is_(None),
                )
            )

    # Filtros de Tienda Nube
    if tn_con_descuento or tn_sin_descuento or tn_no_publicado:
        from app.models.tienda_nube_producto import TiendaNubeProducto

        if tn_con_descuento:
            # Productos que tienen promotional_price (con descuento)
            query = query.join(
                TiendaNubeProducto,
                and_(
                    ProductoERP.item_id == TiendaNubeProducto.item_id,
                    TiendaNubeProducto.activo == True,
                    TiendaNubeProducto.promotional_price.isnot(None),
                    TiendaNubeProducto.promotional_price > 0,
                ),
            )
        elif tn_sin_descuento:
            # Productos publicados pero sin promotional_price
            query = query.join(
                TiendaNubeProducto,
                and_(
                    ProductoERP.item_id == TiendaNubeProducto.item_id,
                    TiendaNubeProducto.activo == True,
                    or_(TiendaNubeProducto.promotional_price.is_(None), TiendaNubeProducto.promotional_price == 0),
                ),
            )
        elif tn_no_publicado:
            # Productos con stock pero NO en Tienda Nube
            from sqlalchemy.sql import exists

            subquery = exists().where(
                and_(TiendaNubeProducto.item_id == ProductoERP.item_id, TiendaNubeProducto.activo == True)
            )
            query = query.filter(and_(ProductoERP.stock > 0, ~subquery))

    # Filtros de markup
    if markup_clasica_positivo is not None:
        if markup_clasica_positivo:
            query = query.filter(ProductoPricing.markup_calculado > 0)
        else:
            query = query.filter(ProductoPricing.markup_calculado < 0)

    if markup_rebate_positivo is not None:
        if markup_rebate_positivo:
            query = query.filter(ProductoPricing.markup_rebate > 0)
        else:
            query = query.filter(ProductoPricing.markup_rebate < 0)

    if markup_oferta_positivo is not None:
        if markup_oferta_positivo:
            query = query.filter(ProductoPricing.markup_oferta > 0)
        else:
            query = query.filter(ProductoPricing.markup_oferta < 0)

    if markup_web_transf_positivo is not None:
        if markup_web_transf_positivo:
            query = query.filter(ProductoPricing.markup_web_real > 0)
        else:
            query = query.filter(ProductoPricing.markup_web_real < 0)

    if out_of_cards is not None:
        if out_of_cards:
            query = query.filter(ProductoPricing.out_of_cards == True)
        else:
            query = query.filter(or_(ProductoPricing.out_of_cards == False, ProductoPricing.out_of_cards.is_(None)))

    # Filtro de oferta (ofertas vigentes en MercadoLibre)
    if con_oferta is not None:
        from app.models.oferta_ml import OfertaML
        from app.models.publicacion_ml import PublicacionML
        from datetime import date

        hoy_date = date.today()

        items_con_oferta_vigente_subquery = (
            db.query(PublicacionML.item_id)
            .join(OfertaML, PublicacionML.mla == OfertaML.mla)
            .filter(OfertaML.fecha_desde <= hoy_date, OfertaML.fecha_hasta >= hoy_date, OfertaML.pvp_seller.isnot(None))
            .distinct()
            .scalar_subquery()
        )

        if con_oferta:
            query = query.filter(ProductoERP.item_id.in_(items_con_oferta_vigente_subquery))
        else:
            query = query.filter(~ProductoERP.item_id.in_(items_con_oferta_vigente_subquery))

    # Filtro de colores
    if colores:
        colores_list = colores.split(",")

        # Verificar si se está filtrando por "sin color"
        if "sin_color" in colores_list:
            # Remover 'sin_color' de la lista
            colores_con_valor = [c for c in colores_list if c != "sin_color"]

            if colores_con_valor:
                # Si hay otros colores además de sin_color, buscar ambos
                query = query.filter(
                    or_(ProductoPricing.color_marcado.in_(colores_con_valor), ProductoPricing.color_marcado.is_(None))
                )
            else:
                # Solo sin_color: productos sin color asignado
                query = query.filter(ProductoPricing.color_marcado.is_(None))
        else:
            # Filtro normal por colores específicos
            query = query.filter(ProductoPricing.color_marcado.in_(colores_list))

    # Filtro de MLA (con/sin publicación) - usar subconsultas para evitar conflictos de join
    if con_mla is not None:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
        from app.models.item_sin_mla_banlist import ItemSinMLABanlist

        if con_mla:
            # Con MLA: tienen al menos una publicación (sin importar estado)
            items_con_mla_subquery = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                .distinct()
                .subquery()
            )

            query = query.filter(ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)))
        else:
            # Sin MLA: no tienen ninguna publicación (sin importar estado, excluye banlist)
            items_con_mla_subquery = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                .distinct()
                .subquery()
            )

            items_en_banlist_subquery = db.query(ItemSinMLABanlist.item_id).subquery()

            query = query.filter(
                ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
                ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
            )

    # Filtro de estado de publicaciones MLA
    if estado_mla:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

        if estado_mla == "activa":
            # Tienen al menos una publicación activa
            items_activos_subquery = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(
                    MercadoLibreItemPublicado.mlp_id.isnot(None),
                    or_(
                        MercadoLibreItemPublicado.optval_statusId == 2,
                        MercadoLibreItemPublicado.optval_statusId.is_(None),
                    ),
                )
                .distinct()
                .subquery()
            )

            query = query.filter(ProductoERP.item_id.in_(select(items_activos_subquery.c.item_id)))

        elif estado_mla == "pausada":
            # Tienen publicaciones pero ninguna activa
            # 1. Productos que tienen al menos una publicación
            items_con_publis = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                .distinct()
                .subquery()
            )

            # 2. Productos que tienen al menos una publicación activa
            items_activos = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(
                    MercadoLibreItemPublicado.mlp_id.isnot(None),
                    or_(
                        MercadoLibreItemPublicado.optval_statusId == 2,
                        MercadoLibreItemPublicado.optval_statusId.is_(None),
                    ),
                )
                .distinct()
                .subquery()
            )

            # Productos con publicaciones PERO sin ninguna activa
            query = query.filter(
                ProductoERP.item_id.in_(select(items_con_publis.c.item_id)),
                ~ProductoERP.item_id.in_(select(items_activos.c.item_id)),
            )

    # Filtro de productos nuevos (últimos 7 días)
    if nuevos_ultimos_7_dias:
        from datetime import UTC, datetime, timedelta

        fecha_limite = datetime.now(UTC) - timedelta(days=7)
        query = query.filter(ProductoERP.fecha_sync >= fecha_limite)

    # Filtro de Tienda Oficial
    # NOTE: tienda_oficial param is missing from this endpoint's signature.
    # This block is unreachable until the param is added. Suppressed for CI.
    if False:  # noqa: F821 — tienda_oficial param not wired yet
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

        store_id = int(0)
        item_ids_tienda = (
            db.query(MercadoLibreItemPublicado.item_id)
            .filter(MercadoLibreItemPublicado.mlp_official_store_id == store_id)
            .distinct()
        )
        query = query.filter(ProductoERP.item_id.in_(item_ids_tienda))

    # Ordenamiento
    orden_requiere_calculo = False
    if orden_campos and orden_direcciones:
        campos = orden_campos.split(",")
        direcciones = orden_direcciones.split(",")

        for campo, direccion in zip(campos, direcciones):
            # Mapeo de campos del frontend a columnas de la DB
            if campo == "item_id":
                col = ProductoERP.item_id
            elif campo == "codigo":
                col = ProductoERP.codigo
            elif campo == "descripcion":
                col = ProductoERP.descripcion
            elif campo == "marca":
                col = ProductoERP.marca
            elif campo == "moneda_costo":
                col = ProductoERP.moneda_costo
            elif campo == "costo":
                col = ProductoERP.costo
            elif campo == "stock":
                col = ProductoERP.stock
            elif campo == "precio_lista_ml":
                col = ProductoPricing.precio_lista_ml
            elif campo == "markup" or campo == "precio_clasica":
                col = ProductoPricing.markup_calculado
            elif campo == "precio_rebate":
                # Markup rebate requiere cálculo dinámico
                orden_requiere_calculo = True
                continue
            elif campo == "mejor_oferta":
                # Mejor oferta requiere cálculo dinámico
                orden_requiere_calculo = True
                continue
            elif campo == "web_transf":
                col = ProductoPricing.markup_web_real
            else:
                continue

            if direccion == "asc":
                query = query.order_by(col.asc().nullslast())
            else:
                query = query.order_by(col.desc().nullslast())

    # Contar total y paginar
    # Los filtros de markup ahora se aplican en SQL, no necesitamos traer todo
    total_productos = None
    if not orden_requiere_calculo:
        total_productos = query.count()
        offset = (page - 1) * page_size
        results = query.offset(offset).limit(page_size).all()
    else:
        # Solo si hay ordenamiento que requiere cálculo dinámico
        results = query.all()
        len(results)

    from app.models.oferta_ml import OfertaML
    from app.models.publicacion_ml import PublicacionML
    from app.services.pricing_calculator import (
        obtener_tipo_cambio_actual,
        convertir_a_pesos,
        calcular_comision_ml_total,
        calcular_limpio,
        calcular_markup,
        obtener_constantes_pricing,
        GRUPO_DEFAULT,
    )
    from app.models.comision_config import SubcategoriaGrupo
    from app.models.comision_versionada import ComisionVersion, ComisionBase, ComisionAdicionalCuota
    from datetime import date

    hoy = date.today()

    # ── T-3: Prefetch tipo_cambio + constantes ──────────────────────────
    tipo_cambio_usd = obtener_tipo_cambio_actual(db, "USD")
    constantes = obtener_constantes_pricing(db)

    # ── T-4: Prefetch SubcategoriaGrupo mapping ─────────────────────────
    all_subcat_grupos = db.query(SubcategoriaGrupo).all()
    subcat_to_grupo = {sg.subcat_id: sg.grupo_id for sg in all_subcat_grupos}

    # ── T-5: Prefetch comision lookup ───────────────────────────────────
    _pricelist_pvp_to_web = {
        12: 4,
        18: 17,
        19: 14,
        20: 13,
        21: 23,
    }
    _pricelist_to_cuotas = {17: 3, 14: 6, 13: 9, 23: 12}

    _active_version = (
        db.query(ComisionVersion)
        .filter(
            and_(
                ComisionVersion.fecha_desde <= hoy,
                or_(ComisionVersion.fecha_hasta.is_(None), ComisionVersion.fecha_hasta >= hoy),
                ComisionVersion.activo == True,
            )
        )
        .first()
    )
    _comision_base_map: dict = {}
    _comision_adicional_map: dict = {}
    if _active_version:
        for cb in db.query(ComisionBase).filter(ComisionBase.version_id == _active_version.id).all():
            _comision_base_map[(_active_version.id, cb.grupo_id)] = float(cb.comision_base)
        for ca in (
            db.query(ComisionAdicionalCuota).filter(ComisionAdicionalCuota.version_id == _active_version.id).all()
        ):
            _comision_adicional_map[(_active_version.id, ca.cuotas)] = float(ca.adicional)

    def _lookup_comision(pricelist_id: int, grupo_id: int):
        """Pure dict lookup replacement for obtener_comision_base."""
        resolved_pl = _pricelist_pvp_to_web.get(pricelist_id, pricelist_id)
        if not _active_version:
            return None
        base = _comision_base_map.get((_active_version.id, grupo_id))
        if base is None:
            return None
        if resolved_pl == 4:
            return base
        cuotas = _pricelist_to_cuotas.get(resolved_pl)
        if cuotas is None:
            return base
        adicional = _comision_adicional_map.get((_active_version.id, cuotas), 0)
        return base + adicional

    # ── T-6: Prefetch envio_promedio_grupo (single bulk query) ─────────
    from app.models.producto import ProductoERP as _PE_envio

    unique_grupo_ids = set(subcat_to_grupo.values())
    envio_promedio_by_grupo: dict = {gid: 0.0 for gid in unique_grupo_ids}
    # Build reverse map: grupo_id -> [subcat_ids]
    _grupo_to_subcats: dict = {}
    for sc_id, g_id in subcat_to_grupo.items():
        _grupo_to_subcats.setdefault(g_id, []).append(sc_id)
    # All subcat_ids that belong to any grupo
    _all_subcat_ids_envio = list(subcat_to_grupo.keys())
    if _all_subcat_ids_envio:
        _envio_rows = (
            db.query(_PE_envio.subcategoria_id, func.avg(_PE_envio.envio))
            .filter(
                _PE_envio.subcategoria_id.in_(_all_subcat_ids_envio),
                _PE_envio.activo == True,
                _PE_envio.envio > 0,
            )
            .group_by(_PE_envio.subcategoria_id)
            .all()
        )
        # Aggregate per grupo
        _subcat_envio_avg = {sc_id: float(avg_val) for sc_id, avg_val in _envio_rows}
        for gid, sc_list in _grupo_to_subcats.items():
            vals = [_subcat_envio_avg[sc] for sc in sc_list if sc in _subcat_envio_avg]
            if vals:
                envio_promedio_by_grupo[gid] = sum(vals) / len(vals)

    # ── T-7: Batch-load PublicacionML + OfertaML ────────────────────────
    all_item_ids_page = [r[0].item_id for r in results]
    all_pubs = (
        db.query(PublicacionML).filter(PublicacionML.item_id.in_(all_item_ids_page)).all() if all_item_ids_page else []
    )
    pubs_by_item: dict = {}
    all_mla_list: list = []
    for pub in all_pubs:
        pubs_by_item.setdefault(pub.item_id, []).append(pub)
        all_mla_list.append(pub.mla)

    ofertas_by_mla: dict = {}
    if all_mla_list:
        all_ofertas = (
            db.query(OfertaML)
            .filter(
                OfertaML.mla.in_(all_mla_list),
                OfertaML.fecha_desde <= hoy,
                OfertaML.fecha_hasta >= hoy,
                OfertaML.pvp_seller.isnot(None),
            )
            .all()
        )
        for oferta in all_ofertas:
            if oferta.mla not in ofertas_by_mla:
                ofertas_by_mla[oferta.mla] = oferta

    # ── Batch-resolve real shipping costs (one cross-DB query per page) ──────
    envio_real_by_item: dict[int, float] = resolver_costos_envio_batch(db, all_item_ids_page, pubs_by_item=pubs_by_item)

    def _resolve_envio(item_id: int, producto_envio: float, grupo_id: int, precio: float) -> float:
        """Resolve costo_envio: real mlwebhook cost first, then grupo average fallback."""
        # Real cost from mlwebhook DB (already resolved as batch)
        real_cost = envio_real_by_item.get(item_id)
        if real_cost is not None:
            return real_cost
        # ERP + grupo-average fallback (existing logic)
        costo_envio = producto_envio or 0
        montot3 = constantes["monto_tier3"] if constantes else 33000
        if costo_envio == 0 and precio >= montot3 and grupo_id is not None:
            costo_envio = envio_promedio_by_grupo.get(grupo_id, 0.0)
        return costo_envio

    productos = []
    for producto_erp, producto_pricing in results:
        costo_ars = producto_erp.costo if producto_erp.moneda_costo == "ARS" else None
        # Buscar mejor oferta vigente
        mejor_oferta_precio = None
        mejor_oferta_monto = None
        mejor_oferta_pvp = None
        mejor_oferta_markup = None
        mejor_oferta_porcentaje = None
        mejor_oferta_fecha_hasta = None

        # T-7: Use prefetched pubs + ofertas (dict lookup instead of DB queries)
        pubs = pubs_by_item.get(producto_erp.item_id, [])

        mejor_oferta = None
        mejor_pub = None

        for pub in pubs:
            oferta = ofertas_by_mla.get(pub.mla)
            if oferta and not mejor_oferta:
                mejor_oferta = oferta
                mejor_pub = pub

        # T-4: Resolve grupo_id once per product from prefetched map
        grupo_id = subcat_to_grupo.get(producto_erp.subcategoria_id, GRUPO_DEFAULT)

        if mejor_oferta and mejor_pub:
            mejor_oferta_precio = float(mejor_oferta.precio_final) if mejor_oferta.precio_final else None
            mejor_oferta_pvp = float(mejor_oferta.pvp_seller) if mejor_oferta.pvp_seller else None
            mejor_oferta_porcentaje = (
                float(mejor_oferta.aporte_meli_porcentaje) if mejor_oferta.aporte_meli_porcentaje else None
            )
            mejor_oferta_fecha_hasta = mejor_oferta.fecha_hasta

            # Calcular monto rebate
            if mejor_oferta_precio and mejor_oferta_pvp:
                mejor_oferta_monto = mejor_oferta_pvp - mejor_oferta_precio

            # Calcular markup de la oferta
            if mejor_oferta_pvp and mejor_oferta_pvp > 0:
                # T-3: Use prefetched tipo_cambio_usd
                tipo_cambio = tipo_cambio_usd if producto_erp.moneda_costo == "USD" else None

                costo_calc = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)
                # T-5: Use _lookup_comision instead of obtener_comision_base
                comision_base = _lookup_comision(mejor_pub.pricelist_id, grupo_id)

                if comision_base:
                    # T-3: Pass constantes instead of db
                    comisiones = calcular_comision_ml_total(
                        mejor_oferta_pvp, comision_base, producto_erp.iva, constantes=constantes
                    )
                    # T-6/T-12: Resolve envio (real cost first, then grupo fallback)
                    costo_envio = _resolve_envio(
                        producto_erp.item_id, producto_erp.envio or 0, grupo_id, mejor_oferta_pvp
                    )
                    limpio = calcular_limpio(
                        mejor_oferta_pvp,
                        producto_erp.iva,
                        costo_envio,
                        comisiones["comision_total"],
                        constantes=constantes,
                    )
                    mejor_oferta_markup = calcular_markup(limpio, costo_calc)

        # Calcular precio_rebate y markup_rebate
        precio_rebate = None
        markup_rebate = None
        if producto_pricing and producto_pricing.precio_lista_ml and producto_pricing.participa_rebate:
            porcentaje_rebate_val = float(
                producto_pricing.porcentaje_rebate if producto_pricing.porcentaje_rebate is not None else 3.8
            )
            precio_rebate = float(producto_pricing.precio_lista_ml) / (1 - porcentaje_rebate_val / 100)

            # Calcular markup del rebate
            tipo_cambio_rebate = tipo_cambio_usd if producto_erp.moneda_costo == "USD" else None

            costo_rebate = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_rebate)
            comision_base_rebate = _lookup_comision(4, grupo_id)  # Lista clásica

            if comision_base_rebate and precio_rebate > 0:
                comisiones_rebate = calcular_comision_ml_total(
                    precio_rebate, comision_base_rebate, producto_erp.iva, constantes=constantes
                )
                costo_envio_rebate = _resolve_envio(
                    producto_erp.item_id, producto_erp.envio or 0, grupo_id, precio_rebate
                )
                limpio_rebate = calcular_limpio(
                    precio_rebate,
                    producto_erp.iva,
                    costo_envio_rebate,
                    comisiones_rebate["comision_total"],
                    constantes=constantes,
                )
                markup_rebate = calcular_markup(limpio_rebate, costo_rebate) * 100

        # Si el producto tiene rebate y está out_of_cards, replicar el rebate a mejor_oferta
        if (
            producto_pricing
            and producto_pricing.out_of_cards
            and precio_rebate is not None
            and markup_rebate is not None
        ):
            # Replicar datos del rebate a mejor_oferta
            mejor_oferta_precio = precio_rebate
            mejor_oferta_pvp = precio_rebate  # El PVP es el mismo que el precio rebate
            mejor_oferta_markup = markup_rebate / 100  # Convertir de porcentaje a decimal
            mejor_oferta_porcentaje = None  # No hay aporte de Meli en rebate
            mejor_oferta_monto = None  # No hay monto de rebate en este caso
            mejor_oferta_fecha_hasta = None  # No aplica fecha para rebate

        # Calcular markups para precios de cuotas
        markup_3_cuotas = None
        markup_6_cuotas = None
        markup_9_cuotas = None
        markup_12_cuotas = None

        if producto_pricing:
            cuotas_config = [
                (producto_pricing.precio_3_cuotas, 17, "3_cuotas"),
                (producto_pricing.precio_6_cuotas, 14, "6_cuotas"),
                (producto_pricing.precio_9_cuotas, 13, "9_cuotas"),
                (producto_pricing.precio_12_cuotas, 23, "12_cuotas"),
            ]

            tipo_cambio_cuota = tipo_cambio_usd if producto_erp.moneda_costo == "USD" else None
            costo_cuota = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_cuota)

            for precio_cuota, pricelist_id, nombre_cuota in cuotas_config:
                if precio_cuota and float(precio_cuota) > 0:
                    try:
                        comision_base_cuota = _lookup_comision(pricelist_id, grupo_id)

                        if comision_base_cuota:
                            comisiones_cuota = calcular_comision_ml_total(
                                float(precio_cuota), comision_base_cuota, producto_erp.iva, constantes=constantes
                            )
                            costo_envio_cuota = _resolve_envio(
                                producto_erp.item_id, producto_erp.envio or 0, grupo_id, float(precio_cuota)
                            )
                            limpio_cuota = calcular_limpio(
                                float(precio_cuota),
                                producto_erp.iva,
                                costo_envio_cuota,
                                comisiones_cuota["comision_total"],
                                constantes=constantes,
                            )
                            markup_calculado = calcular_markup(limpio_cuota, costo_cuota) * 100

                            if nombre_cuota == "3_cuotas":
                                markup_3_cuotas = markup_calculado
                            elif nombre_cuota == "6_cuotas":
                                markup_6_cuotas = markup_calculado
                            elif nombre_cuota == "9_cuotas":
                                markup_9_cuotas = markup_calculado
                            elif nombre_cuota == "12_cuotas":
                                markup_12_cuotas = markup_calculado
                    except Exception:
                        pass

        # Calcular markups para precios PVP
        markup_pvp = None
        markup_pvp_3_cuotas = None
        markup_pvp_6_cuotas = None
        markup_pvp_9_cuotas = None
        markup_pvp_12_cuotas = None

        if producto_pricing:
            # Markup PVP clásica
            if producto_pricing.precio_pvp and float(producto_pricing.precio_pvp) > 0:
                try:
                    tipo_cambio_pvp = tipo_cambio_usd if producto_erp.moneda_costo == "USD" else None
                    costo_pvp = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_pvp)
                    comision_base_pvp = _lookup_comision(12, grupo_id)

                    if comision_base_pvp:
                        pvp_precio = float(producto_pricing.precio_pvp)
                        comisiones_pvp = calcular_comision_ml_total(
                            pvp_precio, comision_base_pvp, producto_erp.iva, constantes=constantes
                        )
                        costo_envio_pvp = _resolve_envio(
                            producto_erp.item_id, producto_erp.envio or 0, grupo_id, pvp_precio
                        )
                        limpio_pvp = calcular_limpio(
                            pvp_precio,
                            producto_erp.iva,
                            costo_envio_pvp,
                            comisiones_pvp["comision_total"],
                            constantes=constantes,
                        )
                        markup_pvp = round(calcular_markup(limpio_pvp, costo_pvp) * 100, 2)
                except Exception:
                    pass

            # Markups PVP cuotas
            cuotas_pvp_config = [
                (producto_pricing.precio_pvp_3_cuotas, 18, "pvp_3_cuotas"),
                (producto_pricing.precio_pvp_6_cuotas, 19, "pvp_6_cuotas"),
                (producto_pricing.precio_pvp_9_cuotas, 20, "pvp_9_cuotas"),
                (producto_pricing.precio_pvp_12_cuotas, 21, "pvp_12_cuotas"),
            ]

            tipo_cambio_cuota_pvp = tipo_cambio_usd if producto_erp.moneda_costo == "USD" else None
            costo_cuota_pvp = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_cuota_pvp)

            for precio_cuota_pvp, pricelist_id_pvp, nombre_cuota_pvp in cuotas_pvp_config:
                if precio_cuota_pvp and float(precio_cuota_pvp) > 0:
                    try:
                        comision_base_cuota_pvp = _lookup_comision(pricelist_id_pvp, grupo_id)

                        if comision_base_cuota_pvp:
                            pvp_cuota_val = float(precio_cuota_pvp)
                            comisiones_cuota_pvp = calcular_comision_ml_total(
                                pvp_cuota_val, comision_base_cuota_pvp, producto_erp.iva, constantes=constantes
                            )
                            costo_envio_pvp_c = _resolve_envio(
                                producto_erp.item_id, producto_erp.envio or 0, grupo_id, pvp_cuota_val
                            )
                            limpio_cuota_pvp = calcular_limpio(
                                pvp_cuota_val,
                                producto_erp.iva,
                                costo_envio_pvp_c,
                                comisiones_cuota_pvp["comision_total"],
                                constantes=constantes,
                            )
                            markup_calculado_pvp = round(calcular_markup(limpio_cuota_pvp, costo_cuota_pvp) * 100, 2)

                            if nombre_cuota_pvp == "pvp_3_cuotas":
                                markup_pvp_3_cuotas = markup_calculado_pvp
                            elif nombre_cuota_pvp == "pvp_6_cuotas":
                                markup_pvp_6_cuotas = markup_calculado_pvp
                            elif nombre_cuota_pvp == "pvp_9_cuotas":
                                markup_pvp_9_cuotas = markup_calculado_pvp
                            elif nombre_cuota_pvp == "pvp_12_cuotas":
                                markup_pvp_12_cuotas = markup_calculado_pvp
                    except Exception:
                        pass

        producto_obj = ProductoResponse(
            item_id=producto_erp.item_id,
            codigo=producto_erp.codigo,
            descripcion=producto_erp.descripcion,
            marca=producto_erp.marca,
            categoria=producto_erp.categoria,
            subcategoria_id=producto_erp.subcategoria_id,
            moneda_costo=producto_erp.moneda_costo,
            costo=producto_erp.costo,
            costo_ars=costo_ars,
            iva=producto_erp.iva,
            stock=producto_erp.stock,
            precio_lista_ml=producto_pricing.precio_lista_ml if producto_pricing else None,
            markup=producto_pricing.markup_calculado if producto_pricing else None,
            usuario_modifico=None,
            fecha_modificacion=producto_pricing.fecha_modificacion if producto_pricing else None,
            tiene_precio=producto_pricing.precio_lista_ml is not None if producto_pricing else False,
            necesita_revision=False,
            participa_rebate=producto_pricing.participa_rebate if producto_pricing else False,
            porcentaje_rebate=float(producto_pricing.porcentaje_rebate)
            if producto_pricing and producto_pricing.porcentaje_rebate is not None
            else 3.8,
            precio_rebate=precio_rebate,
            markup_rebate=markup_rebate,
            participa_web_transferencia=producto_pricing.participa_web_transferencia if producto_pricing else False,
            porcentaje_markup_web=float(producto_pricing.porcentaje_markup_web)
            if producto_pricing and producto_pricing.porcentaje_markup_web
            else 6.0,
            precio_web_transferencia=float(producto_pricing.precio_web_transferencia)
            if producto_pricing and producto_pricing.precio_web_transferencia
            else None,
            markup_web_real=float(producto_pricing.markup_web_real)
            if producto_pricing and producto_pricing.markup_web_real
            else None,
            preservar_porcentaje_web=producto_pricing.preservar_porcentaje_web if producto_pricing else False,
            mejor_oferta_precio=mejor_oferta_precio,
            mejor_oferta_monto_rebate=mejor_oferta_monto,
            mejor_oferta_pvp_seller=mejor_oferta_pvp,
            mejor_oferta_markup=mejor_oferta_markup,
            mejor_oferta_porcentaje_rebate=mejor_oferta_porcentaje,
            mejor_oferta_fecha_hasta=mejor_oferta_fecha_hasta,
            out_of_cards=producto_pricing.out_of_cards if producto_pricing else False,
            color_marcado=producto_pricing.color_marcado if producto_pricing else None,
            precio_3_cuotas=float(producto_pricing.precio_3_cuotas)
            if producto_pricing and producto_pricing.precio_3_cuotas
            else None,
            precio_6_cuotas=float(producto_pricing.precio_6_cuotas)
            if producto_pricing and producto_pricing.precio_6_cuotas
            else None,
            precio_9_cuotas=float(producto_pricing.precio_9_cuotas)
            if producto_pricing and producto_pricing.precio_9_cuotas
            else None,
            precio_12_cuotas=float(producto_pricing.precio_12_cuotas)
            if producto_pricing and producto_pricing.precio_12_cuotas
            else None,
            markup_3_cuotas=markup_3_cuotas,
            markup_6_cuotas=markup_6_cuotas,
            markup_9_cuotas=markup_9_cuotas,
            markup_12_cuotas=markup_12_cuotas,
            recalcular_cuotas_auto=producto_pricing.recalcular_cuotas_auto if producto_pricing else None,
            markup_adicional_cuotas_custom=float(producto_pricing.markup_adicional_cuotas_custom)
            if producto_pricing and producto_pricing.markup_adicional_cuotas_custom
            else None,
            markup_adicional_cuotas_pvp_custom=float(producto_pricing.markup_adicional_cuotas_pvp_custom)
            if producto_pricing and producto_pricing.markup_adicional_cuotas_pvp_custom
            else None,
            # Campos PVP
            precio_pvp=float(producto_pricing.precio_pvp) if producto_pricing and producto_pricing.precio_pvp else None,
            precio_pvp_3_cuotas=float(producto_pricing.precio_pvp_3_cuotas)
            if producto_pricing and producto_pricing.precio_pvp_3_cuotas
            else None,
            precio_pvp_6_cuotas=float(producto_pricing.precio_pvp_6_cuotas)
            if producto_pricing and producto_pricing.precio_pvp_6_cuotas
            else None,
            precio_pvp_9_cuotas=float(producto_pricing.precio_pvp_9_cuotas)
            if producto_pricing and producto_pricing.precio_pvp_9_cuotas
            else None,
            precio_pvp_12_cuotas=float(producto_pricing.precio_pvp_12_cuotas)
            if producto_pricing and producto_pricing.precio_pvp_12_cuotas
            else None,
            markup_pvp=markup_pvp,
            markup_pvp_3_cuotas=markup_pvp_3_cuotas,
            markup_pvp_6_cuotas=markup_pvp_6_cuotas,
            markup_pvp_9_cuotas=markup_pvp_9_cuotas,
            markup_pvp_12_cuotas=markup_pvp_12_cuotas,
            catalog_status=None,  # Se llenará después
            has_catalog=None,  # Se llenará después
        )

        # Los filtros de markup ahora se aplican en SQL
        # Solo agregamos el producto a la lista
        productos.append(producto_obj)

    # Obtener catalog status de los productos con publicaciones ML
    if productos:
        from sqlalchemy import text

        # Reuse T-7 prefetched pubs_by_item instead of re-querying PublicacionML
        item_to_mlas = {}
        for item_id, pub_list in pubs_by_item.items():
            item_to_mlas[item_id] = [pub.mla for pub in pub_list]

        # Consultar catalog status de estos MLAs
        if all_mla_list:
            catalog_statuses = db.execute(
                text("""
                SELECT mla, catalog_product_id, status, price_to_win, winner_price
                FROM v_ml_catalog_status_latest
                WHERE mla = ANY(:mla_ids)
            """),
                {"mla_ids": all_mla_list},
            ).fetchall()

            # Crear diccionario mla -> datos de catálogo
            mla_to_catalog = {}
            for mla, catalog_id, status, price_to_win, winner_price in catalog_statuses:
                mla_to_catalog[mla] = {
                    "status": status,
                    "price_to_win": float(price_to_win) if price_to_win else None,
                    "winner_price": float(winner_price) if winner_price else None,
                }

            # Asignar status a productos
            for producto in productos:
                if producto.item_id in item_to_mlas:
                    mlas = item_to_mlas[producto.item_id]
                    # Si tiene catálogo, tomar el primer status encontrado
                    for mla in mlas:
                        if mla in mla_to_catalog:
                            catalog_data = mla_to_catalog[mla]
                            producto.catalog_status = catalog_data["status"]
                            producto.catalog_price_to_win = catalog_data["price_to_win"]
                            producto.catalog_winner_price = catalog_data["winner_price"]
                            producto.has_catalog = True
                            break

    # Obtener precios de Tienda Nube
    if productos:
        item_ids = [p.item_id for p in productos]

        tn_precios = db.execute(
            text("""
            SELECT
                item_id,
                price,
                promotional_price,
                CASE WHEN promotional_price IS NOT NULL AND promotional_price > 0 THEN true ELSE false END as has_promotion
            FROM tienda_nube_productos
            WHERE item_id = ANY(:item_ids)
            AND activo = true
        """),
            {"item_ids": item_ids},
        ).fetchall()

        # Crear diccionario item_id -> precios TN
        tn_dict = {}
        for item_id, price, promo_price, has_promo in tn_precios:
            tn_dict[item_id] = {
                "price": float(price) if price else None,
                "promotional_price": float(promo_price) if promo_price else None,
                "has_promotion": has_promo,
            }

        # Asignar precios TN a productos
        for producto in productos:
            if producto.item_id in tn_dict:
                tn_data = tn_dict[producto.item_id]
                producto.tn_price = tn_data["price"]
                producto.tn_promotional_price = tn_data["promotional_price"]
                producto.tn_has_promotion = tn_data["has_promotion"]

    # Obtener precios PVP desde precios_ml
    if productos:
        from app.models.precio_ml import PrecioML

        item_ids = [p.item_id for p in productos]

        # Build producto_erp lookup from original results (avoid per-product DB query)
        erp_by_item_id = {r[0].item_id: r[0] for r in results}

        # Query para obtener precios PVP (listas 12, 18, 19, 20, 21)
        precios_pvp_query = (
            db.query(PrecioML.item_id, PrecioML.pricelist_id, PrecioML.precio)
            .filter(PrecioML.item_id.in_(item_ids), PrecioML.pricelist_id.in_([12, 18, 19, 20, 21]))
            .all()
        )

        # Crear diccionario item_id -> {pricelist_id: precio}
        pvp_dict = {}
        for item_id, pricelist_id, precio in precios_pvp_query:
            if item_id not in pvp_dict:
                pvp_dict[item_id] = {}
            pvp_dict[item_id][pricelist_id] = float(precio) if precio else None

        # Asignar precios PVP y calcular markups (using prefetched data)
        for producto in productos:
            if producto.item_id in pvp_dict:
                precios = pvp_dict[producto.item_id]

                # Asignar precios PVP
                producto.precio_pvp = precios.get(12)
                producto.precio_pvp_3_cuotas = precios.get(18)
                producto.precio_pvp_6_cuotas = precios.get(19)
                producto.precio_pvp_9_cuotas = precios.get(20)
                producto.precio_pvp_12_cuotas = precios.get(21)

                # Use prefetched producto_erp from original results
                producto_erp = erp_by_item_id.get(producto.item_id)

                if producto_erp:
                    # Use prefetched tipo_cambio + grupo + comision
                    tipo_cambio_pvp = tipo_cambio_usd if producto_erp.moneda_costo == "USD" else None
                    costo_pvp = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_pvp)
                    grupo_id_pvp = subcat_to_grupo.get(producto_erp.subcategoria_id, GRUPO_DEFAULT)

                    pvp_configs = [
                        (producto.precio_pvp, 12, "pvp"),
                        (producto.precio_pvp_3_cuotas, 18, "pvp_3_cuotas"),
                        (producto.precio_pvp_6_cuotas, 19, "pvp_6_cuotas"),
                        (producto.precio_pvp_9_cuotas, 20, "pvp_9_cuotas"),
                        (producto.precio_pvp_12_cuotas, 21, "pvp_12_cuotas"),
                    ]

                    for precio_pvp, pricelist_id, nombre_pvp in pvp_configs:
                        if precio_pvp and precio_pvp > 0:
                            try:
                                comision_base_pvp = _lookup_comision(pricelist_id, grupo_id_pvp)

                                if comision_base_pvp:
                                    comisiones_pvp = calcular_comision_ml_total(
                                        precio_pvp, comision_base_pvp, producto_erp.iva, constantes=constantes
                                    )
                                    costo_envio_pvp = _resolve_envio(
                                        producto_erp.item_id, producto_erp.envio or 0, grupo_id_pvp, precio_pvp
                                    )
                                    limpio_pvp = calcular_limpio(
                                        precio_pvp,
                                        producto_erp.iva,
                                        costo_envio_pvp,
                                        comisiones_pvp["comision_total"],
                                        constantes=constantes,
                                    )
                                    markup_calculado = calcular_markup(limpio_pvp, costo_pvp) * 100

                                    if nombre_pvp == "pvp":
                                        producto.markup_pvp = markup_calculado
                                    elif nombre_pvp == "pvp_3_cuotas":
                                        producto.markup_pvp_3_cuotas = markup_calculado
                                    elif nombre_pvp == "pvp_6_cuotas":
                                        producto.markup_pvp_6_cuotas = markup_calculado
                                    elif nombre_pvp == "pvp_9_cuotas":
                                        producto.markup_pvp_9_cuotas = markup_calculado
                                    elif nombre_pvp == "pvp_12_cuotas":
                                        producto.markup_pvp_12_cuotas = markup_calculado
                            except Exception:
                                # Si hay error calculando el markup, simplemente no lo mostramos
                                pass

    # Si aplicamos ordenamiento dinámico, necesitamos paginar manualmente
    if orden_requiere_calculo:
        # Ordenamiento dinámico si es necesario
        if orden_requiere_calculo and orden_campos and orden_direcciones:
            campos = orden_campos.split(",")
            direcciones = orden_direcciones.split(",")

            # Ordenar por cada columna con su dirección (en orden inverso para aplicar prioridad correcta)
            for i in range(len(campos) - 1, -1, -1):
                campo = campos[i]
                direccion = direcciones[i]
                reverse = direccion == "desc"

                if campo in ["precio_rebate", "mejor_oferta", "precio_clasica", "web_transf"]:

                    def get_sort_value(prod, campo=campo):
                        if campo == "precio_rebate":
                            val = prod.markup_rebate
                        elif campo == "mejor_oferta":
                            val = prod.mejor_oferta_markup
                            if val is not None:
                                val = val * 100
                        elif campo == "precio_clasica":
                            val = prod.markup
                        elif campo == "web_transf":
                            val = prod.markup_web_real
                        else:
                            val = None
                        return (val is None, val if val is not None else float("-inf"))

                    productos.sort(key=get_sort_value, reverse=reverse)

        total = len(productos)
        offset = (page - 1) * page_size
        productos = productos[offset : offset + page_size]
    else:
        # Si no hay filtros dinámicos, usar el total pre-calculado
        total = total_productos if total_productos is not None else len(productos)

    return ProductoListResponse(total=total, page=page, page_size=page_size, productos=productos)


@router.get("/productos/precios-listas")
def listar_productos_con_precios_listas(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marca: Optional[str] = None,
    con_stock: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista productos con sus precios en todas las listas de ML"""
    from app.models.precio_ml import PrecioML

    # Query base
    query = db.query(ProductoERP).outerjoin(ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id)

    # Filtros
    if search:
        search_normalized = search.replace("-", "").replace(" ", "").upper()
        query = query.filter(
            or_(
                func.replace(func.replace(func.upper(ProductoERP.descripcion), "-", ""), " ", "").like(
                    f"%{search_normalized}%"
                ),
                func.replace(func.replace(func.upper(ProductoERP.marca), "-", ""), " ", "").like(
                    f"%{search_normalized}%"
                ),
                func.replace(func.upper(ProductoERP.codigo), "-", "").like(f"%{search_normalized}%"),
            )
        )

    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)
    if marca:
        query = query.filter(ProductoERP.marca == marca)
    if con_stock is not None:
        query = query.filter(ProductoERP.stock > 0 if con_stock else ProductoERP.stock == 0)

    total = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    productos = []
    for producto_erp in results:
        # Obtener precios de todas las listas directamente por item_id
        precios_listas = {}

        for pricelist_id in [4, 17, 14, 13, 23]:
            precio_ml = (
                db.query(PrecioML)
                .filter(PrecioML.item_id == producto_erp.item_id, PrecioML.pricelist_id == pricelist_id)
                .first()
            )

            if precio_ml:
                precios_listas[pricelist_id] = {
                    "precio": float(precio_ml.precio) if precio_ml.precio else None,
                    "mla": precio_ml.mla,
                    "cotizacion_dolar": float(precio_ml.cotizacion_dolar) if precio_ml.cotizacion_dolar else None,
                }

        productos.append(
            {
                "item_id": producto_erp.item_id,
                "codigo": producto_erp.codigo,
                "descripcion": producto_erp.descripcion,
                "marca": producto_erp.marca,
                "categoria": producto_erp.categoria,
                "stock": producto_erp.stock,
                "costo": float(producto_erp.costo),
                "moneda_costo": producto_erp.moneda_costo,
                "precios_listas": precios_listas,
            }
        )

    return {"total": total, "page": page, "page_size": page_size, "productos": productos}


# ========== ENDPOINT TIENDA ==========


@router.get("/productos/tienda", response_model=ProductoTiendaListResponse)
def listar_productos_tienda(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    orden_campos: Optional[str] = None,
    orden_direcciones: Optional[str] = None,
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    con_rebate: Optional[bool] = None,
    con_oferta: Optional[bool] = None,
    con_web_transf: Optional[bool] = None,
    tn_con_descuento: Optional[bool] = None,
    tn_sin_descuento: Optional[bool] = None,
    tn_no_publicado: Optional[bool] = None,
    markup_clasica_positivo: Optional[bool] = None,
    markup_rebate_positivo: Optional[bool] = None,
    markup_oferta_positivo: Optional[bool] = None,
    markup_web_transf_positivo: Optional[bool] = None,
    out_of_cards: Optional[bool] = None,
    colores: Optional[str] = None,
    pms: Optional[str] = None,
    con_mla: Optional[bool] = None,
    estado_mla: Optional[str] = None,
    nuevos_ultimos_7_dias: Optional[bool] = None,
    tienda_oficial: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Endpoint específico para la página de Tienda con precio_gremio."""
    from app.models.markup_tienda import MarkupTiendaBrand, MarkupTiendaProducto
    from app.services.pricing_calculator import obtener_constantes_pricing
    from sqlalchemy import text

    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

    # EXCLUIR PRODUCTOS BANEADOS
    from app.models.producto_banlist import ProductoBanlist

    productos_baneados_item_ids = (
        db.query(ProductoBanlist.item_id)
        .filter(ProductoBanlist.activo == True, ProductoBanlist.item_id.isnot(None))
        .all()
    )
    productos_baneados_eans = (
        db.query(ProductoBanlist.ean).filter(ProductoBanlist.activo == True, ProductoBanlist.ean.isnot(None)).all()
    )

    filtros_ban = []
    if productos_baneados_item_ids:
        banned_ids = [pid[0] for pid in productos_baneados_item_ids]
        filtros_ban.append(ProductoERP.item_id.in_(banned_ids))
    if productos_baneados_eans:
        banned_eans = [ean[0] for ean in productos_baneados_eans]
        filtros_ban.append(and_(ProductoERP.ean.in_(banned_eans), ProductoERP.ean.isnot(None), ProductoERP.ean != ""))
    if filtros_ban:
        query = query.filter(~or_(*filtros_ban))

    # FILTRADO POR AUDITORÍA
    if audit_usuarios or audit_tipos_accion or audit_fecha_desde or audit_fecha_hasta:
        from app.models.auditoria import Auditoria
        from datetime import datetime, timedelta, date as date_type

        filtros_audit = [Auditoria.item_id.isnot(None)]

        if audit_usuarios:
            usuarios_ids = [int(u) for u in audit_usuarios.split(",")]
            filtros_audit.append(Auditoria.usuario_id.in_(usuarios_ids))

        if audit_tipos_accion:
            tipos_list = audit_tipos_accion.split(",")
            filtros_audit.append(Auditoria.tipo_accion.in_(tipos_list))

        if audit_fecha_desde:
            try:
                fecha_desde_dt = datetime.strptime(audit_fecha_desde, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    fecha_desde_dt = datetime.strptime(audit_fecha_desde, "%Y-%m-%d %H:%M")
                except ValueError:
                    try:
                        fecha_desde_dt = datetime.strptime(audit_fecha_desde, "%Y-%m-%d")
                    except ValueError:
                        fecha_desde_dt = datetime.combine(date_type.today(), datetime.min.time())
            fecha_desde_dt = fecha_desde_dt + timedelta(hours=3)
            filtros_audit.append(Auditoria.fecha >= fecha_desde_dt)

        if audit_fecha_hasta:
            try:
                fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, "%Y-%m-%d %H:%M")
                except ValueError:
                    try:
                        fecha_hasta_dt = datetime.strptime(audit_fecha_hasta, "%Y-%m-%d")
                        fecha_hasta_dt = fecha_hasta_dt.replace(hour=23, minute=59, second=59)
                    except ValueError:
                        fecha_hasta_dt = datetime.combine(date_type.today(), datetime.max.time())
            fecha_hasta_dt = fecha_hasta_dt + timedelta(hours=3)
            filtros_audit.append(Auditoria.fecha <= fecha_hasta_dt)

        audit_query = db.query(Auditoria.item_id).filter(and_(*filtros_audit))
        item_ids = [item_id for (item_id,) in audit_query.distinct().all()]

        if item_ids:
            query = query.filter(ProductoERP.item_id.in_(item_ids))
        else:
            return ProductoTiendaListResponse(total=0, page=page, page_size=page_size, productos=[])

    # Aplicar filtros
    if search:
        search_normalized = search.replace("-", "").replace(" ", "").upper()
        query = query.filter(
            or_(
                func.replace(func.replace(func.upper(ProductoERP.descripcion), "-", ""), " ", "").like(
                    f"%{search_normalized}%"
                ),
                func.replace(func.replace(func.upper(ProductoERP.marca), "-", ""), " ", "").like(
                    f"%{search_normalized}%"
                ),
                func.replace(func.upper(ProductoERP.codigo), "-", "").like(f"%{search_normalized}%"),
            )
        )
    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)
    if marcas:
        query = query.filter(ProductoERP.marca.in_([m.strip() for m in marcas.split(",")]))
    if subcategorias:
        query = query.filter(ProductoERP.subcategoria_id.in_([int(s.strip()) for s in subcategorias.split(",")]))

    # Filtro por PMs (Product Managers) - filtra por pares (marca, categoria)
    if pms:
        from app.models.marca_pm import MarcaPM

        pm_ids = [int(pm.strip()) for pm in pms.split(",")]
        pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids)).all()

        if pares_pm:
            pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
            query = query.filter(
                tuple_(func.upper(ProductoERP.marca), func.upper(ProductoERP.categoria)).in_(pares_upper)
            )
        else:
            return ProductoTiendaListResponse(total=0, page=page, page_size=page_size, productos=[])

    if con_stock is True:
        query = query.filter(ProductoERP.stock > 0)
    elif con_stock is False:
        query = query.filter(ProductoERP.stock == 0)
    if con_precio is True:
        query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
    elif con_precio is False:
        query = query.filter(or_(ProductoPricing.precio_lista_ml.is_(None), ProductoPricing.item_id.is_(None)))

    # Filtro rebate
    if con_rebate is not None:
        if con_rebate:
            query = query.filter(ProductoPricing.participa_rebate == True)
        else:
            query = query.filter(
                or_(ProductoPricing.participa_rebate == False, ProductoPricing.participa_rebate.is_(None))
            )

    # Filtro web transferencia
    if con_web_transf is not None:
        if con_web_transf:
            query = query.filter(ProductoPricing.participa_web_transferencia == True)
        else:
            query = query.filter(
                or_(
                    ProductoPricing.participa_web_transferencia == False,
                    ProductoPricing.participa_web_transferencia.is_(None),
                )
            )

    # Filtros de Tienda Nube
    if tn_con_descuento or tn_sin_descuento or tn_no_publicado:
        from app.models.tienda_nube_producto import TiendaNubeProducto

        if tn_con_descuento:
            query = query.join(
                TiendaNubeProducto,
                and_(
                    ProductoERP.item_id == TiendaNubeProducto.item_id,
                    TiendaNubeProducto.activo == True,
                    TiendaNubeProducto.promotional_price.isnot(None),
                    TiendaNubeProducto.promotional_price > 0,
                ),
            )
        elif tn_sin_descuento:
            query = query.join(
                TiendaNubeProducto,
                and_(
                    ProductoERP.item_id == TiendaNubeProducto.item_id,
                    TiendaNubeProducto.activo == True,
                    or_(TiendaNubeProducto.promotional_price.is_(None), TiendaNubeProducto.promotional_price == 0),
                ),
            )
        elif tn_no_publicado:
            from sqlalchemy.sql import exists

            subquery = exists().where(
                and_(TiendaNubeProducto.item_id == ProductoERP.item_id, TiendaNubeProducto.activo == True)
            )
            query = query.filter(and_(ProductoERP.stock > 0, ~subquery))

    # Filtros de markup (soportan True=positivo, False=negativo)
    if markup_clasica_positivo is not None:
        if markup_clasica_positivo:
            query = query.filter(ProductoPricing.markup_calculado > 0)
        else:
            query = query.filter(ProductoPricing.markup_calculado < 0)

    if markup_rebate_positivo is not None:
        if markup_rebate_positivo:
            query = query.filter(ProductoPricing.markup_rebate > 0)
        else:
            query = query.filter(ProductoPricing.markup_rebate < 0)

    if markup_oferta_positivo is not None:
        if markup_oferta_positivo:
            query = query.filter(ProductoPricing.markup_oferta > 0)
        else:
            query = query.filter(ProductoPricing.markup_oferta < 0)

    if markup_web_transf_positivo is not None:
        if markup_web_transf_positivo:
            query = query.filter(ProductoPricing.markup_web_real > 0)
        else:
            query = query.filter(ProductoPricing.markup_web_real < 0)

    # Filtro out of cards
    if out_of_cards is not None:
        if out_of_cards:
            query = query.filter(ProductoPricing.out_of_cards == True)
        else:
            query = query.filter(or_(ProductoPricing.out_of_cards == False, ProductoPricing.out_of_cards.is_(None)))

    # Filtro de oferta (ofertas vigentes en MercadoLibre)
    if con_oferta is not None:
        from app.models.oferta_ml import OfertaML
        from app.models.publicacion_ml import PublicacionML

        hoy_date = date.today()

        items_con_oferta_vigente_subquery = (
            db.query(PublicacionML.item_id)
            .join(OfertaML, PublicacionML.mla == OfertaML.mla)
            .filter(OfertaML.fecha_desde <= hoy_date, OfertaML.fecha_hasta >= hoy_date, OfertaML.pvp_seller.isnot(None))
            .distinct()
            .scalar_subquery()
        )

        if con_oferta:
            query = query.filter(ProductoERP.item_id.in_(items_con_oferta_vigente_subquery))
        else:
            query = query.filter(~ProductoERP.item_id.in_(items_con_oferta_vigente_subquery))

    # Filtro de colores (tienda usa color_marcado_tienda)
    if colores:
        colores_list = colores.split(",")

        if "sin_color" in colores_list:
            colores_con_valor = [c for c in colores_list if c != "sin_color"]

            if colores_con_valor:
                query = query.filter(
                    or_(
                        ProductoPricing.color_marcado_tienda.in_(colores_con_valor),
                        ProductoPricing.color_marcado_tienda.is_(None),
                    )
                )
            else:
                query = query.filter(ProductoPricing.color_marcado_tienda.is_(None))
        else:
            query = query.filter(ProductoPricing.color_marcado_tienda.in_(colores_list))

    # Filtro de MLA (con/sin publicación)
    if con_mla is not None:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
        from app.models.item_sin_mla_banlist import ItemSinMLABanlist

        if con_mla:
            items_con_mla_subquery = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                .distinct()
                .subquery()
            )

            query = query.filter(ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)))
        else:
            items_con_mla_subquery = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                .distinct()
                .subquery()
            )

            items_en_banlist_subquery = db.query(ItemSinMLABanlist.item_id).subquery()

            query = query.filter(
                ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
                ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
            )

    # Filtro de estado de publicaciones MLA
    if estado_mla:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

        if estado_mla == "activa":
            items_activos_subquery = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(
                    MercadoLibreItemPublicado.mlp_id.isnot(None),
                    or_(
                        MercadoLibreItemPublicado.optval_statusId == 2,
                        MercadoLibreItemPublicado.optval_statusId.is_(None),
                    ),
                )
                .distinct()
                .subquery()
            )

            query = query.filter(ProductoERP.item_id.in_(select(items_activos_subquery.c.item_id)))

        elif estado_mla == "pausada":
            items_con_publis = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                .distinct()
                .subquery()
            )

            items_activos = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(
                    MercadoLibreItemPublicado.mlp_id.isnot(None),
                    or_(
                        MercadoLibreItemPublicado.optval_statusId == 2,
                        MercadoLibreItemPublicado.optval_statusId.is_(None),
                    ),
                )
                .distinct()
                .subquery()
            )

            query = query.filter(
                ProductoERP.item_id.in_(select(items_con_publis.c.item_id)),
                ~ProductoERP.item_id.in_(select(items_activos.c.item_id)),
            )

    # Filtro de productos nuevos (últimos 7 días)
    if nuevos_ultimos_7_dias:
        fecha_limite = datetime.now(UTC) - timedelta(days=7)
        query = query.filter(ProductoERP.fecha_sync >= fecha_limite)

    total = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    # Obtener constantes de pricing (VARIOS)
    constantes_pricing = obtener_constantes_pricing(db)
    varios_porcentaje = constantes_pricing.get("varios", 6.5)

    # Precargar markups de tienda
    item_ids_results = [r[0].item_id for r in results]
    markups_producto_dict = {}
    markups_sugerido_producto_dict = {}
    if item_ids_results:
        markups_producto = (
            db.query(MarkupTiendaProducto)
            .filter(MarkupTiendaProducto.item_id.in_(item_ids_results), MarkupTiendaProducto.activo == True)
            .all()
        )
        markups_producto_dict = {m.item_id: m.markup_porcentaje for m in markups_producto}
        markups_sugerido_producto_dict = {
            m.item_id: m.markup_sugerido for m in markups_producto if m.markup_sugerido is not None
        }

    marcas_unicas = list(set([r[0].marca for r in results if r[0].marca]))
    markups_marca_dict = {}
    markups_sugerido_marca_dict = {}
    if marcas_unicas:
        brand_query = db.execute(
            text("SELECT brand_desc, brand_id FROM tb_brand WHERE brand_desc = ANY(:marcas)"), {"marcas": marcas_unicas}
        ).fetchall()
        marca_to_brand_id = {row[0]: row[1] for row in brand_query}
        brand_ids = list(marca_to_brand_id.values())
        if brand_ids:
            markups_marca = (
                db.query(MarkupTiendaBrand)
                .filter(MarkupTiendaBrand.brand_id.in_(brand_ids), MarkupTiendaBrand.activo == True)
                .all()
            )
            brand_id_to_markup = {m.brand_id: m.markup_porcentaje for m in markups_marca}
            brand_id_to_sugerido = {
                m.brand_id: m.markup_sugerido for m in markups_marca if m.markup_sugerido is not None
            }
            for marca, brand_id in marca_to_brand_id.items():
                if brand_id in brand_id_to_markup:
                    markups_marca_dict[marca] = brand_id_to_markup[brand_id]
                if brand_id in brand_id_to_sugerido:
                    markups_sugerido_marca_dict[marca] = brand_id_to_sugerido[brand_id]

    # Cargar overrides de precio gremio manual
    from app.models.precio_gremio_override import PrecioGremioOverride

    precio_gremio_overrides = {}
    if item_ids_results:
        overrides = db.query(PrecioGremioOverride).filter(PrecioGremioOverride.item_id.in_(item_ids_results)).all()
        precio_gremio_overrides = {o.item_id: o for o in overrides}

    from app.models.oferta_ml import OfertaML
    from app.models.publicacion_ml import PublicacionML
    from app.services.pricing_calculator import (
        obtener_tipo_cambio_actual,
        convertir_a_pesos,
        calcular_comision_ml_total,
        calcular_limpio,
        calcular_markup,
        GRUPO_DEFAULT,
    )
    from app.models.comision_config import SubcategoriaGrupo
    from app.models.comision_versionada import ComisionVersion, ComisionBase, ComisionAdicionalCuota

    hoy = date.today()
    productos = []

    # ── T-8/T-3: Prefetch tipo_cambio + constantes (reuse constantes_pricing) ──
    tipo_cambio_usd_t = obtener_tipo_cambio_actual(db, "USD")
    constantes_t = constantes_pricing  # Already fetched above

    # ── T-8/T-4: Prefetch SubcategoriaGrupo mapping ─────────────────────
    all_subcat_grupos_t = db.query(SubcategoriaGrupo).all()
    subcat_to_grupo_t = {sg.subcat_id: sg.grupo_id for sg in all_subcat_grupos_t}

    # ── T-8/T-5: Prefetch comision lookup ────────────────────────────────
    _pricelist_pvp_to_web_t = {12: 4, 18: 17, 19: 14, 20: 13, 21: 23}
    _pricelist_to_cuotas_t = {17: 3, 14: 6, 13: 9, 23: 12}

    _active_version_t = (
        db.query(ComisionVersion)
        .filter(
            and_(
                ComisionVersion.fecha_desde <= hoy,
                or_(ComisionVersion.fecha_hasta.is_(None), ComisionVersion.fecha_hasta >= hoy),
                ComisionVersion.activo == True,
            )
        )
        .first()
    )
    _comision_base_map_t: dict = {}
    _comision_adicional_map_t: dict = {}
    if _active_version_t:
        for cb in db.query(ComisionBase).filter(ComisionBase.version_id == _active_version_t.id).all():
            _comision_base_map_t[(_active_version_t.id, cb.grupo_id)] = float(cb.comision_base)
        for ca in (
            db.query(ComisionAdicionalCuota).filter(ComisionAdicionalCuota.version_id == _active_version_t.id).all()
        ):
            _comision_adicional_map_t[(_active_version_t.id, ca.cuotas)] = float(ca.adicional)

    def _lookup_comision_t(pricelist_id: int, grupo_id: int):
        resolved_pl = _pricelist_pvp_to_web_t.get(pricelist_id, pricelist_id)
        if not _active_version_t:
            return None
        base = _comision_base_map_t.get((_active_version_t.id, grupo_id))
        if base is None:
            return None
        if resolved_pl == 4:
            return base
        cuotas = _pricelist_to_cuotas_t.get(resolved_pl)
        if cuotas is None:
            return base
        adicional = _comision_adicional_map_t.get((_active_version_t.id, cuotas), 0)
        return base + adicional

    # ── T-8/T-6: Prefetch envio_promedio_grupo (single bulk query) ──────
    from app.models.producto import ProductoERP as _PE_envio_t

    unique_grupo_ids_t = set(subcat_to_grupo_t.values())
    envio_promedio_by_grupo_t: dict = {gid: 0.0 for gid in unique_grupo_ids_t}
    _grupo_to_subcats_t: dict = {}
    for sc_id, g_id in subcat_to_grupo_t.items():
        _grupo_to_subcats_t.setdefault(g_id, []).append(sc_id)
    _all_subcat_ids_envio_t = list(subcat_to_grupo_t.keys())
    if _all_subcat_ids_envio_t:
        _envio_rows_t = (
            db.query(_PE_envio_t.subcategoria_id, func.avg(_PE_envio_t.envio))
            .filter(
                _PE_envio_t.subcategoria_id.in_(_all_subcat_ids_envio_t),
                _PE_envio_t.activo == True,
                _PE_envio_t.envio > 0,
            )
            .group_by(_PE_envio_t.subcategoria_id)
            .all()
        )
        _subcat_envio_avg_t = {sc_id: float(avg_val) for sc_id, avg_val in _envio_rows_t}
        for gid, sc_list in _grupo_to_subcats_t.items():
            vals = [_subcat_envio_avg_t[sc] for sc in sc_list if sc in _subcat_envio_avg_t]
            if vals:
                envio_promedio_by_grupo_t[gid] = sum(vals) / len(vals)

    # ── T-8/T-7: Batch-load PublicacionML + OfertaML ─────────────────────
    all_pubs_t = (
        db.query(PublicacionML).filter(PublicacionML.item_id.in_(item_ids_results)).all() if item_ids_results else []
    )
    pubs_by_item_t: dict = {}
    all_mla_list_t: list = []
    for pub in all_pubs_t:
        pubs_by_item_t.setdefault(pub.item_id, []).append(pub)
        all_mla_list_t.append(pub.mla)

    ofertas_by_mla_t: dict = {}
    if all_mla_list_t:
        all_ofertas_t = (
            db.query(OfertaML)
            .filter(
                OfertaML.mla.in_(all_mla_list_t),
                OfertaML.fecha_desde <= hoy,
                OfertaML.fecha_hasta >= hoy,
                OfertaML.pvp_seller.isnot(None),
            )
            .all()
        )
        for oferta in all_ofertas_t:
            if oferta.mla not in ofertas_by_mla_t:
                ofertas_by_mla_t[oferta.mla] = oferta

    # ── Batch-resolve real shipping costs (one cross-DB query per page) ──────
    envio_real_by_item_t: dict[int, float] = resolver_costos_envio_batch(
        db, item_ids_results, pubs_by_item=pubs_by_item_t
    )

    def _resolve_envio_t(item_id: int, producto_envio: float, grupo_id: int, precio: float) -> float:
        # Real cost from mlwebhook DB (already resolved as batch)
        real_cost = envio_real_by_item_t.get(item_id)
        if real_cost is not None:
            return real_cost
        # ERP + grupo-average fallback (existing logic)
        costo_envio = producto_envio or 0
        montot3 = constantes_t["monto_tier3"] if constantes_t else 33000
        if costo_envio == 0 and precio >= montot3 and grupo_id is not None:
            costo_envio = envio_promedio_by_grupo_t.get(grupo_id, 0.0)
        return costo_envio

    for producto_erp, producto_pricing in results:
        # Calcular costo en ARS
        costo_ars = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_usd_t)

        # T-4: Resolve grupo_id once per product
        grupo_id = subcat_to_grupo_t.get(producto_erp.subcategoria_id, GRUPO_DEFAULT)

        # Mejor oferta (T-7: dict lookup)
        (
            mejor_oferta_precio,
            mejor_oferta_monto,
            mejor_oferta_pvp,
            mejor_oferta_markup,
            mejor_oferta_porcentaje,
            mejor_oferta_fecha_hasta,
        ) = None, None, None, None, None, None
        pubs = pubs_by_item_t.get(producto_erp.item_id, [])
        mejor_oferta, mejor_pub = None, None
        for pub in pubs:
            oferta = ofertas_by_mla_t.get(pub.mla)
            if oferta and not mejor_oferta:
                mejor_oferta, mejor_pub = oferta, pub
        if mejor_oferta and mejor_pub:
            mejor_oferta_precio = float(mejor_oferta.precio_final) if mejor_oferta.precio_final else None
            mejor_oferta_pvp = float(mejor_oferta.pvp_seller) if mejor_oferta.pvp_seller else None
            mejor_oferta_porcentaje = (
                float(mejor_oferta.aporte_meli_porcentaje) if mejor_oferta.aporte_meli_porcentaje else None
            )
            mejor_oferta_fecha_hasta = mejor_oferta.fecha_hasta
            if mejor_oferta_precio and mejor_oferta_pvp:
                mejor_oferta_monto = mejor_oferta_pvp - mejor_oferta_precio
            if mejor_oferta_pvp and mejor_oferta_pvp > 0:
                tc_oferta = tipo_cambio_usd_t if producto_erp.moneda_costo == "USD" else None
                costo_calc = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tc_oferta)
                comision_base = _lookup_comision_t(mejor_pub.pricelist_id, grupo_id)
                if comision_base:
                    comisiones = calcular_comision_ml_total(
                        mejor_oferta_pvp, comision_base, producto_erp.iva, constantes=constantes_t
                    )
                    costo_envio_of = _resolve_envio_t(
                        producto_erp.item_id, producto_erp.envio or 0, grupo_id, mejor_oferta_pvp
                    )
                    limpio = calcular_limpio(
                        mejor_oferta_pvp,
                        producto_erp.iva,
                        costo_envio_of,
                        comisiones["comision_total"],
                        constantes=constantes_t,
                    )
                    mejor_oferta_markup = calcular_markup(limpio, costo_calc)

        # Rebate
        precio_rebate, markup_rebate = None, None
        if producto_pricing and producto_pricing.precio_lista_ml and producto_pricing.participa_rebate:
            porcentaje_rebate_val = float(
                producto_pricing.porcentaje_rebate if producto_pricing.porcentaje_rebate is not None else 3.8
            )
            precio_rebate = float(producto_pricing.precio_lista_ml) / (1 - porcentaje_rebate_val / 100)
            tc_rebate = tipo_cambio_usd_t if producto_erp.moneda_costo == "USD" else None
            costo_rebate = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tc_rebate)
            comision_base_rebate = _lookup_comision_t(4, grupo_id)
            if comision_base_rebate and precio_rebate > 0:
                comisiones_rebate = calcular_comision_ml_total(
                    precio_rebate, comision_base_rebate, producto_erp.iva, constantes=constantes_t
                )
                costo_envio_reb = _resolve_envio_t(
                    producto_erp.item_id, producto_erp.envio or 0, grupo_id, precio_rebate
                )
                limpio_rebate = calcular_limpio(
                    precio_rebate,
                    producto_erp.iva,
                    costo_envio_reb,
                    comisiones_rebate["comision_total"],
                    constantes=constantes_t,
                )
                markup_rebate = calcular_markup(limpio_rebate, costo_rebate) * 100

        if (
            producto_pricing
            and producto_pricing.out_of_cards
            and precio_rebate is not None
            and markup_rebate is not None
        ):
            mejor_oferta_precio, mejor_oferta_pvp = precio_rebate, precio_rebate
            mejor_oferta_markup = markup_rebate / 100
            mejor_oferta_porcentaje, mejor_oferta_monto, mejor_oferta_fecha_hasta = None, None, None

        # Precio Gremio - Verificar override manual primero
        precio_gremio_sin_iva, precio_gremio_con_iva, markup_gremio = None, None, None
        tiene_override_gremio = False

        # Si existe override manual, usar esos precios
        if producto_erp.item_id in precio_gremio_overrides:
            override = precio_gremio_overrides[producto_erp.item_id]
            precio_gremio_sin_iva = float(override.precio_gremio_sin_iva_manual)
            precio_gremio_con_iva = float(override.precio_gremio_con_iva_manual)
            tiene_override_gremio = True
            # Calcular markup basado en el precio manual
            if costo_ars and costo_ars > 0:
                # Markup = ((Precio / (1 + varios%)) / Costo) - 1
                precio_base = precio_gremio_sin_iva / (1 + varios_porcentaje / 100)
                markup_gremio = ((precio_base / costo_ars) - 1) * 100
        else:
            # Calcular automáticamente según reglas de marca/producto
            if producto_erp.item_id in markups_producto_dict:
                markup_gremio = markups_producto_dict[producto_erp.item_id]
            elif producto_erp.marca and producto_erp.marca in markups_marca_dict:
                markup_gremio = markups_marca_dict[producto_erp.marca]
            if markup_gremio is not None and costo_ars and costo_ars > 0:
                precio_gremio_sin_iva = costo_ars * (1 + varios_porcentaje / 100) * (1 + markup_gremio / 100)
                iva_producto = producto_erp.iva if producto_erp.iva else 21.0
                precio_gremio_con_iva = precio_gremio_sin_iva * (1 + iva_producto / 100)

        # Precio Sugerido — markup_clasica + markup_sugerido aplicado sobre fórmula gremio
        precio_sugerido_sin_iva, precio_sugerido_con_iva = None, None
        markup_sugerido_valor, markup_sugerido_total = None, None

        # Resolver markup_sugerido con prioridad producto > marca (NULL = 0)
        if producto_erp.item_id in markups_sugerido_producto_dict:
            markup_sugerido_valor = markups_sugerido_producto_dict[producto_erp.item_id]
        elif producto_erp.marca and producto_erp.marca in markups_sugerido_marca_dict:
            markup_sugerido_valor = markups_sugerido_marca_dict[producto_erp.marca]

        markup_clasica = producto_pricing.markup_calculado if producto_pricing else None
        if markup_clasica is not None and costo_ars and costo_ars > 0:
            # Si no hay markup_sugerido configurado, usar 0 (precio = solo markup_clasica)
            effective_sugerido = markup_sugerido_valor if markup_sugerido_valor is not None else 0.0
            markup_sugerido_total = markup_clasica + effective_sugerido
            precio_sugerido_sin_iva = costo_ars * (1 + varios_porcentaje / 100) * (1 + markup_sugerido_total / 100)
            iva_producto = producto_erp.iva if producto_erp.iva else 21.0
            precio_sugerido_con_iva = precio_sugerido_sin_iva * (1 + iva_producto / 100)

        # Markups cuotas
        markup_3_cuotas, markup_6_cuotas, markup_9_cuotas, markup_12_cuotas = None, None, None, None
        if producto_pricing:
            tc_cuota = tipo_cambio_usd_t if producto_erp.moneda_costo == "USD" else None
            cc = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tc_cuota)

            for precio_cuota, pricelist_id, nombre in [
                (producto_pricing.precio_3_cuotas, 17, "3"),
                (producto_pricing.precio_6_cuotas, 14, "6"),
                (producto_pricing.precio_9_cuotas, 13, "9"),
                (producto_pricing.precio_12_cuotas, 23, "12"),
            ]:
                if precio_cuota and float(precio_cuota) > 0:
                    try:
                        cb = _lookup_comision_t(pricelist_id, grupo_id)
                        if cb:
                            com = calcular_comision_ml_total(
                                float(precio_cuota), cb, producto_erp.iva, constantes=constantes_t
                            )
                            ce = _resolve_envio_t(
                                producto_erp.item_id, producto_erp.envio or 0, grupo_id, float(precio_cuota)
                            )
                            lim = calcular_limpio(
                                float(precio_cuota),
                                producto_erp.iva,
                                ce,
                                com["comision_total"],
                                constantes=constantes_t,
                            )
                            mc = calcular_markup(lim, cc) * 100
                            if nombre == "3":
                                markup_3_cuotas = mc
                            elif nombre == "6":
                                markup_6_cuotas = mc
                            elif nombre == "9":
                                markup_9_cuotas = mc
                            elif nombre == "12":
                                markup_12_cuotas = mc
                    except Exception:
                        pass

        productos.append(
            ProductoTiendaResponse(
                item_id=producto_erp.item_id,
                codigo=producto_erp.codigo,
                descripcion=producto_erp.descripcion,
                marca=producto_erp.marca,
                categoria=producto_erp.categoria,
                subcategoria_id=producto_erp.subcategoria_id,
                moneda_costo=producto_erp.moneda_costo,
                costo=producto_erp.costo,
                costo_ars=costo_ars,
                iva=producto_erp.iva,
                stock=producto_erp.stock,
                precio_lista_ml=producto_pricing.precio_lista_ml if producto_pricing else None,
                markup=producto_pricing.markup_calculado if producto_pricing else None,
                usuario_modifico=None,
                fecha_modificacion=producto_pricing.fecha_modificacion if producto_pricing else None,
                tiene_precio=producto_pricing.precio_lista_ml is not None if producto_pricing else False,
                necesita_revision=False,
                participa_rebate=producto_pricing.participa_rebate if producto_pricing else False,
                porcentaje_rebate=float(producto_pricing.porcentaje_rebate)
                if producto_pricing and producto_pricing.porcentaje_rebate is not None
                else 3.8,
                precio_rebate=precio_rebate,
                markup_rebate=markup_rebate,
                precio_gremio_sin_iva=precio_gremio_sin_iva,
                precio_gremio_con_iva=precio_gremio_con_iva,
                markup_gremio=markup_gremio,
                tiene_override_gremio=tiene_override_gremio,
                precio_sugerido_sin_iva=precio_sugerido_sin_iva,
                precio_sugerido_con_iva=precio_sugerido_con_iva,
                markup_sugerido_valor=markup_sugerido_valor,
                markup_sugerido_total=markup_sugerido_total,
                participa_web_transferencia=producto_pricing.participa_web_transferencia if producto_pricing else False,
                porcentaje_markup_web=float(producto_pricing.porcentaje_markup_web)
                if producto_pricing and producto_pricing.porcentaje_markup_web
                else 6.0,
                precio_web_transferencia=float(producto_pricing.precio_web_transferencia)
                if producto_pricing and producto_pricing.precio_web_transferencia
                else None,
                markup_web_real=float(producto_pricing.markup_web_real)
                if producto_pricing and producto_pricing.markup_web_real
                else None,
                preservar_porcentaje_web=producto_pricing.preservar_porcentaje_web if producto_pricing else False,
                mejor_oferta_precio=mejor_oferta_precio,
                mejor_oferta_monto_rebate=mejor_oferta_monto,
                mejor_oferta_pvp_seller=mejor_oferta_pvp,
                mejor_oferta_markup=mejor_oferta_markup,
                mejor_oferta_porcentaje_rebate=mejor_oferta_porcentaje,
                mejor_oferta_fecha_hasta=mejor_oferta_fecha_hasta,
                out_of_cards=producto_pricing.out_of_cards if producto_pricing else False,
                color_marcado=producto_pricing.color_marcado if producto_pricing else None,
                color_marcado_tienda=producto_pricing.color_marcado_tienda if producto_pricing else None,
                precio_3_cuotas=float(producto_pricing.precio_3_cuotas)
                if producto_pricing and producto_pricing.precio_3_cuotas
                else None,
                precio_6_cuotas=float(producto_pricing.precio_6_cuotas)
                if producto_pricing and producto_pricing.precio_6_cuotas
                else None,
                precio_9_cuotas=float(producto_pricing.precio_9_cuotas)
                if producto_pricing and producto_pricing.precio_9_cuotas
                else None,
                precio_12_cuotas=float(producto_pricing.precio_12_cuotas)
                if producto_pricing and producto_pricing.precio_12_cuotas
                else None,
                markup_3_cuotas=markup_3_cuotas,
                markup_6_cuotas=markup_6_cuotas,
                markup_9_cuotas=markup_9_cuotas,
                markup_12_cuotas=markup_12_cuotas,
                recalcular_cuotas_auto=producto_pricing.recalcular_cuotas_auto if producto_pricing else None,
                markup_adicional_cuotas_custom=float(producto_pricing.markup_adicional_cuotas_custom)
                if producto_pricing and producto_pricing.markup_adicional_cuotas_custom
                else None,
                markup_adicional_cuotas_pvp_custom=float(producto_pricing.markup_adicional_cuotas_pvp_custom)
                if producto_pricing and producto_pricing.markup_adicional_cuotas_pvp_custom
                else None,
                catalog_status=None,
                has_catalog=None,
            )
        )

    # Catalog status (reuse T-8/T-7 prefetched pubs_by_item_t)
    if productos:
        item_to_mlas = {}
        for item_id, pub_list in pubs_by_item_t.items():
            item_to_mlas[item_id] = [pub.mla for pub in pub_list]

        if all_mla_list_t:
            catalog_statuses = db.execute(
                text(
                    "SELECT mla, catalog_product_id, status, price_to_win, winner_price FROM v_ml_catalog_status_latest WHERE mla = ANY(:mla_ids)"
                ),
                {"mla_ids": all_mla_list_t},
            ).fetchall()
            mla_to_catalog = {
                mla: {
                    "status": status,
                    "price_to_win": float(ptw) if ptw else None,
                    "winner_price": float(wp) if wp else None,
                }
                for mla, _, status, ptw, wp in catalog_statuses
            }
            for producto in productos:
                if producto.item_id in item_to_mlas:
                    for mla in item_to_mlas[producto.item_id]:
                        if mla in mla_to_catalog:
                            producto.catalog_status = mla_to_catalog[mla]["status"]
                            producto.catalog_price_to_win = mla_to_catalog[mla]["price_to_win"]
                            producto.catalog_winner_price = mla_to_catalog[mla]["winner_price"]
                            producto.has_catalog = True
                            break

    # Tienda Nube
    if productos:
        item_ids = [p.item_id for p in productos]
        tn_precios = db.execute(
            text(
                "SELECT item_id, price, promotional_price, CASE WHEN promotional_price IS NOT NULL AND promotional_price > 0 THEN true ELSE false END FROM tienda_nube_productos WHERE item_id = ANY(:item_ids) AND activo = true"
            ),
            {"item_ids": item_ids},
        ).fetchall()
        tn_dict = {
            item_id: {
                "price": float(price) if price else None,
                "promotional_price": float(pp) if pp else None,
                "has_promotion": hp,
            }
            for item_id, price, pp, hp in tn_precios
        }
        for producto in productos:
            if producto.item_id in tn_dict:
                producto.tn_price = tn_dict[producto.item_id]["price"]
                producto.tn_promotional_price = tn_dict[producto.item_id]["promotional_price"]
                producto.tn_has_promotion = tn_dict[producto.item_id]["has_promotion"]

    return ProductoTiendaListResponse(total=total, page=page, page_size=page_size, productos=productos)


@router.get("/productos/{item_id}", response_model=ProductoResponse)
def obtener_producto(item_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = (
        db.query(ProductoERP, ProductoPricing)
        .outerjoin(ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id)
        .filter(ProductoERP.item_id == item_id)
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    producto_erp, producto_pricing = result
    costo_ars = producto_erp.costo if producto_erp.moneda_costo == "ARS" else None

    # Importar funciones de cálculo
    from app.services.pricing_calculator import (
        obtener_tipo_cambio_actual,
        convertir_a_pesos,
        obtener_grupo_subcategoria,
        obtener_comision_base,
        calcular_comision_ml_total,
        calcular_limpio,
        calcular_markup,
    )

    # Resolve shipping cost once via central resolver (mlwebhook first, ERP fallback)
    costo_envio_producto = resolver_costo_envio(db, producto_erp)

    # Calcular markups PVP
    markup_pvp = None
    markup_pvp_3_cuotas = None
    markup_pvp_6_cuotas = None
    markup_pvp_9_cuotas = None
    markup_pvp_12_cuotas = None

    if producto_pricing:
        # Markup PVP clásica
        if producto_pricing.precio_pvp and float(producto_pricing.precio_pvp) > 0:
            try:
                tipo_cambio_pvp = None
                if producto_erp.moneda_costo == "USD":
                    tipo_cambio_pvp = obtener_tipo_cambio_actual(db, "USD")

                costo_pvp = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_pvp)
                grupo_id_pvp = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)
                comision_base_pvp = obtener_comision_base(db, 12, grupo_id_pvp)

                if comision_base_pvp:
                    comisiones_pvp = calcular_comision_ml_total(
                        float(producto_pricing.precio_pvp), comision_base_pvp, producto_erp.iva, db=db
                    )
                    limpio_pvp = calcular_limpio(
                        float(producto_pricing.precio_pvp),
                        producto_erp.iva,
                        costo_envio_producto,
                        comisiones_pvp["comision_total"],
                        db=db,
                        grupo_id=grupo_id_pvp,
                    )
                    markup_pvp = round(calcular_markup(limpio_pvp, costo_pvp) * 100, 2)
            except Exception:
                pass

        # Markups PVP cuotas
        cuotas_pvp_config = [
            (producto_pricing.precio_pvp_3_cuotas, 18, "pvp_3_cuotas"),
            (producto_pricing.precio_pvp_6_cuotas, 19, "pvp_6_cuotas"),
            (producto_pricing.precio_pvp_9_cuotas, 20, "pvp_9_cuotas"),
            (producto_pricing.precio_pvp_12_cuotas, 21, "pvp_12_cuotas"),
        ]

        for precio_cuota_pvp, pricelist_id_pvp, nombre_cuota_pvp in cuotas_pvp_config:
            if precio_cuota_pvp and float(precio_cuota_pvp) > 0:
                try:
                    tipo_cambio_cuota_pvp = None
                    if producto_erp.moneda_costo == "USD":
                        tipo_cambio_cuota_pvp = obtener_tipo_cambio_actual(db, "USD")

                    costo_cuota_pvp = convertir_a_pesos(
                        producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_cuota_pvp
                    )
                    grupo_id_cuota_pvp = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)
                    comision_base_cuota_pvp = obtener_comision_base(db, pricelist_id_pvp, grupo_id_cuota_pvp)

                    if comision_base_cuota_pvp:
                        comisiones_cuota_pvp = calcular_comision_ml_total(
                            float(precio_cuota_pvp), comision_base_cuota_pvp, producto_erp.iva, db=db
                        )
                        limpio_cuota_pvp = calcular_limpio(
                            float(precio_cuota_pvp),
                            producto_erp.iva,
                            costo_envio_producto,
                            comisiones_cuota_pvp["comision_total"],
                            db=db,
                            grupo_id=grupo_id_cuota_pvp,
                        )
                        markup_calculado_pvp = round(calcular_markup(limpio_cuota_pvp, costo_cuota_pvp) * 100, 2)

                        if nombre_cuota_pvp == "pvp_3_cuotas":
                            markup_pvp_3_cuotas = markup_calculado_pvp
                        elif nombre_cuota_pvp == "pvp_6_cuotas":
                            markup_pvp_6_cuotas = markup_calculado_pvp
                        elif nombre_cuota_pvp == "pvp_9_cuotas":
                            markup_pvp_9_cuotas = markup_calculado_pvp
                        elif nombre_cuota_pvp == "pvp_12_cuotas":
                            markup_pvp_12_cuotas = markup_calculado_pvp
                except Exception:
                    pass

    return ProductoResponse(
        item_id=producto_erp.item_id,
        codigo=producto_erp.codigo,
        descripcion=producto_erp.descripcion,
        marca=producto_erp.marca,
        categoria=producto_erp.categoria,
        subcategoria_id=producto_erp.subcategoria_id,
        moneda_costo=producto_erp.moneda_costo,
        costo=producto_erp.costo,
        costo_ars=costo_ars,
        iva=producto_erp.iva,
        stock=producto_erp.stock,
        precio_lista_ml=producto_pricing.precio_lista_ml if producto_pricing else None,
        markup=producto_pricing.markup_calculado if producto_pricing else None,
        usuario_modifico=None,
        fecha_modificacion=producto_pricing.fecha_modificacion if producto_pricing else None,
        tiene_precio=producto_pricing.precio_lista_ml is not None if producto_pricing else False,
        necesita_revision=False,
        participa_rebate=producto_pricing.participa_rebate if producto_pricing else False,
        porcentaje_rebate=float(producto_pricing.porcentaje_rebate)
        if producto_pricing and producto_pricing.porcentaje_rebate is not None
        else 3.8,
        precio_rebate=None,
        markup_rebate=None,
        participa_web_transferencia=producto_pricing.participa_web_transferencia if producto_pricing else False,
        porcentaje_markup_web=float(producto_pricing.porcentaje_markup_web)
        if producto_pricing and producto_pricing.porcentaje_markup_web
        else 6.0,
        precio_web_transferencia=float(producto_pricing.precio_web_transferencia)
        if producto_pricing and producto_pricing.precio_web_transferencia
        else None,
        markup_web_real=float(producto_pricing.markup_web_real)
        if producto_pricing and producto_pricing.markup_web_real
        else None,
        preservar_porcentaje_web=producto_pricing.preservar_porcentaje_web if producto_pricing else False,
        mejor_oferta_precio=None,
        mejor_oferta_monto_rebate=None,
        mejor_oferta_pvp_seller=None,
        mejor_oferta_markup=None,
        mejor_oferta_porcentaje_rebate=None,
        mejor_oferta_fecha_hasta=None,
        out_of_cards=producto_pricing.out_of_cards if producto_pricing else False,
        color_marcado=producto_pricing.color_marcado if producto_pricing else None,
        precio_3_cuotas=float(producto_pricing.precio_3_cuotas)
        if producto_pricing and producto_pricing.precio_3_cuotas
        else None,
        precio_6_cuotas=float(producto_pricing.precio_6_cuotas)
        if producto_pricing and producto_pricing.precio_6_cuotas
        else None,
        precio_9_cuotas=float(producto_pricing.precio_9_cuotas)
        if producto_pricing and producto_pricing.precio_9_cuotas
        else None,
        precio_12_cuotas=float(producto_pricing.precio_12_cuotas)
        if producto_pricing and producto_pricing.precio_12_cuotas
        else None,
        markup_3_cuotas=None,
        markup_6_cuotas=None,
        markup_9_cuotas=None,
        markup_12_cuotas=None,
        recalcular_cuotas_auto=producto_pricing.recalcular_cuotas_auto if producto_pricing else None,
        markup_adicional_cuotas_custom=float(producto_pricing.markup_adicional_cuotas_custom)
        if producto_pricing and producto_pricing.markup_adicional_cuotas_custom
        else None,
        markup_adicional_cuotas_pvp_custom=float(producto_pricing.markup_adicional_cuotas_pvp_custom)
        if producto_pricing and producto_pricing.markup_adicional_cuotas_pvp_custom
        else None,
        # Campos PVP
        precio_pvp=float(producto_pricing.precio_pvp) if producto_pricing and producto_pricing.precio_pvp else None,
        precio_pvp_3_cuotas=float(producto_pricing.precio_pvp_3_cuotas)
        if producto_pricing and producto_pricing.precio_pvp_3_cuotas
        else None,
        precio_pvp_6_cuotas=float(producto_pricing.precio_pvp_6_cuotas)
        if producto_pricing and producto_pricing.precio_pvp_6_cuotas
        else None,
        precio_pvp_9_cuotas=float(producto_pricing.precio_pvp_9_cuotas)
        if producto_pricing and producto_pricing.precio_pvp_9_cuotas
        else None,
        precio_pvp_12_cuotas=float(producto_pricing.precio_pvp_12_cuotas)
        if producto_pricing and producto_pricing.precio_pvp_12_cuotas
        else None,
        markup_pvp=markup_pvp,
        markup_pvp_3_cuotas=markup_pvp_3_cuotas,
        markup_pvp_6_cuotas=markup_pvp_6_cuotas,
        markup_pvp_9_cuotas=markup_pvp_9_cuotas,
        markup_pvp_12_cuotas=markup_pvp_12_cuotas,
        catalog_status=None,
        has_catalog=None,
    )


@router.get("/productos/{item_id}/pricing-stored")
def obtener_precio_stored(
    item_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene el precio_lista_ml almacenado en productos_pricing para un item_id
    """
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    if not pricing:
        raise HTTPException(status_code=404, detail="Precio no encontrado para este producto")

    return {
        "item_id": item_id,
        "precio_lista_ml": float(pricing.precio_lista_ml) if pricing.precio_lista_ml else None,
        "markup_calculado": float(pricing.markup_calculado) if pricing.markup_calculado else None,
    }
