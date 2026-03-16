from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class SectorUsuario(Base):
    """
    Tabla M2M que asocia usuarios a sectores de tickets.

    Define qué usuarios pueden ser asignados a tickets dentro de un sector.
    Un usuario puede pertenecer a múltiples sectores y un sector puede
    tener múltiples usuarios.

    La constraint UNIQUE(sector_id, usuario_id) evita duplicados.
    El flag 'activo' permite soft-delete sin perder historial.
    """

    __tablename__ = "tickets_sectores_usuarios"
    __table_args__ = (UniqueConstraint("sector_id", "usuario_id", name="uq_sector_usuario"),)

    id = Column(Integer, primary_key=True, index=True)
    sector_id = Column(
        Integer,
        ForeignKey("tickets_sectores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    usuario_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relaciones
    sector = relationship("Sector", back_populates="usuarios_sector")
    usuario = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<SectorUsuario sector={self.sector_id} usuario={self.usuario_id} activo={self.activo}>"
