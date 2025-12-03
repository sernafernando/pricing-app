"""
Modelo para tbDocumentFile - Tipos de Documento (versión reducida)
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TBDocumentFile(Base):
    """Tabla de tipos de documento del ERP"""
    __tablename__ = "tb_document_file"

    # Primary Keys
    comp_id = Column(Integer, primary_key=True)
    bra_id = Column(Integer, primary_key=True)
    df_id = Column(Integer, primary_key=True, index=True)

    # Datos básicos
    df_desc = Column(String(255))
    df_pointofsale = Column(Integer)
    df_number = Column(Integer)
    df_tonumber = Column(Integer)

    # Estado
    df_disabled = Column(Boolean, default=False)
    df_iselectronicinvoice = Column(Boolean, default=False)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBDocumentFile(df_id={self.df_id}, df_desc='{self.df_desc}')>"
