"""
SaleDocument — catálogo de tipos de documento del ERP (seed estático).

Réplica local de la tabla `tbSaleDocument` del ERP. El clasificador
(`sale_document_classifier`) usa los flags booleanos de esta tabla para
determinar la semántica de cada `tb_commercial_transactions.sd_id`
(factura, nota de crédito, anulación, orden de pago, remito, etc.)
sin recurrir a listas hardcodeadas de sd_id.

NO hay sync automático: el ERP cambia 1-2 veces al año estos tipos, así
que se popula vía Alembic migration seed (ver COMPRAS-1.2b) y tipos
nuevos se agregan con una nueva migración. PK manual: `sd_id` viene del
ERP, no es autogenerado.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Index,
    Integer,
    SmallInteger,
    String,
)

from app.core.database import Base


class SaleDocument(Base):
    """Tipo de documento del ERP (factura, NC, ND, anulación, etc.)."""

    __tablename__ = "tb_sale_document"

    sd_id = Column(Integer, primary_key=True, autoincrement=False)
    sd_desc = Column(String(200), nullable=False)
    sd_iscredit = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_isquotation = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_isreceipt = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_istaxable = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_isinbalance = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_issales = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_ispurchase = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_isbanking = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_ispackinglist = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_iscreditnote = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_isdebitnote = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_isannulment = Column(Boolean, nullable=False, default=False, server_default="false")
    sd_plusorminus = Column(SmallInteger, nullable=False)
    hacc_group = Column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint("sd_plusorminus IN (1, -1)", name="ck_tb_sale_document_plusorminus"),
        Index(
            "ix_tb_sale_document_ispurchase",
            "sd_ispurchase",
            postgresql_where="sd_ispurchase = true",
        ),
        Index(
            "ix_tb_sale_document_isannul",
            "sd_isannulment",
            postgresql_where="sd_isannulment = true",
        ),
        Index(
            "ix_tb_sale_document_hacc",
            "hacc_group",
            postgresql_where="hacc_group IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<SaleDocument(sd_id={self.sd_id}, sd_desc='{self.sd_desc}')>"
