"""
Documentos del legajo de un empleado.

Cada documento es un archivo físico (PDF, imagen) asociado a un empleado
y clasificado por tipo (RRHHTipoDocumento).

Archivos almacenados en: {RRHH_UPLOADS_DIR}/{empleado_id}/{uuid}_{filename}
El campo path_archivo guarda el path relativo (no absoluto).
"""

from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RRHHDocumento(Base):
    """
    Archivo del legajo de un empleado.

    Almacena metadata del archivo + path relativo en disco.
    El archivo real se sirve a través de un endpoint auth-gated (no StaticFiles).
    """

    __tablename__ = "rrhh_documentos"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo_documento_id = Column(
        Integer,
        ForeignKey("rrhh_tipo_documento.id"),
        nullable=False,
        index=True,
    )

    # File storage
    nombre_archivo = Column(String(255), nullable=False)
    path_archivo = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    tamano_bytes = Column(Integer, nullable=True)

    # Metadata
    descripcion = Column(Text, nullable=True)
    fecha_vencimiento = Column(Date, nullable=True)
    numero_documento = Column(String(100), nullable=True)

    # Audit
    subido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado", back_populates="documentos")
    tipo_documento = relationship("RRHHTipoDocumento")
    subido_por = relationship("Usuario")

    __table_args__ = (Index("idx_rrhh_docs_empleado_tipo", "empleado_id", "tipo_documento_id"),)

    def __repr__(self) -> str:
        return f"<RRHHDocumento(id={self.id}, empleado_id={self.empleado_id}, archivo='{self.nombre_archivo}')>"
