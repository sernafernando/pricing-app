"""Re-freeze ML sale costs when a product's costo SI changes (sell-in-costo-si T3 PR 7; owner L15: "se tienen que
recalcular todos los costos posteriores"; inventory §12; T4 reuses it on deploy, L17).

A costo SI recompute that changed a product's history from date d (`costo_si.queue.drenar` -> `despues.despachar`)
queues the product and every combo containing it in `ml_costo_si_dirty` (`encolar`, cheap and idempotent, inside the
recompute's transaction: interface §3). `sell.drain` then drains that queue (`drenar`), one product per transaction:
every `ml_order_item_costos` row of the product whose sale date (ART) is on or after d is re-frozen at the cost in
force on its sale date, through THE reader's SQL fragment (`lote.sql_en_fecha`), so the freeze at ingestion
(`costeo_service.congelar`, which reads the same rule through `lote.en_fechas`) and this re-freeze never disagree.

What is rewritten: `costo_origen`, `moneda`, `tipo_cambio`, `tipo_cambio_fecha`, `costo_unitario_ars`, `fuente`,
`costo_fecha` -- only on a row whose cost is, or was, costo SI (a list-cost row that stays list cost is left as it was
frozen), only when a value actually changes (a second run is a no-op), and each changed row is copied whole to
`ml_order_item_costos_backups` first (same statement). Never the sale price (D4) nor the TP list-8 cost (D3); a sale
whose cost is unknown on its date keeps its row. The `UPDATE OF costo_unitario_ars` trigger re-queues the order's
metrics (`order_metrics`), which rewrites `ml_sale_lines.mcosto` and wakes sell in. In the same transaction the
product's sale-cost bonuses are recomputed (D2: a sale at costo SI no longer takes a % / per-unit bonus, any channel).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, Iterable, Optional, Set

from sqlalchemy import Date, Integer, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.core.constants import BUSINESS_TIMEZONE
from app.services.costo_si import lote

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
# Products re-frozen per `sell.drain` pass: the rest stays queued for the next wake (a whole-history change of many
# products must not hold the sales worker for one long run).
LIMITE_POR_PASADA = 50

# The `fuente` of a row frozen at costo SI, by how the product was found (publication / SKU) or summed (combo).
FUENTE_COSTO_SI_PUB = "costo_si_pub"
FUENTE_COSTO_SI_SKU = "costo_si_sku"
FUENTE_COSTO_SI_COMBO = "costo_si_combo"
FUENTES_COSTO_SI = (FUENTE_COSTO_SI_PUB, FUENTE_COSTO_SI_SKU, FUENTE_COSTO_SI_COMBO)

FECHA_VENTA_SQL = f"(o.date_created AT TIME ZONE '{BUSINESS_TIMEZONE}')::date"


# The new `fuente` of a row: costo SI keeps the linkage it was found by (a combo, costo SI with no step date, is
# `costo_si_combo`); list cost on a row that was costo SI goes back to the linkage's list fuente.
_FUENTE_SQL = f"""
    CASE WHEN cs.costo_si_fuente = '{lote.FUENTE_COSTO_SI}' THEN
        CASE WHEN cs.costo_si_desde IS NULL THEN '{FUENTE_COSTO_SI_COMBO}'
             WHEN c.fuente IN ('erp_sku', 'hist_sku', '{FUENTE_COSTO_SI_SKU}') THEN '{FUENTE_COSTO_SI_SKU}'
             ELSE '{FUENTE_COSTO_SI_PUB}' END
    ELSE CASE c.fuente WHEN '{FUENTE_COSTO_SI_SKU}' THEN 'erp_sku' WHEN '{FUENTE_COSTO_SI_COMBO}' THEN 'combo'
                       WHEN '{FUENTE_COSTO_SI_PUB}' THEN 'erp_publicacion' ELSE c.fuente END
    END"""

_RECONGELAR_SQL = text(f"""
WITH nuevos AS (
    SELECT c.id, {FECHA_VENTA_SQL} AS fecha_venta,
           round(cs.costo_si_costo, 4) AS costo_origen, cs.costo_si_moneda AS moneda,
           round(cs.costo_si_tipo_cambio, 4) AS tipo_cambio,
           cs.costo_si_tipo_cambio_fecha AS tipo_cambio_fecha,
           round(cs.costo_si_ars, 4) AS costo_unitario_ars, {_FUENTE_SQL} AS fuente
    FROM ml_order_item_costos c
    JOIN ml_orders_ops o ON o.order_id = c.order_id AND o.date_created IS NOT NULL
    LEFT JOIN LATERAL ({lote.sql_en_fecha("c.producto_item_id", FECHA_VENTA_SQL)}) cs ON true
    WHERE c.producto_item_id = :item
      AND (CAST(:desde AS date) IS NULL OR {FECHA_VENTA_SQL} >= CAST(:desde AS date))
      AND cs.costo_si_ars > 0
      -- A list-cost combo too, frozen live ('combo') or backfilled ('hist_combo', a dated list cost): the reader
      -- labels a combo 'lista' when one component has no costo SI, yet its cost carries the costo SI of the others
      -- (a combo is queued only when one of its components changes).
      AND (cs.costo_si_fuente = '{lote.FUENTE_COSTO_SI}' OR c.fuente IN :costo_si OR c.fuente IN ('combo', 'hist_combo'))
),
cambiados AS (
    SELECT n.* FROM nuevos n JOIN ml_order_item_costos c ON c.id = n.id
    WHERE (c.costo_origen, c.moneda, c.tipo_cambio, c.tipo_cambio_fecha, c.costo_unitario_ars, c.fuente, c.costo_fecha)
          IS DISTINCT FROM
          (n.costo_origen, n.moneda, n.tipo_cambio, n.tipo_cambio_fecha, n.costo_unitario_ars, n.fuente, n.fecha_venta)
),
respaldo AS (
    INSERT INTO ml_order_item_costos_backups (costo_id, order_id, item_id, variation_id, fila, motivo, desde)
    SELECT c.id, c.order_id, c.item_id, c.variation_id, to_jsonb(c), :motivo, CAST(:desde AS date)
    FROM ml_order_item_costos c JOIN cambiados x ON x.id = c.id
)
UPDATE ml_order_item_costos c
SET costo_origen = x.costo_origen, moneda = x.moneda, tipo_cambio = x.tipo_cambio,
    tipo_cambio_fecha = x.tipo_cambio_fecha, costo_unitario_ars = x.costo_unitario_ars, fuente = x.fuente,
    costo_fecha = x.fecha_venta
