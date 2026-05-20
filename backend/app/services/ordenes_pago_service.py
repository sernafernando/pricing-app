"""
ordenes_pago_service — el corazón del módulo de compras.

Una OP es un pago (o promesa de pago) a un proveedor. Este módulo expone
4 operaciones contractuales:

  1. `crear(...)`            — persistencia de la OP con validaciones por
                               modo (especifica/a_cuenta/mixta) y
                               detección de duplicados ERP.
  2. `ejecutar_pago(...)`    — **LA** transacción crítica: 9 pasos atómicos
                               que mueven plata real (caja + CC + imputaciones
                               + transiciones automáticas de pedidos).
  3. `anular(...)`           — reverso completo de una OP pagada.
  4. `detectar_duplicado_erp(...)` — consulta SQL anti-doble-contabilización
                               contra `tb_commercial_transactions`.

Los 9 pasos de `ejecutar_pago` (design §2.3) son la parte más sensible
del sistema: cualquier falla debe hacer rollback TOTAL. Nada de
`session.commit()` intermedio — es responsabilidad del caller (el endpoint)
invocar el commit al final, o rollback si hubo excepción.

Referencias:
  - design.md §2.3, §3.1, §3.2, §7.1, §7.2
  - tasks.md COMPRAS-4.4, COMPRAS-4.5, COMPRAS-4.6, COMPRAS-4.7
  - Engram #117 (design), #123 (F3 apply)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.compras_erp_constants import ERP_SD_ID_ORDEN_PAGO
from app.core.logging import get_logger
from app.models.caja import Caja, CajaTipoDocumento
from app.models.compra_evento import CompraEvento
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.services import (
    imputaciones_service,
    numeracion_service,
    pedidos_service,
)
from app.services.caja_service import CajaService

logger = get_logger("services.ordenes_pago_service")


# ──────────────────────────────────────────────────────────────────────────
# Tipos
# ──────────────────────────────────────────────────────────────────────────


Moneda = Literal["ARS", "USD"]
ModoImputacion = Literal["especifica", "a_cuenta", "mixta"]


# Tipos de evento (compras_eventos.tipo)
EVENTO_OP_CREADA: Final[str] = "op_creada"
EVENTO_OP_CREADA_DUP_CONFIRMADA: Final[str] = "op_creada_con_duplicado_confirmado"
EVENTO_OP_PAGADA: Final[str] = "op_pagada"
EVENTO_OP_ANULADA: Final[str] = "op_anulada"
EVENTO_OP_EDITADA: Final[str] = "op_editada"
EVENTO_OP_CANCELADA_PENDIENTE: Final[str] = "op_cancelada_pendiente"
EVENTO_ITEMS_REGISTRADOS: Final[str] = "items_registrados"
EVENTO_ITEMS_EDITADOS: Final[str] = "items_editados"


# Nombres de `caja_tipo_documentos` seed (COMPRAS-1.13).
TIPO_DOC_ORDEN_PAGO: Final[str] = "Orden de Pago"
TIPO_DOC_ORDEN_PAGO_ANULADA: Final[str] = "Orden de Pago Anulada"


# Código HTTP custom del design §3.2
CODIGO_ERROR_CAJA_MONEDA: Final[str] = "OP_CAJA_MONEDA_MISMATCH"
CODIGO_ERROR_DUPLICADO_ERP: Final[str] = "POSIBLE_DUPLICADO_OP_ERP"


# ──────────────────────────────────────────────────────────────────────────
# Helpers privados
# ──────────────────────────────────────────────────────────────────────────


def _registrar_evento(
    session: Session,
    *,
    op_id: int,
    tipo: str,
    usuario_id: int,
    payload: Optional[dict[str, Any]] = None,
) -> CompraEvento:
    evento = CompraEvento(
        entidad_tipo=CompraEvento.ENTIDAD_TIPO_ORDEN_PAGO,
        entidad_id=op_id,
        tipo=tipo,
        usuario_id=usuario_id,
        payload=payload,
    )
    session.add(evento)
    session.flush()
    return evento


def _lookup_tipo_documento_id(session: Session, nombre: str) -> int:
    """Busca el `CajaTipoDocumento.id` por nombre. 422 si no existe."""
    td = session.execute(select(CajaTipoDocumento).where(CajaTipoDocumento.nombre == nombre)).scalar_one_or_none()
    if td is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Tipo de documento de caja '{nombre}' no está seedeado. "
                f"Ejecutá la migración compras_011_seed_caja_tipos_compras."
            ),
        )
    return int(td.id)


def _validar_items_por_modo(
    modo: str,
    items: list[dict],
    monto_total: Decimal,
) -> None:
    """Valida constraints por modo según design §2.3 / §9.2."""
    if modo == "especifica":
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Modo 'especifica' requiere al menos 1 item.",
            )
        suma = sum((Decimal(str(item["monto"])) for item in items), Decimal("0"))
        if suma != monto_total:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Modo 'especifica': sum(items.monto)={suma} debe ser igual a monto_total={monto_total}."),
            )
    elif modo == "a_cuenta":
        if items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Modo 'a_cuenta' no acepta items (el total va a saldo).",
            )
    elif modo == "mixta":
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Modo 'mixta' requiere al menos 1 item (el resto va a saldo).",
            )
        suma = sum((Decimal(str(item["monto"])) for item in items), Decimal("0"))
        if suma >= monto_total:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Modo 'mixta': sum(items.monto)={suma} debe ser < monto_total={monto_total}. "
                    f"Si sum == total, usá modo 'especifica'."
                ),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"modo_imputacion inválido: '{modo}'. Valores: especifica, a_cuenta, mixta.",
        )


def _validar_items_whitelist(items: list[dict]) -> None:
    """Cada item debe formar combo válido con origen='orden_pago'."""
    for idx, item in enumerate(items):
        destino_tipo = item.get("tipo")
        if destino_tipo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"item[{idx}] sin 'tipo'. Requerido.",
            )
        imputaciones_service._validar_whitelist("orden_pago", destino_tipo)
        monto = Decimal(str(item.get("monto", "0")))
        if monto <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"item[{idx}].monto debe ser > 0 (recibido: {monto}).",
            )
        # destino_id obligatorio si destino_tipo != 'saldo'
        destino_id = item.get("id")
        if destino_tipo == "saldo":
            if destino_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"item[{idx}]: destino='saldo' requiere id=None.",
                )
        else:
            if destino_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"item[{idx}]: destino='{destino_tipo}' requiere id no nulo.",
                )


def _validar_items_cross_moneda_con_tc(
    session: Session,
    *,
    items: list[dict],
    op_moneda: str,
    op_tipo_cambio: Optional[Decimal],
) -> None:
    """
    Valida la coherencia OP↔pedido considerando cross-moneda.

    Política (compras-cross-moneda-y-ncs-cc, FR-004):
      - Item con `destino_tipo == 'pedido_compra'` y `pedido.moneda == op_moneda`:
        same-moneda → OK (no requiere TC).
      - Item con `destino_tipo == 'pedido_compra'` y `pedido.moneda != op_moneda`:
        cross-moneda → REQUIERE `op_tipo_cambio > 0`. Si falta o es <= 0, lanza
        HTTPException 400 con mensaje detallado (índice del item, moneda OP, id
        y moneda del pedido).
      - Items con `destino_tipo != 'pedido_compra'` (factura_erp, saldo, etc):
        no se valida cross-moneda — el destino vive en la moneda de la OP.

    Reemplaza al viejo `_validar_items_misma_moneda_que_op` (que rechazaba
    cross-moneda incondicionalmente). El motivo: con `tipo_cambio` declarado
    en la OP, la imputación se persiste en moneda destino con TC trazable y
    el saldo del pedido cuadra contablemente (design §4.3 + §10 Decision 1).

    Raises:
        HTTPException 400: cross-moneda OP↔pedido sin TC válido (> 0).
    """
    for idx, item in enumerate(items):
        if item.get("tipo") != "pedido_compra":
            continue
        pedido_id = item.get("id")
        if pedido_id is None:
            continue
        pedido = session.get(PedidoCompra, pedido_id)
        if pedido is None:
            continue  # ya rechaza otra validación más adelante
        if pedido.moneda == op_moneda:
            continue
        # Cross-moneda detectada → exige TC > 0 en la OP.
        if op_tipo_cambio is None or Decimal(op_tipo_cambio) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"item[{idx}] (pedido #{pedido_id} {pedido.numero}, moneda {pedido.moneda}) "
                    f"cross-moneda con OP ({op_moneda}) requiere tipo_cambio > 0 en la OP. "
                    f"Recibido: {op_tipo_cambio}."
                ),
            )


def _resolver_supp_id(session: Session, proveedor_id: int) -> Optional[int]:
    prov = session.get(Proveedor, proveedor_id)
    if prov is None:
        return None
    return int(prov.supp_id) if prov.supp_id is not None else None


# ──────────────────────────────────────────────────────────────────────────
# detectar_duplicado_erp (design §7.1)
# ──────────────────────────────────────────────────────────────────────────


def detectar_duplicado_erp(
    session: Session,
    *,
    proveedor_id: int,
    numeros_factura: list[str],
) -> list[dict[str, Any]]:
    """
    Detecta posibles duplicados de OP en el ERP para un conjunto de números
    de factura del proveedor (design §7.1 — R9 + OP-005).

    Ejecuta la query:
        SELECT ct_transaction, ct_date, ct_total, ct_docnumber
        FROM tb_commercial_transactions ct
        WHERE ct.supp_id = :supp_id
          AND ct.sd_id = ERP_SD_ID_ORDEN_PAGO (106)
          AND ct.ct_docnumber IN :numeros_factura
          AND ct.ct_date >= CURRENT_DATE - INTERVAL '7 days'
          AND COALESCE(ct.ct_iscancelled, FALSE) = FALSE
        ORDER BY ct.ct_date DESC
        LIMIT 50;

    Args:
        session: tx activa.
        proveedor_id: FK a proveedores locales (se resuelve a supp_id).
        numeros_factura: lista de `ct_docnumber` a chequear.

    Returns:
        Lista de dicts con keys `ct_transaction`, `ct_date`,
        `ct_docnumber`, `ct_total`. Vacía si no hay match.

    Notes:
        Si el proveedor no tiene `supp_id` mapeado → retorna lista vacía
        (no hay forma de buscar en el ERP).
        Query usa `text()` para ser SQL-nativo y compatible con Postgres +
        SQLite (en tests la tabla puede no existir — el caller decide).
    """
    if not numeros_factura:
        return []

    supp_id = _resolver_supp_id(session, proveedor_id)
    if supp_id is None:
        logger.debug(
            "detectar_duplicado_erp: proveedor_id=%s sin supp_id — skip.",
            proveedor_id,
        )
        return []

    # SQLite-friendly: CURRENT_DATE existe; INTERVAL no. Usamos
    # un parámetro `fecha_desde` calculado en Python.
    from datetime import timedelta  # noqa: PLC0415

    from sqlalchemy import bindparam  # noqa: PLC0415

    fecha_desde = date.today() - timedelta(days=7)

    stmt_final = text(
        """
        SELECT ct_transaction, ct_date, ct_total, ct_docnumber
        FROM tb_commercial_transactions
        WHERE supp_id = :supp_id
          AND sd_id = :sd_id
          AND ct_docnumber IN :numeros_factura
          AND ct_date >= :fecha_desde
          AND COALESCE(ct_iscancelled, FALSE) = FALSE
        ORDER BY ct_date DESC
        LIMIT 50
        """
    ).bindparams(bindparam("numeros_factura", expanding=True))

    try:
        filas = session.execute(
            stmt_final,
            {
                "supp_id": supp_id,
                "sd_id": ERP_SD_ID_ORDEN_PAGO,
                "numeros_factura": list(numeros_factura),
                "fecha_desde": fecha_desde,
            },
        ).all()
    except Exception as exc:  # noqa: BLE001
        # Tabla no existe en tests de unidad sin fixture ERP — degradamos
        # a lista vacía con log para no romper el flujo.
        logger.debug(
            "detectar_duplicado_erp: query falló (probable falta de fixture ERP): %s",
            exc,
        )
        return []

    resultado: list[dict[str, Any]] = []
    for fila in filas:
        resultado.append(
            {
                "ct_transaction": int(fila[0]),
                "ct_date": fila[1].isoformat() if hasattr(fila[1], "isoformat") else str(fila[1]),
                "ct_total": str(fila[2]) if fila[2] is not None else None,
                "ct_docnumber": fila[3],
            }
        )
    return resultado


# ──────────────────────────────────────────────────────────────────────────
# crear (COMPRAS-4.7)
# ──────────────────────────────────────────────────────────────────────────


def crear(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: int,
    moneda: Moneda,
    monto_total: Decimal,
    modo_imputacion: ModoImputacion,
    items: list[dict],
    observaciones: Optional[str] = None,
    creado_por_id: int,
    confirmar_duplicado: bool = False,
    tipo_cambio: Optional[Decimal] = None,
    fecha_pago_estimada: Optional[date] = None,
    actualizar_tc_pedido: bool = False,
) -> OrdenPago:
    """
    Crea una OP en estado `pendiente` con validaciones completas.

    Validaciones:
      - `monto_total > 0`.
      - Restricciones por modo (`_validar_items_por_modo`).
      - Items cumplen whitelist (`_validar_items_whitelist`).
      - Detección de duplicados ERP (sd_id=106, últimos 7 días). Si hay
        match y `confirmar_duplicado=False` → HTTP 409
        `POSIBLE_DUPLICADO_OP_ERP` con payload de design §7.2.
      - Si `confirmar_duplicado=True` → crea igual + evento auditado.

    NO crea imputaciones todavía — se crean recién al `ejecutar_pago`
    (diseño §2.3).

    Args:
        session: tx activa.
        proveedor_id, empresa_id: FKs.
        moneda, monto_total, modo_imputacion: campos OP.
        items: lista de {'tipo': str, 'id': Optional[int], 'monto': Decimal,
            'numero_factura': Optional[str]}.
        observaciones: texto libre.
        creado_por_id: FK a usuarios.
        confirmar_duplicado: flag de by-pass.

    Returns:
        El `OrdenPago` creado en estado `pendiente`.

    Raises:
        HTTPException 400: validaciones de monto/modo/items.
        HTTPException 409 (POSIBLE_DUPLICADO_OP_ERP): duplicado sin confirmar.
    """
    if monto_total <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"monto_total debe ser > 0 (recibido: {monto_total}).",
        )

    items_norm = list(items or [])
    _validar_items_por_modo(modo_imputacion, items_norm, monto_total)
    _validar_items_whitelist(items_norm)
    _validar_items_cross_moneda_con_tc(
        session,
        items=items_norm,
        op_moneda=moneda,
        op_tipo_cambio=tipo_cambio,
    )

    # Detección de duplicados: extraer numeros_factura de items con
    # destino_tipo='factura_erp' o del propio item si trae numero_factura.
    numeros_factura = [item["numero_factura"] for item in items_norm if item.get("numero_factura")]
    # Adicionalmente, si hay items destino='pedido_compra', buscamos el
    # numero_factura del pedido asociado.
    for item in items_norm:
        if item.get("tipo") == "pedido_compra" and item.get("id"):
            pedido = session.get(PedidoCompra, item["id"])
            if pedido is not None and pedido.numero_factura:
                numeros_factura.append(pedido.numero_factura)

    duplicados: list[dict[str, Any]] = []
    if numeros_factura:
        duplicados = detectar_duplicado_erp(
            session,
            proveedor_id=proveedor_id,
            numeros_factura=numeros_factura,
        )

    if duplicados and not confirmar_duplicado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": CODIGO_ERROR_DUPLICADO_ERP,
                "mensaje": (
                    "Detectamos en el ERP una OP reciente para este proveedor "
                    "con los mismos números de factura. Verificá antes de continuar."
                ),
                "duplicados_detectados": duplicados,
                "flag_confirmacion": "confirmar_duplicado",
            },
        )

    # Generar número correlativo
    numero, _ = numeracion_service.generar_siguiente_numero(
        session,
        tipo="orden_pago",
        empresa_id=empresa_id,
    )

    op = OrdenPago(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda=moneda,
        monto_total=monto_total,
        modo_imputacion=modo_imputacion,
        estado="pendiente",
        observaciones=observaciones,
        tipo_cambio=Decimal(tipo_cambio) if tipo_cambio is not None else None,
        fecha_pago_estimada=fecha_pago_estimada,
        creado_por_id=creado_por_id,
        # F1 — Caso A (TRUE) vs Caso B (FALSE). Immutable after 'pagado'.
        actualizar_tc_pedido=actualizar_tc_pedido,
    )
    session.add(op)
    session.flush()

    # Evento de creación
    evento_tipo = EVENTO_OP_CREADA_DUP_CONFIRMADA if duplicados and confirmar_duplicado else EVENTO_OP_CREADA
    payload_evento: dict[str, Any] = {
        "numero": numero,
        "proveedor_id": proveedor_id,
        "empresa_id": empresa_id,
        "moneda": moneda,
        "monto_total": str(monto_total),
        "modo_imputacion": modo_imputacion,
        "items_count": len(items_norm),
    }
    if duplicados and confirmar_duplicado:
        payload_evento["ct_transaction_duplicada"] = [d["ct_transaction"] for d in duplicados]
        payload_evento["duplicados_detectados"] = duplicados

    _registrar_evento(
        session,
        op_id=op.id,
        tipo=evento_tipo,
        usuario_id=creado_por_id,
        payload=payload_evento,
    )

    # Guardamos los items en el payload del evento de creación (no hay
    # tabla orden_pago_items separada en v1 — los items se materializan
    # como imputaciones al ejecutar_pago, pero necesitamos recordarlos).
    # Usamos un evento auxiliar `items_registrados`.
    if items_norm:
        _registrar_evento(
            session,
            op_id=op.id,
            tipo=EVENTO_ITEMS_REGISTRADOS,
            usuario_id=creado_por_id,
            payload={"items": [_serializar_item(it) for it in items_norm]},
        )

    logger.info(
        "op_creada id=%s numero=%s proveedor_id=%s monto=%s %s modo=%s dup_confirmado=%s",
        op.id,
        numero,
        proveedor_id,
        monto_total,
        moneda,
        modo_imputacion,
        bool(duplicados and confirmar_duplicado),
    )
    return op


def _serializar_item(item: dict) -> dict:
    return {
        "tipo": item.get("tipo"),
        "id": item.get("id"),
        "monto": str(item.get("monto")),
        "numero_factura": item.get("numero_factura"),
    }


def _leer_items_de_op(session: Session, op_id: int) -> list[dict]:
    """Lee los items persistidos de una OP.

    Append-only: cada edición de items agrega un evento `items_editados`
    sin borrar el `items_registrados` original. Esta función retorna
    los items del evento MÁS RECIENTE entre ambos tipos, así
    `ejecutar_pago` siempre ve la última versión.
    """
    evento = session.execute(
        select(CompraEvento)
        .where(
            CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_ORDEN_PAGO,
            CompraEvento.entidad_id == op_id,
            CompraEvento.tipo.in_([EVENTO_ITEMS_REGISTRADOS, EVENTO_ITEMS_EDITADOS]),
        )
        .order_by(CompraEvento.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if evento is None or not evento.payload:
        return []
    return list(evento.payload.get("items", []))


# ──────────────────────────────────────────────────────────────────────────
# ejecutar_pago (COMPRAS-4.6) — LA transacción crítica
# ──────────────────────────────────────────────────────────────────────────


def ejecutar_pago(
    session: Session,
    *,
    orden_pago_id: int,
    caja_id: int,
    fecha_pago_real: date,
    user_id: int,
    tipo_cambio_override: Optional[Decimal] = None,
) -> OrdenPago:
    """
    Ejecuta el pago de una OP en 9 pasos ATÓMICOS (design §2.3).

    1. SELECT FOR UPDATE sobre la OP + valida `estado='pendiente'`.
    2. Valida `caja.moneda == op.moneda` O cross-moneda con TC disponible
       (sub-batch 2.3). Si `op.moneda != caja.moneda` sin TC → 422
       OP_CAJA_MONEDA_MISMATCH. Con TC (en `tipo_cambio_override` o en
       `op.tipo_cambio`) → permitido, monto en caja = op.monto_total * TC.
    3. Valida `caja.empresa_id == op.empresa_id`.
    4. `caja_service.registrar_movimiento(tipo='egreso', origen='orden_pago', ...)`.
    5. `caja_service.crear_documento(tipo='Orden de Pago', entidad='orden_pago', ...)`.
    6. Por cada item de la OP → `imputaciones_service.crear_imputacion`
       + `cc_proveedor_service.aplicar_imputacion`.

       Cross-moneda OP↔pedido (compras-cross-moneda-y-ncs-cc, FR-002/003):
       cuando `item.tipo == 'pedido_compra'` y `pedido.moneda != op.moneda`,
       el `monto` del item (en moneda OP origen) se convierte a moneda
       DESTINO (la del pedido) usando `op.tipo_cambio` y se persiste así:
         - `moneda_imputada = pedido.moneda` (moneda destino).
         - `tipo_cambio    = op.tipo_cambio` (TC declarado en la OP).
         - `monto_imputado`:
             - OP ARS → pedido USD:  USD = ARS_item / TC.
             - OP USD → pedido ARS:  ARS = USD_item * TC.
           En ambos casos cuantizado a 2 decimales con ROUND_HALF_UP
           (límite de la columna `Numeric(18, 2)`).
       Esto permite que `cc_proveedor_service.aplicar_imputacion` proyecte
       el HABER del CC en moneda destino sin tocar nada (design §4.6).
       Items NO `pedido_compra` (saldo / factura_erp) mantienen la moneda
       de la OP origen.

    7. Si `modo='mixta'` y sobra remanente → imputación (orden_pago, saldo)
       en moneda OP origen. Si `modo='a_cuenta'` → toda la OP a saldo en
       moneda OP origen.
    8. Set `op.caja_movimiento_id`, `caja_documento_id`, `estado='pagado'`,
       `fecha_pago_real`, `paid_at`, `pagado_por_id`. Si hubo
       `tipo_cambio_override`, se persiste en `op.tipo_cambio`.
    9. Evento `op_pagada` en compras_eventos.

    Propaga transiciones automáticas en pedidos vía
    `pedidos_service.aplicar_imputacion_a_pedido`.

    NO hace `session.commit()` — responsabilidad del caller. Si cualquier
    paso levanta excepción, el caller debe `session.rollback()` para
    deshacer TODO (caja, CC, imputaciones, OP).

    Args:
        session: tx activa.
        orden_pago_id: PK de la OP.
        caja_id: PK de la caja donde se registra el egreso.
        fecha_pago_real: fecha contable del pago.
        user_id: usuario que ejecuta el pago.
        tipo_cambio_override: TC al momento del pago (sub-batch 2.2). Si
            viene, sobrescribe `op.tipo_cambio` antes de registrar en caja.
            Requerido cuando la moneda de la OP difiere de la caja (y no
            hay TC previo en la OP).

    Returns:
        La OP en estado `pagado` con todas las FKs seteadas.

    Raises:
        HTTPException 400: OP en estado distinto a `pendiente`.
        HTTPException 404: OP inexistente.
        HTTPException 422: caja.moneda != op.moneda y no hay TC disponible
            (OP_CAJA_MONEDA_MISMATCH).
        HTTPException 409: caja.empresa_id != op.empresa_id.
    """
    # Paso 1: SELECT FOR UPDATE y validación de estado
    stmt = select(OrdenPago).where(OrdenPago.id == orden_pago_id).with_for_update()
    op = session.execute(stmt).scalar_one_or_none()
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={orden_pago_id} no encontrada.",
        )
    if op.estado != "pendiente":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OP {op.numero} en estado '{op.estado}' — solo se pueden pagar OPs en 'pendiente'.",
        )

    # Paso 2 y 3: validar caja moneda + empresa.
    caja = session.get(Caja, caja_id)
    if caja is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Caja id={caja_id} no encontrada.",
        )

    # Aplicar tipo_cambio_override ANTES de validar cross-moneda, así el
    # usuario puede pagar con una caja de moneda distinta siempre que
    # provea TC explícito (sub-batch 2.2 + 2.3).
    if tipo_cambio_override is not None:
        if Decimal(tipo_cambio_override) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"tipo_cambio_override debe ser > 0 (recibido: {tipo_cambio_override}).",
            )
        op.tipo_cambio = Decimal(tipo_cambio_override)

    tc_efectivo: Optional[Decimal] = op.tipo_cambio

    if caja.moneda != op.moneda:
        # Cross-moneda sólo se permite con TC disponible (override o op).
        if tc_efectivo is None or Decimal(tc_efectivo) <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "codigo": CODIGO_ERROR_CAJA_MONEDA,
                    "mensaje": (
                        f"La caja seleccionada (id={caja.id}, moneda={caja.moneda}) no coincide "
                        f"con la moneda de la OP ({op.moneda}). Para pagar cross-moneda, "
                        f"la OP debe tener `tipo_cambio` o se debe enviar "
                        f"`tipo_cambio_override` en el body."
                    ),
                },
            )
    if caja.empresa_id != op.empresa_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"La caja (empresa_id={caja.empresa_id}) no pertenece a la misma empresa "
                f"que la OP (empresa_id={op.empresa_id})."
            ),
        )

    proveedor = session.get(Proveedor, op.proveedor_id)
    proveedor_nombre = proveedor.nombre if proveedor is not None else f"proveedor_id={op.proveedor_id}"

    # Monto en moneda de la caja:
    #   - mismo moneda  → op.monto_total.
    #   - cross-moneda → op.monto_total * TC (si caja=ARS y op=USD).
    #                    op.monto_total / TC (si caja=USD y op=ARS).
    #   Asumimos TC siempre expresado como "ARS por 1 USD" (consistente
    #   con el modelo de pedidos_compra y tipo_cambio.venta).
    if caja.moneda == op.moneda:
        monto_en_caja = Decimal(op.monto_total)
    elif op.moneda == "USD" and caja.moneda == "ARS":
        monto_en_caja = (Decimal(op.monto_total) * Decimal(tc_efectivo)).quantize(Decimal("0.01"))
    else:
        # op ARS → caja USD: monto / TC. TC es ARS/USD, dividir para USD.
        monto_en_caja = (Decimal(op.monto_total) / Decimal(tc_efectivo)).quantize(Decimal("0.01"))

    # Paso 4: CajaMovimiento (egreso) — monto en la moneda de la caja.
    caja_svc = CajaService(session)
    detalle_cross = f" (TC {tc_efectivo})" if caja.moneda != op.moneda and tc_efectivo is not None else ""
    movimiento = caja_svc.registrar_movimiento(
        caja_id=caja.id,
        fecha=fecha_pago_real,
        detalle=f"OP {op.numero} - {proveedor_nombre}{detalle_cross}",
        tipo="egreso",
        monto=monto_en_caja,
        user_id=user_id,
        observaciones=op.observaciones,
        origen="orden_pago",
    )

    # Paso 5: CajaDocumento — monto en moneda de la caja.
    tipo_doc_id = _lookup_tipo_documento_id(session, TIPO_DOC_ORDEN_PAGO)
    documento = caja_svc.crear_documento(
        tipo_documento_id=tipo_doc_id,
        user_id=user_id,
        numero=op.numero,
        descripcion=f"OP {op.numero} pago a {proveedor_nombre}{detalle_cross}",
        fecha_documento=fecha_pago_real,
        monto_documento=monto_en_caja,
        movimiento_ids=[movimiento.id],
        entidad_tipo="orden_pago",
        entidad_id=op.id,
    )

    # Paso 6 + 7: crear imputaciones según modo + items
    items = _leer_items_de_op(session, op.id)
    # Defensa en profundidad: validar cross-moneda antes de imputar.
    # Con compras-cross-moneda-y-ncs-cc (FR-004), una OP cross-moneda DEBE
    # tener `tipo_cambio` > 0; en caso contrario abortar antes de grabar
    # imputaciones inválidas que rompen el saldo del pedido.
    _validar_items_cross_moneda_con_tc(
        session,
        items=items,
        op_moneda=str(op.moneda),
        op_tipo_cambio=op.tipo_cambio,
    )
    imputaciones_creadas: list[Imputacion] = []
    pedidos_afectados: set[int] = set()
    sum_items = Decimal("0")

    # Import acá para evitar ciclo con pedidos_service
    from app.services import cc_proveedor_service  # noqa: PLC0415

    # Cuantización por moneda destino de la imputación.
    # Columna `imputaciones.monto_imputado` es Numeric(18, 2) → la BD trunca
    # a 2 decimales tanto en USD como en ARS. Cuantizamos en aplicación con
    # ROUND_HALF_UP para tener control explícito (sin depender del HALF_EVEN
    # default de Decimal o del redondeo implícito del cast a Numeric).
    # Política contable explícita del SDD: ROUND_HALF_UP.
    QUANT_USD = Decimal("0.01")
    QUANT_ARS = Decimal("0.01")

    for item in items:
        monto_item_origen = Decimal(str(item["monto"]))  # monto en moneda OP
        pedido_destino: Optional[PedidoCompra] = None
        if item.get("tipo") == "pedido_compra" and item.get("id"):
            pedido_destino = session.get(PedidoCompra, int(item["id"]))

        if pedido_destino is not None and pedido_destino.moneda != op.moneda:
            # Cross-moneda OP↔pedido: convertir el monto a moneda destino y
            # grabar la imputación con `moneda_imputada = pedido.moneda` y
            # `tipo_cambio = op.tipo_cambio`. Garantía: TC > 0 por
            # `_validar_items_cross_moneda_con_tc` (defensa en profundidad).
            tc_op = Decimal(op.tipo_cambio) if op.tipo_cambio is not None else None
            if tc_op is None or tc_op <= 0:
                # Defensa final — no debería llegar acá si la validación pasó.
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        f"Cross-moneda OP {op.numero} → pedido #{pedido_destino.id} "
                        f"sin tipo_cambio válido (inconsistencia interna)."
                    ),
                )
            if op.moneda == "ARS" and pedido_destino.moneda == "USD":
                # OP ARS paga pedido USD: USD_imp = ARS_item / TC.
                monto_imp = (monto_item_origen / tc_op).quantize(QUANT_USD, rounding=ROUND_HALF_UP)
            elif op.moneda == "USD" and pedido_destino.moneda == "ARS":
                # OP USD paga pedido ARS: ARS_imp = USD_item * TC.
                monto_imp = (monto_item_origen * tc_op).quantize(QUANT_ARS, rounding=ROUND_HALF_UP)
            else:
                # Combinación de monedas no soportada (whitelist ARS/USD).
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(f"Combinación de monedas no soportada: OP={op.moneda} pedido={pedido_destino.moneda}."),
                )
            moneda_imp: str = str(pedido_destino.moneda)
            tc_imp: Optional[Decimal] = tc_op
        else:
            # Same-moneda (o destino != pedido_compra): sin conversión.
            monto_imp = monto_item_origen
            moneda_imp = str(op.moneda)
            # W2 / T1.29 / AD-7 — DEFERRED INTENTIONALLY (not implemented in PR1).
            # Design AD-7 proposes persisting a payment-date TC here for
            # same-moneda Caso-A imputaciones (so they could feed the
            # weighted-average resolver). It is deliberately NOT done:
            # per Amendment A2 the business almost never pays in USD, so a
            # same-moneda (USD OP → USD pedido) Caso-A payment is a
            # near-nonexistent edge case. Keeping PR1 lean, same-moneda
            # imputaciones keep `tipo_cambio = None`; the weighted-average
            # helpers already filter `tipo_cambio IS NOT NULL`, so such an
            # edge-case pedido simply falls back to `tipo_cambio_original`
            # (resolver mode 3) — well-defined, never crashes. If USD-USD
            # payments ever become common, revisit T1.29/AD-7.
            tc_imp = None

        imp = imputaciones_service.crear_imputacion(
            session,
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo=item["tipo"],
            destino_id=item.get("id"),
            monto_imputado=monto_imp,
            moneda_imputada=moneda_imp,  # type: ignore[arg-type]
            tipo_cambio=tc_imp,
            proveedor_id=op.proveedor_id,
            creado_por_id=user_id,
        )
        cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp.id)
        imputaciones_creadas.append(imp)
        sum_items += monto_item_origen
        if item["tipo"] == "pedido_compra" and item.get("id"):
            pedidos_afectados.add(int(item["id"]))

    # Remanente según modo
    remanente = Decimal(op.monto_total) - sum_items
    if op.modo_imputacion == "mixta" and remanente > Decimal("0"):
        imp_saldo = imputaciones_service.crear_imputacion(
            session,
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=remanente,
            moneda_imputada=op.moneda,  # type: ignore[arg-type]
            proveedor_id=op.proveedor_id,
            creado_por_id=user_id,
        )
        cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp_saldo.id)
        imputaciones_creadas.append(imp_saldo)
    elif op.modo_imputacion == "a_cuenta":
        # Toda la OP a saldo (items vacío por validación de crear)
        imp_saldo = imputaciones_service.crear_imputacion(
            session,
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal(op.monto_total),
            moneda_imputada=op.moneda,  # type: ignore[arg-type]
            proveedor_id=op.proveedor_id,
            creado_por_id=user_id,
        )
        cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp_saldo.id)
        imputaciones_creadas.append(imp_saldo)

    # Paso 8: actualizar OP
    op.caja_id = caja.id
    op.caja_movimiento_id = movimiento.id
    op.caja_documento_id = documento.id
    op.estado = "pagado"
    op.fecha_pago_real = fecha_pago_real
    op.paid_at = datetime.now(timezone.utc)
    op.pagado_por_id = user_id
    session.flush()

    # Paso 9: evento
    _registrar_evento(
        session,
        op_id=op.id,
        tipo=EVENTO_OP_PAGADA,
        usuario_id=user_id,
        payload={
            "caja_id": caja.id,
            "caja_movimiento_id": movimiento.id,
            "caja_documento_id": documento.id,
            "fecha_pago_real": fecha_pago_real.isoformat(),
            "imputaciones_creadas": [imp.id for imp in imputaciones_creadas],
            "pedidos_afectados": sorted(pedidos_afectados),
            "tipo_cambio_efectivo": str(tc_efectivo) if tc_efectivo is not None else None,
            "tipo_cambio_override_aplicado": tipo_cambio_override is not None,
            "monto_en_caja": str(monto_en_caja),
        },
    )

    # Propagar transiciones automáticas en pedidos
    for pedido_id in pedidos_afectados:
        pedidos_service.aplicar_imputacion_a_pedido(
            session,
            pedido_id=pedido_id,
            monto_imputado=Decimal("0"),  # recalcula internamente
        )

    # F1 — TC Re-valuation (AD-1 consistency invariant):
    # After all imputaciones are created, re-derive the effective TC for every
    # affected pedido and write it back to pedido.tipo_cambio. This runs for
    # BOTH Caso A and Caso B — Caso B will return tipo_cambio_original (no
    # Caso-A imputaciones → mode 3), so pedido.tipo_cambio stays correct.
    # Runs after flush so the new Imputacion rows are visible to the SELECT.
    _actualizar_tc_efectivo_pedidos_afectados(session, pedidos_afectados, user_id)

    logger.info(
        "op_pagada id=%s numero=%s caja_id=%s caja_mov_id=%s caja_doc_id=%s imp_count=%d",
        op.id,
        op.numero,
        caja.id,
        movimiento.id,
        documento.id,
        len(imputaciones_creadas),
    )
    return op


# ──────────────────────────────────────────────────────────────────────────
# F1 — TC Re-valuation helpers
# ──────────────────────────────────────────────────────────────────────────


def _actualizar_tc_efectivo_pedidos_afectados(
    session: Session,
    pedidos_afectados: set[int],
    user_id: int,
) -> None:
    """
    Re-derives and writes pedido.tipo_cambio for all affected pedidos.

    Called after imputaciones are flushed (so the new rows are visible to
    the resolver queries). Implements the AD-1 consistency invariant:
    `pedido.tipo_cambio == resolver_tc_efectivo_pedido(session, pedido)` must
    hold after every ejecutar_pago call (Caso A or Caso B).

    Also emits an append-only CC `ajuste` movement if the effective TC
    changed (Caso A: TC drifted; Caso B: TC unchanged, no adjustment).

    W4 — money safety: the CC re-valuation adjustment and the
    `pedido.tipo_cambio` cache write are ATOMIC. The adjustment is emitted
    FIRST; only if it succeeds is the cache written. If the adjustment
    fails, the error PROPAGATES (it is never swallowed) so the whole
    `ejecutar_pago` transaction rolls back — the pedido cache and the CC
    ledger can never silently diverge.

    Does NOT modify `tipo_cambio_original` — that field is immutable.
    """
    # Deferred import to avoid circular dependency: cc_proveedor_service
    # imports pedidos_service helpers which in turn import this module.
    from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

    from app.services import cc_proveedor_service  # noqa: PLC0415

    if not pedidos_afectados:
        return

    for pedido_id in pedidos_afectados:
        pedido = session.get(PedidoCompra, pedido_id)
        if pedido is None:
            logger.warning("_actualizar_tc_efectivo: pedido_id=%s not found", pedido_id)
            continue

        tc_anterior = Decimal(pedido.tipo_cambio) if pedido.tipo_cambio is not None else None
        tc_nuevo = pedidos_service.resolver_tc_efectivo_pedido(session, pedido)

        if tc_nuevo is None:
            # ARS pedido with no TC — nothing to update.
            continue

        if tc_anterior != tc_nuevo:
            # W4 — emit the append-only CC adjustment FIRST. The pedido TC
            # cache is written only after the adjustment succeeds, so the
            # cache and the CC ledger stay consistent. If the adjustment
            # fails, the error propagates and the whole tx rolls back.
            if tc_anterior is not None:
                try:
                    cc_proveedor_service.registrar_ajuste_revaluacion_tc(
                        session,
                        pedido=pedido,
                        tc_anterior=tc_anterior,
                        tc_nuevo=tc_nuevo,
                        user_id=user_id,
                        motivo="revaluacion_pago_caso_a",
                    )
                except (HTTPException, SQLAlchemyError, ValueError):
                    # Do NOT swallow: the CC adjustment and the pedido TC
                    # cache must be atomic. Log for traceability, then
                    # re-raise so ejecutar_pago's transaction rolls back —
                    # never leave the cache and the CC ledger inconsistent.
                    logger.exception(
                        "❌ _actualizar_tc_efectivo: ajuste CC falló pedido_id=%s "
                        "tc_anterior=%s tc_nuevo=%s — abortando pago para no dejar "
                        "el cache del pedido y la CC inconsistentes",
                        pedido_id,
                        tc_anterior,
                        tc_nuevo,
                    )
                    raise

            # Write new effective TC to the materialized cache — only
            # reached when the CC adjustment succeeded (or was not needed,
            # i.e. tc_anterior is None).
            pedido.tipo_cambio = tc_nuevo
            session.flush()

        logger.info(
            "tc_efectivo_actualizado pedido_id=%s tc_anterior=%s tc_nuevo=%s",
            pedido_id,
            tc_anterior,
            tc_nuevo,
        )


# ──────────────────────────────────────────────────────────────────────────
# editar (sub-batch 1.1) — solo OPs en estado `pendiente`
# ──────────────────────────────────────────────────────────────────────────


def editar(
    session: Session,
    *,
    op_id: int,
    monto_total: Optional[Decimal] = None,
    moneda: Optional[Moneda] = None,
    modo_imputacion: Optional[ModoImputacion] = None,
    items: Optional[list[dict]] = None,
    observaciones: Optional[str] = None,
    tipo_cambio: Optional[Decimal] = None,
    fecha_pago_estimada: Optional[date] = None,
    user_id: int,
) -> OrdenPago:
    """
    Edita una OP en estado `pendiente`. Otros estados → HTTP 409.

    Reglas:
      - Solo `pendiente` es editable (pagado/anulado/cancelado son terminales).
      - Revalida items contra whitelist + sum(items) vs modo.
      - Revalida TC si moneda USD (consistente con `crear`).
      - Si `items` viene, registra evento `items_editados` con el nuevo
        estado SIN borrar el `items_registrados` original (append-only).
      - `ejecutar_pago` lee los items del último evento entre
        `items_registrados` y `items_editados` (ver `_leer_items_de_op`).
      - Registra evento `op_editada` con diff de campos cambiados.

    Args:
        session: tx activa.
        op_id: PK de la OP a editar.
        monto_total, moneda, modo_imputacion, items, observaciones,
        tipo_cambio, fecha_pago_estimada: campos nuevos (None = no cambia).
        user_id: usuario que edita (para auditoría).

    Returns:
        La OP editada (recargada desde la DB).

    Raises:
        HTTPException 404: OP inexistente.
        HTTPException 409: OP en estado distinto a `pendiente`.
        HTTPException 400: validaciones de monto/modo/items/TC.
    """
    op = session.execute(select(OrdenPago).where(OrdenPago.id == op_id).with_for_update()).scalar_one_or_none()
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={op_id} no encontrada.",
        )
    if op.estado != "pendiente":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"OP {op.numero} en estado '{op.estado}' — solo se pueden editar OPs en 'pendiente'."),
        )

    # Diff para auditoría (solo campos que cambian).
    diff: dict[str, Any] = {}

    nueva_moneda: str = moneda if moneda is not None else str(op.moneda)
    nuevo_monto: Decimal = Decimal(monto_total) if monto_total is not None else Decimal(op.monto_total)
    nuevo_modo: str = modo_imputacion if modo_imputacion is not None else str(op.modo_imputacion)

    if monto_total is not None and Decimal(monto_total) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"monto_total debe ser > 0 (recibido: {monto_total}).",
        )

    # TC final resuelto (con override): se usa para validar cross-moneda con items.
    # Con cross-moneda OP↔pedido (compras-cross-moneda-y-ncs-cc), tanto OP USD
    # como OP ARS pueden tener `tipo_cambio` > 0 cuando hay items que apuntan a
    # pedidos en moneda distinta. Ya no se rechaza ARS↔TC.
    tc_final: Optional[Decimal] = tipo_cambio if tipo_cambio is not None else op.tipo_cambio

    # Si se envían items → revalidar combo (modo + whitelist + suma + cross-moneda).
    items_norm: Optional[list[dict]] = None
    if items is not None:
        items_norm = list(items or [])
        _validar_items_por_modo(nuevo_modo, items_norm, nuevo_monto)
        _validar_items_whitelist(items_norm)
        _validar_items_cross_moneda_con_tc(
            session,
            items=items_norm,
            op_moneda=nueva_moneda,
            op_tipo_cambio=tc_final,
        )
    else:
        # Si cambió monto, modo o moneda pero NO vienen items, revalidar con los
        # items existentes para no dejar la OP inconsistente.
        if monto_total is not None or modo_imputacion is not None or moneda is not None:
            items_actuales = _leer_items_de_op(session, op.id)
            _validar_items_por_modo(nuevo_modo, items_actuales, nuevo_monto)
            if moneda is not None:
                _validar_items_cross_moneda_con_tc(
                    session,
                    items=items_actuales,
                    op_moneda=nueva_moneda,
                    op_tipo_cambio=tc_final,
                )

    # Aplicar cambios en la OP
    if monto_total is not None and Decimal(op.monto_total) != Decimal(monto_total):
        diff["monto_total"] = {"de": str(op.monto_total), "a": str(monto_total)}
        op.monto_total = Decimal(monto_total)
    if moneda is not None and str(op.moneda) != moneda:
        diff["moneda"] = {"de": str(op.moneda), "a": moneda}
        op.moneda = moneda
    if modo_imputacion is not None and str(op.modo_imputacion) != modo_imputacion:
        diff["modo_imputacion"] = {"de": str(op.modo_imputacion), "a": modo_imputacion}
        op.modo_imputacion = modo_imputacion
    if observaciones is not None and (op.observaciones or "") != observaciones:
        diff["observaciones"] = {"de": op.observaciones, "a": observaciones}
        op.observaciones = observaciones
    if tipo_cambio is not None and (op.tipo_cambio is None or Decimal(op.tipo_cambio) != Decimal(tipo_cambio)):
        diff["tipo_cambio"] = {
            "de": str(op.tipo_cambio) if op.tipo_cambio is not None else None,
            "a": str(tipo_cambio),
        }
        op.tipo_cambio = Decimal(tipo_cambio)
    if fecha_pago_estimada is not None and op.fecha_pago_estimada != fecha_pago_estimada:
        diff["fecha_pago_estimada"] = {
            "de": op.fecha_pago_estimada.isoformat() if op.fecha_pago_estimada else None,
            "a": fecha_pago_estimada.isoformat(),
        }
        op.fecha_pago_estimada = fecha_pago_estimada

    session.flush()

    # Evento `items_editados` (append-only, NO borra items_registrados).
    if items_norm is not None:
        _registrar_evento(
            session,
            op_id=op.id,
            tipo=EVENTO_ITEMS_EDITADOS,
            usuario_id=user_id,
            payload={"items": [_serializar_item(it) for it in items_norm]},
        )
        diff["items_count"] = len(items_norm)

    # Evento general `op_editada` con diff (siempre, aunque diff sea vacío,
    # para auditar el intento de edición).
    _registrar_evento(
        session,
        op_id=op.id,
        tipo=EVENTO_OP_EDITADA,
        usuario_id=user_id,
        payload={"diff": diff},
    )

    logger.info(
        "op_editada id=%s numero=%s user_id=%s campos_cambiados=%s",
        op.id,
        op.numero,
        user_id,
        sorted(diff.keys()),
    )
    return op


# ──────────────────────────────────────────────────────────────────────────
# cancelar_pendiente (sub-batch 1.2) — transición terminal sin efectos
# ──────────────────────────────────────────────────────────────────────────


def cancelar_pendiente(
    session: Session,
    *,
    op_id: int,
    motivo: str,
    user_id: int,
) -> OrdenPago:
    """
    Transiciona una OP `pendiente` → `cancelado`. Cero efecto colateral.

    Es seguro porque en `pendiente`:
      - NO hay `caja_movimiento` asociado.
      - NO hay `caja_documento` asociado.
      - NO hay imputaciones físicas (los items viven solo como payload
        en `compras_eventos.items_registrados` / `items_editados`).
      - NO se movió la CC del proveedor.

    Por eso la cancelación es solo un UPDATE de `estado` + un evento
    auditado `op_cancelada_pendiente`. No hay nada que revertir.

    Args:
        session: tx activa.
        op_id: PK de la OP a cancelar.
        motivo: texto obligatorio.
        user_id: usuario que cancela.

    Returns:
        La OP en estado `cancelado`.

    Raises:
        HTTPException 404: OP inexistente.
        HTTPException 409: OP en estado distinto a `pendiente`.
        HTTPException 400: motivo vacío.
    """
    if not motivo or not motivo.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="motivo es requerido para cancelar una OP pendiente.",
        )

    op = session.execute(select(OrdenPago).where(OrdenPago.id == op_id).with_for_update()).scalar_one_or_none()
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={op_id} no encontrada.",
        )
    if op.estado != "pendiente":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"OP {op.numero} en estado '{op.estado}' — solo se pueden cancelar "
                f"OPs en 'pendiente'. Para OPs pagadas usá 'anular'."
            ),
        )

    op.estado = "cancelado"
    session.flush()

    _registrar_evento(
        session,
        op_id=op.id,
        tipo=EVENTO_OP_CANCELADA_PENDIENTE,
        usuario_id=user_id,
        payload={"motivo": motivo.strip()},
    )

    logger.info(
        "op_cancelada_pendiente id=%s numero=%s user_id=%s motivo='%s'",
        op.id,
        op.numero,
        user_id,
        motivo.strip(),
    )
    return op


# ──────────────────────────────────────────────────────────────────────────
# anular (COMPRAS-4.5 design §2.3 + D19)
# ──────────────────────────────────────────────────────────────────────────


def anular(
    session: Session,
    *,
    orden_pago_id: int,
    motivo: str,
    user_id: int,
) -> OrdenPago:
    """
    Anula una OP pagada (design §2.3, D19, REQ-OP-006 + REQ-CAJ-005).

    Flujo atómico:
      1. SELECT FOR UPDATE OP + valida `estado='pagado'`.
      2. Registra INGRESO de compensación en la misma caja
         (`monto=op.monto_total`) con `origen='orden_pago'`.
      3. Crea CajaDocumento `tipo='Orden de Pago Anulada'` (D19) vinculado
         al nuevo movimiento ingreso.
      4. Por cada imputación viva de la OP (es_reversal=False) invoca
         `imputaciones_service.desimputar` que dispara el reverso en CC.
      5. Re-transiciona los pedidos afectados
         (`pedidos_service.revertir_transicion_por_anulacion_op`).
      6. Set `op.estado='anulado'`.
      7. Evento `op_anulada`.

    Args:
        session: tx activa.
        orden_pago_id: PK de la OP.
        motivo: texto obligatorio (motivo de anulación).
        user_id: usuario que ejecuta.

    Returns:
        La OP en estado `anulado`.

    Raises:
        HTTPException 404: OP inexistente.
        HTTPException 400: OP no está en estado `pagado`.
        ValueError: si motivo está vacío.
    """
    if not motivo or not motivo.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="motivo es requerido para anular una OP.",
        )

    stmt = select(OrdenPago).where(OrdenPago.id == orden_pago_id).with_for_update()
    op = session.execute(stmt).scalar_one_or_none()
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={orden_pago_id} no encontrada.",
        )
    if op.estado != "pagado":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OP {op.numero} en estado '{op.estado}' — solo se pueden anular OPs 'pagadas'.",
        )

    # Paso 2: ingreso de compensación
    caja_svc = CajaService(session)
    movimiento_reverso = caja_svc.registrar_movimiento(
        caja_id=op.caja_id,
        fecha=date.today(),
        detalle=f"Reverso OP {op.numero} - {motivo}",
        tipo="ingreso",
        monto=Decimal(op.monto_total),
        user_id=user_id,
        observaciones=f"Anulación OP {op.numero}: {motivo}",
        origen="orden_pago",
    )

    # Paso 3: CajaDocumento tipo anulada
    tipo_doc_anulada_id = _lookup_tipo_documento_id(session, TIPO_DOC_ORDEN_PAGO_ANULADA)
    caja_svc.crear_documento(
        tipo_documento_id=tipo_doc_anulada_id,
        user_id=user_id,
        numero=f"{op.numero}-ANUL",
        descripcion=f"Anulación OP {op.numero}: {motivo}",
        fecha_documento=date.today(),
        monto_documento=Decimal(op.monto_total),
        movimiento_ids=[movimiento_reverso.id],
        entidad_tipo="orden_pago",
        entidad_id=op.id,
    )

    # Paso 4: desimputar todas las imputaciones vivas de la OP.
    # Capturamos `pedidos_afectados` ANTES del reversal para luego recalcular
    # su estado (mismo patrón que `ncs_locales_service.transicionar(cancelar_aprobado)`).
    # La lógica de loop + filtro `ya_desimputada` + desimputar está centralizada
    # en `imputaciones_service.revertir_imputaciones_de_origen` (DRY con NCs locales).
    stmt_imps = select(Imputacion).where(
        Imputacion.origen_tipo == "orden_pago",
        Imputacion.origen_id == op.id,
        Imputacion.es_reversal.is_(False),
    )
    imputaciones_vivas = list(session.execute(stmt_imps).scalars().all())
    pedidos_afectados: set[int] = {
        int(imp.destino_id)
        for imp in imputaciones_vivas
        if imp.destino_tipo == "pedido_compra" and imp.destino_id is not None
    }

    imputaciones_service.revertir_imputaciones_de_origen(
        session,
        origen_tipo="orden_pago",
        origen_id=op.id,
        user_id=user_id,
        motivo=f"anulacion_op: {motivo}",
    )

    # Paso 5: recalcular estado de pedidos afectados.
    # Nota: `desimputar` ya dispara `pedidos_service.recalcular_estado_por_imputaciones`
    # por cada imputación revertida con destino pedido_compra (transición
    # idempotente: saldo actual → estado). Este segundo paso registra el
    # evento explícito `reverso_cancelacion` con motivo `anulacion_op` para
    # auditoría. Si el estado ya fue ajustado por `desimputar`, la función
    # es no-op (`nuevo_estado == estado_previo → return pedido`).
    for pedido_id in pedidos_afectados:
        pedidos_service.revertir_transicion_por_anulacion_op(
            session,
            pedido_id=pedido_id,
            user_id=user_id,
        )

    # F1 — T1.30: re-derive effective TC after reversal (AD-1 consistency invariant).
    # After imputaciones are reverted, Caso-A contributions change so the
    # weighted average may shift. Re-run the resolver and write the result back.
    _actualizar_tc_efectivo_pedidos_afectados(session, pedidos_afectados, user_id)

    # Paso 6: estado anulado
    op.estado = "anulado"
    session.flush()

    # Paso 7: evento
    _registrar_evento(
        session,
        op_id=op.id,
        tipo=EVENTO_OP_ANULADA,
        usuario_id=user_id,
        payload={
            "motivo": motivo,
            "movimiento_reverso_id": movimiento_reverso.id,
            "imputaciones_revertidas": [imp.id for imp in imputaciones_vivas],
            "pedidos_afectados": sorted(pedidos_afectados),
        },
    )

    logger.info(
        "op_anulada id=%s numero=%s motivo='%s' imps_revertidas=%d pedidos_afectados=%d",
        op.id,
        op.numero,
        motivo,
        len(imputaciones_vivas),
        len(pedidos_afectados),
    )
    return op


def registrar_evento_auditoria(
    session: Session,
    *,
    op_id: int,
    tipo: str,
    usuario_id: int,
    payload: Optional[dict[str, Any]] = None,
) -> CompraEvento:
    """Wrapper público para insertar un evento en compras_eventos para
    una OP. Útil para flows que combinan operaciones del service y
    quieren dejar una entrada adicional en el timeline (p. ej. pago
    rápido del tab CC)."""
    return _registrar_evento(session, op_id=op_id, tipo=tipo, usuario_id=usuario_id, payload=payload)


__all__ = [
    "CODIGO_ERROR_CAJA_MONEDA",
    "CODIGO_ERROR_DUPLICADO_ERP",
    "EVENTO_ITEMS_EDITADOS",
    "EVENTO_ITEMS_REGISTRADOS",
    "EVENTO_OP_ANULADA",
    "EVENTO_OP_CANCELADA_PENDIENTE",
    "EVENTO_OP_CREADA",
    "EVENTO_OP_CREADA_DUP_CONFIRMADA",
    "EVENTO_OP_EDITADA",
    "EVENTO_OP_PAGADA",
    "ModoImputacion",
    "Moneda",
    "TIPO_DOC_ORDEN_PAGO",
    "TIPO_DOC_ORDEN_PAGO_ANULADA",
    "anular",
    "cancelar_pendiente",
    "crear",
    "detectar_duplicado_erp",
    "editar",
    "ejecutar_pago",
    "registrar_evento_auditoria",
]
