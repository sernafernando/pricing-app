"""PARA GANAR advisor — read-only MLA queue for the sandbox/advisor UI.

Intent: docs/para-ganar-pro-source-map.md. Unit of work is MLA (sync pairs
surfaced via inventory_id when present). No suggestion engine yet.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
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


def _precio_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)  # type: ignore[arg-type]


@router.get(
    "/cola",
    response_model=ParaGanarColaResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_cola(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None, max_length=120, description="Filter by MLA, codigo or title"),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> ParaGanarColaResponse:
    """Paginated active MLAs from the local sandbox (joined with ERP + price + sync)."""
    offset = (page - 1) * page_size
    q_norm = (q or "").strip()
    params: dict = {"limit": page_size, "offset": offset}
    where_extra = ""
    if q_norm:
        params["q"] = f"%{q_norm}%"
        where_extra = """
          AND (
            p.mla ILIKE :q
            OR COALESCE(p.codigo, '') ILIKE :q
            OR COALESCE(p.item_title, '') ILIKE :q
            OR COALESCE(e.descripcion, '') ILIKE :q
          )
        """

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
