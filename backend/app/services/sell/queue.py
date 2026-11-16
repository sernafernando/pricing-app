"""The `sell_dirty` queue (sell-in-sell-out T4): which sale lines must have
their sell-in / sell-out allocation recomputed. No cron: writers queue a line
and `pg_notify('sell_dirty')`, and `sell.drain` (worker REGISTRY) drains it.

Writers, all inside the transaction that changes the sale:

- `ventas_tienda_nube_metricas` (`canal = 'tn'`): row triggers, keyed by
  `it_transaction`. An INSERT or DELETE always queues; an UPDATE queues only
  when a column the allocation reads actually changes (`ALLOCATION_COLUMNS`),
  so the ERP sync rewriting a row with the same values queues nothing. An
  UPDATE that changes `it_transaction` queues both keys. The trigger does one
  upsert and one notify per row: no reads, no allocation work.
- `ventas_fuera_operacion_lineas` (`canal = 'pdf'`, ventas por fuera from the
  GBP PDF reports, VPF T4): row triggers keyed by the line `id`. A line with a
  product queues on INSERT and DELETE (a re-upload deletes the lines of its
  scope, also through the document's cascade, and inserts new ones), and on an
  UPDATE of its product or amounts; a line "sin producto" is never a sale. A
  document whose date or client changes (`ventas_fuera_operaciones`; pairing a
  later summary fills its client code) queues its lines: the client decides
  which sale a return reverses. The GBP sync (`ventas_fuera_ml_metricas`) queues
  nothing since T4: it is not a sale source any more (owner, S18).
- `ml_sale_lines` (`canal = 'ml'`): `enqueue_ml`, called by
  `store_sale_lines` with the lines that appeared, changed or disappeared.
- `ml_order_items_ops`, BEFORE DELETE: a deleted item takes its line with it
  through the `ml_sale_lines.item_row_id` cascade, bypassing `store_sale_lines`,
  so this trigger queues the item's line (with its product) while it still
  exists. One indexed INSERT ... SELECT per deleted item, a notify only if a
  line was queued; items are deleted rarely (stale items on re-ingestion). No
  trigger on `ml_sale_lines` itself: `store_sale_lines` deletes and reinserts
  every line on each store, and its RETURNING diff already filters that noise.

`UPGRADE_SQL`/`DOWNGRADE_SQL` are the live definition of the triggers; the
migration `20261031_sell_dirty_queue` carries a frozen copy and also owns the
table (`app.models.sell_dirty`); `20261213_sell_in_bono_costo_triggers` replaced
the two UPDATE triggers (they also watch `costo_total`, T25b2) and carries
their frozen copy.

A claimed row is locked (`FOR UPDATE SKIP LOCKED`): a trigger re-queueing the
same line waits for the drain's short transaction, then lands as a fresh row,
so a change made while the line was being processed is never lost.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.combos.componentes import componentes_de

CHANNEL = "sell_dirty"
BATCH_SIZE = 500

# What the allocators read from a TN sale row. Changing anything else
# (customer, seller, commission...) does not move an allocation.
# `costo_total` is the base of a % of cost sell-in bonus (`bonos_costo`, `sell_out.alcance.ventas`; T25b2).
ALLOCATION_COLUMNS = (
    "it_transaction",
    "item_id",
    "cantidad",
    "fecha_venta",
    "signo",
    "monto_total",
    "costo_unitario",
    "costo_total",
)

UPGRADE_SQL: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_dirty_enqueue_venta() RETURNS TRIGGER AS $trg$
BEGIN
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.it_transaction IS DISTINCT FROM NEW.it_transaction) THEN
        INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES (TG_ARGV[0], OLD.it_transaction, OLD.item_id)
        ON CONFLICT (canal, venta_ref) DO UPDATE
        SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES (TG_ARGV[0], NEW.it_transaction, NEW.item_id)
        ON CONFLICT (canal, venta_ref) DO UPDATE
        SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    END IF;
    PERFORM pg_notify('sell_dirty', '');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION sell_dirty_enqueue_pdf_linea() RETURNS TRIGGER AS $trg$
DECLARE
    fila ventas_fuera_operacion_lineas%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' OR NEW.item_id IS NULL THEN
        fila := OLD;
    ELSE
        fila := NEW;
    END IF;
    IF fila.item_id IS NULL THEN
        RETURN NULL;
    END IF;
    INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES ('pdf', fila.id, fila.item_id)
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    PERFORM pg_notify('sell_dirty', '');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_dirty_pdf_insert_delete
AFTER INSERT OR DELETE ON ventas_fuera_operacion_lineas
FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_pdf_linea()
""",
    """
CREATE TRIGGER trg_sell_dirty_pdf_update
AFTER UPDATE OF item_id, cantidad, precio, precio_costo, operacion_id ON ventas_fuera_operacion_lineas
FOR EACH ROW WHEN (
    (OLD.item_id, OLD.cantidad, OLD.precio, OLD.precio_costo, OLD.operacion_id)
    IS DISTINCT FROM (NEW.item_id, NEW.cantidad, NEW.precio, NEW.precio_costo, NEW.operacion_id)
)
EXECUTE FUNCTION sell_dirty_enqueue_pdf_linea()
""",
    """
CREATE OR REPLACE FUNCTION sell_dirty_enqueue_pdf_operacion() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO sell_dirty (canal, venta_ref, item_id)
    SELECT 'pdf', l.id, l.item_id FROM ventas_fuera_operacion_lineas AS l
    WHERE l.operacion_id = NEW.id AND l.item_id IS NOT NULL
    ORDER BY l.id
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_dirty_pdf_operacion_update
AFTER UPDATE OF empresa, cliente, cliente_codigo, fecha ON ventas_fuera_operaciones
FOR EACH ROW WHEN (
    (OLD.empresa, OLD.cliente, OLD.cliente_codigo, OLD.fecha)
    IS DISTINCT FROM (NEW.empresa, NEW.cliente, NEW.cliente_codigo, NEW.fecha)
)
EXECUTE FUNCTION sell_dirty_enqueue_pdf_operacion()
""",
    """
CREATE TRIGGER trg_sell_dirty_tn_insert_delete
AFTER INSERT OR DELETE ON ventas_tienda_nube_metricas
FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_venta('tn')
""",
    """
CREATE TRIGGER trg_sell_dirty_tn_update
AFTER UPDATE OF it_transaction, item_id, cantidad, fecha_venta, signo, monto_total, costo_unitario, costo_total
ON ventas_tienda_nube_metricas
FOR EACH ROW WHEN (
    (OLD.it_transaction, OLD.item_id, OLD.cantidad, OLD.fecha_venta, OLD.signo, OLD.monto_total, OLD.costo_unitario,
     OLD.costo_total)
    IS DISTINCT FROM
    (NEW.it_transaction, NEW.item_id, NEW.cantidad, NEW.fecha_venta, NEW.signo, NEW.monto_total, NEW.costo_unitario,
     NEW.costo_total)
)
EXECUTE FUNCTION sell_dirty_enqueue_venta('tn')
""",
    """
CREATE OR REPLACE FUNCTION sell_dirty_enqueue_ml_item_delete() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO sell_dirty (canal, venta_ref, item_id)
    SELECT 'ml', item_row_id, product FROM ml_sale_lines WHERE item_row_id = OLD.id
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_dirty', '');
    END IF;
    RETURN OLD;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_dirty_ml_items_delete
BEFORE DELETE ON ml_order_items_ops
FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_ml_item_delete()
""",
]

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_dirty_ml_items_delete ON ml_order_items_ops",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_ml_item_delete()",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_tn_update ON ventas_tienda_nube_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_tn_insert_delete ON ventas_tienda_nube_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_operacion_update ON ventas_fuera_operaciones",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_pdf_operacion()",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_update ON ventas_fuera_operacion_lineas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_insert_delete ON ventas_fuera_operacion_lineas",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_pdf_linea()",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_venta()",
]

