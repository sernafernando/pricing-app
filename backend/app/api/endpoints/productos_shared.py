"""
Shared Pydantic models for the productos module.

All schemas used across productos sub-modules live here.
"""

from typing import Optional, List, Literal, Tuple
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, date
import logging

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import InstrumentedAttribute, Query, Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.equipo import Equipo, EquipoMiembro
from app.models.usuario import Usuario
from app.services.ml_promotions_service import (
    fetch_mlas_with_active_promo_type,
    fetch_mlas_with_candidate_only,
    fetch_mlas_with_candidate_only_for_types,
    fetch_mlas_with_started,
)
from app.services.ml_pxq_tiers_read_service import fetch_mlas_with_pxq_tiers
from app.services.promo_filter_resolver import PromoResolverFns, select_promo_resolver
from app.schemas.costo_ppp import PppPayload

logger = logging.getLogger(__name__)

__all__ = ["PppPayload"]  # re-exported for backward compatibility; canonical home is app.schemas.costo_ppp


class ProductoResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    moneda_costo: Optional[str]
    costo: float
    costo_ars: Optional[float]
    iva: float
    stock: int
    precio_lista_ml: Optional[float]
    markup: Optional[float]
    usuario_modifico: Optional[str]
    fecha_modificacion: Optional[datetime]
    tiene_precio: bool
    necesita_revision: bool
    participa_rebate: Optional[bool] = False
    porcentaje_rebate: Optional[float] = 3.8
    precio_rebate: Optional[float] = None
    markup_rebate: Optional[float] = None
    participa_web_transferencia: Optional[bool] = False
    porcentaje_markup_web: Optional[float] = 6.0
    precio_web_transferencia: Optional[float] = None
    markup_web_real: Optional[float] = None
    preservar_porcentaje_web: Optional[bool] = False
    mejor_oferta_precio: Optional[float] = None
    mejor_oferta_monto_rebate: Optional[float] = None
    mejor_oferta_pvp_seller: Optional[float] = None
    mejor_oferta_markup: Optional[float] = None
    mejor_oferta_porcentaje_rebate: Optional[float] = None
    mejor_oferta_fecha_hasta: Optional[date] = None
    out_of_cards: Optional[bool] = False
    color_marcado: Optional[str] = None
    # Team color-layer hints (see productos_shared: resolver_layer_activo).
    # color_marcado above is sourced from the active layer (default: global "U").
    color_hint_global: Optional[str] = None
    color_hint_equipo_inicial: Optional[str] = None
    precio_3_cuotas: Optional[float] = None
    precio_6_cuotas: Optional[float] = None
    precio_9_cuotas: Optional[float] = None
    precio_12_cuotas: Optional[float] = None
    markup_3_cuotas: Optional[float] = None
    markup_6_cuotas: Optional[float] = None
    markup_9_cuotas: Optional[float] = None
    markup_12_cuotas: Optional[float] = None

    # Precios PVP
    precio_pvp: Optional[float] = None
    precio_pvp_3_cuotas: Optional[float] = None
    precio_pvp_6_cuotas: Optional[float] = None
    precio_pvp_9_cuotas: Optional[float] = None
    precio_pvp_12_cuotas: Optional[float] = None
    markup_pvp: Optional[float] = None
    markup_pvp_3_cuotas: Optional[float] = None
    markup_pvp_6_cuotas: Optional[float] = None
    markup_pvp_9_cuotas: Optional[float] = None
    markup_pvp_12_cuotas: Optional[float] = None

    # Configuración individual
    recalcular_cuotas_auto: Optional[bool] = None
    markup_adicional_cuotas_custom: Optional[float] = None
    markup_adicional_cuotas_pvp_custom: Optional[float] = None

    # Estado de catálogo ML
    catalog_status: Optional[str] = None
    has_catalog: Optional[bool] = None
    catalog_price_to_win: Optional[float] = None
    catalog_winner_price: Optional[float] = None

    # Precios Tienda Nube
    tn_price: Optional[float] = None  # Precio normal
    tn_promotional_price: Optional[float] = None  # Precio promocional
    tn_has_promotion: Optional[bool] = None  # Si tiene promoción activa

    # PPP (ERP weighted-average cost) — informational only, never persisted.
    ppp: Optional[PppPayload] = None

    # PxQ wholesale tiers quick view (cross-DB, mlwebhook — FAIL-OPEN: both
    # stay None when that read fails, so the row renders without the chip
    # instead of taking the listing down).
    pxq_tramos: Optional[int] = None
    pxq_precio_desde: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ProductoListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    productos: List[ProductoResponse]