FROM cambiados x WHERE c.id = x.id
RETURNING c.id
""").bindparams(bindparam("costo_si", value=FUENTES_COSTO_SI, expanding=True))


def recongelar(db: Session, producto_item_id: int, desde: Optional[date], motivo: str = "costo SI") -> int:
    """Re-freezes the ML sales of `producto_item_id` dated (ART) on or after `desde` (None: all of them) at the cost
    in force on each sale date, backing up every changed row first. Returns how many rows changed. Does not commit."""
    filas = db.execute(_RECONGELAR_SQL, {"item": producto_item_id, "desde": desde, "motivo": motivo})
    cambiadas = len(filas.fetchall())
    desconocidas = db.execute(_DESCONOCIDAS_SQL, {"item": producto_item_id, "desde": desde}).scalar()
    if desconocidas:
        # Unknown stays unknown (interface §7): the row keeps what it froze, never 0, and it is said.
        logger.warning(
            "recongelar_costo_si: unknown cost for producto_item_id=%s on %s sale row(s) from %s: kept as frozen",
            producto_item_id,
            desconocidas,
            desde,
        )
    return cambiadas


# The rows the re-freeze would cover but the reader cannot cost on their date (no cost, or a USD one with no rate).
_DESCONOCIDAS_SQL = text(f"""
    SELECT count(*)
    FROM ml_order_item_costos c
    JOIN ml_orders_ops o ON o.order_id = c.order_id AND o.date_created IS NOT NULL
    LEFT JOIN LATERAL ({lote.sql_en_fecha("c.producto_item_id", FECHA_VENTA_SQL)}) cs ON true
    WHERE c.producto_item_id = :item
      AND (CAST(:desde AS date) IS NULL OR {FECHA_VENTA_SQL} >= CAST(:desde AS date))
      AND (cs.costo_si_ars IS NULL OR cs.costo_si_ars <= 0)
      AND (cs.costo_si_fuente = '{lote.FUENTE_COSTO_SI}' OR c.fuente IN :costo_si OR c.fuente IN ('combo', 'hist_combo'))
""").bindparams(bindparam("costo_si", value=FUENTES_COSTO_SI, expanding=True))


_ENCOLAR_SQL = text("""
    INSERT INTO ml_costo_si_dirty (producto_item_id, desde) SELECT unnest(:ids), CAST(:desde AS date)
    ON CONFLICT (producto_item_id) DO UPDATE
    SET desde = CASE WHEN ml_costo_si_dirty.desde IS NULL OR EXCLUDED.desde IS NULL THEN NULL
                     ELSE LEAST(ml_costo_si_dirty.desde, EXCLUDED.desde) END,
        enqueued_at = now(), attempts = 0, last_error = NULL
