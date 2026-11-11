"""The shipping cost a PM chose for a product (Publicaciones ML, S7b).

No row means `max`: the MAX of the product's active publications' ML `list_cost`, today's behavior. `mla` names the
publication whose own cost the product uses (only with `modo = 'mla'`); `promedio` is the simple mean of the active
publications' costs and `ponderado` the mean weighted by their units sold in the last 30 days. The rules live in
`app.services.envio_real_service`; this row only records the choice, who made it and when.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, func

from app.core.database import Base


class ProductoEnvioEleccion(Base):
    __tablename__ = "producto_envio_eleccion"
    __table_args__ = (
        CheckConstraint("modo IN ('max', 'mla', 'promedio', 'ponderado')", name="ck_producto_envio_eleccion_modo"),
        Index("ix_producto_envio_eleccion_usuario_id", "usuario_id"),
    )

    item_id = Column(Integer, ForeignKey("productos_erp.item_id"), primary_key=True, autoincrement=False)
    modo = Column(String(16), nullable=False)
    mla = Column(String(32), nullable=True)  # only with modo = 'mla'
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
