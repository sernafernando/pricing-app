from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Boolean, Text, PrimaryKeyConstraint
from app.core.database import Base


class PurchaseOrderHeader(Base):
    """
    Modelo para tbPurchaseOrderHeader del ERP
    Cabecera de órdenes de compra
    """

    __tablename__ = "tb_purchase_order_header"
    __table_args__ = (PrimaryKeyConstraint("comp_id", "bra_id", "poh_id"),)

    # Clave primaria compuesta
    comp_id = Column(Integer, nullable=False, index=True)
    bra_id = Column(Integer, nullable=False, index=True)
    poh_id = Column(BigInteger, nullable=False, index=True)

    # Campos de fecha
    poh_cd = Column(DateTime, index=True)
    poh_estdeliverydate = Column(DateTime)
    poh_deliverydate = Column(DateTime)

    # Observaciones
    poh_observation1 = Column(Text)
    poh_observation2 = Column(Text)
    poh_observation3 = Column(Text)
    poh_observation4 = Column(Text)

    # Proveedor y referencias
    supp_id = Column(Integer, index=True)
    poh_quotation = Column(String(100))
    pt_id = Column(Integer)

    # Flags de edición
    poh_isediting = Column(Boolean)
    poh_iseditingcd = Column(DateTime, index=True)

    # Tipo de transacción
    ptr_id = Column(Integer)

    # Moneda y financiero
    poh_acurrency = Column(Integer)
    poh_acurrencyexchange = Column(Numeric(18, 6))
    poh_perceptions = Column(Numeric(18, 6))
    poh_taxes = Column(Numeric(18, 6))
    poh_charges = Column(Numeric(18, 6))

    # Descuentos
    poh_discount1 = Column(Numeric(18, 6))
    poh_discount2 = Column(Numeric(18, 6))
    poh_discount3 = Column(Numeric(18, 6))
    poh_discount4 = Column(Numeric(18, 6))

    # Campo con typo original del ERP conservado (pho_ en lugar de poh_)
    pho_selectedinrecepcion = Column(Boolean)

    # Otros campos
    user_id = Column(Integer)
    poh_validup2date = Column(DateTime)
    poa_id = Column(Integer)
    poh_pendingcoeficient = Column(Numeric(18, 6))
    poh_taxcoeficient = Column(Numeric(18, 6))
    simi_id = Column(Integer)
    pro_id = Column(Integer)

    # Totales
    poh_total = Column(Numeric(18, 6))
    poh_totalinsuppcurrency = Column(Numeric(18, 6))
    poh_isemailenvied = Column(Boolean)

    def __repr__(self) -> str:
        return f"<PurchaseOrderHeader(poh_id={self.poh_id}, comp_id={self.comp_id}, bra_id={self.bra_id})>"
