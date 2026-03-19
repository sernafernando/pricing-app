"""
Sistema de Templates de Documentos
- Templates diseñados visualmente con pdfme (WYSIWYG)
- Almacenados como JSON (JSONB) en PostgreSQL
- Asociados a un contexto (módulo: pedidos, rrhh, envios, etc.)
- PDF se genera 100% en frontend con @pdfme/generator
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


# Contextos válidos — cada uno mapea a un módulo del sistema
CONTEXTOS_VALIDOS = [
    "pedidos",
    "rrhh",
    "envios",
    "productos",
    "ventas",
    "rma",
    "remito_manual",
    "sanciones",
    "vacaciones",
]


class DocumentTemplate(Base):
    """
    Template de documento PDF.
    El campo template_json almacena el schema completo de pdfme:
    {
        "basePdf": BLANK_PDF | base64 | { width, height, padding },
        "schemas": [ [ { name, type, position, width, height, ... } ] ]
    }
    """

    __tablename__ = "document_templates"

    id = Column(Integer, primary_key=True, index=True)

    # Metadatos
    nombre = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)

    # Contexto: a qué módulo pertenece este template
    contexto = Column(String(50), nullable=False, index=True)

    # Template pdfme completo (JSON)
    template_json = Column(JSONB, nullable=False)

    # Estado
    activo = Column(Boolean, default=True, nullable=False, index=True)

    # Auditoría
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    actualizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    actualizado_por = relationship("Usuario", foreign_keys=[actualizado_por_id])

    def __repr__(self) -> str:
        return f"<DocumentTemplate(id={self.id}, nombre='{self.nombre}', contexto='{self.contexto}', activo={self.activo})>"
