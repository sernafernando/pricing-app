"""Suspicious purchase prices held out of costo SI until reviewed (owner L29).

The engine (`engine.calcular`) decides which purchases are suspicious: their net unit price is below 1/10 or above
10x the costo SI right before them (or the list cost when there is none). This module keeps the review list in
`costo_si_compras_sospechosas` in step with each recompute, and records the reviewer's decision:

- The recompute calls `reconciliar` with the steps it just computed, in its own transaction:
  - a new suspicious purchase is inserted 'pendiente' and logged;
  - a row whose price or quantity changed (a corrected invoice in GBP, picked up by the daily whole-history requeue)
    goes back to 'pendiente', with its review cleared, and is logged;
  - a row whose purchase is no longer suspicious, or no longer exists, is deleted.
- `fuentes.entrada` reads `aceptadas`: the accepted rows whose price and quantity still match the purchase. Those
  enter the average; every other suspicious purchase is excluded.
- A reviewer accepts or keeps excluded (`decidir`). The trigger below requeues the product from the invoice date on
  every change of `estado`, so the normal drain recomputes it (backups, L15 callbacks).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, FrozenSet, List, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.commercial_transaction import CommercialTransaction
from app.models.costo_si import CostoSiCompraSospechosa
from app.models.tb_item import TBItem
from app.models.usuario import Usuario
from app.services.costo_si.engine import Paso, redondear

logger = logging.getLogger(__name__)

PERMISO_REVISAR = "costo_si.revisar"  # decide on a suspicious purchase (migration 20261129)

PENDIENTE = "pendiente"
ACEPTADA = "aceptada"
EXCLUIDA = "excluida"
ESTADOS = (PENDIENTE, ACEPTADA, EXCLUIDA)
DECISIONES = (ACEPTADA, EXCLUIDA)

RATIO = Decimal("0.000001")

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION costo_si_trg_sospechosa() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar(NEW.item_id, NEW.fecha);
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
"""

UPGRADE_SQL: List[str] = [
    _TRIGGER_FN,
    "CREATE TRIGGER costo_si_sospechosa AFTER UPDATE OF estado ON costo_si_compras_sospechosas FOR EACH ROW "
    "WHEN (OLD.estado IS DISTINCT FROM NEW.estado) EXECUTE FUNCTION costo_si_trg_sospechosa()",
]

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS costo_si_sospechosa ON costo_si_compras_sospechosas",
    "DROP FUNCTION IF EXISTS costo_si_trg_sospechosa()",
]


class DecisionInvalida(ValueError):
    """The decision is not one of `DECISIONES`."""


class PrecioCambiado(ValueError):
    """The row changed (its price, quantity or state) since the reviewer saw it."""


@dataclass(frozen=True)
class _Guardada:
    id: int
    cantidad: int
    precio: Decimal
    estado: str


def aceptadas(db: Session, item_id: int, compras: Sequence) -> FrozenSet[int]:
    """The invoices of `item_id` whose suspicious purchase a reviewer accepted, as long as its price and quantity are
    still the ones accepted (`compras`: the engine's `Compra`s): a corrected invoice needs a new review."""
    filas = db.execute(
        text(
            "SELECT ct_transaction, cantidad, precio FROM costo_si_compras_sospechosas "
            "WHERE item_id = :i AND estado = :e"
        ),
        {"i": item_id, "e": ACEPTADA},
    ).all()
    if not filas:
        return frozenset()
    actuales = {c.ct_transaction: (c.cantidad, redondear(c.costo_neto_usd)) for c in compras}
    return frozenset(ct for ct, cantidad, precio in filas if actuales.get(ct) == (cantidad, Decimal(precio)))


def _ratio(paso: Paso) -> Decimal:
    return (paso.costo_neto_usd / paso.referencia).quantize(RATIO)


