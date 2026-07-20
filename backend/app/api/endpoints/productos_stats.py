from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_, select, tuple_
from typing import Optional
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user
import logging

from app.api.endpoints.productos_shared import (  # noqa: F401
    ProductoResponse,
    ProductoListResponse,
    color_slot,
    filtro_colores,
    join_color_layer,
    resolver_layer_activo,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats")
def obtener_estadisticas(
    # Filtros de búsqueda
    search: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    con_rebate: Optional[bool] = None,
    con_oferta: Optional[bool] = None,
    con_web_transf: Optional[bool] = None,
    markup_clasica_positivo: Optional[bool] = None,
    markup_rebate_positivo: Optional[bool] = None,
    markup_oferta_positivo: Optional[bool] = None,
    markup_web_transf_positivo: Optional[bool] = None,
    out_of_cards: Optional[bool] = None,
    colores: Optional[str] = None,
    product_managers: Optional[str] = None,
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    con_mla: Optional[bool] = None,
    nuevos_ultimos_7_dias: Optional[bool] = None,
    equipo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Obtiene estadísticas de productos según filtros aplicados.
    Si no se aplican filtros, devuelve estadísticas globales.
    """
    from datetime import datetime, timedelta
    from app.models.auditoria_precio import AuditoriaPrecio
    from app.models.item_sin_mla_banlist import ItemSinMLABanlist
    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

    layer_activo = resolver_layer_activo(equipo_id, current_user, db)

    # Query base - seleccionar ambos ProductoERP y ProductoPricing
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )
    query = join_color_layer(query, layer_activo)

    # Aplicar filtros de búsqueda
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                ProductoERP.codigo.ilike(search_pattern),
                ProductoERP.descripcion.ilike(search_pattern),
                ProductoERP.marca.ilike(search_pattern),
            )
        )

    # Filtro de stock
    if con_stock is not None:
        if con_stock:
            query = query.filter(ProductoERP.stock > 0)
        else:
            query = query.filter(ProductoERP.stock == 0)

    # Filtro de precio
    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(or_(ProductoPricing.precio_lista_ml.is_(None), ProductoPricing.id.is_(None)))

    # Filtro de marcas
    if marcas:
        marcas_list = marcas.split(",")
        query = query.filter(ProductoERP.marca.in_(marcas_list))

    # Filtro de subcategorías
    if subcategorias:
        subcategorias_list = [int(s) for s in subcategorias.split(",")]
        query = query.filter(ProductoERP.subcategoria_id.in_(subcategorias_list))

    # Filtro de rebate
    if con_rebate is not None:
        if con_rebate:
            query = query.filter(ProductoPricing.participa_rebate == True, ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(
                or_(ProductoPricing.participa_rebate == False, ProductoPricing.participa_rebate.is_(None))
            )

    # Filtro de mejor oferta
    if con_oferta is not None:
        if con_oferta:
            query = query.filter(ProductoPricing.precio_3_cuotas.isnot(None))
        else:
            query = query.filter(or_(ProductoPricing.precio_3_cuotas.is_(None), ProductoPricing.id.is_(None)))

    # Filtro de web transferencia
    if con_web_transf is not None:
        if con_web_transf:
            query = query.filter(
                ProductoPricing.participa_web_transferencia == True,
                ProductoPricing.precio_web_transferencia.isnot(None),
            )
        else:
            query = query.filter(
                or_(
                    ProductoPricing.participa_web_transferencia == False,
                    ProductoPricing.participa_web_transferencia.is_(None),
                )
            )

    # Filtros de markup
    if markup_clasica_positivo is not None:
        if markup_clasica_positivo:
            query = query.filter(ProductoPricing.markup_calculado > 0)
        else:
            query = query.filter(or_(ProductoPricing.markup_calculado <= 0, ProductoPricing.markup_calculado.is_(None)))

    # Filtro out of cards
    if out_of_cards is not None:
        if out_of_cards:
            query = query.filter(ProductoPricing.out_of_cards == True)
        else:
            query = query.filter(or_(ProductoPricing.out_of_cards == False, ProductoPricing.out_of_cards.is_(None)))

    # Filtro de colores (lee del layer de equipo activo, ver productos_shared)
    query = filtro_colores(query, colores, color_slot(None))

    # Filtro de Product Managers
    if product_managers:
        pm_list = product_managers.split(",")
        from app.models.subcategoria import Subcategoria

        pm_ints = [int(pm) for pm in pm_list]
        query = query.filter(
            ProductoERP.subcategoria_id.in_(db.query(Subcategoria.id).filter(Subcategoria.pm_id.in_(pm_ints)))
        )

    # Filtros de auditoría
    if audit_usuarios or audit_tipos_accion or audit_fecha_desde or audit_fecha_hasta:
        subquery_auditoria = db.query(AuditoriaPrecio.item_id).distinct()

        if audit_usuarios:
            usuarios_list = [int(u) for u in audit_usuarios.split(",")]
            subquery_auditoria = subquery_auditoria.filter(AuditoriaPrecio.usuario_id.in_(usuarios_list))

        if audit_tipos_accion:
            tipos_list = audit_tipos_accion.split(",")
            subquery_auditoria = subquery_auditoria.filter(AuditoriaPrecio.tipo_accion.in_(tipos_list))

        if audit_fecha_desde:
            fecha_desde_dt = datetime.fromisoformat(audit_fecha_desde)
            fecha_desde_dt = fecha_desde_dt + timedelta(hours=3)
            subquery_auditoria = subquery_auditoria.filter(AuditoriaPrecio.fecha_accion >= fecha_desde_dt)

        if audit_fecha_hasta:
            fecha_hasta_dt = datetime.fromisoformat(audit_fecha_hasta)
            fecha_hasta_dt = fecha_hasta_dt + timedelta(hours=3)
            subquery_auditoria = subquery_auditoria.filter(AuditoriaPrecio.fecha_accion <= fecha_hasta_dt)

        query = query.filter(ProductoERP.item_id.in_(subquery_auditoria))

    # Filtro de MLA (con/sin publicación) - usar subconsultas para evitar conflictos de join
    if con_mla is not None:
        if con_mla:
            # Con MLA: tienen publicación activa
            items_con_mla_subquery = (
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

            query = query.filter(ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)))
        else:
            # Sin MLA: no tienen publicación (excluye banlist)
            items_con_mla_subquery = (
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

            items_en_banlist_subquery = db.query(ItemSinMLABanlist.item_id).subquery()

            query = query.filter(
                ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
                ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
            )

    # Filtro de productos nuevos (últimos 7 días)
    if nuevos_ultimos_7_dias:
        from datetime import timezone

        fecha_limite = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.filter(ProductoERP.fecha_sync >= fecha_limite)

    # TODO: tienda_oficial filter — param missing from endpoint signature (dead code)
    # Needs `tienda_oficial: Optional[str] = None` added to function params to activate.

    # ESTADÍSTICAS CALCULADAS
    # Las estadísticas son un desglose de los productos YA filtrados
    # Usar COUNT SQL para mejor rendimiento en lugar de iterar en Python

    from datetime import date, timezone
    from app.models.oferta_ml import OfertaML
    from app.models.publicacion_ml import PublicacionML

    # Total según filtros
    total_filtrado = query.count()

    hoy = date.today()
    fecha_limite_nuevos = datetime.now(timezone.utc) - timedelta(days=7)

    # Subquery para items con MLA
    items_con_mla_subquery = (
        db.query(MercadoLibreItemPublicado.item_id)
        .filter(
            MercadoLibreItemPublicado.mlp_id.isnot(None),
            or_(MercadoLibreItemPublicado.optval_statusId == 2, MercadoLibreItemPublicado.optval_statusId.is_(None)),
        )
        .distinct()
        .subquery()
    )

    # Subquery para items en banlist
    items_en_banlist_subquery = db.query(ItemSinMLABanlist.item_id).subquery()

    # Subquery para items con oferta vigente
    items_con_oferta_subquery = (
        db.query(PublicacionML.item_id)
        .join(OfertaML, PublicacionML.mla == OfertaML.mla)
        .filter(OfertaML.fecha_desde <= hoy, OfertaML.fecha_hasta >= hoy, OfertaML.pvp_seller.isnot(None))
        .distinct()
        .subquery()
    )

    # Con stock
    total_con_stock = query.filter(ProductoERP.stock > 0).count()

    # Con precio
    total_con_precio = query.filter(ProductoPricing.precio_lista_ml.isnot(None)).count()

    # Nuevos (últimos 7 días)
    nuevos = query.filter(ProductoERP.fecha_sync >= fecha_limite_nuevos).count()

    # Nuevos sin precio
    nuevos_sin_precio = query.filter(
        ProductoERP.fecha_sync >= fecha_limite_nuevos,
        or_(ProductoPricing.precio_lista_ml.is_(None), ProductoPricing.item_id.is_(None)),
    ).count()

    # Con stock sin precio
    stock_sin_precio = query.filter(
        ProductoERP.stock > 0, or_(ProductoPricing.precio_lista_ml.is_(None), ProductoPricing.item_id.is_(None))
    ).count()

    # Sin MLA (no en banlist)
    sin_mla_count = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
    ).count()

    # Sin MLA con stock
    sin_mla_con_stock = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
        ProductoERP.stock > 0,
    ).count()

    # Sin MLA sin stock
    sin_mla_sin_stock = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
        ProductoERP.stock == 0,
    ).count()

    # Sin MLA nuevos
    sin_mla_nuevos = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
        ProductoERP.fecha_sync >= fecha_limite_nuevos,
    ).count()

    # Mejor oferta sin rebate
    mejor_oferta_sin_rebate = query.filter(
        ProductoERP.item_id.in_(select(items_con_oferta_subquery.c.item_id)),
        or_(
            ProductoPricing.participa_rebate.is_(False),
            ProductoPricing.participa_rebate.is_(None),
            ProductoPricing.item_id.is_(None),
        ),
    ).count()

    # Markup negativo clásica
    markup_negativo_clasica = query.filter(ProductoPricing.markup_calculado < 0).count()

    # Markup negativo rebate
    markup_negativo_rebate = query.filter(ProductoPricing.markup_rebate < 0).count()

    # Markup negativo oferta
    markup_negativo_oferta = query.filter(ProductoPricing.markup_oferta < 0).count()

    # Markup negativo web
    markup_negativo_web = query.filter(ProductoPricing.markup_web_real < 0).count()

    return {
        "total_productos": total_filtrado,
        "nuevos_ultimos_7_dias": nuevos,
        "nuevos_sin_precio": nuevos_sin_precio,
        "con_stock_sin_precio": stock_sin_precio,
        "sin_mla_no_banlist": sin_mla_count,
        "sin_mla_con_stock": sin_mla_con_stock,
        "sin_mla_sin_stock": sin_mla_sin_stock,
        "sin_mla_nuevos": sin_mla_nuevos,
        "mejor_oferta_sin_rebate": mejor_oferta_sin_rebate,
        "markup_negativo_clasica": markup_negativo_clasica,
        "markup_negativo_rebate": markup_negativo_rebate,
        "markup_negativo_oferta": markup_negativo_oferta,
        "markup_negativo_web": markup_negativo_web,
        "con_stock": total_con_stock,
        "con_precio": total_con_precio,
    }


@router.get("/stats-dinamicos")
def obtener_stats_dinamicos(
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
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
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    equipo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Obtiene estadísticas dinámicas de productos según filtros aplicados.
    Las estadísticas se calculan SOLO sobre los productos que cumplen con los filtros.
    """
    from datetime import datetime, timedelta, date, timezone
    from app.models.oferta_ml import OfertaML
    from app.models.publicacion_ml import PublicacionML
    from app.models.item_sin_mla_banlist import ItemSinMLABanlist
    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

    layer_activo_t = resolver_layer_activo(equipo_id, current_user, db)

    # Query base - igual que en /productos
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )
    query = join_color_layer(query, layer_activo_t)

    # EXCLUIR PRODUCTOS BANEADOS (consistente con /productos)
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
                        fecha_desde_dt = datetime.combine(date.today(), datetime.min.time())
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
                        fecha_hasta_dt = datetime.combine(date.today(), datetime.max.time())
            fecha_hasta_dt = fecha_hasta_dt + timedelta(hours=3)
            filtros_audit.append(Auditoria.fecha <= fecha_hasta_dt)

        audit_query = db.query(Auditoria.item_id).filter(and_(*filtros_audit))
        item_ids = [item_id for (item_id,) in audit_query.distinct().all()]

        if item_ids:
            query = query.filter(ProductoERP.item_id.in_(item_ids))
        else:
            # Sin resultados de auditoría, retornar stats vacíos
            return {
                "total_productos": 0,
                "con_stock": 0,
                "con_precio": 0,
                "con_stock_sin_precio": 0,
                "markup_negativo_clasica": 0,
                "markup_negativo_rebate": 0,
                "markup_negativo_oferta": 0,
                "markup_negativo_web": 0,
                "mejor_oferta_sin_rebate": 0,
                "nuevos_ultimos_7_dias": 0,
                "nuevos_sin_precio": 0,
                "sin_mla_no_banlist": 0,
                "sin_mla_con_stock": 0,
                "sin_mla_sin_stock": 0,
                "sin_mla_nuevos": 0,
            }

    # APLICAR TODOS LOS FILTROS (copiado del endpoint /productos)

    # Filtro de búsqueda
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

    # Filtros básicos
    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)

    if marcas:
        marcas_list = marcas.split(",")
        query = query.filter(ProductoERP.marca.in_(marcas_list))

    if subcategorias:
        subcat_list = [int(s) for s in subcategorias.split(",")]
        query = query.filter(ProductoERP.subcategoria_id.in_(subcat_list))

    if con_stock is not None:
        if con_stock:
            query = query.filter(ProductoERP.stock > 0)
        else:
            query = query.filter(ProductoERP.stock == 0)

    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(or_(ProductoPricing.precio_lista_ml.is_(None), ProductoPricing.item_id.is_(None)))

    # Filtros de participación
    if con_rebate is not None:
        if con_rebate:
            query = query.filter(ProductoPricing.participa_rebate == True)
        else:
            query = query.filter(
                or_(
                    ProductoPricing.participa_rebate == False,
                    ProductoPricing.participa_rebate.is_(None),
                    ProductoPricing.item_id.is_(None),
                )
            )

    if con_web_transf is not None:
        if con_web_transf:
            query = query.filter(ProductoPricing.participa_web_transferencia == True)
        else:
            query = query.filter(
                or_(
                    ProductoPricing.participa_web_transferencia == False,
                    ProductoPricing.participa_web_transferencia.is_(None),
                    ProductoPricing.item_id.is_(None),
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

    # Filtro de oferta
    if con_oferta is not None:
        from datetime import date

        hoy = date.today()

        items_con_oferta_subquery = (
            db.query(PublicacionML.item_id)
            .join(OfertaML, PublicacionML.mla == OfertaML.mla)
            .filter(OfertaML.fecha_desde <= hoy, OfertaML.fecha_hasta >= hoy, OfertaML.pvp_seller.isnot(None))
            .distinct()
            .scalar_subquery()
        )

        if con_oferta:
            query = query.filter(ProductoERP.item_id.in_(items_con_oferta_subquery))
        else:
            query = query.filter(~ProductoERP.item_id.in_(items_con_oferta_subquery))

    # Filtro de colores (vista tienda, lee del layer de equipo activo)
    query = filtro_colores(query, colores, color_slot("tienda"))

    # Filtro de PMs - filtra por pares (marca, categoria)
    if pms:
        from app.models.marca_pm import MarcaPM

        pm_list = pms.split(",")
        pm_ints = [int(pm) for pm in pm_list]
        pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ints)).all()
        if pares_pm:
            pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
            query = query.filter(
                tuple_(func.upper(ProductoERP.marca), func.upper(ProductoERP.categoria)).in_(pares_upper)
            )
        else:
            # Si el PM no tiene marcas asignadas, filtrar para que no devuelva nada
            query = query.filter(ProductoERP.item_id == -1)

    # Filtro de MLA
    if con_mla is not None:
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

            # 3. Filtrar: tienen publicaciones PERO NO tienen activas
            query = query.filter(
                ProductoERP.item_id.in_(select(items_con_publis.c.item_id)),
                ~ProductoERP.item_id.in_(select(items_activos.c.item_id)),
            )

    # Filtro de productos nuevos
    if nuevos_ultimos_7_dias:
        fecha_limite = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.filter(ProductoERP.fecha_sync >= fecha_limite)

    # Filtro de Tienda Oficial
    if tienda_oficial:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

        store_id = int(tienda_oficial)
        item_ids_tienda = (
            db.query(MercadoLibreItemPublicado.item_id)
            .filter(MercadoLibreItemPublicado.mlp_official_store_id == store_id)
            .distinct()
        )
        query = query.filter(ProductoERP.item_id.in_(item_ids_tienda))

    # CALCULAR ESTADÍSTICAS SOBRE PRODUCTOS FILTRADOS

    hoy = date.today()
    fecha_limite_nuevos = datetime.now(timezone.utc) - timedelta(days=7)

    # Subqueries para cálculos
    items_con_mla_subquery = (
        db.query(MercadoLibreItemPublicado.item_id)
        .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
        .distinct()
        .subquery()
    )

    items_en_banlist_subquery = db.query(ItemSinMLABanlist.item_id).subquery()

    items_con_oferta_subquery = (
        db.query(PublicacionML.item_id)
        .join(OfertaML, PublicacionML.mla == OfertaML.mla)
        .filter(OfertaML.fecha_desde <= hoy, OfertaML.fecha_hasta >= hoy, OfertaML.pvp_seller.isnot(None))
        .distinct()
        .subquery()
    )

    # Total según filtros
    total_filtrado = query.count()

    # Estadísticas con COUNT SQL
    total_con_stock = query.filter(ProductoERP.stock > 0).count()
    total_con_precio = query.filter(ProductoPricing.precio_lista_ml.isnot(None)).count()
    nuevos = query.filter(ProductoERP.fecha_sync >= fecha_limite_nuevos).count()

    nuevos_sin_precio = query.filter(
        ProductoERP.fecha_sync >= fecha_limite_nuevos,
        or_(ProductoPricing.precio_lista_ml.is_(None), ProductoPricing.item_id.is_(None)),
    ).count()

    stock_sin_precio = query.filter(
        ProductoERP.stock > 0, or_(ProductoPricing.precio_lista_ml.is_(None), ProductoPricing.item_id.is_(None))
    ).count()

    sin_mla_count = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
    ).count()

    sin_mla_con_stock = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
        ProductoERP.stock > 0,
    ).count()

    sin_mla_sin_stock = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
        ProductoERP.stock == 0,
    ).count()

    sin_mla_nuevos = query.filter(
        ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
        ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
        ProductoERP.fecha_sync >= fecha_limite_nuevos,
    ).count()

    mejor_oferta_sin_rebate = query.filter(
        ProductoERP.item_id.in_(select(items_con_oferta_subquery.c.item_id)),
        or_(
            ProductoPricing.participa_rebate.is_(False),
            ProductoPricing.participa_rebate.is_(None),
            ProductoPricing.item_id.is_(None),
        ),
    ).count()

    markup_negativo_clasica = query.filter(ProductoPricing.markup_calculado < 0).count()
    markup_negativo_rebate = query.filter(ProductoPricing.markup_rebate < 0).count()
    markup_negativo_oferta = query.filter(ProductoPricing.markup_oferta < 0).count()
    markup_negativo_web = query.filter(ProductoPricing.markup_web_real < 0).count()

    return {
        "total_productos": total_filtrado,
        "nuevos_ultimos_7_dias": nuevos,
        "nuevos_sin_precio": nuevos_sin_precio,
        "con_stock_sin_precio": stock_sin_precio,
        "sin_mla_no_banlist": sin_mla_count,
        "sin_mla_con_stock": sin_mla_con_stock,
        "sin_mla_sin_stock": sin_mla_sin_stock,
        "sin_mla_nuevos": sin_mla_nuevos,
        "mejor_oferta_sin_rebate": mejor_oferta_sin_rebate,
        "markup_negativo_clasica": markup_negativo_clasica,
        "markup_negativo_rebate": markup_negativo_rebate,
        "markup_negativo_oferta": markup_negativo_oferta,
        "markup_negativo_web": markup_negativo_web,
        "con_stock": total_con_stock,
        "con_precio": total_con_precio,
    }
