"""Schemas Pydantic para el endpoint de wipe del módulo compras (PR1 testing)."""

from pydantic import BaseModel, ConfigDict, field_validator


class WipeComprasRequest(BaseModel):
    """Body del endpoint de wipe. El campo confirmacion debe ser exactamente 'WIPE'."""

    confirmacion: str
    incluir_caja_banco: bool = True

    model_config = ConfigDict(json_schema_extra={"example": {"confirmacion": "WIPE", "incluir_caja_banco": True}})

    @field_validator("confirmacion")
    @classmethod
    def validar_confirmacion(cls, v: str) -> str:
        if v != "WIPE":
            raise ValueError("El campo confirmacion debe ser exactamente 'WIPE'.")
        return v


class WipeComprasResponse(BaseModel):
    """Respuesta del endpoint de wipe con conteo de filas eliminadas por tabla."""

    confirmado: bool
    tablas_limpiadas: dict[str, int]
    mensaje: str

    model_config = ConfigDict(from_attributes=True)
