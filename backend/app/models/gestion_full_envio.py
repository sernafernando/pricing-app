"""Local Full envíos (inbound_id) and persisted INBOUND_RECEPTION ops."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class GestionFullEnvio(Base):
    """One ML inbound_id under a locked/exported package (D4 / D7)."""

    __tablename__ = "gestion_full_envio"

    inbound_id = Column(Text, primary_key=True)
    package_id = Column(
        Integer,
        ForeignKey("gestion_full_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    week_monday = Column(Date, nullable=False)
    reception_closed_at = Column(DateTime(timezone=True), nullable=True)
    last_reception_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    package = relationship("GestionFullPackage")
    ops = relationship(
        "GestionFullInboundReceptionOp",
        back_populates="envio",
        cascade="all, delete-orphan",
    )


class GestionFullInboundReceptionOp(Base):
    """Persisted INBOUND_RECEPTION credit for reconcile (D8b)."""

    __tablename__ = "gestion_full_inbound_reception_op"
    __table_args__ = (UniqueConstraint("operation_id", name="uq_gestion_full_inbound_reception_op_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation_id = Column(BigInteger, nullable=False)
    inbound_id = Column(
        Text,
        ForeignKey("gestion_full_envio.inbound_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inventory_id = Column(Text, nullable=False, index=True)
    cantidad = Column(Integer, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    envio = relationship("GestionFullEnvio", back_populates="ops")
