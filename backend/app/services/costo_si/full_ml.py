"""Full stock for costo SI: Mercado Libre's, never GBP depot 17 (S3, owner L8: "el depósito de full no es el stock
de full, el stock de full lo traemos de ml, y ese podés calcular para atrás dependiendo las ventas de full").

Today's Full stock of a product is what the rest of the app reads (`ml_user_product_stock.full_quantity`, the source
of `producto_stock_diario.stock_full`) for the user products of its own publications (linked at item level; combos'
publications are not the product's: S11, L7.1). A past instant is walked back from it with ML's Full stock operations
of each `inventory_id` (`GET /stock/fulfillment/operations/search`, the endpoint `gestion_full.inbound` already calls):
every operation carries `detail.available_quantity` (its change) and `result.available_quantity` (the available stock
right after it), so the stock at `t` is `result - detail` of the first operation at or after `t`, or today's stock
when nothing moved since. Sales confirmed, cancellations, inbounds, returns and adjustments are all operations.

ML keeps 12 months and answers at most 60 days per call, up to the day before `date_to`. The operations are kept in
`costo_si_full_operaciones` and the fetched range per inventory in `costo_si_full_cobertura`, so a recompute only asks
for what is missing (and always the last day again, for the new operations).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

# The same endpoint `gestion_full.inbound` calls; not imported from there: `sell.drain` (the sales worker) imports this
# module and must not load the ML client (design D1, `test_registry_ml`).
ENDPOINT_FAMILY = "fulfillment_operations"
OPERATIONS_PATH = "/stock/fulfillment/operations/search"
MAX_DIAS = 60
RETENCION_DIAS = 365
PAGINA = 1000


class FullNoDisponible(RuntimeError):
    """ML did not answer the operations of an inventory: a recompute must not go on with a guessed Full stock."""


class FullPendiente(RuntimeError):
    """The Full operations since the product's start are not kept yet: the recompute waits for `stock.snapshot` to
    fetch them (it re-queues the product after). Never charged as a failure."""


class ClienteMl(Protocol):
    def get(self, family: str, path: str, params: Optional[dict] = None) -> Any: ...


_INVENTARIOS_SQL = text("""
    SELECT DISTINCT ON (i.inventory_id) i.inventory_id, i.user_product_id
    FROM ml_item_product_links l
    JOIN ml_items i ON i.item_id = l.item_id
    WHERE l.producto_item_id = :i AND l.variation_id = 0 AND i.inventory_id IS NOT NULL
    ORDER BY i.inventory_id, i.user_product_id
""")

_ACTUAL_SQL = text("SELECT COALESCE(full_quantity, 0) FROM ml_user_product_stock WHERE user_product_id = :up")

_PRIMERA_DESDE_SQL = text("""
    SELECT disponible - delta FROM costo_si_full_operaciones
    WHERE inventory_id = :inv AND date_created >= :t
    ORDER BY date_created, operation_id LIMIT 1
