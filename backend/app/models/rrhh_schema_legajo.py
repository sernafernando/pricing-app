"""
Schema de campos custom del legajo de empleados.

Cada fila define un campo personalizado que RRHH puede agregar al legajo.
Los valores se almacenan en rrhh_empleados.datos_custom (JSONB).

Ejemplo: RRHH agrega campo "grupo_sanguineo" tipo "select" con opciones
["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].
El valor del empleado se guarda en datos_custom["grupo_sanguineo"] = "O+".
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class RRHHSchemaLegajo(Base):
    """
    Definición de un campo custom para el legajo de empleados.

    - nombre: key en el JSONB datos_custom (debe ser único, snake_case).
    - label: nombre visible en el frontend.
    - tipo_campo: text | number | date | select | boolean.
    - opciones: para tipo_campo=select, array de opciones ["op1", "op2"].
    - orden: posición de display en el formulario.
    """

    __tablename__ = "rrhh_schema_legajo"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    label = Column(String(200), nullable=False)
    tipo_campo = Column(String(50), nullable=False)
    requerido = Column(Boolean, nullable=False, default=False)
    opciones = Column(JSONB, nullable=True)
    orden = Column(Integer, nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RRHHSchemaLegajo(nombre='{self.nombre}', tipo='{self.tipo_campo}')>"
