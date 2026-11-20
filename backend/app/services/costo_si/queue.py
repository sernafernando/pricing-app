"""The `costo_si_dirty` queue: which products must have their costo SI recomputed, and from which date (S8).

No cron: row triggers queue the product (earliest date wins, NULL = whole history) and `pg_notify('sell_dirty')`, the
channel `sell.drain` already listens on; the drain recomputes them after the sale lines (`drenar`). Writers:

- a Compras sell in: `sell_in_compra_items` (insert / update / delete), `sell_in_compras` (update: voided, amounts)
  and its operations `sell_in_compra_pedidos`; from the purchase date;
- a brand bonus of the sale-cost kind (the loyalty, S6) and its models: `sell_in_bonos_marca`, `sell_in_bono_items`;
  every product of its scope, from `fecha_desde`;
- a purchase link: `pedido_compra_facturas` (an invoice linked to or unlinked from a Compras operation, S7) and a PM
  FX correction `costo_si_factura_tc`; the invoice's products, from its date.

A new purchase invoice arrives through the GBP sync, which has no trigger: the daily `stock.snapshot` job queues every
product that has a costo SI or a sell in (`encolar_vigentes`), so it enters the average within a day.

`UPGRADE_SQL`/`DOWNGRADE_SQL` are the live definition; the migration `20261125_costo_si` carries a frozen copy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.costo_si import full_ml, recompute

logger = logging.getLogger(__name__)

CHANNEL = "sell_dirty"
MAX_ATTEMPTS = 5

_ENCOLAR = """
CREATE OR REPLACE FUNCTION costo_si_encolar(p_item integer, p_desde date) RETURNS void AS $f$
BEGIN
    IF p_item IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO costo_si_dirty (item_id, desde) VALUES (p_item, p_desde)
    ON CONFLICT (item_id) DO UPDATE
    SET desde = CASE WHEN costo_si_dirty.desde IS NULL OR EXCLUDED.desde IS NULL THEN NULL
                     ELSE LEAST(costo_si_dirty.desde, EXCLUDED.desde) END,
        enqueued_at = now(), attempts = 0, last_error = NULL;
    PERFORM pg_notify('sell_dirty', '');
END
$f$ LANGUAGE plpgsql
"""

_COMPRA_ITEM = """
CREATE OR REPLACE FUNCTION costo_si_trg_compra_item() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar(OLD.item_id, (SELECT fecha_compra FROM sell_in_compras WHERE id = OLD.compra_id));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar(NEW.item_id, (SELECT fecha_compra FROM sell_in_compras WHERE id = NEW.compra_id));
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

