from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum as SQLEnum, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class TipoMoneda(str, enum.Enum):
    ARS = "ARS"
    USD = "USD"


class ProductoERP(Base):
    __tablename__ = "productos_erp"

    item_id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(100), index=True)
    descripcion = Column(String(500), index=True)
    marca = Column(String(100), index=True)
    categoria = Column(String(100))
    subcategoria_id = Column(Integer)

    costo = Column(Float)
    moneda_costo = Column(SQLEnum(TipoMoneda), default=TipoMoneda.ARS)
    iva = Column(Float, default=21.0)
    envio = Column(Float, default=0.0)

    stock = Column(Integer, default=0)
    activo = Column(Boolean, default=True)

    fecha_sync = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    hash_datos = Column(String(64))

    # Relaciones
    pricing = relationship("ProductoPricing", back_populates="producto", uselist=False)
    publicaciones_ml = relationship("PublicacionML", back_populates="producto")


class ProductoPricing(Base):
    __tablename__ = "productos_pricing"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("productos_erp.item_id"), index=True, unique=True)

    precio_lista_ml = Column(Float)
    markup_calculado = Column(Float)
    markup_rebate = Column(Float)
    markup_oferta = Column(Float)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    motivo_cambio = Column(String(255))
    markup_web_real = Column(Numeric(10, 2))
    fecha_modificacion = Column(DateTime(timezone=True), server_default=func.now())

    # Precios con cuotas
    precio_3_cuotas = Column(Numeric(15, 2))
    precio_6_cuotas = Column(Numeric(15, 2))
    precio_9_cuotas = Column(Numeric(15, 2))
    precio_12_cuotas = Column(Numeric(15, 2))

    # Precios PVP
    precio_pvp = Column(Numeric(15, 2))
    precio_pvp_3_cuotas = Column(Numeric(15, 2))
    precio_pvp_6_cuotas = Column(Numeric(15, 2))
    precio_pvp_9_cuotas = Column(Numeric(15, 2))
    precio_pvp_12_cuotas = Column(Numeric(15, 2))

    # Markups PVP
    markup_pvp = Column(Numeric(10, 2))
    markup_pvp_3_cuotas = Column(Numeric(10, 2))
    markup_pvp_6_cuotas = Column(Numeric(10, 2))
    markup_pvp_9_cuotas = Column(Numeric(10, 2))
    markup_pvp_12_cuotas = Column(Numeric(10, 2))

    participa_rebate = Column(Boolean, default=False)
    porcentaje_rebate = Column(Numeric(5, 2), default=3.8)
    out_of_cards = Column(Boolean, default=False)

    participa_web_transferencia = Column(Boolean, default=False)
    porcentaje_markup_web = Column(Numeric(5, 2), default=6.0)
    precio_web_transferencia = Column(Numeric(15, 2))
    preservar_porcentaje_web = Column(Boolean, nullable=False, default=False)

    # Tienda Nube
    precio_tiendanube = Column(Numeric(15, 2))
    descuento_tiendanube = Column(Numeric(5, 2))
    publicado_tiendanube = Column(Boolean, default=False)

    color_marcado = Column(String(20), default=None)  # rojo, naranja, amarillo, verde, azul, purpura, gris, NULL
    color_marcado_tienda = Column(String(20), default=None)  # Color separado para página Tienda

    # Configuración individual de recálculo de cuotas y markup adicional
    recalcular_cuotas_auto = Column(Boolean, default=None)  # NULL = usar global, TRUE/FALSE = override
    markup_adicional_cuotas_custom = Column(
        Numeric(5, 2), default=None
    )  # NULL = usar global, número = override (para cuotas web)
    markup_adicional_cuotas_pvp_custom = Column(
        Numeric(5, 2), default=None
    )  # NULL = usar global, número = override (para cuotas PVP)

    producto = relationship("ProductoERP", back_populates="pricing")
    usuario = relationship("Usuario", back_populates="precios_modificados")
    historial = relationship("HistorialPrecio", back_populates="producto_pricing")
    auditoria = relationship("AuditoriaPrecio", back_populates="producto")


class HistorialPrecio(Base):
    __tablename__ = "historial_precios"

    id = Column(Integer, primary_key=True, index=True)
    producto_pricing_id = Column(Integer, ForeignKey("productos_pricing.id"), index=True)

    precio_anterior = Column(Float)
    precio_nuevo = Column(Float)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    motivo = Column(String(255))
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    producto_pricing = relationship("ProductoPricing", back_populates="historial")
