"""
Documentación médica de un caso ART — módulo RRHH.

Almacena archivos adjuntos (certificados médicos, informes de la ART,
alta médica, etc.) vinculados a un caso de accidente de trabajo.

El archivo físico se guarda en {RRHH_UPLOADS_DIR}/art/{art_caso_id}/.
El path_archivo almacena la ruta relativa desde el base upload dir.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RRHHArtDocumento(Base):
    """
    Documento adjunto a un caso ART.

    - path_archivo: ruta relativa (e.g. 'art/42/a1b2c3d4e5f6_informe.pdf')
    - subido_por: usuario que subió el archivo.
    """

    __tablename__ = "rrhh_art_documentos"

    id = Column(Integer, primary_key=True, index=True)
    art_caso_id = Column(
        Integer,
        ForeignKey("rrhh_art_casos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre_archivo = Column(String(255), nullable=False)
    path_archivo = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    tamano_bytes = Column(Integer, nullable=True)
    descripcion = Column(Text, nullable=True)
    subido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    art_caso = relationship("RRHHArtCaso", back_populates="documentos")
    subido_por = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<RRHHArtDocumento(id={self.id}, caso={self.art_caso_id}, archivo='{self.nombre_archivo}')>"