class PrecioUpdate(BaseModel):
    precio_lista_final: Optional[float] = None
    precio_contado_final: Optional[float] = None
    comentario: Optional[str] = None


class RebateUpdate(BaseModel):
    participa_rebate: bool
    porcentaje_rebate: float = Field(ge=0, le=100)


class ProductoTiendaResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    moneda_costo: Optional[str]
    costo: float
    costo_ars: Optional[float]
    iva: float
    stock: int
    precio_lista_ml: Optional[float]
    markup: Optional[float]
    usuario_modifico: Optional[str]
    fecha_modificacion: Optional[datetime]
    tiene_precio: bool
    necesita_revision: bool
    participa_rebate: Optional[bool] = False
    porcentaje_rebate: Optional[float] = 3.8
    precio_rebate: Optional[float] = None
    markup_rebate: Optional[float] = None
    precio_gremio_sin_iva: Optional[float] = None
    precio_gremio_con_iva: Optional[float] = None
    markup_gremio: Optional[float] = None
    tiene_override_gremio: Optional[bool] = False  # Indica si tiene precio manual
    precio_sugerido_sin_iva: Optional[float] = None
    precio_sugerido_con_iva: Optional[float] = None
    markup_sugerido_valor: Optional[float] = None  # % sugerido configurado (marca o producto)
    markup_sugerido_total: Optional[float] = None  # markup_clasica + markup_sugerido
    markup_sugerido_origen: Optional[Literal["producto", "marca"]] = None  # origen del markup sugerido efectivo
    participa_web_transferencia: Optional[bool] = False
    porcentaje_markup_web: Optional[float] = 6.0
    precio_web_transferencia: Optional[float] = None
    markup_web_real: Optional[float] = None
    preservar_porcentaje_web: Optional[bool] = False
    mejor_oferta_precio: Optional[float] = None
    mejor_oferta_monto_rebate: Optional[float] = None
    mejor_oferta_pvp_seller: Optional[float] = None
    mejor_oferta_markup: Optional[float] = None
    mejor_oferta_porcentaje_rebate: Optional[float] = None
    mejor_oferta_fecha_hasta: Optional[date] = None
    out_of_cards: Optional[bool] = False
    color_marcado: Optional[str] = None
    color_marcado_tienda: Optional[str] = None
    # Team color-layer hints (tienda slot; see productos_shared: resolver_layer_activo).
    # color_marcado_tienda above is sourced from the active layer (default: global "U").
    color_hint_global: Optional[str] = None
    color_hint_equipo_inicial: Optional[str] = None
    precio_3_cuotas: Optional[float] = None
    precio_6_cuotas: Optional[float] = None
    precio_9_cuotas: Optional[float] = None
    precio_12_cuotas: Optional[float] = None
    markup_3_cuotas: Optional[float] = None
    markup_6_cuotas: Optional[float] = None
    markup_9_cuotas: Optional[float] = None
    markup_12_cuotas: Optional[float] = None
    recalcular_cuotas_auto: Optional[bool] = None
    markup_adicional_cuotas_custom: Optional[float] = None
    markup_adicional_cuotas_pvp_custom: Optional[float] = None
    catalog_status: Optional[str] = None
    has_catalog: Optional[bool] = None
    catalog_price_to_win: Optional[float] = None
    catalog_winner_price: Optional[float] = None
    tn_price: Optional[float] = None
    tn_promotional_price: Optional[float] = None
    tn_has_promotion: Optional[bool] = None

    # PPP (ERP weighted-average cost) — informational only, never persisted.
    ppp: Optional[PppPayload] = None

    model_config = ConfigDict(from_attributes=True)


class ProductoTiendaListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    productos: List[ProductoTiendaResponse]


# =============================================================================
# SHARED PRICING HELPERS
# =============================================================================


