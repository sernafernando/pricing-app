from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class NotificacionIgnorada(Base):
    """
    Reglas de ignorar notificaciones por producto/tipo/markup.
    
    Cuando un usuario "ignora" una notificación, se crea una regla que previene
    futuras notificaciones del mismo producto con el mismo tipo y markup.
    
    Ejemplo:
    - item_id: 12345 (Mouse G203)
    - tipo: "markup_bajo"
    - markup_real: -4.17
    
    Cualquier futura venta del Mouse G203 con markup -4.17% NO generará notificación
    para este usuario.
    """
    __tablename__ = "notificaciones_ignoradas"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Criterios de matching
    item_id = Column(Integer, nullable=True, index=True)  # Producto específico
    tipo = Column(String(50), nullable=False)  # Tipo de notificación
    markup_real = Column(Numeric(10, 2), nullable=True)  # Markup específico (redondeado a 2 decimales)
    
    # Metadata para mostrar en admin
    codigo_producto = Column(String(100), nullable=True)
    descripcion_producto = Column(String(500), nullable=True)
    
    # Timestamps
    fecha_ignorado = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ignorado_por_notificacion_id = Column(Integer, nullable=True)  # Referencia a la notificación original
    
    # Constraint único: un usuario no puede tener duplicados de la misma regla
    __table_args__ = (
        UniqueConstraint('user_id', 'item_id', 'tipo', 'markup_real', name='uq_notificacion_ignorada'),
    )
    
    # Relaciones
    usuario = relationship("Usuario")
    
    def __repr__(self):
        return f"<NotificacionIgnorada user={self.user_id} item={self.item_id} tipo={self.tipo} markup={self.markup_real}>"
    
    def matches(self, item_id: int, tipo: str, markup_real: float) -> bool:
        """
        Verifica si esta regla matchea con una posible notificación.
        
        Args:
            item_id: ID del producto
            tipo: Tipo de notificación
            markup_real: Markup real de la venta
        
        Returns:
            True si matchea (debe ignorarse), False si no
        """
        # Item debe coincidir (si está definido)
        if self.item_id is not None and self.item_id != item_id:
            return False
        
        # Tipo debe coincidir
        if self.tipo != tipo:
            return False
        
        # Markup debe coincidir (redondeado a 2 decimales)
        if self.markup_real is not None:
            markup_redondeado = round(markup_real, 2)
            if float(self.markup_real) != markup_redondeado:
                return False
        
        return True
