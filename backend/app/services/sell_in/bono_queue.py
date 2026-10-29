"""The `sell_in_bono_dirty` queue (sell-in-sell-out T3c-3): which brand bonuses
and Compras operations must have their generated sell ins reconciled. No cron:
row triggers queue a key and `pg_notify('sell_in_bono_dirty')`.

Every trigger is GATED on an active bonus, so nothing is queued while no bonus
exists (and a key is only queued when some active bonus can care about it):

- `sell_in_bonos_marca`: an INSERT of an active bonus, or an UPDATE that changes
  what it pays (scope and its field, kind, amount or percentage, currency,
  range, estado, author) while it is or was active (a void is queued: what it
  generated must be voided; so is an invoice bonus whose operation was deleted,
  since its `pedido_id` goes NULL);
- `sell_in_bono_items` (a models bonus's models, T3e): any INSERT, DELETE or
  UPDATE queues its bonus while it is active;
- `pedidos_compra`: an UPDATE of `fecha_factura`, `estado`, `tipo_cambio` or
  `proveedor_id` that changes it, and an INSERT or DELETE, queue the operation
  when its old or new invoice date falls in an active bonus's range;
- `pedido_compra_lineas_facturadas` (invoiced units and net amount): an INSERT or
  DELETE, or an UPDATE that changes `pedido_id`, `item_id`, `cantidad`,
  `importe_neto` or `moneda` (the base of a percentage bonus), queue the operation
  under the same date rule (a line deleted by its operation's cascade is
  covered by the operation's own DELETE);
- `productos_erp`: a new product, one whose `marca` or `categoria` changes, or a
  deleted one queues the operations invoicing it when an active bonus that
  reaches it on its old or new side covers their invoice date
  (`sell_in_bono_cubre_producto`): by brand, by category, by model (listed in
  `sell_in_bono_items`) or by invoice (that very operation: a line with no
  product is out of an invoice bonus's base, so the product's arrival or
  removal moves it). A NULL brand or category matches no bonus.

The `pedidos_compra` and invoiced-line triggers gate on the invoice date only,
not on the brands of the operation's items: a deliberate over-queue (an
operation covered by some active bonus but holding none of its brands is
queued) that keeps those triggers cheap; the worker reconciles it as a no-op.

The gates are `sell_in_bono_cubre(fecha[, marca])` (date only, any scope, for
the operation and line triggers; with a brand, brand bonuses only) and
`sell_in_bono_cubre_producto(fecha, pedido, item, marca, categoria)`: one EXISTS
over the (few) bonuses each. A trigger does no reconcile work.
`UPGRADE_SQL`/`DOWNGRADE_SQL` are the live definition; the migration
`20261115_sell_in_bono_queue_alcance` carries a frozen copy (it replaced the
one `20261107_sell_in_bonos_marca` installed, which owns the table,
`app.models.sell_in.SellInBonoDirty`).

The `sell_in.bono` worker drains it. A claimed row is locked (`FOR UPDATE SKIP
LOCKED`) for the drain's short transaction: a trigger re-queueing it waits and
then lands as a fresh row, so a change made while it is being reconciled is
never lost. The claim and the work share one transaction, so no lease token is
needed (unlike `order_metrics`, whose compute runs outside the claiming one).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

CHANNEL = "sell_in_bono_dirty"
BATCH_SIZE = 50
# A key is retried on later wakes until it fails this many times; a new change re-queues it with attempts = 0.
MAX_ATTEMPTS = 5

Key = Tuple[str, int]  # (tipo, ref)

_UPSERT = (
    "INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ({tipo}, {ref}) "
    "ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL"
)

UPGRADE_SQL: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre(p_fecha DATE, p_marca TEXT DEFAULT NULL) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (p_marca IS NULL OR b.marca = p_marca)
    )
$fn$ LANGUAGE sql STABLE
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_producto(
    p_fecha DATE, p_pedido BIGINT, p_item INTEGER, p_marca TEXT, p_categoria TEXT
) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (
            (b.alcance = 'marca' AND b.marca = p_marca)
            OR (b.alcance = 'categoria' AND b.categoria = p_categoria)
            OR (b.alcance = 'modelos'
                AND EXISTS (SELECT 1 FROM sell_in_bono_items AS i WHERE i.bono_id = b.id AND i.item_id = p_item))
            OR (b.alcance = 'factura' AND b.pedido_id = p_pedido)
          )
    )
$fn$ LANGUAGE sql STABLE
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_bono() RETURNS TRIGGER AS $trg$
BEGIN
    IF NEW.estado = 'activa' OR (TG_OP = 'UPDATE' AND OLD.estado = 'activa') THEN
        {_UPSERT.format(tipo="'bono'", ref="NEW.id")};
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_pedido() RETURNS TRIGGER AS $trg$
DECLARE
    encolado BOOLEAN := false;
BEGIN
    IF TG_OP <> 'INSERT' AND sell_in_bono_cubre(OLD.fecha_factura) THEN
        {_UPSERT.format(tipo="'pedido'", ref="OLD.id")};
        encolado := true;
    END IF;
    IF TG_OP <> 'DELETE' AND sell_in_bono_cubre(NEW.fecha_factura) THEN
        {_UPSERT.format(tipo="'pedido'", ref="NEW.id")};
        encolado := true;
    END IF;
    IF encolado THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_linea() RETURNS TRIGGER AS $trg$
DECLARE
    pedidos BIGINT[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        pedidos := ARRAY[NEW.pedido_id];
    ELSIF TG_OP = 'DELETE' THEN
        pedidos := ARRAY[OLD.pedido_id];
    ELSE
        pedidos := ARRAY[OLD.pedido_id, NEW.pedido_id];
    END IF;
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'pedido', p.id FROM pedidos_compra AS p
    WHERE p.id = ANY(pedidos) AND sell_in_bono_cubre(p.fecha_factura)
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_bono_item() RETURNS TRIGGER AS $trg$
DECLARE
    bonos BIGINT[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        bonos := ARRAY[NEW.bono_id];
    ELSIF TG_OP = 'DELETE' THEN
        bonos := ARRAY[OLD.bono_id];
    ELSE
        bonos := ARRAY[OLD.bono_id, NEW.bono_id];
    END IF;
    -- A bonus deleted with its models (CASCADE) is gone: nothing to queue.
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'bono', b.id FROM sell_in_bonos_marca AS b
    WHERE b.id = ANY(bonos) AND b.estado = 'activa'
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_producto() RETURNS TRIGGER AS $trg$
DECLARE
    item productos_erp.item_id%TYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        item := OLD.item_id;
    ELSE
        item := NEW.item_id;
    END IF;
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'pedido', l.pedido_id
    FROM pedido_compra_lineas_facturadas AS l
    JOIN pedidos_compra AS p ON p.id = l.pedido_id
    WHERE l.item_id = item
      AND ((TG_OP <> 'DELETE' AND sell_in_bono_cubre_producto(p.fecha_factura, p.id, item, NEW.marca, NEW.categoria))
           OR (TG_OP <> 'INSERT'
               AND sell_in_bono_cubre_producto(p.fecha_factura, p.id, item, OLD.marca, OLD.categoria)))
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_in_bono_bonos_insert
AFTER INSERT ON sell_in_bonos_marca
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_bono()
""",
    """
CREATE TRIGGER trg_sell_in_bono_bonos_update
AFTER UPDATE ON sell_in_bonos_marca
FOR EACH ROW WHEN (
    (OLD.alcance, OLD.marca, OLD.categoria, OLD.pedido_id, OLD.tipo, OLD.monto_unit, OLD.porcentaje, OLD.moneda,
     OLD.fecha_desde, OLD.fecha_hasta, OLD.estado, OLD.usuario_id, OLD.tope_unidades, OLD.tope_monto,
     OLD.base, OLD.incluye_iva)
    IS DISTINCT FROM
    (NEW.alcance, NEW.marca, NEW.categoria, NEW.pedido_id, NEW.tipo, NEW.monto_unit, NEW.porcentaje, NEW.moneda,
     NEW.fecha_desde, NEW.fecha_hasta, NEW.estado, NEW.usuario_id, NEW.tope_unidades, NEW.tope_monto,
     NEW.base, NEW.incluye_iva)
)
EXECUTE FUNCTION sell_in_bono_enqueue_bono()
""",
    """
CREATE TRIGGER trg_sell_in_bono_items_change
AFTER INSERT OR UPDATE OR DELETE ON sell_in_bono_items
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_bono_item()
""",
    """
CREATE TRIGGER trg_sell_in_bono_pedidos_insert_delete
AFTER INSERT OR DELETE ON pedidos_compra
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_pedido()
""",
    """
CREATE TRIGGER trg_sell_in_bono_pedidos_update
AFTER UPDATE OF fecha_factura, estado, tipo_cambio, proveedor_id ON pedidos_compra
FOR EACH ROW WHEN (
    (OLD.fecha_factura, OLD.estado, OLD.tipo_cambio, OLD.proveedor_id)
    IS DISTINCT FROM (NEW.fecha_factura, NEW.estado, NEW.tipo_cambio, NEW.proveedor_id)
)
EXECUTE FUNCTION sell_in_bono_enqueue_pedido()
""",
    """
CREATE TRIGGER trg_sell_in_bono_lineas_insert_delete
AFTER INSERT OR DELETE ON pedido_compra_lineas_facturadas
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
    """
