"""
Modelo para tbItem - Items/Productos
"""

from sqlalchemy import Boolean, Column, Integer, Numeric, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class TBItem(Base):
    """Tabla principal de items del ERP"""

    __tablename__ = "tb_item"

    comp_id = Column(Integer, primary_key=True)
    item_id = Column(Integer, primary_key=True, index=True)
    item_code = Column(String(100), nullable=False)
    item_desc = Column(String(500))
    cat_id = Column(Integer)
    subcat_id = Column(Integer)
    brand_id = Column(Integer)
    item_liquidation = Column(String(50))
    # Flag GBP: el item exige N° de serie (BIT en SQL Server → BOOLEAN local)
    # NULL hasta que el sync lo populate; default lógico en queries: TRUE
    item_expser = Column(Boolean, nullable=True)
    item_cd = Column(DateTime)  # created date
    item_LastUpdate = Column(DateTime)  # last update (generic)
    item_lastUpdate_byProcess = Column(DateTime)  # last update by process (más preciso para sync incremental)

    # Whole scriptItem row as the ERP sent it: nothing the ERP returns is dropped.
    raw = Column(JSONB, nullable=True)

    # Dimensions (ERP spelling kept, including "higth")
    item_weight = Column(Numeric(18, 9), nullable=True)
    item_volume = Column(Numeric(18, 9), nullable=True)
    item_wide = Column(Numeric(18, 9), nullable=True)
    item_large = Column(Numeric(18, 9), nullable=True)
    item_higth = Column(Numeric(18, 9), nullable=True)

    # Website images
    item_WebSite_url4Image1 = Column(Text, nullable=True)
    item_WebSite_url4Image2 = Column(Text, nullable=True)
    item_WebSite_url4Image3 = Column(Text, nullable=True)
    item_WebSite_url4Image4 = Column(Text, nullable=True)
    item_WebSite_url4Image5 = Column(Text, nullable=True)
    item_WebSite_url4Image6 = Column(Text, nullable=True)
    item_WebSite_url4Image7 = Column(Text, nullable=True)
    item_WebSite_url4Image8 = Column(Text, nullable=True)
    item_WebSite_url4Image9 = Column(Text, nullable=True)
    item_WebSite_url4Image10 = Column(Text, nullable=True)

    def __repr__(self):
        return f"<TBItem(item_id={self.item_id}, item_code='{self.item_code}', item_desc='{self.item_desc}')>"
