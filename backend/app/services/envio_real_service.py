"""
envio_real_service — resolves the real ML shipping cost for a product.

Replaces static ProductoERP.envio with MAX(list_cost) from ml_seller_shipping_costs
in the mlwebhook DB. All consumers that need a shipping cost for pricing or display
MUST call resolver_costo_envio (single) or resolver_costos_envio_batch (bulk).

Design decisions (ADR):
  1. New module isolates cross-DB I/O from the pure pricing formula.
  2. MAX computed in Python because the mla→item_id mapping lives in the main DB;
     cross-DB GROUP BY is not possible.
  3. Batch dict is keyed by item_id for O(1) lookup in listing loops.
  4. list_cost is stored WITH IVA in ml_seller_shipping_costs → returned AS-IS.
     calcular_limpio performs the /1.21 division; this module must NOT do it.
  5. Broad try/except on every cross-DB call → graceful ERP fallback, never raises.
  6. A PM may choose another cost for a product (`producto_envio_eleccion`, S7b): one publication's own cost
     (`mla`), the simple mean of the active MLAs' costs (`promedio`) or their mean weighted by the units each sold in
     the last 30 days (`ponderado`; no sales -> `promedio`). No row, or `max`, is the MAX above. A chosen MLA that is
     inactive or has no cost falls back to the MAX. Applied inside both resolvers, so every product-pricing caller
     gets it; the choices are read in ONE statement and the units sold in ONE more, only for `ponderado` products.
  7. ML charges the seller by item-price bracket. ml-webhook stores list_cost at the sale price and every
     bracket's cost (`cost_by_bracket`); a cost read with brackets is a `CostoEnvioTramos` (envio_tramos): the
     same float for display, which `calcular_limpio` resolves at the price it evaluates. Every aggregation here
     (MAX, choice, means) also runs bracket by bracket, so no caller needs the price to get the right bracket.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import ARRAY, Integer, any_, literal, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_mlwebhook_engine
from app.models.producto import ProductoERP
from app.models.producto_envio_eleccion import ProductoEnvioEleccion
from app.models.publicacion_ml import PublicacionML
from app.services.envio_tramos import CostoEnvioTramos, por_tramo

logger = logging.getLogger(__name__)

MODOS_ENVIO = ("max", "mla", "promedio", "ponderado")
MODO_DEFAULT = "max"
DIAS_PONDERADO = 30  # the sales window a stored `ponderado` resolves with


# ---------------------------------------------------------------------------
# Internal cross-DB helper
# ---------------------------------------------------------------------------


def _query_list_cost_by_mla(mla_ids: list[str]) -> dict[str, float]:
    """
    Query ml_seller_shipping_costs in the mlwebhook DB for the given MLA IDs; RAISES on any error.

    Returns {mla_id: list_cost} for rows where list_cost > 0 (or with a bracket that costs > 0) and
    currency_id = 'ARS'. list_cost is the cost at the
    publication's sale price; a row with `cost_by_bracket` comes back as a `CostoEnvioTramos` (still that float)
    that `calcular_limpio` evaluates at the price it prices. `cost_by_bracket` is read through `to_jsonb(row)`, so
    the query also works before ml-webhook's migration adds the column (it is then NULL: a plain float).

    list_cost is stored WITH IVA — returned as-is; caller decides what to do with it.

    The ids travel as ONE JSON text parameter, unnested server side (as `fetch_inputs` does): bound as an array of
    N text elements the driver quotes and the server parses N literals, and ~24k MLAs make that visible.
    """
    result: dict[str, float] = {}
    if not mla_ids:
        return result

    engine = get_mlwebhook_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT mla_id, list_cost, to_jsonb(s) -> 'cost_by_bracket' AS tramos
                FROM ml_seller_shipping_costs s
                WHERE mla_id = ANY(ARRAY(SELECT jsonb_array_elements_text(CAST(:ids AS jsonb))))
                  AND list_cost IS NOT NULL
                  AND list_cost >= 0
                  AND currency_id = 'ARS'
                """
            ),
            {"ids": json.dumps(mla_ids)},
        ).fetchall()
    for row in rows:
        cost = CostoEnvioTramos.desde_fila(float(row.list_cost), row.tramos)
        # A 0 at the sale price (a promo under the free-shipping floor) still has its brackets' costs
        if cost > 0 or (isinstance(cost, CostoEnvioTramos) and cost.cobra()):
            result[row.mla_id] = cost
    return result


