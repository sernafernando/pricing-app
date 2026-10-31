"""Gestión Full send package and lines (shared weekly envío plan)."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
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

PACKAGE_STATUS_OPEN = "open"
PACKAGE_STATUS_EXPORTED = "exported"
PACKAGE_STATUS_LOCKED = "locked"


class GestionFullPackage(Base):
    """One shared working package until hard-locked (all inbound_ids assigned)."""

    __tablename__ = "gestion_full_package"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'exported', 'locked')",
            name="ck_gestion_full_package_status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_monday = Column(Date, nullable=False, index=True)
    status = Column(Text, nullable=False, server_default=PACKAGE_STATUS_OPEN)
    exported_at = Column(DateTime(timezone=True), nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    created_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    created_by = relationship("Usuario", foreign_keys=[created_by_id])
    lines = relationship(
        "GestionFullPackageLine",
        back_populates="package",
        cascade="all, delete-orphan",
    )


class GestionFullPackageLine(Base):
    """One ERP+MLAU line inside a package; qty_export drives Excel."""

    __tablename__ = "gestion_full_package_line"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "producto_item_id",
            "user_product_id",
            name="uq_gestion_full_package_line_key",
        ),
        CheckConstraint("qty_pm >= 0", name="ck_gestion_full_package_line_qty_pm"),
        CheckConstraint("qty_export >= 0", name="ck_gestion_full_package_line_qty_export"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    package_id = Column(
        Integer,
        ForeignKey("gestion_full_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    producto_item_id = Column(
        Integer,
        ForeignKey("productos_erp.item_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_product_id = Column(Text, nullable=False)
    inventory_id = Column(Text, nullable=False)
    qty_pm = Column(Integer, nullable=False)
    qty_export = Column(Integer, nullable=False)
    qty_export_reason = Column(Text, nullable=True)
    qty_export_updated_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    qty_export_updated_at = Column(DateTime(timezone=True), nullable=True)
    inbound_id = Column(Text, nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    package = relationship("GestionFullPackage", back_populates="lines")
    qty_export_updated_by = relationship(
        "Usuario",
        foreign_keys=[qty_export_updated_by_id],
    )
    audits = relationship(
        "GestionFullQtyExportAudit",
        back_populates="line",
        cascade="all, delete-orphan",
    )


class GestionFullQtyExportAudit(Base):
    """Audit trail for gestor qty_export adjustments (reason optional)."""

    __tablename__ = "gestion_full_qty_export_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    package_line_id = Column(
        Integer,
        ForeignKey("gestion_full_package_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_qty = Column(Integer, nullable=False)
    new_qty = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    updated_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    line = relationship("GestionFullPackageLine", back_populates="audits")
    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])
