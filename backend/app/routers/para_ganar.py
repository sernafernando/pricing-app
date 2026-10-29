"""PARA GANAR advisor — MLA queue + per-MLA criteria + TOP rank board.

Intent: docs/para-ganar-pro-source-map.md. Unit of work is MLA (sync pairs
surfaced via inventory_id when present). TOP engine: dense rank by price (D12).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.api.endpoints.productos_shared import parsear_tiendas_oficiales_mla
from app.core.database import get_db
from app.models.para_ganar_catalog_seller import (
    DISPOSITION_ACTIVE,
    DISPOSITION_VALUES,
    ParaGanarCatalogSeller,
    is_excluded,
    normalize_disposition,
)
from app.models.para_ganar_criterio_mla import ParaGanarCriterioMla
from app.models.usuario import Usuario
from app.services.ml_catalog_competition_service import refrescar_competencia_catalogo
from app.models.para_ganar_consulta_job import SOURCE_MANUAL
from app.services.para_ganar_consulta import enqueue_consulta
from app.services.para_ganar_evaluacion import evaluar_mlas
from app.services.para_ganar_sugerencia import (
    SugerenciaMla,
    catalog_product_id_for_mla,
    compute_sugerencia_mla,
    mla_exists,
)
from app.services.para_ganar_tipos_publicacion import (
    TIPO_TO_WEB_PRICELIST,
    pricelists_for_tipos,
)
from app.services.pricing_calculator import obtener_tipo_cambio_actual
from app.services.pricing_columns import resolve_pvp_to_web
from app.utils.async_bridge import resolve_maybe_async

router = APIRouter(prefix="/para-ganar", tags=["PARA GANAR"])

# Internal publication types (not ML listing_type_id). Keys are API tokens.
TIPO_PUBLICACION_OPCIONES: list[tuple[str, str]] = [
    ("clasica", "Clásica"),
    ("3", "3 cuotas"),
    ("6", "6 cuotas"),
    ("9", "9 cuotas"),
    ("12", "12 cuotas"),
]


class ParaGanarColaItem(BaseModel):
    mla: str
    item_id: int
    codigo: Optional[str] = None
    titulo: Optional[str] = None
    producto_descripcion: Optional[str] = None
    lista_nombre: Optional[str] = None
    pricelist_id: Optional[int] = None
    precio: Optional[float] = None
    catalog_listing: Optional[bool] = None
    catalog_product_id: Optional[str] = None
    sync_partner_mla: Optional[str] = None
    # True when a row exists in para_ganar_criterios_mla (PM assigned defaults or custom).
    criterios_aplicados: bool = False
    # Advisor work-queue state from para_ganar_revision_mla (P4); null until P5 evaluates.
    revision_estado: Optional[str] = None
    # Legacy placeholder (TOP board uses winning/losing separately).
    suggestion_status: str = "none"

    model_config = ConfigDict(from_attributes=True)


class ParaGanarColaResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ParaGanarColaItem]


class ParaGanarSubcategoriaOpcion(BaseModel):
    id: int
    nombre: str


class ParaGanarPmOpcion(BaseModel):
    id: int
    nombre: str


class ParaGanarTipoPublicacionOpcion(BaseModel):
    id: str
    nombre: str


class ParaGanarListaPrecioOpcion(BaseModel):
    id: int
    nombre: str


class ParaGanarAlcanceOpciones(BaseModel):
    marcas: List[str]
    subcategorias: List[ParaGanarSubcategoriaOpcion]
    pms: List[ParaGanarPmOpcion]
    tipos_publicacion: List[ParaGanarTipoPublicacionOpcion]
    listas_precios: List[ParaGanarListaPrecioOpcion]


def _precio_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)  # type: ignore[arg-type]


def _split_csv(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _pricelists_for_tipos(tipos: list[str]) -> list[int]:
    """Adapter kept for callers inside this module."""
    return pricelists_for_tipos(tipos)


def _parse_int_csv(raw: Optional[str]) -> list[int]:
    values: list[int] = []
    for part in _split_csv(raw):
        try:
            values.append(int(part))
        except ValueError:
            continue
    return values


def _parse_optional_float(raw: Optional[float]) -> Optional[float]:
    if raw is None:
        return None
    return float(raw)


def _parse_scope_query(
    *,
    q: Optional[str] = None,
    marcas: Optional[str] = None,
    subcategorias: Optional[str] = None,
    pms: Optional[str] = None,
    tipos_publicacion: Optional[str] = None,
    pricelists: Optional[str] = None,
    tiendas: Optional[str] = None,
    ean: Optional[str] = None,
    catalog_product_id: Optional[str] = None,
    costo_usd_min: Optional[float] = None,
    costo_usd_max: Optional[float] = None,
    incluir_tradicionales_sincronizadas: bool = False,
    criterios_aplicados: Optional[bool] = None,
) -> dict:
    """Normalize cola/alcance query params into filter lists."""
    parsed_tiendas = parsear_tiendas_oficiales_mla(tiendas)
    tienda_ids: list[int] = []
    incluir_sin_tienda = False
    if parsed_tiendas is not None:
        tienda_ids, incluir_sin_tienda = parsed_tiendas
    min_usd = _parse_optional_float(costo_usd_min)
    max_usd = _parse_optional_float(costo_usd_max)
    if min_usd is not None and max_usd is not None and min_usd > max_usd:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="costo_usd_min no puede ser mayor que costo_usd_max",
        )
    return {
        "q_norm": (q or "").strip(),
        "marcas": _split_csv(marcas),
        "subcategorias": _parse_int_csv(subcategorias),
        "pms": _parse_int_csv(pms),
        "tipos_publicacion": [t.lower() for t in _split_csv(tipos_publicacion) if t.lower() in TIPO_TO_WEB_PRICELIST],
        "pricelist_ids": _parse_int_csv(pricelists),
        "tienda_ids": tienda_ids,
        "incluir_sin_tienda": incluir_sin_tienda,
        "ean_norm": (ean or "").strip(),
        "catalog_product_id_norm": (catalog_product_id or "").strip(),
        "costo_usd_min": min_usd,
        "costo_usd_max": max_usd,
        "incluir_tradicionales_sincronizadas": bool(incluir_tradicionales_sincronizadas),
        "criterios_aplicados": criterios_aplicados,
    }


def _build_alcance_where(
    *,
    q_norm: str,
    marcas: list[str],
    subcategorias: list[int],
    pms: list[int],
    tipos_publicacion: list[str],
    pricelist_ids: list[int],
    tienda_ids: list[int],
    incluir_sin_tienda: bool,
    ean_norm: str,
    catalog_product_id_norm: str,
    costo_usd_min: Optional[float],
    costo_usd_max: Optional[float],
    incluir_tradicionales_sincronizadas: bool = False,
    criterios_aplicados: Optional[bool] = None,
    params: dict,
    skip: Optional[set[str]] = None,
    tipo_cambio_usd: Optional[float] = None,
) -> str:
    """Append scope filters shared by count + page + facet queries. Mutates `params`.

    `skip` omits facets when computing cascading option lists (e.g. skip marcas
    while listing available marcas under the other active filters).
    """
    omit = skip or set()
    clauses: list[str] = []

    # Default: only true catalog listings. Opt-in: also traditional sync partners
    # that share a catalog_product_id (catalog_listing = false).
    if "catalog_mode" not in omit:
        if incluir_tradicionales_sincronizadas:
            clauses.append(
                """
              AND EXISTS (
                SELECT 1 FROM ml_publication_links lx
                WHERE lx.mla = p.mla
                  AND lx.catalog_product_id IS NOT NULL
              )
                """
            )
        else:
            clauses.append(
                """
              AND EXISTS (
                SELECT 1 FROM ml_publication_links lx
                WHERE lx.mla = p.mla
                  AND lx.catalog_listing IS TRUE
              )
                """
            )

    # PM assignment: row in para_ganar_criterios_mla = criteria applied.
    if "criterios_aplicados" not in omit and criterios_aplicados is not None:
        if criterios_aplicados:
            clauses.append(
                """
              AND EXISTS (
                SELECT 1 FROM para_ganar_criterios_mla cg
                WHERE cg.mla = p.mla
              )
                """
            )
        else:
            clauses.append(
                """
              AND NOT EXISTS (
                SELECT 1 FROM para_ganar_criterios_mla cg
                WHERE cg.mla = p.mla
              )
                """
            )

    if q_norm and "q" not in omit:
        # LOWER/LIKE keeps SQLite unit tests and Postgres in sync (no ILIKE).
        params["q"] = f"%{q_norm.lower()}%"
        clauses.append(
            """
          AND (
            LOWER(p.mla) LIKE :q
            OR LOWER(COALESCE(p.codigo, '')) LIKE :q
            OR LOWER(COALESCE(p.item_title, '')) LIKE :q
            OR LOWER(COALESCE(e.descripcion, '')) LIKE :q
            OR LOWER(COALESCE(e.marca, '')) LIKE :q
          )
            """
        )

    if marcas and "marcas" not in omit:
        placeholders = []
        for i, marca in enumerate(marcas):
            key = f"marca_{i}"
            params[key] = marca.upper()
            placeholders.append(f":{key}")
        clauses.append(f" AND UPPER(e.marca) IN ({', '.join(placeholders)})")

    if subcategorias and "subcategorias" not in omit:
        placeholders = []
        for i, subcat_id in enumerate(subcategorias):
            key = f"subcat_{i}"
            params[key] = subcat_id
            placeholders.append(f":{key}")
        clauses.append(f" AND e.subcategoria_id IN ({', '.join(placeholders)})")

    if pms and "pms" not in omit:
        # Same semantics as /productos: marca+categoria pairs from marcas_pm.
        placeholders = []
        for i, pm_id in enumerate(pms):
            key = f"pm_{i}"
            params[key] = pm_id
            placeholders.append(f":{key}")
        clauses.append(
            f"""
          AND EXISTS (
            SELECT 1 FROM marcas_pm mp
            WHERE mp.usuario_id IN ({", ".join(placeholders)})
              AND UPPER(mp.marca) = UPPER(e.marca)
              AND UPPER(mp.categoria) = UPPER(e.categoria)
          )
            """
        )

    apply_tipos = "tipos_publicacion" not in omit
    apply_pricelists = "pricelists" not in omit
    tipos_for_where = tipos_publicacion if apply_tipos else []
    pricelists_for_where = pricelist_ids if apply_pricelists else []

    # Tipo (Clásica / N cuotas) and explicit pricelist intersect when both set.
    tipo_pricelists = _pricelists_for_tipos(tipos_for_where)
    effective_pricelists: list[int]
    if tipo_pricelists and pricelists_for_where:
        tipo_set = set(tipo_pricelists)
        effective_pricelists = [pid for pid in pricelists_for_where if pid in tipo_set]
        if not effective_pricelists:
            clauses.append(" AND 1=0")
            return "".join(clauses)
    elif tipo_pricelists:
        effective_pricelists = tipo_pricelists
    else:
        effective_pricelists = pricelists_for_where

    if effective_pricelists:
        placeholders = []
        for i, pid in enumerate(effective_pricelists):
            key = f"pricelist_{i}"
            params[key] = pid
            placeholders.append(f":{key}")
        clauses.append(f" AND p.pricelist_id IN ({', '.join(placeholders)})")

    if ("tiendas" not in omit) and (tienda_ids or incluir_sin_tienda):
        # Named stores require a publicados row. "Sin tienda" also matches MLAs
        # with no publicados row yet (common in local sandbox).
        parts: list[str] = []
        if tienda_ids:
            placeholders = []
            for i, store_id in enumerate(tienda_ids):
                key = f"tienda_{i}"
                params[key] = store_id
                placeholders.append(f":{key}")
            parts.append(
                f"""
              EXISTS (
                SELECT 1 FROM tb_mercadolibre_items_publicados m
                WHERE m.mlp_publicationid = p.mla
                  AND m.mlp_official_store_id IN ({", ".join(placeholders)})
              )
                """
            )
        if incluir_sin_tienda:
            parts.append(
                """
              NOT EXISTS (
                SELECT 1 FROM tb_mercadolibre_items_publicados m
                WHERE m.mlp_publicationid = p.mla
                  AND m.mlp_official_store_id IS NOT NULL
              )
                """
            )
        clauses.append(f" AND ({' OR '.join(parts)})")

    if ean_norm and "ean" not in omit:
        # Sandbox ERP uses `codigo` as the operator-facing EAN/barcode key
        # (same as Productos `ean:` search → codigo).
        params["ean"] = f"%{ean_norm.lower()}%"
        clauses.append(" AND LOWER(COALESCE(e.codigo, '')) LIKE :ean")

    if catalog_product_id_norm and "catalog_product_id" not in omit:
        params["catalog_product_id"] = catalog_product_id_norm.upper()
        clauses.append(
            """
          AND EXISTS (
            SELECT 1 FROM ml_publication_links l_cat
            WHERE l_cat.mla = p.mla
              AND UPPER(COALESCE(l_cat.catalog_product_id, '')) = :catalog_product_id
          )
            """
        )

    # Cost band in USD (scope, not criteria). ARS rows convert via tipo_cambio
    # venta; without a rate only native-USD costs can match.
    if ("costo_usd" not in omit) and (costo_usd_min is not None or costo_usd_max is not None):
        tc = float(tipo_cambio_usd) if tipo_cambio_usd and float(tipo_cambio_usd) > 0 else 0.0
        params["tc_usd"] = tc
        costo_usd_expr = """
          CASE
            WHEN e.costo IS NULL THEN NULL
            WHEN CAST(e.moneda_costo AS TEXT) = 'USD' THEN e.costo
            WHEN :tc_usd > 0 THEN e.costo / :tc_usd
            ELSE NULL
          END
        """
        clauses.append(f" AND ({costo_usd_expr}) IS NOT NULL")
        if costo_usd_min is not None:
            params["costo_usd_min"] = float(costo_usd_min)
            clauses.append(f" AND ({costo_usd_expr}) >= :costo_usd_min")
        if costo_usd_max is not None:
            params["costo_usd_max"] = float(costo_usd_max)
            clauses.append(f" AND ({costo_usd_expr}) <= :costo_usd_max")

    return "".join(clauses)


def _tipo_ids_for_pricelists(pricelist_ids: list[int]) -> list[str]:
    """Internal tipo tokens present among the given pricelist ids (stable order)."""
    present_web = {resolve_pvp_to_web(pid) for pid in pricelist_ids}
    return [tipo_id for tipo_id, _nombre in TIPO_PUBLICACION_OPCIONES if TIPO_TO_WEB_PRICELIST[tipo_id] in present_web]


@router.get(
    "/alcance-opciones",
    response_model=ParaGanarAlcanceOpciones,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_alcance_opciones(
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
    incluir_tradicionales_sincronizadas: bool = Query(
        False,
        description="When false (default), only catalog_listing publications; when true, also traditional sync partners with a catalog id",
    ),
    criterios_aplicados: Optional[bool] = Query(
        None,
        description="True = only MLAs with saved criteria; false = only without; omit = all",
    ),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarAlcanceOpciones:
    """Facet options for the scope bar, cascading from the other active filters."""
    scope = _parse_scope_query(
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
        criterios_aplicados=criterios_aplicados,
    )
    tipo_cambio_usd = (
        obtener_tipo_cambio_actual(db, "USD")
        if scope["costo_usd_min"] is not None or scope["costo_usd_max"] is not None
        else None
    )

    def where_skip(*facets: str) -> tuple[str, dict]:
        params: dict = {}
        clause = _build_alcance_where(**scope, params=params, skip=set(facets), tipo_cambio_usd=tipo_cambio_usd)
        return clause, params

    marcas_where, marcas_params = where_skip("marcas")
    marcas_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT e.marca
            FROM productos_erp e
            JOIN publicaciones_ml p ON p.item_id = e.item_id AND p.activo = true
            WHERE e.marca IS NOT NULL AND e.marca <> ''
            {marcas_where}
            ORDER BY e.marca
            """
        ),
        marcas_params,
    ).all()

    subcat_where, subcat_params = where_skip("subcategorias")
    subcat_rows = (
        db.execute(
            text(
                f"""
            SELECT DISTINCT e.subcategoria_id AS id,
              COALESCE(sg.nombre_subcategoria, CAST(e.subcategoria_id AS TEXT)) AS nombre
            FROM productos_erp e
            JOIN publicaciones_ml p ON p.item_id = e.item_id AND p.activo = true
            LEFT JOIN subcategorias_grupos sg ON sg.subcat_id = e.subcategoria_id
            WHERE e.subcategoria_id IS NOT NULL
            {subcat_where}
            ORDER BY nombre
            """
            ),
            subcat_params,
        )
        .mappings()
        .all()
    )

    pm_where, pm_params = where_skip("pms")
    pm_rows = (
        db.execute(
            text(
                f"""
            SELECT DISTINCT u.id, COALESCE(u.nombre, u.username) AS nombre
            FROM usuarios u
            JOIN marcas_pm mp ON mp.usuario_id = u.id
            WHERE u.activo = true
              AND EXISTS (
                SELECT 1
                FROM productos_erp e
                JOIN publicaciones_ml p ON p.item_id = e.item_id AND p.activo = true
                WHERE UPPER(mp.marca) = UPPER(e.marca)
                  AND UPPER(mp.categoria) = UPPER(e.categoria)
                  {pm_where}
              )
            ORDER BY nombre
            """
            ),
            pm_params,
        )
        .mappings()
        .all()
    )

    # Lista options respect selected tipo (and other facets); skip only self.
    lista_where, lista_params = where_skip("pricelists")
    lista_rows = (
        db.execute(
            text(
                f"""
            SELECT DISTINCT p.pricelist_id AS id,
              COALESCE(NULLIF(p.lista_nombre, ''), CAST(p.pricelist_id AS TEXT)) AS nombre
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            WHERE p.activo = true AND p.pricelist_id IS NOT NULL
            {lista_where}
            ORDER BY nombre
            """
            ),
            lista_params,
        )
        .mappings()
        .all()
    )

    # Tipo options respect selected listas (and other facets); skip only self.
    tipo_where, tipo_params = where_skip("tipos_publicacion")
    tipo_pricelist_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT p.pricelist_id
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            WHERE p.activo = true AND p.pricelist_id IS NOT NULL
            {tipo_where}
            """
        ),
        tipo_params,
    ).all()
    tipo_ids = set(_tipo_ids_for_pricelists([int(row[0]) for row in tipo_pricelist_rows]))

    return ParaGanarAlcanceOpciones(
        marcas=[row[0] for row in marcas_rows],
        subcategorias=[
            ParaGanarSubcategoriaOpcion(id=int(row["id"]), nombre=str(row["nombre"])) for row in subcat_rows
        ],
        pms=[ParaGanarPmOpcion(id=int(row["id"]), nombre=str(row["nombre"])) for row in pm_rows],
        tipos_publicacion=[
            ParaGanarTipoPublicacionOpcion(id=tipo_id, nombre=nombre)
            for tipo_id, nombre in TIPO_PUBLICACION_OPCIONES
            if tipo_id in tipo_ids
        ],
        listas_precios=[ParaGanarListaPrecioOpcion(id=int(row["id"]), nombre=str(row["nombre"])) for row in lista_rows],
    )


@router.get(
    "/cola",
    response_model=ParaGanarColaResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_cola(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None, max_length=120, description="Filter by MLA, codigo, title or marca"),
    marcas: Optional[str] = Query(None, description="Comma-separated brand names"),
    subcategorias: Optional[str] = Query(None, description="Comma-separated subcategory ids"),
    pms: Optional[str] = Query(None, description="Comma-separated PM user ids"),
    tipos_publicacion: Optional[str] = Query(None, description="Comma-separated internal types: clasica,3,6,9,12"),
    pricelists: Optional[str] = Query(None, description="Comma-separated pricelist ids"),
    tiendas: Optional[str] = Query(None, description="Comma-separated official store ids and/or sin_tienda"),
    ean: Optional[str] = Query(None, max_length=80, description="ERP codigo / EAN substring"),
    catalog_product_id: Optional[str] = Query(
        None, max_length=64, description="Exact catalog_product_id (e.g. MLA24106790)"
    ),
    costo_usd_min: Optional[float] = Query(None, ge=0, description="Min ERP cost in USD (ARS converted via TC)"),
    costo_usd_max: Optional[float] = Query(None, ge=0, description="Max ERP cost in USD (ARS converted via TC)"),
    incluir_tradicionales_sincronizadas: bool = Query(
        False,
        description="When false (default), only catalog listings; when true, also traditional sync partners",
    ),
    criterios_aplicados: Optional[bool] = Query(
        None,
        description="True = only MLAs with saved criteria; false = only without; omit = all",
    ),
    revision_estado: Optional[str] = Query(
        None,
        description="Advisor P4: pendiente | sin_novedades — filter by persisted revision row",
    ),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarColaResponse:
    """Paginated active MLAs from the local sandbox (joined with ERP + price + sync)."""
    offset = (page - 1) * page_size
    scope = _parse_scope_query(
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
        criterios_aplicados=criterios_aplicados,
    )

    revision_filter: Optional[str] = None
    if revision_estado is not None and str(revision_estado).strip():
        token = str(revision_estado).strip().lower()
        if token not in ("pendiente", "sin_novedades"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="revision_estado debe ser pendiente o sin_novedades",
            )
        revision_filter = token

    params: dict = {"limit": page_size, "offset": offset}
    tipo_cambio_usd = (
        obtener_tipo_cambio_actual(db, "USD")
        if scope["costo_usd_min"] is not None or scope["costo_usd_max"] is not None
        else None
    )
    where_extra = _build_alcance_where(**scope, params=params, tipo_cambio_usd=tipo_cambio_usd)
    if revision_filter is not None:
        params["revision_estado"] = revision_filter
        where_extra += """
              AND EXISTS (
                SELECT 1 FROM para_ganar_revision_mla rv
                WHERE rv.mla = p.mla AND rv.estado = :revision_estado
              )
        """

    # PM filter with no marcas_pm rows → empty universe (same as /productos).
    if scope["pms"]:
        pm_pair_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM marcas_pm
                WHERE usuario_id IN ({})
                """.format(", ".join(f":pm_check_{i}" for i in range(len(scope["pms"]))))
            ),
            {f"pm_check_{i}": pm_id for i, pm_id in enumerate(scope["pms"])},
        ).scalar_one()
        if int(pm_pair_count) == 0:
            return ParaGanarColaResponse(total=0, page=page, page_size=page_size, items=[])

    total = db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            WHERE p.activo = true
            {where_extra}
            """
        ),
        params,
    ).scalar_one()

    rows = (
        db.execute(
            text(
                f"""
            SELECT
              p.mla,
              p.item_id,
              p.codigo,
              p.item_title AS titulo,
              e.descripcion AS producto_descripcion,
              p.lista_nombre,
              p.pricelist_id,
              pm.precio,
              l.catalog_listing,
              l.catalog_product_id,
              l.inventory_id,
              CASE WHEN cg.mla IS NOT NULL THEN 1 ELSE 0 END AS criterios_aplicados,
              rv.estado AS revision_estado
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            LEFT JOIN precios_ml pm
              ON pm.item_id = p.item_id
             AND pm.pricelist_id = p.pricelist_id
            LEFT JOIN ml_publication_links l ON l.mla = p.mla
            LEFT JOIN para_ganar_criterios_mla cg ON cg.mla = p.mla
            LEFT JOIN para_ganar_revision_mla rv ON rv.mla = p.mla
            WHERE p.activo = true
            {where_extra}
            ORDER BY
              CASE rv.estado
                WHEN 'pendiente' THEN 0
                WHEN 'sin_novedades' THEN 1
                ELSE 2
              END,
              p.codigo NULLS LAST,
              p.lista_nombre NULLS LAST,
              p.mla
            LIMIT :limit OFFSET :offset
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    # Sync partner without LATERAL (SQLite unit tests + Postgres sandbox).
    by_inv: dict[str, list[str]] = {}
    inventory_ids = sorted({row["inventory_id"] for row in rows if row["inventory_id"]})
    if inventory_ids:
        inv_params = {f"inv_{i}": inv for i, inv in enumerate(inventory_ids)}
        inv_placeholders = ", ".join(f":inv_{i}" for i in range(len(inventory_ids)))
        partner_rows = (
            db.execute(
                text(
                    f"""
                SELECT l.inventory_id, l.mla
                FROM ml_publication_links l
                JOIN publicaciones_ml p ON p.mla = l.mla AND p.activo = true
                WHERE l.inventory_id IN ({inv_placeholders})
                ORDER BY l.inventory_id, l.mla
                """
                ),
                inv_params,
            )
            .mappings()
            .all()
        )
        for prow in partner_rows:
            by_inv.setdefault(prow["inventory_id"], []).append(prow["mla"])

    items: List[ParaGanarColaItem] = []
    for row in rows:
        partner = None
        inv = row["inventory_id"]
        if inv and inv in by_inv:
            for other in by_inv[inv]:
                if other != row["mla"]:
                    partner = other
                    break
        items.append(
            ParaGanarColaItem(
                mla=row["mla"],
                item_id=row["item_id"],
                codigo=row["codigo"],
                titulo=row["titulo"],
                producto_descripcion=row["producto_descripcion"],
                lista_nombre=row["lista_nombre"],
                pricelist_id=row["pricelist_id"],
                precio=_precio_float(row["precio"]),
                catalog_listing=row["catalog_listing"],
                catalog_product_id=row["catalog_product_id"],
                sync_partner_mla=partner,
                criterios_aplicados=bool(row["criterios_aplicados"]),
                revision_estado=str(row["revision_estado"]) if row["revision_estado"] else None,
                suggestion_status="none",
            )
        )

    return ParaGanarColaResponse(
        total=int(total),
        page=page,
        page_size=page_size,
        items=items,
    )


