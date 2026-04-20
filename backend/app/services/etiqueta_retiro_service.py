"""
etiqueta_retiro_service — genera etiquetas de envío tipo `retiro_proveedor`
asociadas a un pedido de compra (design §1.9, §9.1 + D16, D17).

Una etiqueta de retiro registra la logística de ir a buscar mercadería al
depósito del proveedor. Reutiliza la tabla `etiquetas_envio` con
`tipo_envio='retiro_proveedor'` y los campos `proveedor_id`,
`proveedor_direccion_id` y `pedido_compra_id` nuevos (COMPRAS-1.7).

Reglas de negocio:
  - El pedido debe tener `requiere_envio=True` (HTTP 400 si no).
  - Si ya existe etiqueta con `pedido_compra_id=<id>` → HTTP 409 (D16).
    Para cambiar dirección: anular la vieja + crear nueva (no regenerar).
  - Si no se provee `proveedor_direccion_id` → elige la que tenga
    `etiqueta` con marker `retiro` o la `es_principal` (no existe en
    este modelo — usamos la primera activa como fallback).
  - Copia los datos manuales (receiver, street, city, zip) desde la
    dirección del proveedor para que la etiqueta sea autónoma.

Referencias:
  - design.md §1.9, §9.1
  - tasks.md COMPRAS-4.2
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor_direccion import ProveedorDireccion

logger = get_logger("services.etiqueta_retiro_service")


def _obtener_pedido(session: Session, pedido_id: int) -> PedidoCompra:
    pedido = session.get(PedidoCompra, pedido_id)
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PedidoCompra id={pedido_id} no encontrado.",
        )
    return pedido


def _elegir_direccion_default(session: Session, proveedor_id: int) -> Optional[ProveedorDireccion]:
    """
    Busca una dirección 'retiro' del proveedor. Convención (D17):
      1. Dirección activa cuya `etiqueta` contenga 'retiro' (case-insensitive).
      2. Fallback: primera dirección activa ordenada por id.
    """
    from sqlalchemy import func as sa_func  # noqa: PLC0415

    stmt = (
        select(ProveedorDireccion)
        .where(
            ProveedorDireccion.proveedor_id == proveedor_id,
            ProveedorDireccion.activo.is_(True),
            sa_func.lower(ProveedorDireccion.etiqueta).like("%retiro%"),
        )
        .order_by(ProveedorDireccion.id.asc())
    )
    direccion = session.execute(stmt).scalars().first()
    if direccion is not None:
        return direccion

    # Fallback: primera activa
    stmt_fb = (
        select(ProveedorDireccion)
        .where(
            ProveedorDireccion.proveedor_id == proveedor_id,
            ProveedorDireccion.activo.is_(True),
        )
        .order_by(ProveedorDireccion.id.asc())
    )
    return session.execute(stmt_fb).scalars().first()


def _existe_etiqueta_para_pedido(session: Session, pedido_id: int) -> bool:
    stmt = select(EtiquetaEnvio.id).where(EtiquetaEnvio.pedido_compra_id == pedido_id).limit(1)
    return session.execute(stmt).first() is not None


def generar_etiqueta_retiro(
    session: Session,
    *,
    pedido_id: int,
    proveedor_direccion_id: Optional[int] = None,
    user_id: int,
) -> EtiquetaEnvio:
    """
    Genera una etiqueta de envío tipo `retiro_proveedor` para un pedido.

    Validaciones:
      - Pedido existe (404).
      - `pedido.requiere_envio == True` (400).
      - No existe etiqueta previa para este pedido (409 — D16).
      - Si se pasa `proveedor_direccion_id`, debe pertenecer al proveedor
        del pedido (400).
      - Si no se pasa, se resuelve con `_elegir_direccion_default`; si no
        hay dirección activa → 400.

    Side effects:
      - Inserta `etiquetas_envio` con:
          tipo_envio='retiro_proveedor', proveedor_id, proveedor_direccion_id,
          pedido_compra_id, es_manual=True, shipping_id generado,
          fecha_envio=hoy, manual_* copiados de la dirección.
      - Inserta evento `etiqueta_envio_generada` en `compras_eventos`.

    Args:
        session: tx activa.
        pedido_id: PK del pedido.
        proveedor_direccion_id: PK opcional de dirección del proveedor.
        user_id: usuario que ejecuta la acción.

    Returns:
        El `EtiquetaEnvio` recién creado.

    Raises:
        HTTPException 404: pedido inexistente.
        HTTPException 400: pedido sin `requiere_envio`, dirección inválida,
            sin dirección configurada.
        HTTPException 409: ya existe etiqueta para el pedido.
    """
    pedido = _obtener_pedido(session, pedido_id)

    if not pedido.requiere_envio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El pedido {pedido.numero} no requiere envío (requiere_envio=False).",
        )

    if _existe_etiqueta_para_pedido(session, pedido.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ya existe una etiqueta de retiro para el pedido {pedido.numero}. "
                f"Para cambiar dirección: anulá la vieja y creá una nueva."
            ),
        )

    # Resolver dirección
    if proveedor_direccion_id is not None:
        direccion = session.get(ProveedorDireccion, proveedor_direccion_id)
        if direccion is None or not direccion.activo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ProveedorDireccion id={proveedor_direccion_id} no existe o está inactiva.",
            )
        if direccion.proveedor_id != pedido.proveedor_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"La dirección id={direccion.id} no pertenece al proveedor del pedido "
                    f"(proveedor_id_dir={direccion.proveedor_id} vs proveedor_id_pedido={pedido.proveedor_id})."
                ),
            )
    else:
        direccion = _elegir_direccion_default(session, pedido.proveedor_id)
        if direccion is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Proveedor id={pedido.proveedor_id} no tiene direcciones activas configuradas "
                    f"para retiro. Cargá una dirección primero."
                ),
            )

    # Shipping ID determinístico-ish basado en el número del pedido + sufijo random
    shipping_id = f"RETIRO-{pedido.numero}-{uuid.uuid4().hex[:6].upper()}"

    etiqueta = EtiquetaEnvio(
        shipping_id=shipping_id,
        fecha_envio=date.today(),
        es_manual=True,
        tipo_envio="retiro_proveedor",
        proveedor_id=pedido.proveedor_id,
        proveedor_direccion_id=direccion.id,
        pedido_compra_id=pedido.id,
        manual_receiver_name=direccion.contacto_nombre or f"Retiro {pedido.numero}",
        manual_street_name=direccion.direccion,
        manual_zip_code=direccion.cp,
        manual_city_name=direccion.ciudad,
        manual_status="ready_to_ship",
        manual_phone=direccion.contacto_telefono,
        manual_comment=direccion.notas,
        creado_por_usuario_id=user_id,
    )
    session.add(etiqueta)
    session.flush()

    evento = CompraEvento(
        entidad_tipo=CompraEvento.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        tipo="etiqueta_envio_generada",
        usuario_id=user_id,
        payload={
            "etiqueta_id": etiqueta.id,
            "shipping_id": shipping_id,
            "proveedor_direccion_id": direccion.id,
        },
    )
    session.add(evento)
    session.flush()

    logger.info(
        "etiqueta_retiro_generada pedido_id=%s etiqueta_id=%s shipping_id=%s proveedor_direccion_id=%s",
        pedido.id,
        etiqueta.id,
        shipping_id,
        direccion.id,
    )
    return etiqueta


__all__ = ["generar_etiqueta_retiro"]
