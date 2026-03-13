"""
Caso de Accidente de Trabajo (ART) — módulo RRHH.

Cada caso representa un siniestro laboral registrado ante la ART
(Aseguradora de Riesgos del Trabajo). Almacena datos del accidente,
la aseguradora, la evolución médica, y documentación adjunta.

Flujo: abierto → en_tratamiento → alta_medica → cerrado.
"""

import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Numeric,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class EstadoArt(str, enum.Enum):
    ABIERTO = "abierto"
    EN_TRATAMIENTO = "en_tratamiento"
    ALTA_MEDICA = "alta_medica"
    CERRADO = "cerrado"


class RRHHArtCaso(Base):
    """
    Caso de accidente de trabajo (ART).

    - numero_siniestro: asignado por la aseguradora.
    - estado: flujo abierto → en_tratamiento → alta_medica → cerrado.
    - porcentaje_incapacidad: determinado por la ART al cierre.
    - documentos: relación a RRHHArtDocumento para certificados médicos, etc.
    """

    __tablename__ = "rrhh_art_casos"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Siniestro
    numero_siniestro = Column(String(50), nullable=True, index=True)
    fecha_accidente = Column(Date, nullable=False)
    descripcion_accidente = Column(Text, nullable=True)
    lugar_accidente = Column(String(255), nullable=True)
    tipo_lesion = Column(String(100), nullable=True)
    parte_cuerpo = Column(String(100), nullable=True)

    # ART (aseguradora)
    art_nombre = Column(String(200), nullable=True)
    numero_expediente_art = Column(String(50), nullable=True)

    # Evolución
    estado = Column(String(30), nullable=False, default="abierto", index=True)
    fecha_alta_medica = Column(Date, nullable=True)
    dias_baja = Column(Integer, nullable=True)
    porcentaje_incapacidad = Column(Numeric(5, 2), nullable=True)

    # Costo
    monto_indemnizacion = Column(Numeric(15, 2), nullable=True)

    observaciones = Column(Text, nullable=True)

    # Audit
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    creado_por = relationship("Usuario")
    documentos = relationship(
        "RRHHArtDocumento",
        back_populates="art_caso",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<RRHHArtCaso(id={self.id}, empleado_id={self.empleado_id}, estado='{self.estado}')>"