""").bindparams(bindparam("ids", type_=ARRAY(Integer)), bindparam("desde", type_=Date()))


def encolar(db: Session, item_ids: Iterable[int], desde: Optional[date]) -> None:
    """Queues these products' ML sales to re-freeze from `desde` (the earliest date wins; None: every sale)."""
    ids = sorted({int(i) for i in item_ids})
    if ids:
        db.execute(_ENCOLAR_SQL, {"ids": ids, "desde": desde})
        db.execute(text("SELECT pg_notify('sell_dirty', '')"))


def hay_pendientes(db: Session) -> bool:
    return db.execute(
        text("SELECT EXISTS (SELECT 1 FROM ml_costo_si_dirty WHERE attempts < :max)"), {"max": MAX_ATTEMPTS}
    ).scalar()


def _reclamar(db: Session, excluidos: Set[int]):
    return db.execute(
        text("""
            SELECT producto_item_id, desde FROM ml_costo_si_dirty
            WHERE attempts < :max AND NOT (producto_item_id = ANY(:excluidos))
            ORDER BY enqueued_at, producto_item_id
            LIMIT 1 FOR UPDATE SKIP LOCKED
        """).bindparams(bindparam("excluidos", type_=ARRAY(Integer))),
        {"max": MAX_ATTEMPTS, "excluidos": sorted(excluidos)},
    ).first()


def _cobrar(db: Session, item_id: int, error: str) -> int:
    return (
        db.execute(
            text(
                "UPDATE ml_costo_si_dirty SET attempts = attempts + 1, last_error = :e"
                " WHERE producto_item_id = :i RETURNING attempts"
            ),
            {"i": item_id, "e": error[:2000]},
        ).scalar()
        or 0
    )


def _bonos_costo(db: Session, item_id: int) -> None:
    """D2 follows the cost: the product's sale-cost bonuses in every channel, now that its sales may be (or stop being)
    at costo SI (`bonos_costo._en_costo_si`), in the product's transaction. A bonus that cannot be computed is
    logged by `bonos_costo`, never charged to the re-freeze."""
    from app.services.sell_in import bonos_costo  # imported here: sell_in reaches ML ingestion through its readers

    bonos_costo.registrar_fallidos(bonos_costo.recalcular(db, [item_id]), "ml costo SI")


@dataclass
class Drenado:
    productos: int = 0
    filas: int = 0
    fallidos: Dict[int, str] = field(default_factory=dict)


def drenar(
    session_factory: Callable[[], object],
    deadline: datetime,
    *,
    is_transient: Callable[[BaseException], bool],
    limite: int = LIMITE_POR_PASADA,
) -> Drenado:
    """Re-freezes the queued products, one per transaction, until the queue is empty, `limite` products were done or
    the deadline passes (the rest stays queued for the next wake). A product that fails is charged in its own
    transaction and not retried in this run; it parks after `MAX_ATTEMPTS` until a new costo SI change re-queues it.
    A transient error charges nothing and stops the run. Same contract as `costo_si.queue.drenar`."""
    out = Drenado()
    while out.productos + len(out.fallidos) < limite and datetime.now(timezone.utc) < deadline:
        item_id: Optional[int] = None
        try:
            with session_factory() as db:
                fila = _reclamar(db, set(out.fallidos))
                if fila is None:
                    break
                item_id, desde = int(fila[0]), fila[1]
                motivo = f"costo SI desde {desde.isoformat()}" if desde else "costo SI completo"
                cambiadas = recongelar(db, item_id, desde, motivo)
                _bonos_costo(db, item_id)
                db.execute(text("DELETE FROM ml_costo_si_dirty WHERE producto_item_id = :i"), {"i": item_id})
                db.commit()
            out.productos += 1
            out.filas += cambiadas
        except Exception as exc:
            if item_id is None:
                raise  # nothing was claimed: not a product's fault
            if is_transient(exc):
                logger.warning(
                    "ml costo SI: transient error on product %s, nothing charged; stopping: %s", item_id, exc
                )
                break
            logger.exception("ml costo SI: sales of product %s not re-frozen", item_id)
            out.fallidos[item_id] = f"{type(exc).__name__}: {exc}"
            with session_factory() as db:
                attempts = _cobrar(db, item_id, out.fallidos[item_id])
                db.commit()
            if attempts >= MAX_ATTEMPTS:
                logger.error("ml costo SI: product %s parked after %s attempts: %s", item_id, attempts, exc)
    return out