def reconciliar(db: Session, item_id: int, pasos: Sequence[Paso], moneda: str) -> None:
    """Brings the review rows of `item_id` in step with its freshly computed steps (module docstring). Does not
    commit; never fires the requeue trigger for a new or unchanged row."""
    sospechas: Dict[int, Paso] = {p.ct_transaction: p for p in pasos if p.referencia is not None}
    guardadas = {
        ct: _Guardada(id_, cantidad, Decimal(precio), estado)
        for id_, ct, cantidad, precio, estado in db.execute(
            text(
                "SELECT id, ct_transaction, cantidad, precio, estado FROM costo_si_compras_sospechosas "
                "WHERE item_id = :i"
            ),
            {"i": item_id},
        )
    }
    sobran = [g.id for ct, g in guardadas.items() if ct not in sospechas]
    if sobran:
        db.execute(text("DELETE FROM costo_si_compras_sospechosas WHERE id = ANY(:ids)"), {"ids": sobran})
        for ct, g in guardadas.items():
            if ct not in sospechas and g.estado != PENDIENTE:
                logger.info(
                    "costo SI: item %s invoice %s is no longer suspicious; its %s review was dropped",
                    item_id,
                    ct,
                    g.estado,
                )
    for ct, paso in sospechas.items():
        datos = {
            "i": item_id,
            "ct": ct,
            "fecha": paso.fecha,
            "cantidad": paso.cantidad,
            "precio": paso.costo_neto_usd,
            "moneda": moneda,
            "ref": paso.referencia,
            "fuente": paso.fuente_ref,
            "ratio": _ratio(paso),
        }
        g = guardadas.get(ct)
        if g is None:
            db.execute(
                text(
                    "INSERT INTO costo_si_compras_sospechosas "
                    "(item_id, ct_transaction, fecha, cantidad, precio, moneda, referencia, fuente_ref, ratio) "
                    "VALUES (:i, :ct, :fecha, :cantidad, :precio, :moneda, :ref, :fuente, :ratio)"
                ),
                datos,
            )
            logger.warning(
                "costo SI: suspicious purchase held out of the average: item %s invoice %s date %s price %s %s "
                "reference %s (%s)",
                item_id,
                ct,
                paso.fecha,
                paso.costo_neto_usd,
                moneda,
                paso.referencia,
                paso.fuente_ref,
            )
        elif (g.cantidad, g.precio) != (paso.cantidad, paso.costo_neto_usd):
            # A corrected invoice: a new review. Going back to 'pendiente' requeues once more (harmless: the engine
            # already left it out, since `aceptadas` only keeps an unchanged accepted row).
            db.execute(
                text(
                    "UPDATE costo_si_compras_sospechosas SET fecha = :fecha, cantidad = :cantidad, precio = :precio, "
                    "moneda = :moneda, referencia = :ref, fuente_ref = :fuente, ratio = :ratio, estado = 'pendiente', "
                    "revisado_por = NULL, revisado_at = NULL, detectada_at = now() WHERE id = :id"
                ),
                {**datos, "id": g.id},
            )
            logger.warning(
                "costo SI: suspicious purchase changed, back to review: item %s invoice %s date %s price %s -> %s %s "
                "reference %s (%s)",
                item_id,
                ct,
                paso.fecha,
                g.precio,
                paso.costo_neto_usd,
                moneda,
                paso.referencia,
                paso.fuente_ref,
            )
        else:
            db.execute(
                text(
                    "UPDATE costo_si_compras_sospechosas SET fecha = :fecha, moneda = :moneda, referencia = :ref, "
                    "fuente_ref = :fuente, ratio = :ratio WHERE id = :id AND (fecha, moneda, referencia, fuente_ref, "
                    "ratio) IS DISTINCT FROM (:fecha, :moneda, :ref, :fuente, :ratio)"
                ),
                {**datos, "id": g.id},
            )


# ------------------------------------------------------------------------------------------------------------ review
# The ORM, not raw SQL: the API runs on Postgres and its tests on SQLite.


def _consulta(db: Session):
    s = CostoSiCompraSospechosa
    factura = (
        select(CommercialTransaction.ct_docNumber)
        .where(CommercialTransaction.ct_transaction == s.ct_transaction)
        .limit(1)
        .scalar_subquery()
    )
    item = select(TBItem).where(TBItem.item_id == s.item_id).order_by(TBItem.comp_id).limit(1)
    codigo = item.with_only_columns(TBItem.item_code).scalar_subquery()
    descripcion = item.with_only_columns(TBItem.item_desc).scalar_subquery()
    revisor = select(Usuario.nombre).where(Usuario.id == s.revisado_por).scalar_subquery()
    return db.query(
        s,
        factura.label("factura"),
        codigo.label("codigo"),
        descripcion.label("descripcion"),
        revisor.label("revisor"),
    )


def _dict(fila) -> dict:
    s = fila[0]
    return {
        **{c.name: getattr(s, c.key) for c in CostoSiCompraSospechosa.__table__.columns},
        "factura": fila.factura,
        "codigo": fila.codigo,
        "descripcion": fila.descripcion,
        "revisor": fila.revisor,
    }


def listar(
    db: Session, estado: Optional[str] = None, item_id: Optional[int] = None, desde: Optional[date] = None
) -> List[dict]:
    """The review list, newest invoice first, with the invoice number, product code and description, and reviewer."""
    s = CostoSiCompraSospechosa
    q = _consulta(db)
    if estado is not None:
        q = q.filter(s.estado == estado)
    if item_id is not None:
        q = q.filter(s.item_id == item_id)
    if desde is not None:
        q = q.filter(s.fecha >= desde)
    return [_dict(f) for f in q.order_by(s.fecha.desc(), s.id.desc()).all()]


def pendientes(db: Session) -> int:
    s = CostoSiCompraSospechosa
    return int(db.query(func.count(s.id)).filter(s.estado == PENDIENTE).scalar() or 0)


def decidir(
    db: Session,
    sospecha_id: int,
    decision: str,
    usuario_id: int,
    precio_visto: Decimal,
    nota: Optional[str] = None,
) -> Optional[dict]:
    """Records the reviewer's decision ('aceptada' or 'excluida') on one row; None when there is no such row. The
    row must still have the price the reviewer saw (`PrecioCambiado` otherwise: a corrected invoice is a new review).
    Does not commit: the trigger requeues the product from the invoice date when the state changes."""
    if decision not in DECISIONES:
        raise DecisionInvalida(decision)
    s = CostoSiCompraSospechosa
    fila = db.query(s).filter(s.id == sospecha_id).with_for_update().one_or_none()
    if fila is None:
        return None
    if redondear(Decimal(fila.precio)) != redondear(Decimal(precio_visto)):
        raise PrecioCambiado(sospecha_id)
    fila.estado = decision
    fila.revisado_por = usuario_id
    fila.revisado_at = datetime.now(timezone.utc)
    fila.nota = nota
    db.flush()
    return _dict(_consulta(db).filter(s.id == sospecha_id).one())
