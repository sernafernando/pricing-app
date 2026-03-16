from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class AdjuntoTicket(Base):
    """
    Archivos adjuntos asociados a un ticket.

    Almacenamiento en disco (no BLOB) siguiendo el mismo patrón que RRHH.
    Los archivos se guardan en TICKETS_UPLOADS_DIR/{ticket_id}/{uuid}_{filename}.

    MIME types permitidos: imágenes (png, jpg, gif, webp), PDF, documentos Office.
    Tamaño máximo: TICKETS_MAX_FILE_SIZE_MB (default 5MB).
    """

    __tablename__ = "tickets_adjuntos"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre_archivo = Column(String(255), nullable=False)
    path_archivo = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    tamano_bytes = Column(Integer, nullable=False)
    subido_por_id = Column(
        Integer,
        ForeignKey("usuarios.id"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relaciones
    ticket = relationship("Ticket", back_populates="adjuntos")
    subido_por = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<AdjuntoTicket ticket={self.ticket_id} archivo={self.nombre_archivo}>"
