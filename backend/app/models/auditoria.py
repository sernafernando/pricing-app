from sqlalchemy import Boolean, Column, Integer, String, DateTime, JSON, ForeignKey, Enum as SQLEnum
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
    # a tactical's invoice total re-split in place when another invoice of its operation links (one row per new line).
    SELL_IN_COMPRA_REPARTIDA = "sell_in_compra_repartida"
    # brand bonus: one row per bonus load, edit or void (`item_id` NULL, `bono_id` in the values), and one
    # row per change the worker makes to a purchase it generated (`item_id` NULL, lines before/after).
    SELL_IN_BONO_CREADO = "sell_in_bono_creado"
    SELL_IN_BONO_EDITADO = "sell_in_bono_editado"
    SELL_IN_BONO_ANULADO = "sell_in_bono_anulado"
    SELL_IN_COMPRA_BONO_ACTUALIZADA = "sell_in_compra_bono_actualizada"
    # cost mode: one row per mode row saved (`item_id` is the product; the row, its date and what the preview showed
    # travel in the values).
    SELL_IN_MODO_CREADO = "sell_in_modo_creado"
    # the cost-mode selector's default: one row per admin change (`item_id` NULL; the mode before and after).
    SELL_IN_MODO_POR_DEFECTO = "sell_in_modo_por_defecto"
    # sell out: one row per campaign load, edit or void (`item_id` is NULL, `campana_id` travels in the values).
    SELL_OUT_CAMPANA_CREADA = "sell_out_campana_creada"
    SELL_OUT_CAMPANA_EDITADA = "sell_out_campana_editada"
    SELL_OUT_CAMPANA_ANULADA = "sell_out_campana_anulada"
    SELL_OUT_CAMPANA_TC_DEFINIDO = "sell_out_campana_tc_definido"
    # sell out: one row per campaign whose program changed (campaign system S1; `item_id` NULL, `campana_id` and the
    # program before/after travel in the values). Same VARCHAR(50) column: no DDL.
    SELL_OUT_CAMPANA_PROGRAMA = "sell_out_campana_programa"
    # tacticals (T1): one row per tactical created or voided (`item_id` NULL, `tactical_id` and its lines' children in
    # the values); each child writes its own engine's row too. Same VARCHAR(50) column: no DDL.
    TACTICAL_CREADO = "tactical_creado"
    TACTICAL_ANULADO = "tactical_anulado"
    TACTICAL_EDITADO = "tactical_editado"
    # ML Ads brand aportes (ml-ads-aportes-robust S5): one row per load, edit or delete (`item_id` NULL; the aporte,
    # its id included, travels in the values: before/after). Same VARCHAR(50) column: no DDL.
    ML_ADS_APORTE_CREADO = "ml_ads_aporte_creado"
    ML_ADS_APORTE_EDITADO = "ml_ads_aporte_editado"
    ML_ADS_APORTE_BORRADO = "ml_ads_aporte_borrado"
    # S7b: one row per change of a product's shipping-cost choice (`item_id` the product; {modo, mla} before and
    # after, a product without a stored choice reads as `max`). Same VARCHAR(50) column: no DDL.
    ENVIO_PRODUCTO_ELECCION = "envio_producto_eleccion"
    # Gestión Full: one row per human mutation (same VARCHAR(50) column — no DDL).
    # Destructive ops (remove lines) store a denormalized snapshot so history survives CASCADE.
    GESTION_FULL_OVERRIDE = "gestion_full_override"
    GESTION_FULL_PM_READY = "gestion_full_pm_ready"
    GESTION_FULL_PM_UNLOCK = "gestion_full_pm_unlock"
    GESTION_FULL_LINE_ADD = "gestion_full_line_add"
    GESTION_FULL_LINES_READY = "gestion_full_lines_ready"
    GESTION_FULL_QTY_EXPORT = "gestion_full_qty_export"
    GESTION_FULL_INBOUND_SET = "gestion_full_inbound_set"
    GESTION_FULL_LINES_REMOVE = "gestion_full_lines_remove"
    GESTION_FULL_INBOUND_CLEAR = "gestion_full_inbound_clear"
    GESTION_FULL_EXPORTED = "gestion_full_exported"
    GESTION_FULL_LOCKED = "gestion_full_locked"
    GESTION_FULL_CAJA = "gestion_full_caja"
    GESTION_FULL_CAJA_IMPORT = "gestion_full_caja_import"
    GESTION_FULL_PLAN_RESET = "gestion_full_plan_reset"


class Auditoria(Base):
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, index=True)  # Puede ser None si es masivo
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Production's column is VARCHAR(50) holding the member NAME, with no `tipoaccion` type behind it: a
    # native enum would make SQLAlchemy cast to that missing type in multi-row INSERTs.
    tipo_accion = Column(SQLEnum(TipoAccion, native_enum=False, length=50), nullable=False, index=True)
    valores_anteriores = Column(JSON)  # Valores antes del cambio
    valores_nuevos = Column(JSON)  # Valores después del cambio
    es_masivo = Column(Boolean, default=False)  # Si afectó a múltiples productos
    productos_afectados = Column(Integer)  # Cantidad de productos si es masivo
    comentario = Column(String(500))
    fecha = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relación
    usuario = relationship("Usuario", back_populates="auditorias")
