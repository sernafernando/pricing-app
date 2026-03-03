"""
Opciones configurables para dropdowns del módulo RMA Seguimiento.

Cada fila representa un valor posible dentro de una categoría de dropdown.
Los admins pueden agregar, editar y desactivar opciones desde el panel.
Esto garantiza consistencia en los datos para métricas y reportes.

Categorías:
- estado_recepcion: estado al recibir el paquete
- causa_devolucion: motivo de la devolución
- apto_venta: si el producto puede volver a venderse
- estado_revision: resultado de la revisión técnica
- estado_reclamo_ml: estado del reclamo en MercadoLibre
- estado_proceso: estado del proceso interno
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base


class RmaSeguimientoOpcion(Base):
    """
    Tabla de lookup para dropdowns configurables del módulo RMA.
    Cada categoría agrupa las opciones de un dropdown específico.
    """

    __tablename__ = "rma_seguimiento_opciones"

    id = Column(Integer, primary_key=True, index=True)

    # Identificador del dropdown al que pertenece
    categoria = Column(String(50), nullable=False, index=True)

    # Valor que se muestra en el dropdown y se guarda como referencia
    valor = Column(String(200), nullable=False)

    # Orden de aparición en el dropdown (menor = primero)
    orden = Column(Integer, default=0, nullable=False)

    # Soft-delete: permite desactivar sin borrar datos históricos
    activo = Column(Boolean, default=True, nullable=False)

    # Color para badges/pills en el frontend (ej: "green", "red", "yellow")
    color = Column(String(20), nullable=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (UniqueConstraint("categoria", "valor", name="uq_rma_opcion_categoria_valor"),)

    def __repr__(self) -> str:
        return f"<RmaSeguimientoOpcion(id={self.id}, categoria='{self.categoria}', valor='{self.valor}')>"
