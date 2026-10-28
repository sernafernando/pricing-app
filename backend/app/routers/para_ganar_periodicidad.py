"""PARA GANAR — Periodicidad subscription CRUD (P2) + catalog browse (P3.1/P3.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
from app.models.para_ganar_periodicidad import (
    ParaGanarPeriodicidadEan,
    ParaGanarPeriodicidadEanMla,
)
from app.models.usuario import Usuario
from app.routers.para_ganar import (
    TIPO_PUBLICACION_OPCIONES,
    TIPO_TO_WEB_PRICELIST,
    _build_alcance_where,
    _parse_scope_query,
    _tipo_ids_for_pricelists,
)
from app.services.para_ganar_evaluacion import evaluar_periodicidad
from app.services.para_ganar_periodicidad import normalize_ean, validate_scope_payload
from app.services.para_ganar_periodicidad_descartes import (
    descartar_mlas_nuevos_alcance,
    descartar_mlas_nuevos_ean,
)
from app.services.pricing_calculator import obtener_tipo_cambio_actual

_TIPO_NOMBRE = {tipo_id: nombre for tipo_id, nombre in TIPO_PUBLICACION_OPCIONES}

router = APIRouter(prefix="/para-ganar", tags=["PARA GANAR"])


class PeriodicidadEanResponse(BaseModel):
    ean: str
    enabled: bool
    scope_mode: str
    mlas: List[str] = Field(default_factory=list)
    tipos_publicacion: List[str] = Field(default_factory=list)
    pricelist_ids: List[int] = Field(default_factory=list)
    tienda_oficial_ids: List[int] = Field(default_factory=list)
    updated_at: Optional[datetime] = None
    updated_by_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadEanUpsert(BaseModel):
    enabled: bool = True
    scope_mode: str = "all"
    mlas: List[str] = Field(default_factory=list)
    tipos_publicacion: List[str] = Field(default_factory=list)
    pricelist_ids: List[int] = Field(default_factory=list)
    tienda_oficial_ids: List[int] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadEanListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PeriodicidadEanResponse]

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadCatalogoEanItem(BaseModel):
    ean: str
    marca: Optional[str] = None
    descripcion: Optional[str] = None
    mla_count: int = 0
    suscripto: bool = False
    enabled: Optional[bool] = None
    # True when scope_mode=mlas and ≥1 active in-scope MLA is not in the saved list.
    tiene_mlas_nuevos: bool = False

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadCatalogoEanListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PeriodicidadCatalogoEanItem]

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadCatalogoMlaItem(BaseModel):
    mla: str
    titulo: Optional[str] = None
    lista_nombre: Optional[str] = None
    pricelist_id: Optional[int] = None
    tipo_publicacion: Optional[str] = None
    tipo_nombre: Optional[str] = None
    tienda_oficial_id: Optional[int] = None
    catalog_listing: Optional[bool] = None
    criterios_aplicados: bool = False
    es_nuevo: bool = False

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadCatalogoMlasResponse(BaseModel):
    ean: str
    mlas: List[PeriodicidadCatalogoMlaItem]

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadDescartarNuevosResponse(BaseModel):
    eans_afectados: int = 0
    mlas_descartados: int = 0

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadEvaluarResponse(BaseModel):
    evaluated: int = 0
    pendiente: int = 0
    sin_novedades: int = 0
    skipped: int = 0

    model_config = ConfigDict(from_attributes=True)


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _to_response(row: ParaGanarPeriodicidadEan) -> PeriodicidadEanResponse:
    return PeriodicidadEanResponse(
        ean=row.ean,
        enabled=bool(row.enabled),
        scope_mode=row.scope_mode,
        mlas=sorted(link.mla for link in (row.mlas or [])),
        tipos_publicacion=_as_str_list(row.tipos_publicacion),
        pricelist_ids=_as_int_list(row.pricelist_ids),
        tienda_oficial_ids=_as_int_list(row.tienda_oficial_ids),
        updated_at=row.updated_at,
        updated_by_id=row.updated_by_id,
    )


def _scope_from_query(
    *,
    q: Optional[str],
    marcas: Optional[str],
    subcategorias: Optional[str],
    pms: Optional[str],
    tipos_publicacion: Optional[str],
    pricelists: Optional[str],
    tiendas: Optional[str],
    ean: Optional[str],
    catalog_product_id: Optional[str],
    costo_usd_min: Optional[float],
    costo_usd_max: Optional[float],
    incluir_tradicionales_sincronizadas: bool,
) -> dict:
    return _parse_scope_query(
        q=q,
        marcas=marcas,
        subcategorias=subcategorias,
        pms=pms,
        tipos_publicacion=tipos_publicacion,
        pricelists=pricelists,
        tiendas=tiendas,
        ean=ean,
        catalog_product_id=catalog_product_id,
        costo_usd_min=costo_usd_min,
        costo_usd_max=costo_usd_max,
        incluir_tradicionales_sincronizadas=incluir_tradicionales_sincronizadas,
        criterios_aplicados=None,
    )


def _sql_tiene_mlas_nuevos(*, incluir_tradicionales: bool) -> str:
    """EAN subscribed with scope_mode=mlas and ≥1 active MLA not in the saved list.

    Respects catalog vs traditional-sync the same way as alcance default, but does
    not re-apply marca/tipo/etc. (safeguard is per-EAN publication growth).
    """
    if incluir_tradicionales:
        catalog_clause = """
                  AND EXISTS (
                    SELECT 1 FROM ml_publication_links lx
                    WHERE lx.mla = p_new.mla
                      AND lx.catalog_product_id IS NOT NULL
                  )
        """
    else:
        catalog_clause = """
                  AND EXISTS (
                    SELECT 1 FROM ml_publication_links lx
                    WHERE lx.mla = p_new.mla
                      AND lx.catalog_listing IS TRUE
                  )
        """
    return f"""
              pe.ean IS NOT NULL
              AND pe.scope_mode = 'mlas'
              AND EXISTS (
                SELECT 1
                FROM publicaciones_ml p_new
                JOIN productos_erp e_new ON e_new.item_id = p_new.item_id
                WHERE e_new.codigo = e.codigo
                  AND p_new.activo = true
                  AND NOT EXISTS (
                    SELECT 1 FROM para_ganar_periodicidad_ean_mla pm
                    WHERE pm.ean = pe.ean AND pm.mla = p_new.mla
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM para_ganar_periodicidad_ean_mla_descartado d
                    WHERE d.ean = pe.ean AND d.mla = p_new.mla
                  )
                  {catalog_clause}
              )
    """


@router.get(
    "/periodicidad/catalogo",
    response_model=PeriodicidadCatalogoEanListResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_catalogo_eans_periodicidad(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None, max_length=120),
    marcas: Optional[str] = Query(None),
    subcategorias: Optional[str] = Query(None),
    pms: Optional[str] = Query(None),
    tipos_publicacion: Optional[str] = Query(None),
    pricelists: Optional[str] = Query(None),
    tiendas: Optional[str] = Query(None),
    ean: Optional[str] = Query(None, max_length=80),
    catalog_product_id: Optional[str] = Query(None, max_length=64),
    costo_usd_min: Optional[float] = Query(None, ge=0),
    costo_usd_max: Optional[float] = Query(None, ge=0),
    incluir_tradicionales_sincronizadas: bool = Query(False),
    suscripto: Optional[bool] = Query(
        None,
        description="True = only subscribed EANs; false = only not subscribed; omit = all",
    ),
    criterios_aplicados: Optional[bool] = Query(
        None,
        description=(
            "EAN-level: true = at least one active MLA of the EAN has criterios; "
            "false = no MLA of the EAN has criterios; omit = all"
        ),
    ),
    mlas_nuevos: Optional[bool] = Query(
        None,
        description=(
            "True = only EANs with scope_mode=mlas that have ≥1 active MLA "
            "not in the saved list; false = subscribed mlas without gaps; omit = all"
        ),
    ),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> PeriodicidadCatalogoEanListResponse:
    """EANs present in the filtered publication universe (subscribed or not)."""
    scope = _scope_from_query(
        q=q,
        marcas=marcas,
        subcategorias=subcategorias,
        pms=pms,
        tipos_publicacion=tipos_publicacion,
        pricelists=pricelists,
        tiendas=tiendas,
        ean=ean,
        catalog_product_id=catalog_product_id,
        costo_usd_min=costo_usd_min,
        costo_usd_max=costo_usd_max,
        incluir_tradicionales_sincronizadas=incluir_tradicionales_sincronizadas,
    )
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    tipo_cambio_usd = (
        obtener_tipo_cambio_actual(db, "USD")
        if scope["costo_usd_min"] is not None or scope["costo_usd_max"] is not None
        else None
    )
    # Do not pass MLA-level criterios into alcance — EAN semantics differ (see below).
    where_extra = _build_alcance_where(**scope, params=params, tipo_cambio_usd=tipo_cambio_usd)
    where_extra += " AND e.codigo IS NOT NULL AND TRIM(e.codigo) <> ''"

    if suscripto is True:
        where_extra += " AND pe.ean IS NOT NULL"
    elif suscripto is False:
        where_extra += " AND pe.ean IS NULL"

    # EAN has ≥1 MLA with criterios vs none (not the same as MLA-row filter).
    ean_criterio_exists = """
              EXISTS (
                SELECT 1
                FROM publicaciones_ml p_cg
                JOIN productos_erp e_cg ON e_cg.item_id = p_cg.item_id
                JOIN para_ganar_criterios_mla cg ON cg.mla = p_cg.mla
                WHERE e_cg.codigo = e.codigo AND p_cg.activo = true
              )
    """
    if criterios_aplicados is True:
        where_extra += f" AND {ean_criterio_exists}"
    elif criterios_aplicados is False:
        where_extra += f" AND NOT {ean_criterio_exists}"

    mlas_nuevos_pred = _sql_tiene_mlas_nuevos(incluir_tradicionales=incluir_tradicionales_sincronizadas)
    if mlas_nuevos is True:
        where_extra += f" AND ({mlas_nuevos_pred})"
    elif mlas_nuevos is False:
        where_extra += f" AND pe.ean IS NOT NULL AND pe.scope_mode = 'mlas' AND NOT ({mlas_nuevos_pred})"

    total = db.execute(
        text(
            f"""
            SELECT COUNT(*) FROM (
              SELECT e.codigo
              FROM publicaciones_ml p
              JOIN productos_erp e ON e.item_id = p.item_id
              LEFT JOIN para_ganar_periodicidad_ean pe ON pe.ean = e.codigo
              WHERE p.activo = true
              {where_extra}
              GROUP BY e.codigo
            ) t
            """
        ),
        params,
    ).scalar_one()

    rows = (
        db.execute(
            text(
                f"""
            SELECT
              e.codigo AS ean,
              MAX(e.marca) AS marca,
              MAX(e.descripcion) AS descripcion,
              COUNT(DISTINCT p.mla) AS mla_count,
              CASE WHEN pe.ean IS NOT NULL THEN 1 ELSE 0 END AS suscripto,
              pe.enabled AS enabled,
              CASE WHEN ({mlas_nuevos_pred}) THEN 1 ELSE 0 END AS tiene_mlas_nuevos
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            LEFT JOIN para_ganar_periodicidad_ean pe ON pe.ean = e.codigo
            WHERE p.activo = true
            {where_extra}
            GROUP BY e.codigo, pe.ean, pe.enabled, pe.scope_mode
            ORDER BY
              CASE WHEN ({mlas_nuevos_pred}) THEN 0 ELSE 1 END,
              e.codigo
            LIMIT :limit OFFSET :offset
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    items = [
        PeriodicidadCatalogoEanItem(
            ean=str(row["ean"]),
            marca=row["marca"],
            descripcion=row["descripcion"],
            mla_count=int(row["mla_count"] or 0),
            suscripto=bool(row["suscripto"]),
            enabled=bool(row["enabled"]) if row["enabled"] is not None else None,
            tiene_mlas_nuevos=bool(row["tiene_mlas_nuevos"]),
        )
        for row in rows
    ]
    return PeriodicidadCatalogoEanListResponse(
        total=int(total),
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get(
    "/periodicidad/catalogo/{ean}/mlas",
    response_model=PeriodicidadCatalogoMlasResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_mlas_de_ean_periodicidad(
    ean: str,
    q: Optional[str] = Query(None, max_length=120),
    marcas: Optional[str] = Query(None),
    subcategorias: Optional[str] = Query(None),
    pms: Optional[str] = Query(None),
    tipos_publicacion: Optional[str] = Query(None),
    pricelists: Optional[str] = Query(None),
    tiendas: Optional[str] = Query(None),
    catalog_product_id: Optional[str] = Query(None, max_length=64),
    costo_usd_min: Optional[float] = Query(None, ge=0),
    costo_usd_max: Optional[float] = Query(None, ge=0),
    incluir_tradicionales_sincronizadas: bool = Query(False),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> PeriodicidadCatalogoMlasResponse:
    """MLAs of one EAN inside the current scope filters (for checkbox pickers)."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EAN inválido")

    # Exact EAN match via path; do not also apply substring ean from filters.
    scope = _scope_from_query(
        q=q,
        marcas=marcas,
        subcategorias=subcategorias,
        pms=pms,
        tipos_publicacion=tipos_publicacion,
        pricelists=pricelists,
        tiendas=tiendas,
        ean=None,
        catalog_product_id=catalog_product_id,
        costo_usd_min=costo_usd_min,
        costo_usd_max=costo_usd_max,
        incluir_tradicionales_sincronizadas=incluir_tradicionales_sincronizadas,
    )
    params: dict = {"ean_exact": ean_norm}
    tipo_cambio_usd = (
        obtener_tipo_cambio_actual(db, "USD")
        if scope["costo_usd_min"] is not None or scope["costo_usd_max"] is not None
        else None
    )
    where_extra = _build_alcance_where(**scope, params=params, tipo_cambio_usd=tipo_cambio_usd)
    where_extra += " AND e.codigo = :ean_exact"

    rows = (
        db.execute(
            text(
                f"""
            SELECT
              p.mla,
              p.item_title AS titulo,
              p.lista_nombre,
              p.pricelist_id,
              l.catalog_listing,
              (
                SELECT m.mlp_official_store_id
                FROM tb_mercadolibre_items_publicados m
                WHERE m.mlp_publicationid = p.mla
                  AND m.mlp_official_store_id IS NOT NULL
                LIMIT 1
              ) AS tienda_oficial_id,
              CASE WHEN cg.mla IS NOT NULL THEN 1 ELSE 0 END AS criterios_aplicados,
              CASE
                WHEN pe.scope_mode = 'mlas'
                 AND NOT EXISTS (
                   SELECT 1 FROM para_ganar_periodicidad_ean_mla pm
                   WHERE pm.ean = pe.ean AND pm.mla = p.mla
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM para_ganar_periodicidad_ean_mla_descartado d
                   WHERE d.ean = pe.ean AND d.mla = p.mla
                 )
                THEN 1 ELSE 0
              END AS es_nuevo
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            LEFT JOIN ml_publication_links l ON l.mla = p.mla
            LEFT JOIN para_ganar_criterios_mla cg ON cg.mla = p.mla
            LEFT JOIN para_ganar_periodicidad_ean pe ON pe.ean = e.codigo
            WHERE p.activo = true
            {where_extra}
            ORDER BY
              CASE
                WHEN pe.scope_mode = 'mlas'
                 AND NOT EXISTS (
                   SELECT 1 FROM para_ganar_periodicidad_ean_mla pm
                   WHERE pm.ean = pe.ean AND pm.mla = p.mla
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM para_ganar_periodicidad_ean_mla_descartado d
                   WHERE d.ean = pe.ean AND d.mla = p.mla
                 )
                THEN 0 ELSE 1
              END,
              p.lista_nombre NULLS LAST,
              p.mla
            """
            ),
            params,
        )
        .mappings()
        .all()
    )
    items: list[PeriodicidadCatalogoMlaItem] = []
    for row in rows:
        pricelist_id = int(row["pricelist_id"]) if row["pricelist_id"] is not None else None
        tipo_ids = _tipo_ids_for_pricelists([pricelist_id]) if pricelist_id is not None else []
        tipo_id = tipo_ids[0] if tipo_ids else None
        # Prefer canonical web mapping when tipo_ids empty but id is a known web list.
        if tipo_id is None and pricelist_id is not None:
            for candidate, web_id in TIPO_TO_WEB_PRICELIST.items():
                if web_id == pricelist_id:
                    tipo_id = candidate
                    break
        items.append(
            PeriodicidadCatalogoMlaItem(
                mla=str(row["mla"]),
                titulo=row["titulo"],
                lista_nombre=row["lista_nombre"],
                pricelist_id=pricelist_id,
                tipo_publicacion=tipo_id,
                tipo_nombre=_TIPO_NOMBRE.get(tipo_id) if tipo_id else None,
                tienda_oficial_id=int(row["tienda_oficial_id"]) if row["tienda_oficial_id"] is not None else None,
                catalog_listing=bool(row["catalog_listing"]) if row["catalog_listing"] is not None else None,
                criterios_aplicados=bool(row["criterios_aplicados"]),
                es_nuevo=bool(row["es_nuevo"]),
            )
        )
    return PeriodicidadCatalogoMlasResponse(ean=ean_norm, mlas=items)


@router.post(
    "/periodicidad/catalogo/descartar-mlas-nuevos",
    response_model=PeriodicidadDescartarNuevosResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def descartar_mlas_nuevos_en_alcance(
    q: Optional[str] = Query(None, max_length=120),
    marcas: Optional[str] = Query(None),
    subcategorias: Optional[str] = Query(None),
    pms: Optional[str] = Query(None),
    tipos_publicacion: Optional[str] = Query(None),
    pricelists: Optional[str] = Query(None),
    tiendas: Optional[str] = Query(None),
    ean: Optional[str] = Query(None, max_length=80),
    catalog_product_id: Optional[str] = Query(None, max_length=64),
    costo_usd_min: Optional[float] = Query(None, ge=0),
    costo_usd_max: Optional[float] = Query(None, ge=0),
    incluir_tradicionales_sincronizadas: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PeriodicidadDescartarNuevosResponse:
    """Dismiss new-MLA alerts for every EAN with gaps inside the current alcance filters."""
    scope = _scope_from_query(
        q=q,
        marcas=marcas,
        subcategorias=subcategorias,
        pms=pms,
        tipos_publicacion=tipos_publicacion,
        pricelists=pricelists,
        tiendas=tiendas,
        ean=ean,
        catalog_product_id=catalog_product_id,
        costo_usd_min=costo_usd_min,
        costo_usd_max=costo_usd_max,
        incluir_tradicionales_sincronizadas=incluir_tradicionales_sincronizadas,
    )
    params: dict = {}
    tipo_cambio_usd = (
        obtener_tipo_cambio_actual(db, "USD")
        if scope["costo_usd_min"] is not None or scope["costo_usd_max"] is not None
        else None
    )
    where_extra = _build_alcance_where(**scope, params=params, tipo_cambio_usd=tipo_cambio_usd)
    where_extra += " AND e.codigo IS NOT NULL AND TRIM(e.codigo) <> ''"
    eans_afectados, mlas_descartados = descartar_mlas_nuevos_alcance(
        db,
        where_extra=where_extra,
        params=params,
        user_id=current_user.id,
        incluir_tradicionales=incluir_tradicionales_sincronizadas,
    )
    db.commit()
    return PeriodicidadDescartarNuevosResponse(
        eans_afectados=eans_afectados,
        mlas_descartados=mlas_descartados,
    )


@router.post(
    "/periodicidad/{ean}/descartar-mlas-nuevos",
    response_model=PeriodicidadDescartarNuevosResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def descartar_mlas_nuevos_de_ean(
    ean: str,
    incluir_tradicionales_sincronizadas: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PeriodicidadDescartarNuevosResponse:
    """Acknowledge current new MLAs for one EAN without adding them to the list."""
    try:
        count = descartar_mlas_nuevos_ean(
            db,
            ean=ean,
            user_id=current_user.id,
            incluir_tradicionales=incluir_tradicionales_sincronizadas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    db.commit()
    return PeriodicidadDescartarNuevosResponse(
        eans_afectados=1 if count else 0,
        mlas_descartados=count,
    )


@router.post(
    "/periodicidad/evaluar",
    response_model=PeriodicidadEvaluarResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def evaluar_periodicidad_habilitada(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PeriodicidadEvaluarResponse:
    """P5 Slice A: evaluate enabled Periodicidad MLAs (R1–R3) and persist revision states."""
    counts = evaluar_periodicidad(db, updated_by_id=current_user.id)
    db.commit()
    return PeriodicidadEvaluarResponse(
        evaluated=counts["evaluated"],
        pendiente=counts["pendiente"],
        sin_novedades=counts["sin_novedades"],
        skipped=counts["skipped"],
    )


@router.get(
    "/periodicidad",
    response_model=PeriodicidadEanListResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_periodicidad(
    q: Optional[str] = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> PeriodicidadEanListResponse:
    """Paginated list of EAN periodicidad subscriptions."""
    query = db.query(ParaGanarPeriodicidadEan)
    ean_q = normalize_ean(q or "")
    if ean_q:
        like = f"%{ean_q.lower()}%"
        query = query.filter(func.lower(ParaGanarPeriodicidadEan.ean).like(like))
    total = query.count()
    rows = (
        query.options(joinedload(ParaGanarPeriodicidadEan.mlas))
        .order_by(ParaGanarPeriodicidadEan.ean.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PeriodicidadEanListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_response(row) for row in rows],
    )


@router.get(
    "/periodicidad/{ean}",
    response_model=PeriodicidadEanResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def obtener_periodicidad(
    ean: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> PeriodicidadEanResponse:
    """Return one EAN periodicidad subscription or 404 if not subscribed."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EAN inválido")
    row = (
        db.query(ParaGanarPeriodicidadEan)
        .options(joinedload(ParaGanarPeriodicidadEan.mlas))
        .filter(ParaGanarPeriodicidadEan.ean == ean_norm)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada")
    return _to_response(row)


@router.put(
    "/periodicidad/{ean}",
    response_model=PeriodicidadEanResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def upsert_periodicidad(
    ean: str,
    body: PeriodicidadEanUpsert,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PeriodicidadEanResponse:
    """Create or replace periodicidad subscription for an EAN."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EAN inválido")
    try:
        cleaned = validate_scope_payload(
            scope_mode=body.scope_mode,
            mlas=body.mlas,
            tipos_publicacion=body.tipos_publicacion,
            pricelist_ids=body.pricelist_ids,
            tienda_oficial_ids=body.tienda_oficial_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    row = db.get(ParaGanarPeriodicidadEan, ean_norm)
    if row is None:
        row = ParaGanarPeriodicidadEan(ean=ean_norm)
        db.add(row)

    row.enabled = bool(body.enabled)
    row.scope_mode = cleaned["scope_mode"]
    row.tipos_publicacion = cleaned["tipos_publicacion"]
    row.pricelist_ids = cleaned["pricelist_ids"]
    row.tienda_oficial_ids = cleaned["tienda_oficial_ids"]
    row.updated_by_id = current_user.id
    row.updated_at = datetime.now(UTC)

    # Replace MLA links
    row.mlas.clear()
    for mla in cleaned["mlas"]:
        row.mlas.append(ParaGanarPeriodicidadEanMla(ean=ean_norm, mla=mla))

    db.commit()
    db.refresh(row)
    row = (
        db.query(ParaGanarPeriodicidadEan)
        .options(joinedload(ParaGanarPeriodicidadEan.mlas))
        .filter(ParaGanarPeriodicidadEan.ean == ean_norm)
        .one()
    )
    return _to_response(row)


@router.delete(
    "/periodicidad/{ean}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def borrar_periodicidad(
    ean: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> None:
    """Remove the EAN from periodic review (cascade drops explicit MLA rows)."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EAN inválido")
    row = db.get(ParaGanarPeriodicidadEan, ean_norm)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada")
    db.delete(row)
    db.commit()
    return None
