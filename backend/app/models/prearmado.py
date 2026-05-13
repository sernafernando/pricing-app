"""
Modelos para el feature de Prearmado de Combos.

Tablas:
- prearmados: cabecera de un prearmado (combo, estado, codigo único, metadata Win11).
- prearmados_seriales: detalle de seriales cargados por componente.
- items_config_serializable: override local de items que no requieren serie (gabinete,
  descuento, servicios, etc.).

NOTA: el modelo legacy `ProduccionPrearmado` (produccion_banlist.py) coexiste y NO se
reemplaza en este cambio. Se evalúa deprecarlo más adelante.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Prearmado(Base):
    """Cabecera de un prearmado de combo. Una unidad pre-armada = una row."""

    __tablename__ = "prearmados"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), nullable=False, unique=True, index=True)
    comp_id = Column(Integer, nullable=False, default=1)
    bra_id = Column(Integer, nullable=False, default=1)
    combo_item_id = Column(Integer, nullable=False, index=True)
    combo_item_code = Column(String(100), nullable=False)
    combo_item_desc = Column(String(500))
    # Win11 implícito por sufijo del item_code ('home' | 'pro' | None). NO es item real
    # del ERP, es metadata derivada del SKU del combo (sufijo WH/WP).
    incluye_windows = Column(String(10), nullable=True)
    estado = Column(String(20), nullable=False, default="pendiente", index=True)
    # Match auto-consumo: cuando todos los seriales serializables aparecen en un sales order
    consumido_por_soh_id = Column(Integer, nullable=True)
    consumido_por_bra_id = Column(Integer, nullable=True)
    consumido_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    notas = Column(Text, nullable=True)

    seriales = relationship(
        "PrearmadoSerial",
        backref="prearmado",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    creador = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<Prearmado(id={self.id}, codigo={self.codigo}, estado={self.estado})>"


class PrearmadoSerial(Base):
    """Serial cargado para un componente de un prearmado."""

    __tablename__ = "prearmados_seriales"

    id = Column(Integer, primary_key=True, index=True)
    prearmado_id = Column(
        Integer,
        ForeignKey("prearmados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    componente_item_id = Column(Integer, nullable=False, index=True)
    componente_item_code = Column(String(100), nullable=False)
    componente_item_desc = Column(String(500))
    # Items con requiere_serie=false (gabinete, descuento) guardan serial=null + validado=true
    serial = Column(String(255), nullable=True)
    # Soft reference a tb_item_serials.is_id cuando el serial fue validado contra el ERP
    is_id = Column(Integer, nullable=True)
    cantidad_esperada = Column(Integer, nullable=False, default=1)
    requiere_serie = Column(Boolean, nullable=False, default=True)
    validado = Column(Boolean, nullable=False, default=False)
    validado_at = Column(DateTime(timezone=True), nullable=True)
    # 'bom' = vino de tb_item_association; 'sufijo' reservado para futuras reglas por sufijo
    origen = Column(String(20), nullable=False, default="bom")
    sufijo = Column(String(10), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<PrearmadoSerial(id={self.id}, prearmado_id={self.prearmado_id}, "
            f"item_id={self.componente_item_id}, validado={self.validado})>"
        )


class ItemConfigSerializable(Base):
    """
    Override local para marcar item_ids que NO requieren serie física en prearmados.
    Casos: gabinete, descuento, servicios, etc.

    La tabla arranca vacía: se puebla via SQL conforme se descubran items.
    Default runtime: si un item no está en esta tabla → requiere_serie=true.
    """

    __tablename__ = "items_config_serializable"

    item_id = Column(Integer, primary_key=True)
    requiere_serie = Column(Boolean, nullable=False, default=True)
    motivo = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by_user_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<ItemConfigSerializable(item_id={self.item_id}, requiere_serie={self.requiere_serie})>"
