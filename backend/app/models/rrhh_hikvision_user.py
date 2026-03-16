"""
Cache local de usuarios registrados en el dispositivo Hikvision.

Se llena manualmente con "Sincronizar usuarios" (consulta ISAPI).
Los datos no cambian frecuentemente — solo cuando se registra un empleado
nuevo en el dispositivo, lo cual es un proceso manual.

Esto evita consultar el ISAPI del dispositivo en cada request.
"""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class RRHHHikvisionUser(Base):
    """Usuario registrado en el dispositivo Hikvision (cache local)."""

    __tablename__ = "rrhh_hikvision_users"

    id = Column(Integer, primary_key=True, index=True)
    employee_no = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False, default="")
    user_type = Column(String(50), nullable=True)
    valid_begin = Column(String(30), nullable=True)
    valid_end = Column(String(30), nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RRHHHikvisionUser(employee_no='{self.employee_no}', name='{self.name}')>"
