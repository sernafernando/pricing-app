"""
Empleado de RRHH — entidad principal del módulo de Recursos Humanos.

Un empleado representa a una persona física contratada por la empresa.
Tiene datos personales fijos, datos laborales, y campos custom definidos
dinámicamente por RRHH (almacenados en JSONB).

Relaciones opcionales:
- usuario_id → Usuario del sistema (si el empleado tiene acceso a la app)
- Documentos, historial, sanciones, vacaciones, cuenta corriente (phases posteriores)
"""

import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Date,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class EstadoEmpleado(str, enum.Enum):
    ACTIVO = "activo"
    LICENCIA = "licencia"
    BAJA = "baja"


class RRHHEmpleado(Base):
    """
    Empleado de la empresa. Nodo central del módulo RRHH.

    - legajo: número manual (de AFIP), no auto-generado.
    - datos_custom: JSONB con campos definidos en rrhh_schema_legajo.
    - usuario_id: link opcional a Usuario (empleados con acceso a la app).
    """

    __tablename__ = "rrhh_empleados"

    id = Column(Integer, primary_key=True, index=True)

    # --- Datos personales ---
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    dni = Column(String(20), unique=True, nullable=False, index=True)
    cuil = Column(String(20), nullable=True, index=True)
    fecha_nacimiento = Column(Date, nullable=True)
    domicilio = Column(String(500), nullable=True)
    telefono = Column(String(50), nullable=True)
    email_personal = Column(String(255), nullable=True)
    contacto_emergencia = Column(String(255), nullable=True)
    contacto_emergencia_tel = Column(String(50), nullable=True)

    # --- Datos laborales ---
    legajo = Column(String(20), unique=True, nullable=False, index=True)
    fecha_ingreso = Column(Date, nullable=False)
    fecha_egreso = Column(Date, nullable=True)
    puesto = Column(String(100), nullable=True)
    area = Column(String(100), nullable=True)
    estado = Column(String(20), nullable=False, default="activo", index=True)

    # --- Hikvision mapping (employeeNo del dispositivo, asignación manual) ---
    hikvision_employee_no = Column(String(20), unique=True, nullable=True, index=True)

    # --- Link a usuario del sistema (opcional, one-to-one) ---
    usuario_id = Column(
        Integer,
        ForeignKey("usuarios.id"),
        nullable=True,
        unique=True,
        index=True,
    )

    # --- Foto (path relativo en uploads/rrhh/{id}/) ---
    foto_path = Column(String(500), nullable=True)

    # --- Campos custom definidos en rrhh_schema_legajo ---
    datos_custom = Column(JSONB, nullable=True, default={})

    # --- Observaciones ---
    observaciones = Column(Text, nullable=True)

    # --- Sistema ---
    activo = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    documentos = relationship("RRHHDocumento", back_populates="empleado", cascade="all, delete-orphan")
    historial = relationship(
        "RRHHLegajoHistorial",
        back_populates="empleado",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_rrhh_empleados_nombre_apellido", "nombre", "apellido"),
        Index("idx_rrhh_empleados_estado_activo", "estado", "activo"),
    )

    @property
    def nombre_completo(self) -> str:
        return f"{self.apellido}, {self.nombre}"

    def __repr__(self) -> str:
        return f"<RRHHEmpleado(id={self.id}, legajo='{self.legajo}', nombre='{self.nombre_completo}')>"
