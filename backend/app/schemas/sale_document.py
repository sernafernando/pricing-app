"""
Schemas Pydantic v2 para SaleDocument (catálogo ERP tb_sale_document).

Usados por los endpoints de administración del catálogo (design §9.5):
  - GET /sale-documents              — lista completa con flags.
  - POST /sale-documents/sync-forzado — re-sync desde el ERP.
  - GET /sale-documents/faltantes    — sd_ids vistos en el fact table
    pero no presentes en el catálogo (alerta de cobertura).

`clasificacion` es un string derivado server-side (no viene del ERP):
lo calcula `sale_document_classifier` en Fase 2.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SaleDocumentResponse(BaseModel):
    """Fila del catálogo ERP con flags + clasificación derivada."""

    sd_id: int
    sd_desc: str
    sd_iscredit: bool
    sd_isquotation: bool
    sd_isreceipt: bool
    sd_istaxable: bool
    sd_isinbalance: bool
    sd_issales: bool
    sd_ispurchase: bool
    sd_isbanking: bool
    sd_ispackinglist: bool
    sd_iscreditnote: bool
    sd_isdebitnote: bool
    sd_isannulment: bool
    sd_plusorminus: int = Field(..., description="+1 o -1")
    hacc_group: int | None = None
    clasificacion: str | None = Field(
        None,
        description="Clasificación derivada (FACTURA, NC, ND, ORDEN_PAGO, ANULACION, OTRO, AMBIGUO, etc.)",
    )

    model_config = ConfigDict(from_attributes=True)


class SaleDocumentsFaltantes(BaseModel):
    """sd_id observado en tb_commercial_transactions sin fila en tb_sale_document.

    Alerta operativa: indica que el catálogo local quedó desincronizado
    o que el ERP agregó un tipo nuevo sin que se haya generado la
    migration de seed correspondiente.
    """

    sd_id: int
    count: int = Field(..., ge=1, description="Cantidad de transacciones con este sd_id huérfano")
    primera_aparicion: datetime
