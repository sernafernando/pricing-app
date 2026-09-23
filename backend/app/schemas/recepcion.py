"""
Pydantic v2 schemas for the reception flow (recepcion de mercaderia por deposito).

Slice A — all request/response models for:
  - GET  /pedidos/{id}/recepcion/saldos
  - POST /pedidos/{id}/recepcion/ingresos
  - POST /pedidos/{id}/recepcion/confirmar-pedido
  - GET  /pedidos/{id}/recepcion/eventos
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


# ──────────────────────────────────────────────────────────────────────────
# GET /recepcion/saldos
# ──────────────────────────────────────────────────────────────────────────


class SaldoLineaResponse(BaseModel):
    """Balance for one OC line (one pod_id)."""

    pod_id: int
    item_id: int | None = None
    item_code: str | None = None
    item_nombre: str | None = None
    stor_id: int | None = None
    deposito_nombre: str | None = None
    pod_qty: Decimal
    cantidad_recibida_total: Decimal
    saldo_pendiente: Decimal

    model_config = ConfigDict(from_attributes=True)


class SaldosResponse(BaseModel):
    """Response for GET /pedidos/{id}/recepcion/saldos."""

    pedido_id: int
    tiene_oc: bool
    estado: str
    requiere_envio: bool
    lineas: list[SaldoLineaResponse]

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────────────────────────────────
# POST /recepcion/ingresos
# ──────────────────────────────────────────────────────────────────────────


class IngresoLinea(BaseModel):
    """One line in a receipt batch request."""

    pod_id: int
    cantidad_recibida: Decimal

    model_config = ConfigDict(from_attributes=True)

    @field_validator("cantidad_recibida")
    @classmethod
    def _cantidad_entera(cls, v: Decimal) -> Decimal:
        """Las unidades no tienen decimales (no existen '1.3 memorias')."""
        if v != v.to_integral_value():
            raise ValueError("cantidad_recibida debe ser un número entero (sin decimales).")
        return v


class RegistrarIngresosRequest(BaseModel):
    """Request body for POST /pedidos/{id}/recepcion/ingresos."""

    lineas: list[IngresoLinea]
    observaciones: str | None = None
    faltantes_texto: str | None = None

    model_config = ConfigDict(from_attributes=True)


class IngresoCreadoResponse(BaseModel):
    """Summary of one created PedidoCompraIngreso row."""

    id: int
    pod_id: int
    cantidad_recibida: Decimal

    model_config = ConfigDict(from_attributes=True)


class SaldoPostIngreso(BaseModel):
    """Per-line balance after a receipt batch."""

    pod_id: int
    saldo_pendiente: Decimal

    model_config = ConfigDict(from_attributes=True)


class RegistrarIngresosResponse(BaseModel):
    """Response for POST /pedidos/{id}/recepcion/ingresos (HTTP 201)."""

    pedido_id: int
    estado_nuevo: str
    ingresos_creados: list[IngresoCreadoResponse]
    saldos: list[SaldoPostIngreso]

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────────────────────────────────
# POST /recepcion/confirmar-pedido
# ──────────────────────────────────────────────────────────────────────────


class ConfirmarPedidoRequest(BaseModel):
    """Request body for POST /pedidos/{id}/recepcion/confirmar-pedido.

    Observation text is optional. When completo=False (marking faltantes),
    `faltantes_texto` is required (D-SINOC / compras-pipeline-alerts).
    """

    completo: bool
    observaciones: str | None = None
    faltantes_texto: str | None = None

    @model_validator(mode="after")
    def _faltantes_texto_requerido_si_incompleto(self) -> "ConfirmarPedidoRequest":
        if not self.completo and (self.faltantes_texto is None or self.faltantes_texto.strip() == ""):
            raise ValueError("faltantes_texto is required when completo=False")
        return self

    model_config = ConfigDict(from_attributes=True)


class ConfirmarPedidoResponse(BaseModel):
    """Response for POST /pedidos/{id}/recepcion/confirmar-pedido (HTTP 200)."""

    pedido_id: int
    estado_nuevo: str

    model_config = ConfigDict(from_attributes=True)


class DeshacerRecibidoResponse(BaseModel):
    """Response for POST /pedidos/{id}/recepcion/deshacer-recibido."""

    pedido_id: int
    estado_nuevo: str

    model_config = ConfigDict(from_attributes=True)


class ResolverFaltantesRequest(BaseModel):
    """Optional note when marking faltantes as resolved (G31)."""

    texto: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ResolverFaltantesResponse(BaseModel):
    """Response for POST /pedidos/{id}/faltantes/resolver."""

    pedido_id: int
    faltantes_resuelto_en: datetime

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────────────────────────────────
# GET /recepcion/eventos
# ──────────────────────────────────────────────────────────────────────────


class EventoRecepcionItem(BaseModel):
    """One event entry from compras_eventos."""

    id: int
    tipo: str
    created_at: datetime
    usuario_nombre: str | None = None
    payload: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class EventosRecepcionResponse(BaseModel):
    """Response for GET /pedidos/{id}/recepcion/eventos."""

    pedido_id: int
    eventos: list[EventoRecepcionItem]

    model_config = ConfigDict(from_attributes=True)


class DespacharRetiroResponse(BaseModel):
    """Compact etiqueta payload for despachar-retiro / generar-etiqueta-envio."""

    id: int
    shipping_id: str | None = None
    tipo_envio: str | None = None
    pedido_compra_id: int | None = None
    proveedor_id: int | None = None
    proveedor_direccion_id: int | None = None
    fecha_envio: str | None = None
    manual_receiver_name: str | None = None
    manual_street_name: str | None = None
    manual_zip_code: str | None = None
    manual_city_name: str | None = None
    manual_phone: str | None = None

    model_config = ConfigDict(from_attributes=True)
