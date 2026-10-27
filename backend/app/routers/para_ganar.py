"""PARA GANAR advisor — MLA queue + per-MLA criteria persistence.

Intent: docs/para-ganar-pro-source-map.md. Unit of work is MLA (sync pairs
surfaced via inventory_id when present). No suggestion engine yet.
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
from app.core.database import get_db
from app.models.para_ganar_catalog_seller import (
    DISPOSITION_ACTIVE,
    DISPOSITION_VALUES,
    ParaGanarCatalogSeller,
)
from app.models.para_ganar_criterio_mla import ParaGanarCriterioMla
from app.models.usuario import Usuario

router = APIRouter(prefix="/para-ganar", tags=["PARA GANAR"])


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
    # Placeholder until criteria produce real suggestion states.
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


class ParaGanarAlcanceOpciones(BaseModel):
    marcas: List[str]
    subcategorias: List[ParaGanarSubcategoriaOpcion]
    pms: List[ParaGanarPmOpcion]


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


def _build_alcance_where(
    *,
    q_norm: str,
    marcas: list[str],
    subcategorias: list[int],
    pms: list[int],
    params: dict,
) -> str:
    """Append scope filters shared by count + page queries. Mutates `params`."""
    clauses: list[str] = []

    if q_norm:
        params["q"] = f"%{q_norm}%"
        clauses.append(
            """
          AND (
            p.mla ILIKE :q
            OR COALESCE(p.codigo, '') ILIKE :q
            OR COALESCE(p.item_title, '') ILIKE :q
            OR COALESCE(e.descripcion, '') ILIKE :q
            OR COALESCE(e.marca, '') ILIKE :q
          )
            """
        )

    if marcas:
        placeholders = []
        for i, marca in enumerate(marcas):
            key = f"marca_{i}"
            params[key] = marca.upper()
            placeholders.append(f":{key}")
        clauses.append(f" AND UPPER(e.marca) IN ({', '.join(placeholders)})")

    if subcategorias:
        placeholders = []
        for i, subcat_id in enumerate(subcategorias):
            key = f"subcat_{i}"
            params[key] = subcat_id
            placeholders.append(f":{key}")
        clauses.append(f" AND e.subcategoria_id IN ({', '.join(placeholders)})")

    if pms:
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

    return "".join(clauses)


@router.get(
    "/alcance-opciones",
    response_model=ParaGanarAlcanceOpciones,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_alcance_opciones(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarAlcanceOpciones:
    """Distinct marcas/subcats/PMs for the PARA GANAR scope filter bar."""
    marcas_rows = db.execute(
        text(
            """
            SELECT DISTINCT e.marca
            FROM productos_erp e
            JOIN publicaciones_ml p ON p.item_id = e.item_id AND p.activo = true
            WHERE e.marca IS NOT NULL AND e.marca <> ''
            ORDER BY e.marca
            """
        )
    ).all()

    subcat_rows = (
        db.execute(
            text(
                """
            SELECT DISTINCT e.subcategoria_id AS id,
              COALESCE(sg.nombre_subcategoria, CAST(e.subcategoria_id AS TEXT)) AS nombre
            FROM productos_erp e
            JOIN publicaciones_ml p ON p.item_id = e.item_id AND p.activo = true
            LEFT JOIN subcategorias_grupos sg ON sg.subcat_id = e.subcategoria_id
            WHERE e.subcategoria_id IS NOT NULL
            ORDER BY nombre
            """
            )
        )
        .mappings()
        .all()
    )

    pm_rows = (
        db.execute(
            text(
                """
            SELECT DISTINCT u.id, COALESCE(u.nombre, u.username) AS nombre
            FROM usuarios u
            JOIN marcas_pm mp ON mp.usuario_id = u.id
            WHERE u.activo = true
            ORDER BY nombre
            """
            )
        )
        .mappings()
        .all()
    )

    return ParaGanarAlcanceOpciones(
        marcas=[row[0] for row in marcas_rows],
        subcategorias=[
            ParaGanarSubcategoriaOpcion(id=int(row["id"]), nombre=str(row["nombre"])) for row in subcat_rows
        ],
        pms=[ParaGanarPmOpcion(id=int(row["id"]), nombre=str(row["nombre"])) for row in pm_rows],
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
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarColaResponse:
    """Paginated active MLAs from the local sandbox (joined with ERP + price + sync)."""
    offset = (page - 1) * page_size
    q_norm = (q or "").strip()
    marcas_list = _split_csv(marcas)
    subcat_list: list[int] = []
    for raw in _split_csv(subcategorias):
        try:
            subcat_list.append(int(raw))
        except ValueError:
            continue
    pm_list: list[int] = []
    for raw in _split_csv(pms):
        try:
            pm_list.append(int(raw))
        except ValueError:
            continue

    params: dict = {"limit": page_size, "offset": offset}
    where_extra = _build_alcance_where(
        q_norm=q_norm,
        marcas=marcas_list,
        subcategorias=subcat_list,
        pms=pm_list,
        params=params,
    )

    # PM filter with no marcas_pm rows → empty universe (same as /productos).
    if pm_list:
        pm_pair_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM marcas_pm
                WHERE usuario_id IN ({})
                """.format(", ".join(f":pm_check_{i}" for i in range(len(pm_list))))
            ),
            {f"pm_check_{i}": pm_id for i, pm_id in enumerate(pm_list)},
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
              l.inventory_id
            FROM publicaciones_ml p
            JOIN productos_erp e ON e.item_id = p.item_id
            LEFT JOIN precios_ml pm
              ON pm.item_id = p.item_id
             AND pm.pricelist_id = p.pricelist_id
            LEFT JOIN ml_publication_links l ON l.mla = p.mla
            WHERE p.activo = true
            {where_extra}
            ORDER BY p.codigo NULLS LAST, p.lista_nombre NULLS LAST, p.mla
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