_COMPRA = """
CREATE OR REPLACE FUNCTION costo_si_trg_compra() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar(ci.item_id, LEAST(OLD.fecha_compra, NEW.fecha_compra))
    FROM sell_in_compra_items ci WHERE ci.compra_id = NEW.id;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

# A link added, removed or moved (UPDATE: both the old and the new sell in) re-dates its products.
_COMPRA_PEDIDO = """
CREATE OR REPLACE FUNCTION costo_si_encolar_compra(p_compra bigint) RETURNS void AS $f$
BEGIN
    PERFORM costo_si_encolar(ci.item_id, c.fecha_compra)
    FROM sell_in_compra_items ci JOIN sell_in_compras c ON c.id = ci.compra_id WHERE ci.compra_id = p_compra;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_compra_pedido() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_compra(OLD.compra_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_compra(NEW.compra_id);
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

# A Compras operation's TC (S4: the pedido TC, manual first) feeds the FX of every invoice linked to it.
_PEDIDO_TC = """
CREATE OR REPLACE FUNCTION costo_si_trg_pedido_tc() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar_factura(pf.ct_transaction_id) FROM pedido_compra_facturas pf WHERE pf.pedido_id = NEW.id;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

# A product's brand or category decides which loyalty bonuses reach it (S6): its whole history again.
_PRODUCTO = """
CREATE OR REPLACE FUNCTION costo_si_trg_producto() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar(NEW.item_id, NULL);
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

# The products a sale-cost % bonus reaches (`fuentes._BONOS_SQL`'s scope rule), for OLD and NEW.
_BONO = """
CREATE OR REPLACE FUNCTION costo_si_encolar_bono(r sell_in_bonos_marca) RETURNS void AS $f$
BEGIN
    IF r.base = 'costo_venta' AND r.tipo = 'porcentaje' THEN
        PERFORM costo_si_encolar(p.item_id, r.fecha_desde)
        FROM productos_erp p
        WHERE (r.alcance = 'marca' AND p.marca = r.marca AND (r.categoria IS NULL OR p.categoria = r.categoria))
           OR (r.alcance = 'categoria' AND p.categoria = r.categoria)
           OR (r.alcance = 'modelos' AND p.item_id IN (SELECT bi.item_id FROM sell_in_bono_items bi WHERE bi.bono_id = r.id));
    END IF;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_bono() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_bono(OLD);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_bono(NEW);
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

_BONO_ITEM = """
CREATE OR REPLACE FUNCTION costo_si_trg_bono_item() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar(OLD.item_id, (SELECT fecha_desde FROM sell_in_bonos_marca WHERE id = OLD.bono_id));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar(NEW.item_id, (SELECT fecha_desde FROM sell_in_bonos_marca WHERE id = NEW.bono_id));
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

# Both `pedido_compra_facturas` (ct_transaction_id) and `costo_si_factura_tc` (ct_transaction) point at an invoice.
_FACTURA = """
CREATE OR REPLACE FUNCTION costo_si_encolar_factura(p_ct bigint) RETURNS void AS $f$
BEGIN
    PERFORM costo_si_encolar(it.item_id, ct.ct_date::date)
    FROM tb_item_transactions it JOIN tb_commercial_transactions ct ON ct.ct_transaction = it.ct_transaction
    WHERE it.ct_transaction = p_ct;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_factura() RETURNS TRIGGER AS $t$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_factura((to_jsonb(OLD) ->> TG_ARGV[0])::bigint);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_factura((to_jsonb(NEW) ->> TG_ARGV[0])::bigint);
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

# A supplier credit note imputed to (or released from) an invoice changes that invoice's cost (owner L5); its own
# products are queued too, so their list of unassigned NCs follows. A reversal re-queues what it reverses.
_IMPUTACION = """
CREATE OR REPLACE FUNCTION costo_si_encolar_imputacion(
    p_origen_tipo text, p_origen_id bigint, p_destino_tipo text, p_destino_id bigint
) RETURNS void AS $f$
BEGIN
    IF p_origen_tipo NOT IN ('nota_credito_erp', 'nota_credito_local') THEN
        RETURN;
    END IF;
    IF p_destino_tipo = 'factura_erp' THEN
        PERFORM costo_si_encolar_factura(p_destino_id);
    END IF;
    PERFORM costo_si_encolar_factura(CASE WHEN p_origen_tipo = 'nota_credito_erp' THEN p_origen_id
        ELSE (SELECT ncl.ct_transaction_id FROM notas_credito_local ncl WHERE ncl.id = p_origen_id) END);
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION costo_si_trg_imputacion() RETURNS TRIGGER AS $t$
DECLARE
    o record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM costo_si_encolar_imputacion(OLD.origen_tipo, OLD.origen_id, OLD.destino_tipo, OLD.destino_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM costo_si_encolar_imputacion(NEW.origen_tipo, NEW.origen_id, NEW.destino_tipo, NEW.destino_id);
        IF NEW.reimputada_desde_id IS NOT NULL THEN
            SELECT origen_tipo, origen_id, destino_tipo, destino_id INTO o
            FROM imputaciones WHERE id = NEW.reimputada_desde_id;
            IF FOUND THEN
                PERFORM costo_si_encolar_imputacion(o.origen_tipo, o.origen_id, o.destino_tipo, o.destino_id);
            END IF;
        END IF;
    END IF;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

# A local NC matched to (or unmatched from) its ERP document changes what its imputations point at.
_NC_LOCAL = """
CREATE OR REPLACE FUNCTION costo_si_trg_nc_local() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar_factura(OLD.ct_transaction_id);
    PERFORM costo_si_encolar_imputacion(i.origen_tipo, i.origen_id, i.destino_tipo, i.destino_id)
    FROM imputaciones i WHERE i.origen_tipo = 'nota_credito_local' AND i.origen_id = NEW.id;
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

_TRIGGERS = [
    ("sell_in_compra_items", "costo_si_compra_item", "INSERT OR UPDATE OR DELETE", "costo_si_trg_compra_item()"),
    ("sell_in_compras", "costo_si_compra", "UPDATE", "costo_si_trg_compra()"),
    (
        "sell_in_compra_pedidos",
        "costo_si_compra_pedido",
        "INSERT OR UPDATE OR DELETE",
        "costo_si_trg_compra_pedido()",
    ),
    ("sell_in_bonos_marca", "costo_si_bono", "INSERT OR UPDATE OR DELETE", "costo_si_trg_bono()"),
    ("sell_in_bono_items", "costo_si_bono_item", "INSERT OR UPDATE OR DELETE", "costo_si_trg_bono_item()"),
    (
        "pedido_compra_facturas",
        "costo_si_factura",
        "INSERT OR UPDATE OR DELETE",
        "costo_si_trg_factura('ct_transaction_id')",
    ),
    (
        "costo_si_factura_tc",
        "costo_si_factura_tc",
        "INSERT OR UPDATE OR DELETE",
        "costo_si_trg_factura('ct_transaction')",
    ),
    (
        "pedidos_compra",
        "costo_si_pedido_tc",
        "UPDATE OF tipo_cambio, tipo_cambio_manual",
        "costo_si_trg_pedido_tc()",
        "OLD.tipo_cambio IS DISTINCT FROM NEW.tipo_cambio "
        "OR OLD.tipo_cambio_manual IS DISTINCT FROM NEW.tipo_cambio_manual",
    ),
    (
        "productos_erp",
        "costo_si_producto",
        "UPDATE OF marca, categoria",
        "costo_si_trg_producto()",
        "OLD.marca IS DISTINCT FROM NEW.marca OR OLD.categoria IS DISTINCT FROM NEW.categoria",
    ),
    ("imputaciones", "costo_si_imputacion", "INSERT OR UPDATE OR DELETE", "costo_si_trg_imputacion()"),
    (
        "notas_credito_local",
        "costo_si_nc_local",
        "UPDATE OF ct_transaction_id",
        "costo_si_trg_nc_local()",
        "OLD.ct_transaction_id IS DISTINCT FROM NEW.ct_transaction_id",
    ),
]

_FUNCIONES = [
    "costo_si_trg_nc_local()",
    "costo_si_trg_imputacion()",
    "costo_si_encolar_imputacion(text, bigint, text, bigint)",
    "costo_si_trg_producto()",
    "costo_si_trg_pedido_tc()",
    "costo_si_encolar_compra(bigint)",
    "costo_si_trg_factura()",
    "costo_si_encolar_factura(bigint)",
    "costo_si_trg_bono_item()",
    "costo_si_trg_bono()",
    "costo_si_encolar_bono(sell_in_bonos_marca)",
    "costo_si_trg_compra_pedido()",
    "costo_si_trg_compra()",
    "costo_si_trg_compra_item()",
    "costo_si_encolar(integer, date)",
]


def _crear(table: str, name: str, events: str, fn: str, cuando: str = "") -> str:
    when = f" WHEN ({cuando})" if cuando else ""
    return f"CREATE TRIGGER {name} AFTER {events} ON {table} FOR EACH ROW{when} EXECUTE FUNCTION {fn}"


UPGRADE_SQL: List[str] = [
    _ENCOLAR,
    _COMPRA_ITEM,
    _COMPRA,
    _COMPRA_PEDIDO,
    _BONO,
    _BONO_ITEM,
    _FACTURA,
    _PEDIDO_TC,
    _PRODUCTO,
    _IMPUTACION,
    _NC_LOCAL,
] + [_crear(*t) for t in _TRIGGERS]

DOWNGRADE_SQL: List[str] = [f"DROP TRIGGER IF EXISTS {t[1]} ON {t[0]}" for t in _TRIGGERS] + [
    f"DROP FUNCTION IF EXISTS {fn}" for fn in _FUNCIONES
]


_VIGENTES_SQL = """
    SELECT DISTINCT item_id FROM costo_si_pasos
    UNION SELECT ci.item_id FROM sell_in_compra_items ci
          JOIN sell_in_compras c ON c.id = ci.compra_id AND c.estado = 'activa'
    UNION SELECT p.item_id FROM sell_in_bonos_marca b JOIN productos_erp p
            ON (b.alcance = 'marca' AND p.marca = b.marca AND (b.categoria IS NULL OR p.categoria = b.categoria))
            OR (b.alcance = 'categoria' AND p.categoria = b.categoria)
          WHERE b.estado = 'activa' AND b.base = 'costo_venta' AND b.tipo = 'porcentaje' AND b.tactical_id IS NULL
    UNION SELECT bi.item_id FROM sell_in_bono_items bi JOIN sell_in_bonos_marca b ON b.id = bi.bono_id
          WHERE b.estado = 'activa' AND b.base = 'costo_venta' AND b.tipo = 'porcentaje' AND b.tactical_id IS NULL
"""


def productos_vigentes(db: Session) -> List[int]:
    """Every product with a costo SI, a Compras sell in or a sale-cost % bonus."""
    return sorted(int(r[0]) for r in db.execute(text(_VIGENTES_SQL)))


def encolar_vigentes(db: Session) -> int:
    """Queues every product of `productos_vigentes` for a whole recompute (the daily pass that brings new purchase
    invoices in). Returns how many products were queued."""
    return (
        db.execute(
            text(f"""
        WITH encolados AS (
            INSERT INTO costo_si_dirty (item_id, desde) SELECT item_id, NULL FROM ({_VIGENTES_SQL}) productos
            ON CONFLICT (item_id) DO UPDATE SET desde = NULL, enqueued_at = now(), attempts = 0, last_error = NULL
            RETURNING 1
        )
        SELECT count(*) FROM encolados
    """)
        ).scalar()
        or 0
    )


def hay_pendientes(db: Session) -> bool:
    return db.execute(
        text("SELECT EXISTS (SELECT 1 FROM costo_si_dirty WHERE attempts < :max)"), {"max": MAX_ATTEMPTS}
    ).scalar()


def _reclamar(db: Session, excluidos: Set[int]) -> Optional[tuple]:
    return db.execute(
        text("""
            SELECT item_id, desde FROM costo_si_dirty
            WHERE attempts < :max AND NOT (item_id = ANY(:excluidos))
            ORDER BY enqueued_at, item_id
            LIMIT 1 FOR UPDATE SKIP LOCKED
        """),
        {"max": MAX_ATTEMPTS, "excluidos": sorted(excluidos)},
    ).first()


def _cobrar(db: Session, item_id: int, error: str) -> int:
    return (
        db.execute(
            text(
                "UPDATE costo_si_dirty SET attempts = attempts + 1, last_error = :e WHERE item_id = :i RETURNING attempts"
            ),
            {"i": item_id, "e": error[:2000]},
        ).scalar()
        or 0
    )


@dataclass
class Drenado:
    productos: int = 0
    cambiados: int = 0
    fallidos: Dict[int, str] = field(default_factory=dict)
    diferidos: Set[int] = field(default_factory=set)  # Full operations not kept yet: left queued, not charged


def drenar(
    session_factory: Callable[[], object],
    deadline: datetime,
    hoy: date,
    *,
    ml: Optional[full_ml.ClienteMl],
    is_transient: Callable[[BaseException], bool],
) -> Drenado:
    """Recomputes the queued products, one per transaction, until the queue is empty or the deadline passes. A product
    that fails is charged in its own transaction and not retried in this run; it parks after `MAX_ATTEMPTS` until a
    new change re-queues it. A transient error charges nothing and stops the run. A product whose Full operations
    are not kept yet stays queued, uncharged, until `stock.snapshot` fetches them and re-queues it."""
    out = Drenado()
    while datetime.now(timezone.utc) < deadline:
        item_id: Optional[int] = None
        try:
            with session_factory() as db:
                fila = _reclamar(db, set(out.fallidos) | out.diferidos)
                if fila is None:
                    break
                item_id, desde = int(fila[0]), fila[1]
                motivo = f"recalculo desde {desde.isoformat()}" if desde else "recalculo completo"
                resultado = recompute.recalcular(db, item_id, ml=ml, hoy=hoy, motivo=motivo)
                db.execute(text("DELETE FROM costo_si_dirty WHERE item_id = :i"), {"i": item_id})
                db.commit()
            out.productos += 1
            out.cambiados += 1 if resultado.desde is not None else 0
        except full_ml.FullPendiente as exc:
            logger.info("costo_si: %s; waiting for stock.snapshot", exc)
            out.diferidos.add(item_id)
        except Exception as exc:
            if item_id is None:
                raise  # nothing was claimed: not a product's fault
            if is_transient(exc):
                logger.warning("costo_si: transient error on product %s, nothing charged; stopping: %s", item_id, exc)
                break
            logger.exception("costo_si: product %s not recomputed", item_id)
            out.fallidos[item_id] = f"{type(exc).__name__}: {exc}"
            with session_factory() as db:
                attempts = _cobrar(db, item_id, out.fallidos[item_id])
                db.commit()
            if attempts >= MAX_ATTEMPTS:
                logger.error("costo_si: product %s parked after %s attempts: %s", item_id, attempts, exc)
    return out
