"""
Sistema de Alertas Globales
- Alertas mostradas como banners en el frontend
- Asignables por roles y/o usuarios específicos
- Track de quién cerró cada alerta
- Configurables con variantes de color, vigencia, persistencia
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Alerta(Base):
    """
    Alertas globales del sistema.
    Se muestran como banners horizontales debajo del topbar.
    """

    __tablename__ = "alertas"

    id = Column(Integer, primary_key=True, index=True)

    # Contenido
    titulo = Column(String(200), nullable=False)  # Para el panel admin
    mensaje = Column(Text, nullable=False)  # Texto mostrado en el banner

    # Estilo
    # Usar String en vez de SQLEnum para evitar problemas de conversión name/value
    # PostgreSQL valida los valores permitidos con el ENUM de DB
    variant = Column(String(20), default="info", nullable=False)

    # Acción (botón opcional en el banner)
    action_label = Column(String(100), nullable=True)  # "Ver ahora", "Más info", etc.
    action_url = Column(String(500), nullable=True)  # URL del botón

    # Comportamiento
    dismissible = Column(Boolean, default=True, nullable=False)  # ¿Se puede cerrar?
    persistent = Column(Boolean, default=False, nullable=False)  # ¿Aparece siempre aunque se cierre? (emergencias)

    # Destinatarios - Roles
    # JSONB array con códigos de roles: ["ADMIN", "VENTAS"] o ["*"] para todos
    roles_destinatarios = Column(JSONB, nullable=False, default=list)

    # Destinatarios - Usuarios específicos (via relación M2M)
    # Ver: AlertaUsuarioDestinatario

    # Estado
    activo = Column(Boolean, default=False, nullable=False)  # Si está publicada

    # Vigencia
    fecha_desde = Column(DateTime(timezone=True), nullable=False)
    fecha_hasta = Column(DateTime(timezone=True), nullable=True)  # Null = indefinida

    # Prioridad (orden de visualización: mayor = arriba)
    prioridad = Column(Integer, default=0, nullable=False)

    # Duración de visualización (para sistema de rotación)
    duracion_segundos = Column(Integer, default=5, nullable=False)  # Tiempo que se muestra antes de rotar

    # Auditoría
    created_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    created_by = relationship("Usuario", foreign_keys=[created_by_id])
    usuarios_destinatarios = relationship(
        "AlertaUsuarioDestinatario", back_populates="alerta", cascade="all, delete-orphan"
    )
    usuarios_estados = relationship("AlertaUsuarioEstado", back_populates="alerta", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Alerta(id={self.id}, titulo='{self.titulo}', variant={self.variant}, activo={self.activo})>"


class AlertaUsuarioDestinatario(Base):
    """
    Tabla M2M: Alerta → Usuarios específicos
    Permite asignar alertas a usuarios individuales además de roles.
    """

    __tablename__ = "alertas_usuarios_destinatarios"

    id = Column(Integer, primary_key=True, index=True)
    alerta_id = Column(Integer, ForeignKey("alertas.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    alerta = relationship("Alerta", back_populates="usuarios_destinatarios")
    usuario = relationship("Usuario")

    __table_args__ = (UniqueConstraint("alerta_id", "usuario_id", name="uq_alerta_usuario_dest"),)

    def __repr__(self):
        return f"<AlertaUsuarioDestinatario(alerta_id={self.alerta_id}, usuario_id={self.usuario_id})>"


class AlertaUsuarioEstado(Base):
    """
    Track de quién cerró cada alerta.
    Evita mostrar alertas ya cerradas al mismo usuario (excepto si es persistent=True).
    """

    __tablename__ = "alertas_usuarios_estado"

    id = Column(Integer, primary_key=True, index=True)
    alerta_id = Column(Integer, ForeignKey("alertas.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)

    cerrada = Column(Boolean, default=False, nullable=False)
    fecha_cerrada = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    alerta = relationship("Alerta", back_populates="usuarios_estados")
    usuario = relationship("Usuario")

    __table_args__ = (UniqueConstraint("alerta_id", "usuario_id", name="uq_alerta_usuario_estado"),)

    def __repr__(self):
        return (
            f"<AlertaUsuarioEstado(alerta_id={self.alerta_id}, usuario_id={self.usuario_id}, cerrada={self.cerrada})>"
        )


class ConfiguracionAlerta(Base):
    """
    Configuración global del sistema de alertas.
    Singleton: una sola fila con id=1.
    """

    __tablename__ = "configuracion_alertas"

    id = Column(Integer, primary_key=True)

    # Máximo de alertas visibles simultáneamente
    max_alertas_visibles = Column(Integer, default=1, nullable=False)

    # Auditoría
    updated_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relación
    updated_by = relationship("Usuario")

    def __repr__(self):
        return f"<ConfiguracionAlerta(max_alertas_visibles={self.max_alertas_visibles})>"