# A data-modifying CTE always runs, referenced or not. The notify is delivered
# at commit, and only if the transaction commits.
_ENQUEUE_ML_SQL = text(
    """
WITH queued AS (
    INSERT INTO sell_dirty (canal, venta_ref, item_id)
    SELECT 'ml', ref, item FROM unnest(CAST(:refs AS bigint[]), CAST(:items AS integer[])) AS t(ref, item)
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL
    RETURNING 1
)
SELECT pg_notify('sell_dirty', '')
"""
)

# A batch: the oldest queued lines, fresh ones (`attempts = 0`) first, skipping
# what another drain holds, parked lines (`attempts >= MAX_ATTEMPTS`) and lines
# that already failed in this run. The rows stay locked until the batch's
# transaction ends, so a trigger re-queueing one of them waits and then lands
# as a fresh row: a change made while the line is being processed is never lost.
_CLAIM_SQL = text(
    """
SELECT canal, venta_ref, item_id FROM sell_dirty AS d
WHERE attempts < :max_attempts
  AND NOT EXISTS (
    SELECT 1 FROM unnest(CAST(:x_canales AS text[]), CAST(:x_refs AS bigint[])) AS x(canal, ref)
    WHERE x.canal = d.canal AND x.ref = d.venta_ref
  )
ORDER BY attempts, enqueued_at, canal, venta_ref
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""
)

# One given line, as `_CLAIM_SQL` would claim it, with the version claimed
# (`enqueued_at`, which every re-queue moves): the drain's line-by-line retry.
_CLAIM_LINE_SQL = text(
    """
SELECT canal, venta_ref, item_id, enqueued_at FROM sell_dirty
WHERE canal = :canal AND venta_ref = :ref AND attempts < :max_attempts
FOR UPDATE SKIP LOCKED
"""
)

# The products a line's stored consumptions are filed under: a line that moved
# to another product is queued under the NEW one and found here under the OLD.
# Served by the unique index (canal, venta_ref, compra_item_id).
_FILED_UNDER_SQL = text(
    """
SELECT c.canal, c.venta_ref, c.item_id
FROM unnest(CAST(:canales AS text[]), CAST(:refs AS bigint[])) AS l(canal, ref)
JOIN sell_in_consumos AS c ON c.canal = l.canal AND c.venta_ref = l.ref
UNION
SELECT c.canal, c.venta_ref, c.item_id
FROM unnest(CAST(:canales AS text[]), CAST(:refs AS bigint[])) AS l(canal, ref)
JOIN sell_in_bono_consumos AS c ON c.canal = l.canal AND c.venta_ref = l.ref
"""
)

_DONE_SQL = text(
    """
DELETE FROM sell_dirty AS d
USING unnest(CAST(:canales AS text[]), CAST(:refs AS bigint[])) AS l(canal, ref)
WHERE d.canal = l.canal AND d.venta_ref = l.ref
"""
)

# Charges a line only while it is still the version that failed: a re-queue
# that landed after the failed transaction rolled back is a fresh change.
_CHARGE_SQL = text(
    "UPDATE sell_dirty SET attempts = attempts + 1, last_error = :error "
    "WHERE canal = :canal AND venta_ref = :ref AND enqueued_at = :enqueued_at RETURNING attempts"
)

# One statement for every failed line of a batch. `settle` runs in the
# transaction that claimed the lines and still holds their row locks, so the
# rows are the claimed version: no re-queue can land in between.
_FAILED_SQL = text(
    """
UPDATE sell_dirty AS d SET attempts = d.attempts + 1, last_error = f.error
FROM unnest(CAST(:canales AS text[]), CAST(:refs AS bigint[]), CAST(:errors AS text[])) AS f(canal, ref, error)
WHERE d.canal = f.canal AND d.venta_ref = f.ref
RETURNING d.canal, d.venta_ref, d.attempts
"""
)

# A line is retried on later wakes until it fails this many times; a new change re-queues it with attempts = 0.
MAX_ATTEMPTS = 5

Line = Tuple[str, int]


def _arrays(lines: Iterable[Line]) -> Dict[str, list]:
    lines = sorted(set(lines))
    return {"canales": [c for c, _ in lines], "refs": [r for _, r in lines]}


def enqueue_ml(db: Session, lines: Sequence[Tuple[int, int]]) -> None:
    """Queues `(item_row_id, product)` ML sale lines and notifies the drain.
    A line given twice keeps its LAST product. Keys are sorted, so two writers
    lock the queue rows in the same order. Does not commit; a no-op for no lines."""
    if not lines:
        return
    ordered = sorted(dict(lines).items())
    db.execute(_ENQUEUE_ML_SQL, {"refs": [ref for ref, _ in ordered], "items": [item for _, item in ordered]})


_ENQUEUE_COMBOS_SQL = text(
    """
WITH ventas AS (
    SELECT 'ml' AS canal, item_row_id AS ref, product AS item FROM ml_sale_lines WHERE product = ANY(:combos)
    UNION ALL
    SELECT 'pdf', id, item_id FROM ventas_fuera_operacion_lineas WHERE item_id = ANY(:combos)
    UNION ALL
    SELECT 'tn', it_transaction, item_id FROM ventas_tienda_nube_metricas WHERE item_id = ANY(:combos)
), queued AS (
    INSERT INTO sell_dirty (canal, venta_ref, item_id)
    SELECT DISTINCT ON (canal, ref) canal, ref, item FROM ventas WHERE ref IS NOT NULL ORDER BY canal, ref
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL
    RETURNING 1
)
SELECT pg_notify('sell_dirty', '') WHERE EXISTS (SELECT 1 FROM queued)
"""
)


def enqueue_combos(db: Session, combo_item_ids: Iterable[int]) -> None:
    """Queues every sale line of these combos, every channel, under the combo (S4 of combos in sell in / sell out):
    their bill of materials changed, so the drain recomputes the components they have now (`products_of`), the ones
    they had (their rows are filed under them) and the sell-out campaigns of both. Does not commit; a no-op for no
    combos."""
    combos = sorted({int(c) for c in combo_item_ids})
    if combos:
        db.execute(_ENQUEUE_COMBOS_SQL, {"combos": combos})


def claim_batch(db: Session, limit: int, excluded: Iterable[Line] = ()) -> List[Tuple[str, int, Optional[int]]]:
    """Claims up to `limit` queued lines (`(canal, venta_ref, item_id)`), locked
    until the transaction ends. Does not commit."""
    x = _arrays(excluded)
    params = {"max_attempts": MAX_ATTEMPTS, "x_canales": x["canales"], "x_refs": x["refs"], "limit": limit}
    return [tuple(row) for row in db.execute(_CLAIM_SQL, params)]


def claim_line(db: Session, line: Line) -> Optional[Tuple[Tuple[str, int, Optional[int]], datetime]]:
    """Claims one queued line, locked until the transaction ends, as
    `((canal, venta_ref, item_id), enqueued_at)`; None when it is gone, parked
    or held by another drain. Does not commit."""
    canal, ref = line
    row = db.execute(_CLAIM_LINE_SQL, {"canal": canal, "ref": ref, "max_attempts": MAX_ATTEMPTS}).first()
    return ((row[0], row[1], row[2]), row[3]) if row is not None else None


def charge(db: Session, line: Line, error: str, enqueued_at: datetime) -> Optional[int]:
    """Charges a failed attempt to `line` if it is still the version claimed at
    `enqueued_at` and returns its attempts; None when it was re-queued (or
    acked) meanwhile. Does not commit."""
    canal, ref = line
    params = {"canal": canal, "ref": ref, "error": error[:1000], "enqueued_at": enqueued_at}
    return db.execute(_CHARGE_SQL, params).scalar()


def products_of(db: Session, claimed: Sequence[Tuple[str, int, Optional[int]]]) -> Dict[Line, Set[int]]:
    """Every product each claimed line touches: its queued product plus the ones its consumptions are filed under,
    from purchases (`sell_in_consumos`) or from % of cost bonuses (`sell_in_bono_consumos`, T25b: a sale moved to
    another product is queued under the new one only, and a cost bonus usually has no purchase row to find the old
    one by), plus the components of a queued combo."""
    products: Dict[Line, Set[int]] = {
        (canal, ref): ({item} if item is not None else set()) for canal, ref, item in claimed
    }
    # A combo's line moves its components' FIFO too (`app.services.combos.ventas`).
    combos = componentes_de(db, {item for _, _, item in claimed if item is not None})
    for canal, ref, item in claimed:
        products[(canal, ref)] |= set(combos.get(item, {}))
    if products:
        for canal, ref, item in db.execute(_FILED_UNDER_SQL, _arrays(products)):
            products[(canal, ref)].add(item)
    return products


def settle(db: Session, done: Iterable[Line], failed: Dict[Line, str]) -> List[Line]:
    """Removes the lines that were recomputed and charges the ones that failed,
    one statement each, and returns the charged lines that are now parked
    (`attempts >= MAX_ATTEMPTS`). Call it in the transaction that claimed the
    lines (it holds their locks). Does not commit."""
    done = list(done)
    if done:
        db.execute(_DONE_SQL, _arrays(done))
    if not failed:
        return []
    ordered = sorted(failed.items())
    rows = db.execute(
        _FAILED_SQL,
        {
            "canales": [canal for (canal, _), _ in ordered],
            "refs": [ref for (_, ref), _ in ordered],
            "errors": [error[:1000] for _, error in ordered],
        },
    )
    return sorted((canal, ref) for canal, ref, attempts in rows if attempts >= MAX_ATTEMPTS)