def _fetch_list_cost_by_mla(mla_ids: list[str]) -> dict[str, float]:
    """`_query_list_cost_by_mla`, returning an empty dict on any error (DB unreachable, table missing, etc.)."""
    try:
        return _query_list_cost_by_mla(mla_ids)
    except Exception as exc:
        logger.warning("No se pudo consultar ml_seller_shipping_costs: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Single-product resolver
# ---------------------------------------------------------------------------


def resolver_costo_envio(
    db: Session,
    producto: ProductoERP,
    *,
    mlas_activas: Optional[list[PublicacionML]] = None,
) -> float:
    """
    Return the resolved shipping cost (ARS, with IVA) for a single product.

    Resolution strategy:
      1. Load active PublicacionML rows for the product (uses mlas_activas if provided).
      2. Query ml_seller_shipping_costs for those MLA IDs via _fetch_list_cost_by_mla.
      3. Apply the product's stored choice (`producto_envio_eleccion`); without one, MAX(list_cost).
      4. If a cost is available, return it.
      5. Otherwise return ProductoERP.envio (ERP fallback).

    This function NEVER raises. All cross-DB exceptions are caught internally.

    Args:
        db: Main application DB session.
        producto: ProductoERP instance (used for item_id and fallback envio).
        mlas_activas: Pre-loaded list of PublicacionML rows (avoids repeated query).
                      If None, they are loaded from the DB.

    Returns:
        Shipping cost in ARS with IVA, as a float.
    """
    # Step 1: resolve active MLAs
    if mlas_activas is None:
        pubs: list[PublicacionML] = db.query(PublicacionML).filter(PublicacionML.item_id == producto.item_id).all()
    else:
        pubs = mlas_activas

    active_mla_ids = [p.mla for p in pubs if p.activo]

    if not active_mla_ids:
        return float(producto.envio or 0.0)

    # Step 2: fetch shipping costs from mlwebhook DB
    costs = _fetch_list_cost_by_mla(active_mla_ids)
    if not costs:
        return float(producto.envio or 0.0)

    # Step 3: the PM's choice, else MAX, in Python (cross-DB GROUP BY is not possible)
    resolved = _resolve_by_item(db, {producto.item_id: active_mla_ids}, costs)
    return resolved.get(producto.item_id, costo_envio_maximo(costs, producto.envio))


def costos_envio_por_mla(mla_ids: Sequence[str]) -> dict[str, float]:
    """{mla: list_cost} (ARS, with IVA) for the given MLAs, in ONE cross-DB read; RAISES when the read fails.

    MLAs without a usable cost are absent. Public face of the read `resolver_costo_envio` does, for a caller that
    needs each publication's own cost instead of the MAX and must tell a failed read from missing data."""
    return _query_list_cost_by_mla(list(mla_ids))


def costo_envio_maximo(costs: Mapping[str, float], fallback: Optional[float]) -> float:
    """The resolved shipping cost of a product from its active MLAs' costs: their MAX, else the ERP `envio`."""
    if not costs:
        return float(fallback or 0.0)
    return por_tramo(lambda cs: max(cs.values()), costs)  # type: ignore[return-value]  # costs is not empty


def _in_item_ids(db: Session, column: Any, item_ids: Sequence[int]) -> Any:
    """`column IN item_ids` as ONE array parameter on PostgreSQL (not N binds); an expanding bind elsewhere."""
    ids = list(item_ids)
    if db.get_bind().dialect.name == "postgresql":
        return column == any_(literal(ids, ARRAY(Integer)))
    return column.in_(ids)  # portable (SQLite in tests): expanding bind, still one statement


def mlas_activas(db: Session, item_id: int) -> list[str]:
    """The MLAs of the active publications of one product (the read the resolvers use)."""
    return _active_mlas_by_item(db, [item_id]).get(item_id, [])


def _active_mlas_by_item(db: Session, item_ids: Sequence[int]) -> dict[int, list[str]]:
    """
    The MLAs of the ACTIVE publications of each product, read as two plain columns in ONE statement.

    Loading `PublicacionML` entities builds every column of every publication (~24k objects, ~0.5 s on a
    25k-publication store) to read `mla` and `activo`. On PostgreSQL the ids travel as one array parameter.
    """
    found: dict[int, list[str]] = {}
    # A read-only lookup: it must not flush the caller's pending objects as a side effect.
    in_ids = _in_item_ids(db, PublicacionML.item_id, item_ids)
    with db.no_autoflush:
        rows = db.execute(
            select(PublicacionML.item_id, PublicacionML.mla).where(in_ids, PublicacionML.activo.is_(True))
        ).all()
    for item_id, mla in rows:
        found.setdefault(item_id, []).append(mla)
    return found


# ---------------------------------------------------------------------------
# Batch resolver
# ---------------------------------------------------------------------------


def resolver_costos_envio_batch(
    db: Session,
    item_ids: list[int],
    *,
    pubs_by_item: Optional[Mapping[int, Sequence[Any]]] = None,
) -> dict[int, float]:
    """
    Return resolved shipping costs for a batch of products.

    Returns a dict keyed by item_id. Items for which no real cost is found
    (no active MLAs, no list_cost, or DB unreachable) are ABSENT from the result.
    Callers should use .get(item_id) and fall back to ProductoERP.envio when None.

    This function NEVER raises. All cross-DB exceptions are caught; on any failure
    the entire batch returns {} so callers fall back to ERP envio for all items.

    Args:
        db: Main application DB session.
        item_ids: List of item IDs to resolve.
        pubs_by_item: Pre-computed {item_id: [publication, ...]} mapping; each publication needs
                      `mla` and `activo`. When provided, the publications are not read again (the stored
                      choices still are, in one statement).

    Returns:
        {item_id: cost} for items that have a resolvable real cost: the PM's chosen cost, else the MAX list_cost.
    """
    if not item_ids:
        return {}

    # Step 1: build active MLA sets per item
    item_to_active_mlas: dict[int, list[str]] = {}
    all_active_mlas: list[str] = []

    if pubs_by_item is None:
        item_to_active_mlas = _active_mlas_by_item(db, item_ids)
        for mlas in item_to_active_mlas.values():
            all_active_mlas.extend(mlas)
    else:
        for item_id in item_ids:
            active_ids = [p.mla for p in pubs_by_item.get(item_id, []) if p.activo]
            if active_ids:
                item_to_active_mlas[item_id] = active_ids
                all_active_mlas.extend(active_ids)

    if not all_active_mlas:
        return {}

    # Step 2: one cross-DB query for all MLAs
    try:
        costs = _fetch_list_cost_by_mla(list(set(all_active_mlas)))
    except Exception as exc:
        # _fetch already catches internally, but guard here for safety
        logger.warning("resolver_costos_envio_batch: error inesperado: %s", exc)
        return {}

    if not costs:
        return {}

    # Step 3: the PM's choice per item, else MAX
    return _resolve_by_item(db, item_to_active_mlas, costs)


# ---------------------------------------------------------------------------
# The PM's choice (S7b)
# ---------------------------------------------------------------------------


def hoy() -> date:
    """Today in the business timezone (Métricas ML's own day)."""
    from app.services.ml_daily_metrics.board import today_business  # lazy: keeps this module's imports light

    return today_business()


def periodo_ponderado() -> tuple[date, date]:
    """The last `DIAS_PONDERADO` business days, today included: the window a stored `ponderado` resolves with."""
    last = hoy()
    return last - timedelta(days=DIAS_PONDERADO - 1), last


def unidades_vendidas_por_mla(db: Session, mlas: Sequence[str], date_from: date, date_to: date) -> Mapping[str, int]:
    """Units sold per MLA in `[date_from, date_to]`, from Métricas ML's own base (`UnitsSoldProvider`, the source the
    Publicaciones screen spreads Ads over). One statement; a failure propagates (the resolvers catch it inside a
    savepoint and resolve `ponderado` as `promedio`; the options endpoint lets it fail)."""
    from app.services.ml_publications.view.units_sold import UnitsSoldProvider  # lazy: avoids an import cycle

    return UnitsSoldProvider().units_by_mla(db, list(mlas), date_from, date_to)


def _unidades_aisladas(db: Session, mlas: Sequence[str], date_from: date, date_to: date) -> Mapping[str, int]:
    """`unidades_vendidas_por_mla` inside a CONNECTION-level savepoint, with autoflush off: a failed read must not
    abort the caller's transaction (Productos keeps working) and, being a read, must not flush the caller's pending
    objects (`Session.begin_nested` would flush them on entry). A failure is the rule for no sales: `{}`, so a
    `ponderado` product resolves to `promedio`."""
    connection = db.connection()  # the session's own connection; getting it does not flush
    savepoint = connection.begin_nested()
    try:
        with db.no_autoflush:
            units = unidades_vendidas_por_mla(db, mlas, date_from, date_to)
    except SQLAlchemyError as exc:
        savepoint.rollback()
        logger.warning("No se pudieron leer las ventas para el envio ponderado: %s", exc)
        return {}
    savepoint.commit()
    return units


def elecciones_por_item(db: Session, item_ids: Sequence[int]) -> dict[int, tuple[str, Optional[str]]]:
    """{item_id: (modo, mla)} of the stored choices of `item_ids`, in ONE statement; products without one are
    absent (they resolve to `max`)."""
    in_ids = _in_item_ids(db, ProductoEnvioEleccion.item_id, item_ids)
    with db.no_autoflush:
        rows = db.execute(
            select(ProductoEnvioEleccion.item_id, ProductoEnvioEleccion.modo, ProductoEnvioEleccion.mla).where(in_ids)
        ).all()
    return {item_id: (modo, mla) for item_id, modo, mla in rows}


def costo_promedio(costs: Mapping[str, float]) -> Optional[float]:
    """The simple mean of the given MLAs' costs; None without any. Bracket by bracket too (`por_tramo`)."""
    if not costs:
        return None
    return por_tramo(lambda cs: round(sum(cs.values()) / len(cs), 2), costs)


def costo_ponderado(costs: Mapping[str, float], units: Mapping[str, int]) -> Optional[float]:
    """The mean of the given MLAs' costs weighted by their units sold; None when none of them sold. Bracket by
    bracket too (`por_tramo`), with the same weights."""
    total = sum(units.get(mla, 0) for mla in costs)
    if total <= 0:
        return None
    return por_tramo(lambda cs: round(sum(cost * units.get(mla, 0) for mla, cost in cs.items()) / total, 2), costs)


def eleccion_cae_a_maximo(modo: str, mla: Optional[str], costs: Mapping[str, float]) -> bool:
    """A stored `mla` choice whose publication is not among the active ones with a cost: it resolves to the MAX."""
    return modo == "mla" and (mla is None or mla not in costs)


def costo_envio_elegido(
    modo: str, mla: Optional[str], costs: Mapping[str, float], units: Mapping[str, int]
) -> Optional[float]:
    """The cost of a product under a choice. `costs` holds ONLY its active MLAs that have a cost; `units` their
    units sold (read only for `ponderado`). None when no MLA has a cost (callers fall back to the ERP envio).

    `mla`: that publication's cost, else MAX. `promedio`: the simple mean. `ponderado`: the sales-weighted mean,
    `promedio` without sales. Anything else (`max`, no choice): MAX. Bracketed costs resolve bracket by bracket
    (`por_tramo`): a product's MAX at 41999 is the MAX of its MLAs' costs at 41999."""
    if not costs:
        return None
    return por_tramo(lambda cs: _costo_elegido(modo, mla, cs, units), costs)


def _costo_elegido(
    modo: str, mla: Optional[str], costs: Mapping[str, float], units: Mapping[str, int]
) -> Optional[float]:
    """`costo_envio_elegido` on plain floats."""
    if modo == "mla" and not eleccion_cae_a_maximo(modo, mla, costs):
        return costs[mla]  # type: ignore[index]  # not None: checked above
    if modo == "promedio":
        return costo_promedio(costs)
    if modo == "ponderado":
        ponderado = costo_ponderado(costs, units)
        return ponderado if ponderado is not None else costo_promedio(costs)
    return max(costs.values())


def _resolve_by_item(
    db: Session, item_to_active_mlas: Mapping[int, Sequence[str]], costs: Mapping[str, float]
) -> dict[int, float]:
    """{item_id: the cost its stored choice resolves to, else MAX list_cost of its active MLAs}; items whose MLAs
    have no cost are absent. One read of the choices, one sales read for the `ponderado` products (if any)."""
    per_item: dict[int, dict[str, float]] = {}
    for item_id, mla_ids in item_to_active_mlas.items():
        item_costs = {mla: costs[mla] for mla in mla_ids if mla in costs}
        if item_costs:
            per_item[item_id] = item_costs
    if not per_item:
        return {}
    choices = elecciones_por_item(db, list(per_item))
    ponderados = [item_id for item_id, (modo, _) in choices.items() if modo == "ponderado"]
    units: Mapping[str, int] = {}
    if ponderados:
        first, last = periodo_ponderado()
        mlas = sorted({mla for item_id in ponderados for mla in item_to_active_mlas[item_id]})
        units = _unidades_aisladas(db, mlas, first, last)
    result: dict[int, float] = {}
    for item_id, item_costs in per_item.items():
        modo, mla = choices.get(item_id, (MODO_DEFAULT, None))
        value = costo_envio_elegido(modo, mla, item_costs, units)
        if value is not None:
            result[item_id] = value
    return result


def costo_envio_producto(
    db: Session, item_id: int, active_mlas: Sequence[str], costs: Mapping[str, float]
) -> tuple[Optional[float], str]:
    """The product's shipping cost from its active MLAs' `costs`, exactly as `resolver_costos_envio_batch` resolves
    it (the PM's choice, else the MAX), and the stored mode (`max` without a choice). `None` when no MLA has a cost.

    For a caller that already read the costs (`precio_variantes_envio`) and must not read mlwebhook twice."""
    value = _resolve_by_item(db, {item_id: list(active_mlas)}, costs).get(item_id)
    if value is None:
        return None, MODO_DEFAULT
    return value, elecciones_por_item(db, [item_id]).get(item_id, (MODO_DEFAULT, None))[0]


@dataclass(frozen=True)
class CostosEnvio:
    """The real shipping costs of a request: the product's cost (its PM choice, else the MAX) and each publication's
    own list_cost.

    `por_producto` is `resolver_costos_envio_batch`'s answer; `por_mla` holds the own cost of each asked MLA.
    Both omit what has no usable cost (callers fall back: own -> product MAX -> ERP)."""

    por_producto: dict[int, float] = field(default_factory=dict)
    por_mla: dict[str, float] = field(default_factory=dict)


def resolver_costos_envio_mlas(db: Session, item_ids: list[int], mla_ids: Sequence[str]) -> CostosEnvio:
    """
    `resolver_costos_envio_batch` for `item_ids` plus the own list_cost of each MLA in `mla_ids`, in ONE
    cross-DB read.

    An asked MLA is read even when its publication is inactive (it still has a shipping cost of its own), but only
    the ACTIVE MLAs of a product count for its cost (choice or MAX), exactly as `resolver_costos_envio_batch`.

    A failed mlwebhook read never raises: both mappings come back empty and callers fall back to the ERP envio. A
    failure of the main-DB read of the active MLAs propagates, as in `resolver_costos_envio_batch`.
    """
    if not item_ids and not mla_ids:
        return CostosEnvio()
    item_to_active_mlas = _active_mlas_by_item(db, item_ids) if item_ids else {}
    wanted = set(mla_ids)
    for mlas in item_to_active_mlas.values():
        wanted.update(mlas)
    if not wanted:
        return CostosEnvio()
    costs = _fetch_list_cost_by_mla(sorted(wanted))
    return CostosEnvio(
        por_producto=_resolve_by_item(db, item_to_active_mlas, costs),
        por_mla={mla: costs[mla] for mla in mla_ids if mla in costs},
    )
