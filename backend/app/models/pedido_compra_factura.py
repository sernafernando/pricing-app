"""
PedidoCompraFactura — N ERP commercial transactions linked to one pedido (M:N).

Relation table is the source of truth. Header `pedidos_compra.ct_transaction_id`
/ `fecha_factura` stay as a first-link cache; writers update both.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import logging
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, UniqueConstraint, bindparam, text
from sqlalchemy.orm import Session, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.pedido_compra import PedidoCompra

logger = logging.getLogger(__name__)


class PedidoCompraFactura(Base):
    """One ERP CT linked to a pedido de compra (documental; may be shared)."""

    __tablename__ = "pedido_compra_facturas"

    id = Column(BigInteger, primary_key=True, index=True)
    pedido_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="CASCADE"),
        nullable=False,
    )
    ct_transaction_id = Column(BigInteger, nullable=False)
    fecha_factura = Column(Date, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    pedido = relationship("PedidoCompra", foreign_keys=[pedido_id], back_populates="facturas")

    __table_args__ = (
        UniqueConstraint(
            "pedido_id",
            "ct_transaction_id",
            name="uq_pedido_compra_facturas_pedido_ct",
        ),
        Index("ix_pedido_compra_facturas_pedido_id", "pedido_id"),
        Index("ix_pedido_compra_facturas_ct_transaction_id", "ct_transaction_id"),
    )

    def __repr__(self) -> str:
        return f"<PedidoCompraFactura(id={self.id}, pedido_id={self.pedido_id}, ct={self.ct_transaction_id})>"


def cts_for_pedido(session: Session, pedido: "PedidoCompra") -> list[tuple[int, date | None]]:
    """SoT CT links from `pedido_compra_facturas`, else the header first-link cache."""
    rows: Sequence[PedidoCompraFactura] = (
        session.query(PedidoCompraFactura)
        .filter(PedidoCompraFactura.pedido_id == pedido.id)
        .order_by(PedidoCompraFactura.id)
        .all()
    )
    if rows:
        return [(int(row.ct_transaction_id), row.fecha_factura) for row in rows]
    if getattr(pedido, "ct_transaction_id", None) is not None:
        return [(int(pedido.ct_transaction_id), getattr(pedido, "fecha_factura", None))]
    return []


def count_pedidos_for_ct(session: Session, ct_transaction_id: int) -> int:
    """How many pedidos documentally link this CT (junction SoT, else header)."""
    junction = (
        session.query(PedidoCompraFactura.pedido_id)
        .filter(PedidoCompraFactura.ct_transaction_id == int(ct_transaction_id))
        .distinct()
        .count()
    )
    if junction:
        return int(junction)
    from app.models.pedido_compra import PedidoCompra

    return session.query(PedidoCompra.id).filter(PedidoCompra.ct_transaction_id == int(ct_transaction_id)).count()


def ct_docnumbers_by_id(session: Session | None, ct_ids: list[int]) -> dict[int, str]:
    """Map ct_transaction → ct_docnumber from the ERP mirror (best-effort).

    Uses a SAVEPOINT so a missing/broken view (SQLite unit tests, or a
    transient Postgres error) does not abort the outer transaction.
    """
    if session is None or not ct_ids:
        return {}

    stmt = text(
        """
        SELECT ct_transaction, ct_docnumber
        FROM v_facturas_compra_vigentes
        WHERE ct_transaction IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    try:
        with session.begin_nested():
            rows = session.execute(stmt, {"ids": [int(x) for x in ct_ids]}).all()
    except Exception as exc:  # noqa: BLE001 — view absent in SQLite unit tests
        logger.warning("facturas payload: ct_docnumber lookup skipped: %s", exc)
        return {}
    out: dict[int, str] = {}
    for row in rows:
        ct = int(row[0])
        doc = str(row[1] or "").strip()
        if doc:
            out[ct] = doc
    return out