CREATE TRIGGER trg_sell_in_bono_lineas_update
AFTER UPDATE OF pedido_id, item_id, cantidad, importe_neto, moneda ON pedido_compra_lineas_facturadas
FOR EACH ROW WHEN (
    (OLD.pedido_id, OLD.item_id, OLD.cantidad, OLD.importe_neto, OLD.moneda)
    IS DISTINCT FROM (NEW.pedido_id, NEW.item_id, NEW.cantidad, NEW.importe_neto, NEW.moneda)
)
EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_insert
AFTER INSERT ON productos_erp
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_marca
AFTER UPDATE OF marca, categoria ON productos_erp
FOR EACH ROW WHEN ((OLD.marca, OLD.categoria) IS DISTINCT FROM (NEW.marca, NEW.categoria))
EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_delete
AFTER DELETE ON productos_erp
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
]

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_delete ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_marca ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_insert ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_update ON pedido_compra_lineas_facturadas",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_insert_delete ON pedido_compra_lineas_facturadas",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_pedidos_update ON pedidos_compra",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_pedidos_insert_delete ON pedidos_compra",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_items_change ON sell_in_bono_items",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_update ON sell_in_bonos_marca",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_insert ON sell_in_bonos_marca",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_producto()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_bono_item()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_linea()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_pedido()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_bono()",
    "DROP FUNCTION IF EXISTS sell_in_bono_cubre_producto(DATE, BIGINT, INTEGER, TEXT, TEXT)",
    "DROP FUNCTION IF EXISTS sell_in_bono_cubre(DATE, TEXT)",
]