# System defaults when no MLA / product / PM override exists yet.
CRITERIOS_DEFAULT_MARKUP_MIN = 5.0
CRITERIOS_DEFAULT_MARKUP_MAX = 15.0
CRITERIOS_DEFAULT_TOP_SELLERS = 5


class ParaGanarCriteriosMla(BaseModel):
    mla: str
    source: str = Field(description="mla when a row exists, otherwise default")
    markup_min: Optional[float] = None
    markup_max: Optional[float] = None
    top_sellers: Optional[int] = Field(default=None, ge=1, le=50)
    precio_min: Optional[float] = None
    precio_max: Optional[float] = None
    ganar_catalogo: bool = False
    ignorar_internacionales: bool = False
    descartar_stock_residual: bool = False
    descartar_reputacion_baja: bool = False
    techo_monopolio: bool = False
    # ERP cost in ARS for UI markup↔precio sync (D11). Null if unknown / no TC for USD.
    costo_ars: Optional[float] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ParaGanarCriteriosMlaUpsert(BaseModel):
    markup_min: Optional[float] = None
    markup_max: Optional[float] = None
    top_sellers: Optional[int] = Field(default=None, ge=1, le=50)
    precio_min: Optional[float] = None
    precio_max: Optional[float] = None
    ganar_catalogo: bool = False
    ignorar_internacionales: bool = False
    descartar_stock_residual: bool = False
    descartar_reputacion_baja: bool = False
    techo_monopolio: bool = False

    @field_validator("markup_min", "markup_max", "precio_min", "precio_max", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @model_validator(mode="after")
    def _ranges(self) -> ParaGanarCriteriosMlaUpsert:
        if self.markup_min is not None and self.markup_max is not None and self.markup_min > self.markup_max:
            raise ValueError("markup_min no puede ser mayor que markup_max")
        if self.precio_min is not None and self.precio_max is not None and self.precio_min > self.precio_max:
            raise ValueError("precio_min no puede ser mayor que precio_max")
        return self


class ParaGanarCriteriosMasivoBody(BaseModel):
    """Mass apply payload (D10/D17): markup + TOP + flags only — never price caps."""

    markup_min: Optional[float] = None
    markup_max: Optional[float] = None
    top_sellers: Optional[int] = Field(default=None, ge=1, le=50)
    ganar_catalogo: bool = False
    ignorar_internacionales: bool = False
    descartar_stock_residual: bool = False
    descartar_reputacion_baja: bool = False
    techo_monopolio: bool = False

    @field_validator("markup_min", "markup_max", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @model_validator(mode="after")
    def _ranges(self) -> ParaGanarCriteriosMasivoBody:
        if self.markup_min is not None and self.markup_max is not None and self.markup_min > self.markup_max:
            raise ValueError("markup_min no puede ser mayor que markup_max")
        return self


class ParaGanarCriteriosMasivoResponse(BaseModel):
    scope_total: int
    applied: int
    created: int
    updated: int


class ParaGanarEvaluarFiltradosResponse(BaseModel):
    """A1 interim: sync P5 evaluation over the current Advisor alcance."""

    scope_total: int = 0
    evaluated: int = 0
    pendiente: int = 0
    sin_novedades: int = 0
    skipped: int = 0

    model_config = ConfigDict(from_attributes=True)


class ParaGanarConsultaJobEnqueueResponse(BaseModel):
    """A1 final: enqueued consultation job (refresh → P5 via ML worker)."""

    job_id: int
    total_count: int
    source: str
    status: str

    model_config = ConfigDict(from_attributes=True)


def _costo_ars_for_mla(db: Session, mla: str) -> Optional[float]:
    """ERP cost converted to ARS for criteria precio↔markup sync (D11)."""
    row = (
        db.execute(
            text(
                """
                SELECT e.costo, CAST(e.moneda_costo AS TEXT) AS moneda
                FROM publicaciones_ml p
                JOIN productos_erp e ON e.item_id = p.item_id
                WHERE p.mla = :mla
                LIMIT 1
                """
            ),
            {"mla": mla},
        )
        .mappings()
        .first()
    )
    if row is None or row["costo"] is None:
        return None
    costo = float(row["costo"])
    moneda = (row["moneda"] or "ARS").strip().upper()
    if moneda == "ARS":
        return costo
    tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
    if tipo_cambio and float(tipo_cambio) > 0:
        return costo * float(tipo_cambio)
    return None


def _criterios_defaults(mla: str, *, costo_ars: Optional[float] = None) -> ParaGanarCriteriosMla:
    """Effective criteria before any MLA override (precio min/max stay unset)."""
    return ParaGanarCriteriosMla(
        mla=mla,
        source="default",
        markup_min=CRITERIOS_DEFAULT_MARKUP_MIN,
        markup_max=CRITERIOS_DEFAULT_MARKUP_MAX,
        top_sellers=CRITERIOS_DEFAULT_TOP_SELLERS,
        precio_min=None,
        precio_max=None,
        ganar_catalogo=False,
        ignorar_internacionales=False,
        descartar_stock_residual=False,
        descartar_reputacion_baja=False,
        techo_monopolio=False,
        costo_ars=costo_ars,
    )


def _criterios_from_row(row: ParaGanarCriterioMla, *, costo_ars: Optional[float] = None) -> ParaGanarCriteriosMla:
    return ParaGanarCriteriosMla(
        mla=row.mla,
        source="mla",
        markup_min=_precio_float(row.markup_min),
        markup_max=_precio_float(row.markup_max),
        top_sellers=row.top_sellers,
        precio_min=_precio_float(row.precio_min),
        precio_max=_precio_float(row.precio_max),
        ganar_catalogo=bool(row.ganar_catalogo),
        ignorar_internacionales=bool(row.ignorar_internacionales),
        descartar_stock_residual=bool(row.descartar_stock_residual),
        descartar_reputacion_baja=bool(row.descartar_reputacion_baja),
        techo_monopolio=bool(row.techo_monopolio),
        costo_ars=costo_ars,
        updated_at=row.updated_at,
    )


def _mla_exists(db: Session, mla: str) -> bool:
    return mla_exists(db, mla)


def _list_scope_mlas(db: Session, scope: dict) -> list[str]:
    """All active MLAs matching the cola/alcance filters (no pagination)."""
    if scope["pms"]:
        pm_pair_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM marcas_pm
                WHERE usuario_id IN ({})
                """.format(", ".join(f":pm_check_{i}" for i in range(len(scope["pms"]))))
            ),
            {f"pm_check_{i}": pm_id for i, pm_id in enumerate(scope["pms"])},
        ).scalar_one()
        if int(pm_pair_count) == 0:
            return []

    params: dict = {}
    tipo_cambio_usd = (
        obtener_tipo_cambio_actual(db, "USD")
        if scope["costo_usd_min"] is not None or scope["costo_usd_max"] is not None
        else None
    )
    where_extra = _build_alcance_where(**scope, params=params, tipo_cambio_usd=tipo_cambio_usd)
    rows = db.execute(
        text(
            f"""
            SELECT p.mla
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            WHERE p.activo = true
            {where_extra}
            ORDER BY p.mla
            """
        ),
        params,
    ).all()
    return [str(row[0]) for row in rows]


@router.get(
    "/criterios/{mla}",
    response_model=ParaGanarCriteriosMla,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def obtener_criterios_mla(
    mla: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarCriteriosMla:
    """Return MLA criteria, or defaults when no override row exists yet."""
    mla_norm = mla.strip().upper()
    if not mla_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MLA inválida")
    costo_ars = _costo_ars_for_mla(db, mla_norm)
    row = db.get(ParaGanarCriterioMla, mla_norm)
    if row is None:
        return _criterios_defaults(mla_norm, costo_ars=costo_ars)
    return _criterios_from_row(row, costo_ars=costo_ars)


@router.put(
    "/criterios/{mla}",
    response_model=ParaGanarCriteriosMla,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def upsert_criterios_mla(
    mla: str,
    body: ParaGanarCriteriosMlaUpsert,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarCriteriosMla:
    """Create or replace per-MLA criteria. MLA must exist as an active publication."""
    mla_norm = mla.strip().upper()
    if not mla_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MLA inválida")
    if not _mla_exists(db, mla_norm):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MLA no encontrada")

    row = db.get(ParaGanarCriterioMla, mla_norm)
    if row is None:
        row = ParaGanarCriterioMla(mla=mla_norm)
        db.add(row)

    row.markup_min = body.markup_min
    row.markup_max = body.markup_max
    row.top_sellers = body.top_sellers
    row.precio_min = body.precio_min
    row.precio_max = body.precio_max
    row.ganar_catalogo = body.ganar_catalogo
    row.ignorar_internacionales = body.ignorar_internacionales
    row.descartar_stock_residual = body.descartar_stock_residual
    row.descartar_reputacion_baja = body.descartar_reputacion_baja
    row.techo_monopolio = body.techo_monopolio
    row.updated_by_id = current_user.id
    row.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(row)
    return _criterios_from_row(row, costo_ars=_costo_ars_for_mla(db, mla_norm))


@router.post(
    "/criterios/{mla}/aplicar-defaults",
    response_model=ParaGanarCriteriosMla,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def aplicar_criterios_defaults_mla(
    mla: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarCriteriosMla:
    """Persist system defaults for this MLA (marks criteria as applied).

    Idempotent if a row already exists: returns the saved criteria unchanged.
    """
    mla_norm = mla.strip().upper()
    if not mla_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MLA inválida")
    if not _mla_exists(db, mla_norm):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MLA no encontrada")

    row = db.get(ParaGanarCriterioMla, mla_norm)
    if row is not None:
        return _criterios_from_row(row, costo_ars=_costo_ars_for_mla(db, mla_norm))

    defaults = _criterios_defaults(mla_norm)
    row = ParaGanarCriterioMla(
        mla=mla_norm,
        markup_min=defaults.markup_min,
        markup_max=defaults.markup_max,
        top_sellers=defaults.top_sellers,
        precio_min=defaults.precio_min,
        precio_max=defaults.precio_max,
        ganar_catalogo=defaults.ganar_catalogo,
        ignorar_internacionales=defaults.ignorar_internacionales,
        descartar_stock_residual=defaults.descartar_stock_residual,
        descartar_reputacion_baja=defaults.descartar_reputacion_baja,
        techo_monopolio=defaults.techo_monopolio,
        updated_by_id=current_user.id,
        updated_at=datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _criterios_from_row(row, costo_ars=_costo_ars_for_mla(db, mla_norm))


@router.post(
    "/criterios/aplicar-masivo",
    response_model=ParaGanarCriteriosMasivoResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def aplicar_criterios_masivo(
    body: ParaGanarCriteriosMasivoBody,
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
    criterios_aplicados: Optional[bool] = Query(
        None,
        description="True = only MLAs with saved criteria; false = only without; omit = all",
    ),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarCriteriosMasivoResponse:
    """Upsert mass criteria onto every MLA in the current cola scope (D17).

    Overwrites markup/TOP/flags on existing rows; leaves precio_min/max untouched.
    New rows get precio caps unset (D10).
    """
    scope = _parse_scope_query(
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
        criterios_aplicados=criterios_aplicados,
    )
    mlas = _list_scope_mlas(db, scope)
    if not mlas:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No hay MLAs en el alcance filtrado",
        )

    now = datetime.now(UTC)
    existing_rows = db.query(ParaGanarCriterioMla).filter(ParaGanarCriterioMla.mla.in_(mlas)).all()
    by_mla = {row.mla: row for row in existing_rows}
    created = 0
    updated = 0
    for mla in mlas:
        row = by_mla.get(mla)
        if row is None:
            row = ParaGanarCriterioMla(
                mla=mla,
                precio_min=None,
                precio_max=None,
            )
            db.add(row)
            created += 1
        else:
            updated += 1
        row.markup_min = body.markup_min
        row.markup_max = body.markup_max
        row.top_sellers = body.top_sellers
        row.ganar_catalogo = body.ganar_catalogo
        row.ignorar_internacionales = body.ignorar_internacionales
        row.descartar_stock_residual = body.descartar_stock_residual
        row.descartar_reputacion_baja = body.descartar_reputacion_baja
        row.techo_monopolio = body.techo_monopolio
        row.updated_by_id = current_user.id
        row.updated_at = now

    db.commit()
    return ParaGanarCriteriosMasivoResponse(
        scope_total=len(mlas),
        applied=len(mlas),
        created=created,
        updated=updated,
    )


@router.post(
    "/evaluar-filtrados",
    response_model=ParaGanarEvaluarFiltradosResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def evaluar_filtrados(
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
    criterios_aplicados: Optional[bool] = Query(
        None,
        description="True = only MLAs with saved criteria; false = only without; omit = all",
    ),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarEvaluarFiltradosResponse:
    """A1: run P5 (R1–R4) on every MLA in the current Advisor alcance filters.

    Same scope params as cola / aplicar-masivo. Does not use revision_estado chips.
    Writes `para_ganar_revision_mla` (pendiente / sin_novedades + baseline).
    """
    scope = _parse_scope_query(
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
        criterios_aplicados=criterios_aplicados,
    )
    mlas = _list_scope_mlas(db, scope)
    if not mlas:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No hay MLAs en el alcance filtrado",
        )
    counts = evaluar_mlas(db, mlas, updated_by_id=current_user.id)
    db.commit()
    return ParaGanarEvaluarFiltradosResponse(
        scope_total=len(mlas),
        evaluated=counts["evaluated"],
        pendiente=counts["pendiente"],
        sin_novedades=counts["sin_novedades"],
        skipped=counts["skipped"],
    )


@router.post(
    "/consulta-jobs",
    response_model=ParaGanarConsultaJobEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def enqueue_consulta_filtrados(
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
    criterios_aplicados: Optional[bool] = Query(
        None,
        description="True = only MLAs with saved criteria; false = only without; omit = all",
    ),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarConsultaJobEnqueueResponse:
    """A1: enqueue a PM-owned consultation job for the Advisor alcance filters.

    Same scope params as cola / evaluar-filtrados. Worker refreshes catalog
    competition then runs P5; revision states land in the shared queue.
    """
    scope = _parse_scope_query(
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
        criterios_aplicados=criterios_aplicados,
    )
    mlas = _list_scope_mlas(db, scope)
    if not mlas:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No hay MLAs en el alcance filtrado",
        )
    try:
        job = enqueue_consulta(
            db,
            mlas,
            created_by_id=current_user.id,
            source=SOURCE_MANUAL,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    db.commit()
    return ParaGanarConsultaJobEnqueueResponse(
        job_id=job.id,
        total_count=job.total_count,
        source=job.source,
        status=job.status,
    )


class ParaGanarCatalogSellerItem(BaseModel):
    seller_id: str
    nickname: Optional[str] = None
    disposition: str = DISPOSITION_ACTIVE
    last_item_id: Optional[str] = None
    last_seen_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ParaGanarCatalogSellersResponse(BaseModel):
    mla: str
    catalog_product_id: Optional[str] = None
    synced_from_competition: bool = False
    excluded_count: int = 0
    sellers: List[ParaGanarCatalogSellerItem]


class ParaGanarSugerenciaPositionSeller(BaseModel):
    seller_id: str
    nickname: Optional[str] = None
    item_id: Optional[str] = None
    is_us: bool = False
    listing_label: Optional[str] = None
    # TOP board hint: Referente | Descartado: markup mín. | Sin markup | …
    referent_note: Optional[str] = None


class ParaGanarSugerenciaPosition(BaseModel):
    rank: int
    price_ars: float
    seller_count: int
    sellers: List[ParaGanarSugerenciaPositionSeller]


class ParaGanarSugerenciaResponse(BaseModel):
    mla: str
    catalog_product_id: Optional[str] = None
    snapshot_at: Optional[datetime] = None
    our_price: Optional[float] = None
    our_rank: Optional[int] = None
    top_sellers: int
    in_top: bool = False
    excluded_count: int = 0
    bucket_label: Optional[str] = None
    positions: List[ParaGanarSugerenciaPosition] = Field(default_factory=list)
    suggestion_status: str = "none"
    precio_sugerido: Optional[float] = None
    delta_ars: Optional[float] = None
    referent_nickname: Optional[str] = None
    referent_reason: Optional[str] = None
    message: Optional[str] = None
    needs_competition_refresh: bool = False


class ParaGanarCatalogSellerDispositionUpdate(BaseModel):
    seller_id: str = Field(min_length=1, max_length=32)
    disposition: str

    @field_validator("disposition")
    @classmethod
    def _disposition_ok(cls, value: str) -> str:
        # Write path: only active|excluded. Legacy labels are normalized on read.
        if value not in DISPOSITION_VALUES:
            raise ValueError(f"disposition inválida: {value}")
        return value


class ParaGanarCatalogSellersUpsert(BaseModel):
    sellers: List[ParaGanarCatalogSellerDispositionUpdate] = Field(min_length=1)


def _catalog_product_id_for_mla(db: Session, mla: str) -> Optional[str]:
    return catalog_product_id_for_mla(db, mla)


def _competition_sellers_by_id(db: Session, catalog_product_id: str) -> tuple[dict[str, dict], Optional[datetime]]:
    """Unique sellers from the newest competition snapshot (no DB writes)."""
    from sqlalchemy.exc import OperationalError, ProgrammingError

    try:
        snap = (
            db.execute(
                text(
                    """
                SELECT competitors, fecha_consulta
                FROM ml_catalog_competition
                WHERE catalog_product_id = :cid
                  AND fetch_status = 'ok'
                  AND competitors IS NOT NULL
                ORDER BY fecha_consulta DESC
                LIMIT 1
                """
                ),
                {"cid": catalog_product_id},
            )
            .mappings()
            .first()
        )
    except (OperationalError, ProgrammingError):
        db.rollback()
        return {}, None
    if not snap:
        return {}, None

    competitors = snap["competitors"] or []
    if not isinstance(competitors, list) or not competitors:
        return {}, None

    by_seller: dict[str, dict] = {}
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        raw_id = competitor.get("seller_id")
        if raw_id is None:
            continue
        seller_id = str(raw_id).strip()
        if not seller_id:
            continue
        nickname = competitor.get("seller_nickname")
        nickname_s = str(nickname).strip()[:128] if nickname else None
        item_raw = competitor.get("item_id")
        item_id = str(item_raw).strip()[:32] if item_raw else None
        by_seller[seller_id] = {"nickname": nickname_s, "item_id": item_id}
    return by_seller, snap["fecha_consulta"]


def _persist_roster_from_competition(
    db: Session,
    catalog_product_id: str,
    *,
    user_id: int,
) -> bool:
    """Write competition members into the roster table (write-permission callers only)."""
    by_seller, seen_at = _competition_sellers_by_id(db, catalog_product_id)
    if not by_seller:
        return False

    now = datetime.now(UTC)
    seen = seen_at or now
    existing = {
        row.seller_id: row
        for row in db.query(ParaGanarCatalogSeller)
        .filter(ParaGanarCatalogSeller.catalog_product_id == catalog_product_id)
        .all()
    }
    for seller_id, meta in by_seller.items():
        row = existing.get(seller_id)
        if row is None:
            row = ParaGanarCatalogSeller(
                catalog_product_id=catalog_product_id,
                seller_id=seller_id,
                disposition=DISPOSITION_ACTIVE,
            )
            db.add(row)
            existing[seller_id] = row
        if meta["nickname"]:
            row.nickname = meta["nickname"]
        if meta["item_id"]:
            row.last_item_id = meta["item_id"]
        row.last_seen_at = seen
        row.updated_at = now
        row.updated_by_id = user_id

    db.commit()
    return True


def _sellers_response(
    *,
    mla: str,
    catalog_product_id: str,
    rows: list[ParaGanarCatalogSeller],
    competition: dict[str, dict],
    seen_at: Optional[datetime],
    synced_from_competition: bool,
) -> ParaGanarCatalogSellersResponse:
    """Merge persisted rows with ephemeral competition members (read path)."""
    by_id: dict[str, ParaGanarCatalogSellerItem] = {}
    for row in rows:
        by_id[row.seller_id] = ParaGanarCatalogSellerItem(
            seller_id=row.seller_id,
            nickname=row.nickname,
            disposition=normalize_disposition(row.disposition),
            last_item_id=row.last_item_id,
            last_seen_at=row.last_seen_at,
        )
    for seller_id, meta in competition.items():
        if seller_id in by_id:
            continue
        by_id[seller_id] = ParaGanarCatalogSellerItem(
            seller_id=seller_id,
            nickname=meta.get("nickname"),
            disposition=DISPOSITION_ACTIVE,
            last_item_id=meta.get("item_id"),
            last_seen_at=seen_at,
        )
    sellers = sorted(
        by_id.values(),
        key=lambda item: ((item.nickname or "").lower(), item.seller_id),
    )
    excluded_count = sum(1 for s in sellers if is_excluded(s.disposition))
    return ParaGanarCatalogSellersResponse(
        mla=mla,
        catalog_product_id=catalog_product_id,
        synced_from_competition=synced_from_competition,
        excluded_count=excluded_count,
        sellers=sellers,
    )


def _list_persisted_sellers(db: Session, catalog_product_id: str) -> list[ParaGanarCatalogSeller]:
    return (
        db.query(ParaGanarCatalogSeller)
        .filter(ParaGanarCatalogSeller.catalog_product_id == catalog_product_id)
        .order_by(ParaGanarCatalogSeller.nickname.nulls_last(), ParaGanarCatalogSeller.seller_id)
        .all()
    )


@router.get(
    "/criterios/{mla}/sellers",
    response_model=ParaGanarCatalogSellersResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_sellers_catalogo(
    mla: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarCatalogSellersResponse:
    """Read-only roster: persisted dispositions + competition members (not written)."""
    mla_norm = mla.strip().upper()
    if not mla_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MLA inválida")

    catalog_product_id = _catalog_product_id_for_mla(db, mla_norm)
    if not catalog_product_id:
        return ParaGanarCatalogSellersResponse(
            mla=mla_norm,
            catalog_product_id=None,
            synced_from_competition=False,
            excluded_count=0,
            sellers=[],
        )

    competition, seen_at = _competition_sellers_by_id(db, catalog_product_id)
    rows = _list_persisted_sellers(db, catalog_product_id)
    return _sellers_response(
        mla=mla_norm,
        catalog_product_id=catalog_product_id,
        rows=rows,
        competition=competition,
        seen_at=seen_at,
        synced_from_competition=False,
    )


@router.post(
    "/criterios/{mla}/sellers/sync",
    response_model=ParaGanarCatalogSellersResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def sincronizar_sellers_catalogo(
    mla: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarCatalogSellersResponse:
    """Persist competition members into the catalog roster (write permission)."""
    mla_norm = mla.strip().upper()
    if not mla_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MLA inválida")
    catalog_product_id = _catalog_product_id_for_mla(db, mla_norm)
    if not catalog_product_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La MLA no tiene catalog_product_id",
        )

    synced = _persist_roster_from_competition(db, catalog_product_id, user_id=current_user.id)
    competition, seen_at = _competition_sellers_by_id(db, catalog_product_id)
    rows = _list_persisted_sellers(db, catalog_product_id)
    return _sellers_response(
        mla=mla_norm,
        catalog_product_id=catalog_product_id,
        rows=rows,
        competition=competition,
        seen_at=seen_at,
        synced_from_competition=synced,
    )


@router.put(
    "/criterios/{mla}/sellers",
    response_model=ParaGanarCatalogSellersResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def actualizar_sellers_catalogo(
    mla: str,
    body: ParaGanarCatalogSellersUpsert,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarCatalogSellersResponse:
    """Update dispositions for sellers in the MLA's catalog roster (bulk)."""
    mla_norm = mla.strip().upper()
    if not mla_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MLA inválida")
    catalog_product_id = _catalog_product_id_for_mla(db, mla_norm)
    if not catalog_product_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La MLA no tiene catalog_product_id",
        )

    seller_ids = [item.seller_id.strip() for item in body.sellers]
    existing = {
        row.seller_id: row
        for row in db.query(ParaGanarCatalogSeller)
        .filter(
            ParaGanarCatalogSeller.catalog_product_id == catalog_product_id,
            ParaGanarCatalogSeller.seller_id.in_(seller_ids),
        )
        .all()
    }
    now = datetime.now(UTC)
    for item in body.sellers:
        seller_id = item.seller_id.strip()
        row = existing.get(seller_id)
        if row is None:
            row = ParaGanarCatalogSeller(
                catalog_product_id=catalog_product_id,
                seller_id=seller_id,
            )
            db.add(row)
            existing[seller_id] = row
        row.disposition = item.disposition
        row.updated_at = now
        row.updated_by_id = current_user.id

    db.commit()
    competition, seen_at = _competition_sellers_by_id(db, catalog_product_id)
    rows = _list_persisted_sellers(db, catalog_product_id)
    return _sellers_response(
        mla=mla_norm,
        catalog_product_id=catalog_product_id,
        rows=rows,
        competition=competition,
        seen_at=seen_at,
        synced_from_competition=False,
    )


def _sugerencia_to_response(sug: SugerenciaMla) -> ParaGanarSugerenciaResponse:
    return ParaGanarSugerenciaResponse(
        mla=sug.mla,
        catalog_product_id=sug.catalog_product_id,
        snapshot_at=sug.snapshot_at,
        our_price=sug.our_price,
        our_rank=sug.our_rank,
        top_sellers=sug.top_sellers,
        in_top=sug.in_top,
        excluded_count=sug.excluded_count,
        bucket_label=sug.bucket_label,
        positions=[ParaGanarSugerenciaPosition(**p) for p in sug.positions],
        suggestion_status=sug.suggestion_status,
        precio_sugerido=sug.precio_sugerido,
        delta_ars=sug.delta_ars,
        referent_nickname=sug.referent_nickname,
        referent_reason=sug.referent_reason,
        message=sug.message,
        needs_competition_refresh=sug.needs_competition_refresh,
    )


@router.get(
    "/criterios/{mla}/sugerencia",
    response_model=ParaGanarSugerenciaResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def obtener_sugerencia_mla(
    mla: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarSugerenciaResponse:
    """TOP board (D12) + suggested price vs same-bucket peers (Pro-style referent)."""
    try:
        sug = compute_sugerencia_mla(db, mla)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _sugerencia_to_response(sug)


@router.post(
    "/criterios/{mla}/competencia/refresh",
    response_model=ParaGanarSugerenciaResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def refrescar_competencia_para_ganar(
    mla: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ParaGanarSugerenciaResponse:
    """Fetch+persist catalog-competition snapshot for this MLA, then return the TOP board.

    Reuses `refrescar_competencia_catalogo` (same path as Promociones). Per-MLA only —
    no bulk refresh (ML throttle). Also upserts the sellers roster when a catalog id exists.
    """
    mla_norm = mla.strip().upper()
    if not mla_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MLA inválida")
    if not _mla_exists(db, mla_norm):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MLA no encontrada")

    rows = resolve_maybe_async(refrescar_competencia_catalogo(db, [mla_norm]))
    row = rows[0] if rows else None
    if row is None or row.fetch_status != "ok":
        detail = None
        if row is not None:
            detail = row.error_detail or row.fetch_status
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo obtener competencia de catálogo ({detail or 'sin respuesta'}).",
        )

    catalog_product_id = _catalog_product_id_for_mla(db, mla_norm)
    if catalog_product_id:
        _persist_roster_from_competition(db, catalog_product_id, user_id=current_user.id)

    return obtener_sugerencia_mla(mla=mla_norm, db=db, _user=current_user)
