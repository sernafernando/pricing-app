"""
Configuración de qué páginas/tabs requieren identificación de operador.

Cada registro define un tab_key (ej: 'envios-flex') dentro de un page_path
(ej: '/pedidos-preparacion') con su timeout de inactividad en minutos.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index
from sqlalchemy.sql import func
from app.core.database import Base


class OperadorConfigTab(Base):
    """Config de tabs que requieren PIN de operador."""

    __tablename__ = "operador_config_tab"

    id = Column(Integer, primary_key=True, index=True)
    tab_key = Column(String(50), nullable=False)  # ej: 'envios-flex', 'preparacion'
    page_path = Column(String(100), nullable=False)  # ej: '/pedidos-preparacion'
    label = Column(String(100), nullable=False)  # ej: 'Envíos Flex'
    timeout_minutos = Column(Integer, nullable=False, default=15)
    activo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_config_tab_key_page", "tab_key", "page_path", unique=True),)

    def __repr__(self) -> str:
        return f"<OperadorConfigTab(tab={self.tab_key}, page={self.page_path}, timeout={self.timeout_minutos}m)>"
