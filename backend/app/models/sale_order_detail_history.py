from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Boolean, Text, PrimaryKeyConstraint
from app.core.database import Base


class SaleOrderDetailHistory(Base):
    """
    Modelo para tbSaleOrderDetailHistory del ERP
    Historial de cambios en detalle de órdenes de venta (líneas/items)
    """

    __tablename__ = "tb_sale_order_detail_history"
    __table_args__ = (PrimaryKeyConstraint("comp_id", "bra_id", "soh_id", "sohh_id", "sod_id"),)

    # Composite Primary Key
    comp_id = Column(Integer, nullable=False, index=True)
    bra_id = Column(Integer, nullable=False, index=True)
    soh_id = Column(BigInteger, nullable=False, index=True)
    sohh_id = Column(BigInteger, nullable=False, index=True)
    sod_id = Column(BigInteger, nullable=False, index=True)

    # Campos principales (todos en minúsculas para PostgreSQL)
    sod_priority = Column(Integer)
    item_id = Column(Integer, index=True)
    sod_itemdesc = Column(Text)
    sod_detail = Column(Text)
    curr_id = Column(Integer)
    sod_initqty = Column(Numeric(18, 6))
    sod_qty = Column(Numeric(18, 6))
    prli_id = Column(Integer, index=True)
    sod_price = Column(Numeric(18, 6))
    stor_id = Column(Integer)
    sod_lastupdate = Column(DateTime)
    sod_isediting = Column(Boolean)
    sod_insertdate = Column(DateTime)
    user_id = Column(Integer)
    sod_quotation = Column(String(100))
    sod_iscredit = Column(Boolean)
    sod_cost = Column(Numeric(18, 6))
    sod_costtax = Column(Numeric(18, 6))
    rmah_id = Column(Integer)
    rmad_id = Column(Integer)
    sod_note1 = Column(Text)
    sod_note2 = Column(Text)
    sod_itemdiscount = Column(Numeric(18, 6))
    sod_tis_id_origin = Column(BigInteger)
    sod_item_id_origin = Column(Integer)
    sod_isparentassociate = Column(Boolean)
    is_id = Column(Integer)
    it_transaction = Column(BigInteger)
    sod_ismade = Column(Boolean)
    sod_expirationdate = Column(DateTime)
    acc_count_id = Column(Integer)
    sod_packagesqty = Column(Integer)
    item_id_ew = Column(Integer)
    tis_idofthisew = Column(BigInteger)
    camp_id = Column(Integer)
    sod_ewaddress = Column(Text)
    sod_mlcost = Column(Numeric(18, 6))
    sdlmt_id = Column(Integer)
    sops_id = Column(BigInteger)
    sops_supp_id = Column(Integer)
    sops_bra_id = Column(Integer)
    sops_date = Column(DateTime)
    mlo_id = Column(BigInteger, index=True)
    sod_mecost = Column(Numeric(18, 6))
    sod_mpcost = Column(Numeric(18, 6))
    sod_isdivided = Column(Boolean)
    sod_isdivided_date = Column(DateTime)
    user_id_division = Column(Integer)
    sodi_id = Column(BigInteger)
    sod_isdivided_costcoeficient = Column(Numeric(18, 6))
    sops_poh_bra_id = Column(Integer)
    sops_poh_id = Column(BigInteger)
    sops_note = Column(Text)
    sops_user_id = Column(Integer)
    sops_lastupdate = Column(DateTime)

    def __repr__(self):
        return f"<SaleOrderDetailHistory(soh_id={self.soh_id}, sohh_id={self.sohh_id}, sod_id={self.sod_id}, item_id={self.item_id})>"
