"""
Productos - Metadata endpoints.

Handles categorias, marcas, subcategorias listing and sync.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_, tuple_
from typing import Optional
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.api.endpoints.productos_shared import (  # noqa: F401
    color_slot,
    filtro_colores,
    join_color_layer,
    resolver_layer_activo,
)

router = APIRouter()


@router.get("/categorias")
def listar_categorias(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    categorias = db.query(ProductoERP.categoria).distinct().order_by(ProductoERP.categoria).all()
    return {"categorias": [c[0] for c in categorias if c[0]]}


@router.get("/marcas")
def listar_marcas(
    search: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
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
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    pms: Optional[str] = None,
    equipo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista marcas disponibles según filtros activos"""
    layer_activo = resolver_layer_activo(equipo_id, current_user, db)

    # Query base igual que en el endpoint de listar productos
    query = (
        db.query(ProductoERP.marca)
        .distinct()
        .join(ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id, isouter=True)
    )
    query = join_color_layer(query, layer_activo)

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

    # Aplicar filtros (reutilizar la lógica del endpoint de listar productos)
    if search:
        query = query.filter(
            or_(
                ProductoERP.codigo.ilike(f"%{search}%"),
                ProductoERP.descripcion.ilike(f"%{search}%"),
                ProductoERP.marca.ilike(f"%{search}%"),
            )
        )

    if con_stock is not None:
        if con_stock:
            query = query.filter(ProductoERP.stock > 0)
        else:
            query = query.filter(ProductoERP.stock == 0)

    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(ProductoPricing.precio_lista_ml.is_(None))

    if subcategorias:
        subcat_list = [int(s.strip()) for s in subcategorias.split(",") if s.strip()]
        query = query.filter(ProductoERP.subcategoria_id.in_(subcat_list))

    if con_rebate is not None:
        query = query.filter(ProductoPricing.participa_rebate == con_rebate)

    if con_web_transf is not None:
        query = query.filter(ProductoPricing.participa_web_transferencia == con_web_transf)

    if out_of_cards is not None:
        if out_of_cards:
            query = query.filter(ProductoPricing.out_of_cards == True)
        else:
            query = query.filter(or_(ProductoPricing.out_of_cards == False, ProductoPricing.out_of_cards.is_(None)))

    # Filtro de colores (lee del layer de equipo activo, ver productos_shared).
    # NOTE: unlike the legacy pre-teams filter here (which had no "sin_color" sentinel),
    # filtro_colores supports it. This is an intentional consistency fix: the sidebar
    # color filter now behaves identically across all listing/metadata endpoints.
    query = filtro_colores(query, colores, color_slot(None))

    if markup_clasica_positivo is not None:
        if markup_clasica_positivo:
            query = query.filter(ProductoPricing.markup_calculado > 0)
        else:
            query = query.filter(ProductoPricing.markup_calculado < 0)

    # Filtro por PMs - filtra por pares (marca, categoria)
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
            return {"marcas": []}

    marcas = query.order_by(ProductoERP.marca).all()
    return {"marcas": [m[0] for m in marcas if m[0]]}


@router.get("/subcategorias")
def listar_subcategorias(
    search: Optional[str] = None,
    con_stock: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    marcas: Optional[str] = None,
    con_rebate: Optional[bool] = None,
    con_oferta: Optional[bool] = None,
    con_web_transf: Optional[bool] = None,
    markup_clasica_positivo: Optional[bool] = None,
    markup_rebate_positivo: Optional[bool] = None,
    markup_oferta_positivo: Optional[bool] = None,
    markup_web_transf_positivo: Optional[bool] = None,
    out_of_cards: Optional[bool] = None,
    colores: Optional[str] = None,
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    pms: Optional[str] = None,
    equipo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista subcategorías disponibles según filtros activos"""
    from app.models.comision_config import SubcategoriaGrupo
    from collections import defaultdict

    layer_activo = resolver_layer_activo(equipo_id, current_user, db)

    # Query para obtener subcategorias_id disponibles según filtros
    query = (
        db.query(ProductoERP.subcategoria_id)
        .distinct()
        .join(ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id, isouter=True)
    )
    query = join_color_layer(query, layer_activo)

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

    # Aplicar filtros
    if search:
        query = query.filter(
            or_(
                ProductoERP.codigo.ilike(f"%{search}%"),
                ProductoERP.descripcion.ilike(f"%{search}%"),
                ProductoERP.marca.ilike(f"%{search}%"),
            )
        )

    if con_stock is not None:
        if con_stock:
            query = query.filter(ProductoERP.stock > 0)
        else:
            query = query.filter(ProductoERP.stock == 0)

    if con_precio is not None:
        if con_precio:
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
        else:
            query = query.filter(ProductoPricing.precio_lista_ml.is_(None))

    if marcas:
        marcas_list = [m.strip() for m in marcas.split(",") if m.strip()]
        query = query.filter(ProductoERP.marca.in_(marcas_list))

    if con_rebate is not None:
        query = query.filter(ProductoPricing.participa_rebate == con_rebate)

    if con_web_transf is not None:
        query = query.filter(ProductoPricing.participa_web_transferencia == con_web_transf)

    if out_of_cards is not None:
        if out_of_cards:
            query = query.filter(ProductoPricing.out_of_cards == True)
        else:
            query = query.filter(or_(ProductoPricing.out_of_cards == False, ProductoPricing.out_of_cards.is_(None)))

    # Filtro de colores (lee del layer de equipo activo, ver productos_shared).
    # NOTE: unlike the legacy pre-teams filter here (which had no "sin_color" sentinel),
    # filtro_colores supports it. This is an intentional consistency fix: the sidebar
    # color filter now behaves identically across all listing/metadata endpoints.
    query = filtro_colores(query, colores, color_slot(None))

    if markup_clasica_positivo is not None:
        if markup_clasica_positivo:
            query = query.filter(ProductoPricing.markup_calculado > 0)
        else:
            query = query.filter(ProductoPricing.markup_calculado < 0)

    # Filtro por PMs - filtra por pares (marca, categoria)
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
            return {"categorias": []}

    # Obtener IDs de subcategorías disponibles
    subcat_ids_disponibles = [s[0] for s in query.all() if s[0]]

    # Obtener todas las subcategorías del mapping
    subcats = (
        db.query(SubcategoriaGrupo)
        .filter(SubcategoriaGrupo.subcat_id.in_(subcat_ids_disponibles))
        .order_by(SubcategoriaGrupo.nombre_categoria, SubcategoriaGrupo.nombre_subcategoria)
        .all()
    )

    # Agrupar por categoría
    agrupadas = defaultdict(list)
    for s in subcats:
        if s.nombre_subcategoria and s.nombre_categoria:
            agrupadas[s.nombre_categoria].append(
                {"id": s.subcat_id, "nombre": s.nombre_subcategoria, "grupo_id": s.grupo_id}
            )

    return {"categorias": [{"nombre": cat, "subcategorias": subs} for cat, subs in sorted(agrupadas.items())]}


@router.post("/sincronizar-subcategorias")
def sincronizar_subcategorias_endpoint(current_user: Usuario = Depends(get_current_user)):
    """Sincroniza subcategorías desde el worker"""
    from app.scripts.sync_subcategorias import sincronizar_subcategorias

    sincronizar_subcategorias()
    return {"mensaje": "Subcategorías sincronizadas"}
