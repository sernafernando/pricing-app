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


class ParaGanarCriteriosMla(BaseModel):
    mla: str
    source: str = Field(description="mla when a row exists, otherwise default")
    markup_min: Optional[float] = None
    markup_max: Optional[float] = None
    top_sellers: Optional[int] = Field(default=None, ge=1, le=50)
    precio_min: Optional[float] = None
    precio_max: Optional[float] = None
    ganar_catalogo: bool = True
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
    ganar_catalogo: bool = True
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
    return ParaGanarCriteriosMla(mla=mla, source="default")


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