# The oldest queued keys, fresh ones first, skipping what another drain holds, parked keys and the
# keys that already failed in this run. Locked until the batch's transaction ends.
_CLAIM_SQL = text(
    """
SELECT tipo, ref FROM sell_in_bono_dirty AS d
WHERE attempts < :max_attempts
  AND NOT EXISTS (
    SELECT 1 FROM unnest(CAST(:x_tipos AS text[]), CAST(:x_refs AS bigint[])) AS x(tipo, ref)
    WHERE x.tipo = d.tipo AND x.ref = d.ref
  )
ORDER BY attempts, enqueued_at, tipo, ref
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""
)

# One given key with the version claimed (`enqueued_at`, moved by every re-queue): the one-by-one retry.
_CLAIM_ONE_SQL = text(
    "SELECT enqueued_at FROM sell_in_bono_dirty WHERE tipo = :tipo AND ref = :ref AND attempts < :max_attempts "
    "FOR UPDATE SKIP LOCKED"
)

_DONE_SQL = text(
    """
DELETE FROM sell_in_bono_dirty AS d
USING unnest(CAST(:tipos AS text[]), CAST(:refs AS bigint[])) AS k(tipo, ref)
WHERE d.tipo = k.tipo AND d.ref = k.ref
"""
)

_FAILED_SQL = text(
    """
UPDATE sell_in_bono_dirty AS d SET attempts = d.attempts + 1, last_error = f.error
FROM unnest(CAST(:tipos AS text[]), CAST(:refs AS bigint[]), CAST(:errors AS text[])) AS f(tipo, ref, error)
WHERE d.tipo = f.tipo AND d.ref = f.ref
RETURNING d.tipo, d.ref, d.attempts
"""
)

# Charges a key only while it is still the version that failed: a re-queue that landed after the
# failed transaction rolled back is a fresh change.
_CHARGE_SQL = text(
    "UPDATE sell_in_bono_dirty SET attempts = attempts + 1, last_error = :error "
    "WHERE tipo = :tipo AND ref = :ref AND enqueued_at = :enqueued_at RETURNING attempts"
)


def _arrays(keys: Iterable[Key]) -> Tuple[list, list]:
    ordered = sorted(set(keys))
    return [t for t, _ in ordered], [r for _, r in ordered]


def claim_batch(db: Session, limit: int, excluded: Iterable[Key] = ()) -> List[Key]:
    """Claims up to `limit` queued keys, locked until the transaction ends. Does not commit."""
    x_tipos, x_refs = _arrays(excluded)
    params = {"max_attempts": MAX_ATTEMPTS, "x_tipos": x_tipos, "x_refs": x_refs, "limit": limit}
    return [(row[0], int(row[1])) for row in db.execute(_CLAIM_SQL, params)]


def claim_one(db: Session, key: Key) -> Optional[datetime]:
    """Claims one queued key and returns the version claimed; None when it is gone, parked or held."""
    tipo, ref = key
    row = db.execute(_CLAIM_ONE_SQL, {"tipo": tipo, "ref": ref, "max_attempts": MAX_ATTEMPTS}).first()
    return row[0] if row is not None else None


def settle(db: Session, done: Iterable[Key], failed: dict) -> List[Key]:
    """Acks `done`, charges `failed` (`{key: error}`) in the claiming transaction; returns the keys
    that park with this charge. Does not commit."""
    tipos, refs = _arrays(done)
    if tipos:
        db.execute(_DONE_SQL, {"tipos": tipos, "refs": refs})
    if not failed:
        return []
    ordered = sorted(failed)
    rows = db.execute(
        _FAILED_SQL,
        {"tipos": [t for t, _ in ordered], "refs": [r for _, r in ordered], "errors": [failed[k] for k in ordered]},
    )
    return [(t, int(r)) for t, r, attempts in rows if attempts >= MAX_ATTEMPTS]


def charge(db: Session, key: Key, error: str, enqueued_at: datetime) -> Optional[int]:
    """Charges one key if it is still the version claimed; returns its attempts, or None. Does not commit."""
    tipo, ref = key
    row = db.execute(_CHARGE_SQL, {"tipo": tipo, "ref": ref, "error": error, "enqueued_at": enqueued_at}).first()
    return row[0] if row is not None else None