""")


def inventarios(db: Session, item_id: int) -> List[Tuple[str, Optional[str]]]:
    return [(r[0], r[1]) for r in db.execute(_INVENTARIOS_SQL, {"i": item_id})]


def full_disponible(db: Session, item_id: int, t: datetime) -> int:
    """The product's Full available stock at instant `t` (aware), walked back from today's."""
    total = 0
    for inventory_id, user_product_id in inventarios(db, item_id):
        antes = db.execute(_PRIMERA_DESDE_SQL, {"inv": inventory_id, "t": t}).scalar()
        if antes is not None:
            total += int(antes)
        elif user_product_id is not None:
            total += int(db.execute(_ACTUAL_SQL, {"up": user_product_id}).scalar() or 0)
    return total


def piso(desde: date, hoy: date) -> date:
    """The oldest day ML still answers for: before it the Full stock is walked back from the oldest kept operation."""
    return max(desde, hoy - timedelta(days=RETENCION_DIAS - 1))


def exigir_cobertura(db: Session, item_id: int, desde: date, hoy: date) -> None:
    """Raises `FullPendiente` unless every Full inventory of the product has its operations kept from `desde` (or
    ML's retention floor) through today, so no past Full stock is guessed from today's."""
    minimo = piso(desde, hoy)
    faltan = []
    for inventory_id, _ in inventarios(db, item_id):
        cobertura = db.execute(_COBERTURA_SQL, {"inv": inventory_id}).first()
        if cobertura is None or cobertura[0] > minimo or cobertura[1] <= hoy:
            faltan.append(inventory_id)
    if faltan:
        raise FullPendiente(f"product {item_id}: Full operations not kept from {minimo} for {faltan}")


# ------------------------------------------------------------------------------------------------------- fetching

_COBERTURA_SQL = text("SELECT desde, hasta FROM costo_si_full_cobertura WHERE inventory_id = :inv")

_GUARDAR_COBERTURA_SQL = text("""
    INSERT INTO costo_si_full_cobertura (inventory_id, desde, hasta) VALUES (:inv, :desde, :hasta)
    ON CONFLICT (inventory_id) DO UPDATE
    SET desde = LEAST(costo_si_full_cobertura.desde, EXCLUDED.desde),
        hasta = GREATEST(costo_si_full_cobertura.hasta, EXCLUDED.hasta), updated_at = now()
""")

_GUARDAR_OPERACION_SQL = text("""
    INSERT INTO costo_si_full_operaciones (operation_id, inventory_id, date_created, tipo, delta, disponible)
    VALUES (:id, :inv, :fecha, :tipo, :delta, :disponible)
    ON CONFLICT (operation_id) DO NOTHING
""")


def sincronizar(db: Session, cliente: ClienteMl, item_id: int, desde: date, hoy: date) -> int:
    """Fetches the Full operations of the product's inventories from `desde` (at most 12 months back) through today
    that are not kept yet. Returns how many operations were stored. Raises `FullNoDisponible` when ML fails."""
    minimo = piso(desde, hoy)
    manana = hoy + timedelta(days=1)
    guardadas = 0
    for inventory_id, _ in inventarios(db, item_id):
        cobertura = db.execute(_COBERTURA_SQL, {"inv": inventory_id}).first()
        if cobertura is None:
            tramos = [(minimo, manana)]
        else:
            tramos = [(minimo, cobertura[0])] if minimo < cobertura[0] else []
            tramos.append((max(cobertura[1] - timedelta(days=1), minimo), manana))
        for a, b in tramos:
            if a >= b:
                continue
            for op in _operaciones(cliente, inventory_id, a, b):
                guardadas += db.execute(_GUARDAR_OPERACION_SQL, op).rowcount or 0
            db.execute(_GUARDAR_COBERTURA_SQL, {"inv": inventory_id, "desde": a, "hasta": b})
    return guardadas


_POR_ANTIGUEDAD_SQL = text("""
    SELECT l.producto_item_id FROM unnest(CAST(:items AS integer[])) AS l(producto_item_id)
    LEFT JOIN ml_item_product_links pl ON pl.producto_item_id = l.producto_item_id AND pl.variation_id = 0
    LEFT JOIN ml_items i ON i.item_id = pl.item_id
    LEFT JOIN costo_si_full_cobertura c ON c.inventory_id = i.inventory_id
    GROUP BY l.producto_item_id
    ORDER BY bool_or(i.inventory_id IS NOT NULL AND c.inventory_id IS NULL) DESC, min(c.hasta) NULLS LAST,
             l.producto_item_id
""")


def por_antiguedad(db: Session, items: Iterable[int]) -> List[int]:
    """`items` with the least recently synced first (a Full inventory never synced first of all), so a daily run cut
    by its deadline reaches the ones it left out the day before."""
    return [int(r[0]) for r in db.execute(_POR_ANTIGUEDAD_SQL, {"items": list(items)})]


def sincronizar_productos(
    session_factory: Callable[[], Any],
    cliente: ClienteMl,
    items: Iterable[int],
    hoy: date,
    deadline: datetime,
    inicio_de: Callable[[Session, int], Optional[date]],
) -> Tuple[int, Dict[int, str]]:
    """`sincronizar` for each of `items` from its start (`inicio_de`; None skips it), one transaction each, until
    `deadline`. A product that fails (ML or anything else) is reported and skipped; the next day retries it. Returns (operations stored,
    failures by product)."""
    guardadas, fallidos = 0, {}
    for item_id in items:
        if datetime.now(UTC) >= deadline:
            break
        with session_factory() as db:
            try:
                inicio = inicio_de(db, item_id)
                if inicio is not None:
                    guardadas += sincronizar(db, cliente, item_id, inicio, hoy)
                db.commit()
            except Exception as exc:  # one broken product never stops the others; the next day retries it
                db.rollback()
                if not isinstance(exc, FullNoDisponible):
                    logger.exception("costo_si: Full sync of product %s failed", item_id)
                fallidos[item_id] = f"{type(exc).__name__}: {exc}"
    if fallidos:
        logger.warning("costo_si: Full operations not fetched for %s product(s): %s", len(fallidos), fallidos)
    return guardadas, fallidos


def _ventanas(a: date, b: date) -> Iterable[Tuple[date, date]]:
    while a < b:
        fin = min(a + timedelta(days=MAX_DIAS), b)
        yield a, fin
        a = fin


def _operaciones(cliente: ClienteMl, inventory_id: str, a: date, b: date) -> Iterable[dict]:
    seller = str(settings.ML_USER_ID or "")
    for desde, hasta in _ventanas(a, b):
        params: dict = {
            "seller_id": seller,
            "inventory_id": inventory_id,
            "date_from": desde.isoformat(),
            "date_to": hasta.isoformat(),
            "limit": PAGINA,
        }
        while True:
            response = cliente.get(ENDPOINT_FAMILY, OPERATIONS_PATH, params)
            if response.status != 200 or not isinstance(response.body, dict):
                raise FullNoDisponible(f"inventory {inventory_id}: ML answered {response.status} for {desde}..{hasta}")
            for row in response.body.get("results") or []:
                op = _operacion(inventory_id, row)
                if op is not None:
                    yield op
            paging = response.body.get("paging") if isinstance(response.body.get("paging"), dict) else {}
            scroll = paging.get("scroll") or response.body.get("scroll")
            if not scroll or not response.body.get("results"):
                break
            params = {**params, "scroll": scroll}


def _fecha(value: Any) -> Optional[datetime]:
    """ML's `date_created` (ISO 8601, `Z` or an offset), aware; None when unreadable."""
    texto = str(value or "").strip()
    if not texto:
        return None
    try:
        parsed = datetime.fromisoformat(texto[:-1] + "+00:00" if texto.endswith("Z") else texto)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _operacion(inventory_id: str, row: Any) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    fecha = _fecha(row.get("date_created"))
    try:
        op_id = int(row["id"])
        delta = int(detail.get("available_quantity") or 0)
        disponible = int(result["available_quantity"])
    except (KeyError, TypeError, ValueError):
        logger.warning("costo_si: Full operation without id or result skipped: %s", row.get("id"))
        return None
    if fecha is None:
        return None
    return {
        "id": op_id,
        "inv": inventory_id,
        "fecha": fecha.astimezone(UTC),
        "tipo": str(row.get("type") or ""),
        "delta": delta,
        "disponible": disponible,
    }