def computar_precio_sugerido(
    costo_ars: float,
    iva: float,
    markup_clasica: Optional[float],
    markup_sugerido_valor: Optional[float],
    varios_porcentaje: float,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Compute precio_sugerido_sin_iva, precio_sugerido_con_iva, and markup_sugerido_total
    from the given inputs.

    This is the single source of truth for the suggested-price formula, shared by:
    - the Tienda listing (productos_listing.py) for bulk computation
    - the PATCH /markups-tienda/productos/{item_id}/markup-sugerido endpoint for single-row recompute

    The formula is:
        effective_sugerido = markup_sugerido_valor if not None else 0.0
        markup_sugerido_total = markup_clasica + effective_sugerido
        precio_sugerido_sin_iva = costo_ars * (1 + varios_porcentaje / 100) * (1 + markup_sugerido_total / 100)
        precio_sugerido_con_iva = precio_sugerido_sin_iva * (1 + iva / 100)

    Args:
        costo_ars: Product cost in ARS (already converted from USD if applicable).
        iva: IVA percentage (e.g. 21.0 for 21%).
        markup_clasica: The Clásica (gremio) markup % from producto_pricing.markup_calculado.
                        If None or costo_ars <= 0 the function returns (None, None, None).
        markup_sugerido_valor: The additional suggested markup % (product or brand level).
                               None is treated as 0.0 (no additional markup).
        varios_porcentaje: Operating cost percentage (e.g. 6.5).

    Returns:
        Tuple (precio_sugerido_sin_iva, precio_sugerido_con_iva, markup_sugerido_total).
        All three are None when required inputs are missing.
    """
    if markup_clasica is None or not costo_ars or costo_ars <= 0:
        return None, None, None

    effective_sugerido = markup_sugerido_valor if markup_sugerido_valor is not None else 0.0
    markup_sugerido_total = markup_clasica + effective_sugerido
    precio_sin_iva = costo_ars * (1 + varios_porcentaje / 100) * (1 + markup_sugerido_total / 100)
    iva_rate = iva if iva is not None else 21.0
    precio_con_iva = precio_sin_iva * (1 + iva_rate / 100)
    return precio_sin_iva, precio_con_iva, markup_sugerido_total


class ExportRebateRequest(BaseModel):
    fecha_desde: Optional[str] = None
    fecha_hasta: Optional[str] = None
    filtros: Optional[dict] = None
    estado_mla: Optional[str] = None
    formato: Optional[str] = "nuevo"  # nuevo, tradicional
    tipo_cuotas: Optional[str] = "clasica"  # clasica, 3, 6, 9, 12
    porcentaje_rebate_override: Optional[float] = None  # Override global para cuotas (ej: 1.5)
    offset_pvp_lleno: Optional[float] = None  # Offset % sobre precio cuotas para PVP LLENO (ej: 5.0)
    tiendas_oficiales: Optional[str] = Field(
        default=None,
        description=(
            "CSV de IDs de tiendas oficiales con literal 'sin_tienda'. "
            "Filtra a nivel MLA (mlp_official_store_id). "
            "Ej: 'sin_tienda,57997,2645'. "
            "Distinto de 'tienda_oficial' (filtro a nivel producto)."
        ),
    )


class CalculoWebMasivoRequest(BaseModel):
    porcentaje_con_precio: float
    porcentaje_sin_precio: float
    filtros: dict = None


class CalculoPVPMasivoRequest(BaseModel):
    markup_pvp_clasica: float
    adicional_cuotas: float
    filtros: dict = None


class RecalcularCuotasMasivoRequest(BaseModel):
    lista_tipo: str = "web"  # "web" o "pvp"
    filtros: dict = None


class ConfigCuotasRequest(BaseModel):
    recalcular_cuotas_auto: Optional[bool] = None
    markup_adicional_cuotas_custom: Optional[float] = None
    markup_adicional_cuotas_pvp_custom: Optional[float] = None


class ConfigCuotasMasivoRequest(BaseModel):
    item_ids: List[int] = Field(..., min_length=1, max_length=100)
    recalcular_cuotas_auto: Optional[bool] = None
    markup_adicional_cuotas_custom: Optional[float] = None
    markup_adicional_cuotas_pvp_custom: Optional[float] = None


class ConfigCuotasMasivoResponse(BaseModel):
    ok: int
    total: int


class ColorLoteRequest(BaseModel):
    item_ids: List[int]
    color: Optional[str] = None
    equipo_id: Optional[int] = None


# =============================================================================
# EQUIPO (TEAM) COLOR-LAYER HELPERS
# =============================================================================


def coerce_equipo_id(filtros: Optional[dict]) -> Optional[int]:
    """Extracts and coerces `equipo_id` from an untyped `filtros` dict.

    Unlike GET endpoints (typed `equipo_id: Optional[int]` query param,
    FastAPI-coerced), masivo/export endpoints receive `equipo_id` inside a raw
    JSON body dict, so it may arrive as a string (e.g. "3") or a bad value.
    This normalizes it to `int` (or `None`), raising a clean 422 instead of
    letting an uncoerced value reach `resolver_layer_activo`/`puede_escribir_layer`
    and blow up as a Postgres type-mismatch 500 on the `== global_layer_id` comparison.
    """
    if not filtros:
        return None

    raw = filtros.get("equipo_id")
    if raw is None:
        return None

    # Reject bool explicitly: `int(True) == 1` would otherwise silently resolve to
    # team 1 instead of surfacing a clean 422.
    if isinstance(raw, bool):
        raise HTTPException(status_code=422, detail="equipo_id inválido: debe ser un entero")

    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="equipo_id inválido: debe ser un entero") from None


def get_global_equipo_id(db: Session) -> int:
    """Returns the id of the singleton global ("U") equipo row.

    The global equipo backs the legacy (pre-teams) color behavior: it is the
    default layer used when a caller does not pass an explicit `equipo_id`.
    """
    equipo = db.query(Equipo).filter(Equipo.es_global.is_(True)).first()
    if equipo is None:
        raise HTTPException(status_code=500, detail="Equipo global no configurado")
    return equipo.id


def puede_escribir_layer(db: Session, user: Usuario, equipo_id: int) -> None:
    """Raises HTTPException(403) unless `user` may write the color layer for `equipo_id`.

    Allowed when either:
    - the user is a member of `equipo_id` (any rol), or
    - `equipo_id` is the global ("U") equipo and the user holds the
      `productos.marcar_color` permission (preserves today's exact rule for
      the default layer).
    """
    from app.services.permisos_service import verificar_permiso

    es_miembro = (
        db.query(EquipoMiembro)
        .filter(EquipoMiembro.equipo_id == equipo_id, EquipoMiembro.usuario_id == user.id)
        .first()
        is not None
    )
    if es_miembro:
        return

    if equipo_id == get_global_equipo_id(db) and verificar_permiso(db, user, "productos.marcar_color"):
        return

    raise HTTPException(status_code=403, detail="No tienes permiso para marcar colores en este equipo")


def color_slot(vista: Optional[str]) -> InstrumentedAttribute:
    """Returns the ProductoColor column matching the given view ('ml'/None or 'tienda')."""
    from app.models.equipo import ProductoColor

    if vista == "tienda":
        return ProductoColor.color_tienda
    return ProductoColor.color_ml


def resolver_layer_activo(
    equipo_id: Optional[int],
    current_user: Usuario,
    db: Session,
    global_equipo_id: Optional[int] = None,
) -> int:
    """Resolves the active color layer for a read request.

    - `equipo_id` is None -> the global ("U") layer (today's default behavior).
    - `equipo_id` == the global layer id -> always allowed.
    - Any other `equipo_id` -> the caller must be a member of that team, else 403.

    `global_equipo_id`: pass the already-resolved global equipo id (from a prior
    `get_global_equipo_id(db)` call) to avoid a redundant lookup when the caller
    also needs the global layer id for its own logic (e.g. computing hints).

    Returns the resolved equipo_id to read colors from.
    """
    global_id = global_equipo_id if global_equipo_id is not None else get_global_equipo_id(db)

    if equipo_id is None:
        return global_id

    if equipo_id == global_id:
        return equipo_id

    es_miembro = (
        db.query(EquipoMiembro)
        .filter(EquipoMiembro.equipo_id == equipo_id, EquipoMiembro.usuario_id == current_user.id)
        .first()
        is not None
    )
    if not es_miembro:
        raise HTTPException(status_code=403, detail="No sos miembro de este equipo")

    return equipo_id


def join_color_layer(query: Query, equipo_id: int) -> Query:
    """Outer-joins `ProductoColor` scoped to `equipo_id` onto `query`.

    Joins on `ProductoERP.item_id`, so `query` must already select/join
    `ProductoERP`. The join is added for filtering purposes (see
    `filtro_colores`); the joined entity does not need to be added to the
    query's selected columns.
    """
    from app.models.equipo import ProductoColor
    from app.models.producto import ProductoERP

    return query.outerjoin(
        ProductoColor,
        and_(ProductoColor.item_id == ProductoERP.item_id, ProductoColor.equipo_id == equipo_id),
    )


def filtro_colores(query: Query, colores_str: Optional[str], slot: InstrumentedAttribute) -> Query:
    """Applies the color sidebar filter against `slot` (a ProductoColor column).

    Behavior-identical to the legacy filter against
    `productos_pricing.color_marcado[_tienda]`: `colores_str` is a
    comma-separated list of color values, optionally including the
    "sin_color" sentinel meaning "no color assigned" (slot IS NULL).
    """
    if not colores_str:
        return query

    colores_list = colores_str.split(",")

    if "sin_color" in colores_list:
        colores_con_valor = [c for c in colores_list if c != "sin_color"]
        if colores_con_valor:
            return query.filter(or_(slot.in_(colores_con_valor), slot.is_(None)))
        return query.filter(slot.is_(None))

    return query.filter(slot.in_(colores_list))


def batch_colores(db: Session, item_ids: List[int], equipo_id: int) -> dict:
    """Batch-fetches `ProductoColor` rows for `item_ids` at `equipo_id`.

    Returns a dict keyed by item_id, mirroring the batch-lookup pattern
    already used across productos_listing.py (e.g. tn_precios).
    """
    from app.models.equipo import ProductoColor

    if not item_ids:
        return {}

    # Chunk to stay well under SQLite's 999-variable limit and Postgres' 65535-param
    # limit on large unpaginated listings/exports.
    chunk_size = 900
    result: dict = {}
    for start in range(0, len(item_ids), chunk_size):
        chunk = item_ids[start : start + chunk_size]
        rows = (
            db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo_id, ProductoColor.item_id.in_(chunk)).all()
        )
        result.update({row.item_id: row for row in rows})
    return result


def parsear_tiendas_oficiales_mla(csv: Optional[str]) -> Optional[Tuple[List[int], bool]]:
    """
    Parsea CSV de tiendas oficiales para filtrar MLAs.

    Acepta IDs numéricos y el literal 'sin_tienda'.
    Retorna (lista_ids, incluir_sin_tienda) o None si el filtro no debe aplicarse.

    Raises HTTPException(400) si encuentra un token inválido (no numérico y distinto de 'sin_tienda').

    Promoted from `productos_export.py` (promos-catalog-prices-and-official-store,
    slice A) so it can be shared with `productos_listing.py` and the publication
    tree service — same behavior, same 400 on bad token.
    """
    if not csv:
        return None
    tokens = [t.strip() for t in csv.split(",") if t.strip()]
    if not tokens:
        return None
    ids: List[int] = []
    incluir_sin_tienda = False
    for token in tokens:
        if token == "sin_tienda":
            # 'sin_tienda' es sentinel para mlp_official_store_id IS NULL (productos publicados sin tienda oficial).
            incluir_sin_tienda = True
        else:
            try:
                ids.append(int(token))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Token inválido en tiendas_oficiales: '{token}'. Esperado: int o 'sin_tienda'.",
                )
    return (ids, incluir_sin_tienda)


def build_filtro_tiendas_oficiales_mla(
    parsed: Tuple[List[int], bool],
) -> Optional[ColumnElement[bool]]:
    """
    Construye la expresión SQLAlchemy para filtrar MLAs por tienda oficial.
    Retorna una expresión que se puede usar en .filter() sobre MercadoLibreItemPublicado.

    parsed: tupla (lista_ids, incluir_sin_tienda) del parser.

    El retorno puede ser:
      - `BinaryExpression` (1 sola condición: `.in_(...)` o `.is_(None)`)
      - `BooleanClauseList` (2 condiciones combinadas con `or_(...)`)
      - `None` (si parsed no produce condiciones, ej. ([], False))

    Ambas variantes concretas heredan de `ColumnElement[bool]` en SQLAlchemy 2.0+,
    que es el ancestro común correcto para tipar el retorno.

    Promoted from `productos_export.py` (promos-catalog-prices-and-official-store,
    slice A).
    """
    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

    ids, incluir_sin_tienda = parsed
    condiciones = []
    if ids:
        condiciones.append(MercadoLibreItemPublicado.mlp_official_store_id.in_(ids))
    if incluir_sin_tienda:
        condiciones.append(MercadoLibreItemPublicado.mlp_official_store_id.is_(None))
    if not condiciones:
        return None
    if len(condiciones) == 1:
        return condiciones[0]
    return or_(*condiciones)


def aplicar_filtros_cross_db_masivo(query, db: Session, filtros: Optional[dict]):
    """Folds the cross-DB (mlwebhook) listing filters — promos and wholesale
    tiers — into a MASS-WRITE query.

    Why it lives here and not next to the two copies in `productos_listing`/
    `productos_export`: those two own their fold because they own its 503
    wording and their own tests. This is the third consumer, and the write
    paths (`calcular-web-masivo`, `calcular-pvp-masivo`,
    `recalcular-cuotas-masivo`) share one contract that neither of the other
    two states, so it gets stated once, here:

    FAIL-CLOSED, twice over.

    * Resolver unreachable -> HTTP 503, the run does not start. These
      endpoints already narrow by `search`/`marcas`/`con_stock`, so the
      operator reads "aplicar filtros" as "the products I am looking at".
      Running anyway would silently widen that set, and a too-broad write is
      a repair job while a 503 is a retry.
    * Empty result set -> zero products, never the unfiltered catalog. Same
      guard, same reason, as the listing's.

    `filtros` mirrors the listing's param names (`promo_tipos`,
    `promo_estado`, `con_promo_aplicada`, `con_promo_sin_aplicar`,
    `con_pxq`); an absent key means "filter off" and costs no query.
    """
    from app.models.producto import ProductoERP
    from app.models.publicacion_ml import PublicacionML
    from sqlalchemy import false as sa_false
    from sqlalchemy.exc import SQLAlchemyError

    if not filtros:
        return query

    def _fold(resolver, log_context: str, detail: str):
        nonlocal query
        try:
            mlas = resolver()
        except (RuntimeError, SQLAlchemyError) as exc:
            logger.warning("%s no disponible (masivo): %s", log_context, exc)
            raise HTTPException(status_code=503, detail=detail) from exc
        if not mlas:
            query = query.filter(sa_false())
            return
        items_subquery = (
            db.query(PublicacionML.item_id).filter(PublicacionML.mla.in_(mlas)).distinct().scalar_subquery()
        )
        query = query.filter(ProductoERP.item_id.in_(items_subquery))

    promo_estado = filtros.get("promo_estado")
    if promo_estado is not None and promo_estado not in ("disponible", "aplicada", "sin_aplicar"):
        raise HTTPException(
            status_code=422,
            detail="promo_estado inválido: debe ser 'disponible', 'aplicada' o 'sin_aplicar'",
        )

    promo_tipos = filtros.get("promo_tipos")
    tipos_list = [t.strip() for t in promo_tipos.split(",") if t.strip()] if promo_tipos else []
    resolver_entry = select_promo_resolver(
        PromoResolverFns(
            active_promo_type=fetch_mlas_with_active_promo_type,
            started=fetch_mlas_with_started,
            candidate_only=fetch_mlas_with_candidate_only,
            candidate_only_for_types=fetch_mlas_with_candidate_only_for_types,
        ),
        tipos_list or None,
        promo_estado,
        filtros.get("con_promo_aplicada"),
        filtros.get("con_promo_sin_aplicar"),
    )
    if resolver_entry:
        resolver, log_context = resolver_entry
        _fold(resolver, log_context, "Filtro de promociones no disponible temporalmente")

    if filtros.get("con_pxq"):
        _fold(
            fetch_mlas_with_pxq_tiers,
            "Filtro precios mayoristas (PxQ)",
            "Filtro de precios mayoristas no disponible temporalmente",
        )

    return query
