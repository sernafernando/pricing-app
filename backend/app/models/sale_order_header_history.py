from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Boolean, Text, PrimaryKeyConstraint
from app.core.database import Base


class SaleOrderHeaderHistory(Base):
    """
    Modelo para tbSaleOrderHeaderHistory del ERP
    Historial de cambios en cabecera de órdenes de venta
    """
    __tablename__ = "tb_sale_order_header_history"
    __table_args__ = (
        PrimaryKeyConstraint('comp_id', 'bra_id', 'soh_id', 'sohh_id'),
    )

    # Composite Primary Key
    comp_id = Column(Integer, nullable=False, index=True)
    bra_id = Column(Integer, nullable=False, index=True)
    soh_id = Column(BigInteger, nullable=False, index=True)
    sohh_id = Column(BigInteger, nullable=False, index=True)

    # Campos principales (todos en minúsculas para PostgreSQL)
    sohh_typeofhistory = Column(Integer)
    soh_cd = Column(DateTime)
    soh_deliverydate = Column(DateTime)
    soh_observation1 = Column(Text)
    soh_observation2 = Column(Text)
    soh_observation3 = Column(Text)
    soh_observation4 = Column(Text)
    soh_quotation = Column(Boolean)
    sm_id = Column(Integer)
    cust_id = Column(Integer, index=True)
    st_id = Column(Integer)
    disc_id = Column(Integer)
    dl_id = Column(Integer)
    soh_lastupdate = Column(DateTime)
    soh_limitdate = Column(DateTime)
    tt_id = Column(Integer)
    tt_class = Column(String(10))
    soh_statusof = Column(Integer)
    user_id = Column(Integer)
    soh_isediting = Column(Boolean)
    soh_iseditingcd = Column(DateTime)
    df_id = Column(Integer)
    soh_total = Column(Numeric(18, 6))
    ssos_id = Column(Integer)
    soh_exchangetocustomercurrency = Column(Numeric(18, 6))
    soh_customercurrency = Column(Integer)
    soh_discount = Column(Numeric(18, 6))
    soh_packagesqty = Column(Integer)
    soh_internalannotation = Column(Text)
    curr_id4exchange = Column(Integer)
    curr_idexchange = Column(Numeric(18, 6))
    soh_atotal = Column(Numeric(18, 6))
    soh_incash = Column(Numeric(18, 6))
    ct_transaction = Column(BigInteger)
    sohh_cd = Column(DateTime)
    sohh_user_id = Column(Integer)
    soh_mlquestionsandanswers = Column(Text)
    soh_mlid = Column(String(100))
    soh_mlguia = Column(String(100))
    ws_paymentgatewaystatusid = Column(Integer)
    soh_deliveryaddress = Column(Text)
    stor_id = Column(Integer)
    mlo_id = Column(BigInteger, index=True)
    soh_note4externaluse = Column(Text)
    sohh_ispackingofpreinvoice = Column(Boolean)
    soh_uniqueid = Column(Integer)

    def __repr__(self):
        return f"<SaleOrderHeaderHistory(soh_id={self.soh_id}, sohh_id={self.sohh_id}, sohh_typeofhistory={self.sohh_typeofhistory})>"