def _criterios_defaults(mla: str) -> ParaGanarCriteriosMla:
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
    )


def _criterios_from_row(row: ParaGanarCriterioMla) -> ParaGanarCriteriosMla:
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
        updated_at=row.updated_at,
    )


def _mla_exists(db: Session, mla: str) -> bool:
    found = db.execute(
        text("SELECT 1 FROM publicaciones_ml WHERE mla = :mla AND activo = true LIMIT 1"),
        {"mla": mla},
    ).first()
    return found is not None


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
    row = db.get(ParaGanarCriterioMla, mla_norm)
    if row is None:
        return _criterios_defaults(mla_norm)
    return _criterios_from_row(row)


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
    return _criterios_from_row(row)


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
    sellers: List[ParaGanarCatalogSellerItem]


class ParaGanarCatalogSellerDispositionUpdate(BaseModel):
    seller_id: str = Field(min_length=1, max_length=32)
    disposition: str

    @field_validator("disposition")
    @classmethod
    def _disposition_ok(cls, value: str) -> str:
        if value not in DISPOSITION_VALUES:
            raise ValueError(f"disposition inválida: {value}")
        return value


class ParaGanarCatalogSellersUpsert(BaseModel):
    sellers: List[ParaGanarCatalogSellerDispositionUpdate] = Field(min_length=1)


def _catalog_product_id_for_mla(db: Session, mla: str) -> Optional[str]:
    # Prefer publication links; fall back to any competition snapshot for this MLA.
    # Avoid the Postgres-only latest view so SQLite unit tests stay portable.
    from sqlalchemy.exc import OperationalError, ProgrammingError

    try:
        link = db.execute(
            text(
                """
                SELECT catalog_product_id
                FROM ml_publication_links
                WHERE mla = :mla AND catalog_product_id IS NOT NULL
                LIMIT 1
                """
            ),
            {"mla": mla},
        ).first()
        if link and link[0]:
            return str(link[0])
    except (OperationalError, ProgrammingError):
        db.rollback()

    try:
        snap = db.execute(
            text(
                """
                SELECT catalog_product_id
                FROM ml_catalog_competition
                WHERE mla = :mla AND catalog_product_id IS NOT NULL
                ORDER BY fecha_consulta DESC
                LIMIT 1
                """
            ),
            {"mla": mla},
        ).first()
        if snap and snap[0]:
            return str(snap[0])
    except (OperationalError, ProgrammingError):
        db.rollback()
    return None


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
            disposition=row.disposition or DISPOSITION_ACTIVE,
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
    return ParaGanarCatalogSellersResponse(
        mla=mla,
        catalog_product_id=catalog_product_id,
        synced_from_competition=synced_from_competition,
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
