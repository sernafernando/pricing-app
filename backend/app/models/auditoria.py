from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class TipoAccion(str, enum.Enum):
    MODIFICAR_PRECIO_CLASICA = "modificar_precio_clasica"
    MODIFICAR_PRECIO_WEB = "modificar_precio_web"
    ACTIVAR_REBATE = "activar_rebate"
    DESACTIVAR_REBATE = "desactivar_rebate"
    MODIFICAR_PORCENTAJE_REBATE = "modificar_porcentaje_rebate"
    MARCAR_OUT_OF_CARDS = "marcar_out_of_cards"
    DESMARCAR_OUT_OF_CARDS = "desmarcar_out_of_cards"
    ACTIVAR_WEB_TRANSFERENCIA = "activar_web_transferencia"
    DESACTIVAR_WEB_TRANSFERENCIA = "desactivar_web_transferencia"
    MODIFICACION_MASIVA = "modificacion_masiva"
    TN_DESPUBLICAR = "tn_despublicar"
    TN_PUBLICAR = "tn_publicar"
    # slice C of `pxq-markup-antes-de-publicar`: one row per PxQ price
    # confirmed by MercadoLibre. `tipo_accion` is `VARCHAR(50)` in Postgres
    # (no native enum type backs it), so this is a pure Python-enum addition
    # -- no migration, no DDL.
    PXQ_PRECIO_PUBLICADO = "pxq_precio_publicado"
    # ml-publicaciones-store, manual product links: one row per operator decision on a publication
    # unit (link by hand / explicitly no product / back to the automatic SKU rule). Same VARCHAR(50)
    # column as above: a pure Python-enum addition, no DDL.
    ML_VINCULO_MANUAL = "ml_vinculo_manual"
    ML_VINCULO_SIN_PRODUCTO = "ml_vinculo_sin_producto"
    ML_VINCULO_AUTOMATICO = "ml_vinculo_automatico"
    # sell in: one row per line of a sell-in purchase when it is loaded or voided (`item_id` is the
    # line's product, `compra_id` travels in the values). Same VARCHAR(50) column: no DDL.
    SELL_IN_COMPRA_CREADA = "sell_in_compra_creada"
    SELL_IN_COMPRA_ANULADA = "sell_in_compra_anulada"
    # brand bonus: one row per change the `sell_in.bono` worker makes to a purchase it generated
    # (`item_id` NULL, the lines before and after). Same VARCHAR(50) column: no DDL.
    SELL_IN_COMPRA_BONO_ACTUALIZADA = "sell_in_compra_bono_actualizada"
    # sell out: one row per campaign load, edit or void (`item_id` is NULL, `campana_id` travels in the values).
    SELL_OUT_CAMPANA_CREADA = "sell_out_campana_creada"
    SELL_OUT_CAMPANA_EDITADA = "sell_out_campana_editada"
    SELL_OUT_CAMPANA_ANULADA = "sell_out_campana_anulada"
    SELL_OUT_CAMPANA_TC_DEFINIDO = "sell_out_campana_tc_definido"


class Auditoria(Base):
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, index=True)  # Puede ser None si es masivo
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo_accion = Column(SQLEnum(TipoAccion), nullable=False, index=True)
    valores_anteriores = Column(JSON)  # Valores antes del cambio
    valores_nuevos = Column(JSON)  # Valores después del cambio
    es_masivo = Column(Integer, default=False)  # Si afectó a múltiples productos
    productos_afectados = Column(Integer)  # Cantidad de productos si es masivo
    comentario = Column(String(500))
    fecha = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relación
    usuario = relationship("Usuario", back_populates="auditorias")
