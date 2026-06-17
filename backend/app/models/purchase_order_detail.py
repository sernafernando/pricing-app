from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Boolean, Text, PrimaryKeyConstraint
from app.core.database import Base


class PurchaseOrderDetail(Base):
    """
    Modelo para tbPurchaseOrderDetail del ERP
    Detalle de órdenes de compra
    """

    __tablename__ = "tb_purchase_order_detail"
    __table_args__ = (PrimaryKeyConstraint("comp_id", "bra_id", "poh_id", "pod_id"),)

    # Clave primaria compuesta
    comp_id = Column(Integer, nullable=False, index=True)
    bra_id = Column(Integer, nullable=False, index=True)
    poh_id = Column(BigInteger, nullable=False, index=True)
    pod_id = Column(BigInteger, nullable=False, index=True)

    # Relaciones
    item_id = Column(Integer, index=True)
    curr_id = Column(Integer)
    cont_id = Column(Integer)

    # Cantidades y precios
    pod_qty = Column(Numeric(18, 6))
    pod_price = Column(Numeric(18, 6))
    tax_id = Column(Integer)

    # Flags de estado
    pod_isprocessed = Column(Boolean)
    pod_isediting = Column(Boolean)
    pod_iseditingcd = Column(DateTime, index=True)

    # Observaciones
    pod_obs = Column(Text)

    # Precio alternativo
    pod_priceb = Column(Numeric(18, 6))

    # Campos custom — ⚠️ tipo inferido, validar contra data real del ERP
    pod_custom = Column(Boolean)  # ⚠️ tipo inferido, validar contra data real del ERP
    pod_customnumber = Column(String(100))  # ⚠️ tipo inferido, validar contra data real del ERP

    # Descuentos
    pod_discount1 = Column(Numeric(18, 6))
    pod_discount2 = Column(Numeric(18, 6))
    pod_discount3 = Column(Numeric(18, 6))
    pod_discount4 = Column(Numeric(18, 6))

    # Importación y cantidades
    djai_id = Column(Integer)
    pod_initqty = Column(Numeric(18, 6))
    pod_confirmedqty = Column(Numeric(18, 6))

    # Recargos
    pod_surcharge1 = Column(Numeric(18, 6))
    pod_surcharge2 = Column(Numeric(18, 6))
    pod_surcharge3 = Column(Numeric(18, 6))
    pod_surcharge4 = Column(Numeric(18, 6))

    # Precio final
    pod_pricewithdiscountandcharges = Column(Numeric(18, 6))

    # Referencias a SIMI
    simi_id = Column(Integer)
    simid_id = Column(Integer)

    # Trazabilidad — ⚠️ tipo inferido, validar contra data real del ERP
    pod_origin = Column(String(100))  # ⚠️ tipo inferido, validar contra data real del ERP
    pod_from = Column(String(100))  # ⚠️ tipo inferido, validar contra data real del ERP
    pod_stamp = Column(String(100))  # ⚠️ tipo inferido, validar contra data real del ERP

    # Lote y vencimiento
    pod_lotnumber = Column(String(100))
    pod_expirationdate = Column(DateTime)
    pod_includeinavailablestock = Column(Boolean)

    # Referencia origen
    pod_id_from = Column(BigInteger)
    pod_id_from_cd = Column(DateTime)
    stor_id = Column(Integer)

    def __repr__(self) -> str:
        return f"<PurchaseOrderDetail(pod_id={self.pod_id}, poh_id={self.poh_id}, comp_id={self.comp_id}, bra_id={self.bra_id})>"
