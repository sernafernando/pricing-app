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
from decimal import Decimal
from typing import Any, Final, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.compras_erp_constants import ERP_SD_ID_ORDEN_PAGO
from app.core.logging import get_logger
from app.models.banco_empresa import BancoEmpresa
from app.models.banco_movimiento import BancoMovimiento
from app.models.caja import Caja, CajaMovimiento, CajaTipoDocumento
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
from app.services.banco_service import BancoService
from app.services.caja_service import CajaService
from app.services.fx_service import q_ars, q_usd

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
# Nota: el nombre del constant y el wire value dicen "CAJA" por compatibilidad con
# el frontend y diseño previo. F7 (PR#2b) lo reutiliza también para banco cross-moneda:
# la semántica es "fuente de fondos cross-moneda sin TC válido". No renombrar el wire
# value (OP_CAJA_MONEDA_MISMATCH) sin migrar el frontend.
CODIGO_ERROR_CAJA_MONEDA: Final[str] = "OP_CAJA_MONEDA_MISMATCH"
CODIGO_ERROR_DUPLICADO_ERP: Final[str] = "POSIBLE_DUPLICADO_OP_ERP"


# ──────────────────────────────────────────────────────────────────────────
# F7 — dispatcher de egreso (AD-10)
# ──────────────────────────────────────────────────────────────────────────


def _registrar_egreso_en_fuente(
    session: Session,
    *,
    op: OrdenPago,
    caja_id: Optional[int],
    banco_id: Optional[int],
    fecha_pago_real: date,
    user_id: int,
    monto_en_fuente: Decimal,
    detalle: str,
    tc_efectivo: Optional[Decimal],
    proveedor_nombre: str,
) -> tuple[int, Optional[int]]:
    """
    Dispatcher de egreso de fondos (AD-10 / design §2.3 step 4-5).

    Decide si el movimiento va a Caja o a Banco según qué fuente viene seteada.
    Devuelve (movimiento_id, documento_id_o_none).

    Caja branch:
      - registrar_movimiento(tipo='egreso') en caja.
      - crear_documento('Orden de Pago') vinculado al movimiento.
      - retorna (caja_movimiento_id, caja_documento_id).

    Banco branch (AD-8 / FR2.9):
      - registrar_movimiento(tipo='egreso') en banco via BancoService.
      - NO crea CajaDocumento (caja_documento_id = None en v1).
      - retorna (banco_movimiento_id, None).

    No hace commit — responsabilidad del caller.
    """
    detalle_cross = f" (TC {tc_efectivo})" if tc_efectivo is not None else ""
    full_detalle = f"{detalle}{detalle_cross}"

    if caja_id is not None:
        # ── Caja branch (existente) ──
        caja_svc = CajaService(session)
        movimiento = caja_svc.registrar_movimiento(
            caja_id=caja_id,
            fecha=fecha_pago_real,
            detalle=full_detalle,
            tipo="egreso",
            monto=monto_en_fuente,
            user_id=user_id,
            observaciones=op.observaciones,
            origen="orden_pago",
        )
        tipo_doc_id = _lookup_tipo_documento_id(session, TIPO_DOC_ORDEN_PAGO)
        documento = caja_svc.crear_documento(
            tipo_documento_id=tipo_doc_id,
            user_id=user_id,
            numero=op.numero,
            descripcion=f"OP {op.numero} pago a {proveedor_nombre}{detalle_cross}",
            fecha_documento=fecha_pago_real,
            monto_documento=monto_en_fuente,
            movimiento_ids=[movimiento.id],
            entidad_tipo="orden_pago",
            entidad_id=op.id,
        )
        return int(movimiento.id), int(documento.id)

    # ── Banco branch (F7 — AD-8 / FR2.9) ──
    banco_svc = BancoService(session)
    movimiento = banco_svc.registrar_movimiento(
        banco_id=banco_id,  # type: ignore[arg-type]
        fecha=fecha_pago_real,
        detalle=full_detalle,
        tipo="egreso",
        monto=monto_en_fuente,
        user_id=user_id,
        observaciones=op.observaciones,
        origen="orden_pago",
    )
    # No CajaDocumento for banco payments (FR2.9 / AD-8).
    return int(movimiento.id), None


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
        # PR3: el balance final (items + ncs_aplicadas == monto_total) se valida en
        # validar_balance_op al momento de ejecutar_pago, no al crear el borrador.
        # Permitimos suma < monto_total en el borrador para habilitar el combo con NCs.
    elif modo == "a_cuenta":
        if items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Modo 'a_cuenta' no acepta items (el total va a saldo).",
            )
        # Nota PR3: modo 'a_cuenta' con items=[] es un draft válido, pero
        # validar_balance_op lo rechazará al confirmar (cobertura=0 ≠ monto_total)
        # salvo que las NCs pendientes cubran el total. Para pagos directos sin
        # NCs, usar 'especifica' + item pago_a_cuenta cubriendo el total.
    elif modo == "mixta":
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Modo 'mixta' requiere al menos 1 item (el resto va a saldo o pago_a_cuenta).",
            )
        # PR3: los items 'pago_a_cuenta' son cobertura explícita del excedente.
        # La suma de documentos (no-pago_a_cuenta) debe ser < monto_total para
        # que exista un excedente a cubrir con pago_a_cuenta o saldo.
        # La suma TOTAL (incluyendo pago_a_cuenta) puede == monto_total — es válida.
        suma_docs = sum(
            (Decimal(str(item["monto"])) for item in items if item.get("tipo") != "pago_a_cuenta"),
            Decimal("0"),
        )
        if suma_docs >= monto_total:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Modo 'mixta': sum(items_documento.monto)={suma_docs} debe ser < monto_total={monto_total}. "
                    f"Si sum == total, usá modo 'especifica'."
                ),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"modo_imputacion inválido: '{modo}'. Valores: especifica, a_cuenta, mixta.",
        )


def _validar_items_whitelist(items: list[dict]) -> None:
    """Cada item debe formar combo válido con origen='orden_pago'.

    Tipos especiales:
      - 'pago_a_cuenta': ítem virtual que se traduce a (orden_pago, dinero_a_cuenta)
        al ejecutar_pago. No pasa por whitelist de imputaciones y no necesita id.
        Se rechaza 'saldo' para OPs nuevas (reemplazado por 'pago_a_cuenta').
    """
    for idx, item in enumerate(items):
        destino_tipo = item.get("tipo")
        if destino_tipo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"item[{idx}] sin 'tipo'. Requerido.",
            )
        monto = Decimal(str(item.get("monto", "0")))
        if monto <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"item[{idx}].monto debe ser > 0 (recibido: {monto}).",
            )
        # 'pago_a_cuenta' es un tipo virtual — no requiere id ni validación de whitelist.
        if destino_tipo == "pago_a_cuenta":
            continue
        # 'saldo' está retirado para OPs nuevas (AD-5/AD-6): usar 'pago_a_cuenta'.
        if destino_tipo == "saldo":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"item[{idx}]: tipo='saldo' no está permitido en OPs nuevas. "
                    f"Usá tipo='pago_a_cuenta' para asignar el excedente."
                ),
            )
        imputaciones_service._validar_whitelist("orden_pago", destino_tipo)
        # destino_id obligatorio para todos los tipos no-virtuales
        destino_id = item.get("id")
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
# _validar_items_saldo_pendiente — anti-over-imputación por pedido
# ──────────────────────────────────────────────────────────────────────────


def _validar_items_saldo_pendiente(
    session: Session,
    items: list[dict],
    op_moneda: str,
) -> None:
    """Rechaza items cuyo monto excede el saldo_pendiente del pedido destino.

    Para cada item con tipo='pedido_compra' cuya moneda coincide con la del
    pedido (same-moneda) verifica:
        item.monto <= pedido.monto - sum(imputaciones_vigentes_al_pedido)

    Si el item excede el saldo lanza HTTPException 422 con mensaje claro que
    indica el número de pedido, el monto del item y el saldo disponible.

    Política (PR5 / fix over-imputación silenciosa):
      - El sistema NUNCA debe aceptar un pago same-moneda mayor al saldo del
        pedido. El usuario debe asignar el excedente como 'pago_a_cuenta'.
      - Esto previene que el CC emita un haber mayor al saldo real del pedido
        y que el saldo del pedido quede negativo.

    Cross-moneda: se salta items donde pedido.moneda != op_moneda. En esos
    casos el monto del item está en moneda OP y el saldo del pedido en moneda
    pedido — no son comparables directamente. La conversión ocurre en
    ejecutar_pago vía tipo_cambio; la validación de TC la hace
    _validar_items_cross_moneda_con_tc.

    Solo aplica a items tipo 'pedido_compra'. Los items 'factura_erp',
    'pago_a_cuenta' y 'dinero_a_cuenta' no tienen esta restricción acá
    (factura_erp no expone saldo en v1; pago_a_cuenta y dinero_a_cuenta no
    tienen destino pedido en este validador).

    Args:
        session: sesión activa.
        items: lista de items del payload (de `_leer_items_de_op`).
        op_moneda: moneda de la OP ('ARS' o 'USD').

    Raises:
        HTTPException 422: item.monto > saldo_pendiente del pedido (same-moneda).
    """
    for idx, item in enumerate(items):
        if item.get("tipo") != "pedido_compra":
            continue
        pedido_id = item.get("id")
        if pedido_id is None:
            continue
        pedido = session.get(PedidoCompra, int(pedido_id))
        if pedido is None:
            continue  # la validación de existencia la maneja otro validador

        # Cross-moneda: skip — el monto del item está en moneda OP,
        # el saldo del pedido está en moneda pedido. No son comparables.
        if str(pedido.moneda) != str(op_moneda):
            continue

        monto_item = Decimal(str(item.get("monto", "0")))
        saldo_pendiente = pedidos_service.calcular_saldo_pendiente_pedido(session, int(pedido_id))

        if monto_item > saldo_pendiente:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"item[{idx}] (pedido #{pedido.numero}, id={pedido_id}): "
                    f"el monto del ítem ({monto_item:.2f} {pedido.moneda}) excede "
                    f"el saldo pendiente ({saldo_pendiente:.2f} {pedido.moneda}). "
                    f"Reducí el monto del ítem o asigná el excedente como 'pago_a_cuenta'."
                ),
            )


# ──────────────────────────────────────────────────────────────────────────
# validar_balance_op — invariante no-diferencia (PR3, design §3.4, AD-5)
# ──────────────────────────────────────────────────────────────────────────


def validar_balance_op(
    session: Session,
    op: OrdenPago,
    items: list[dict],
    cheques_op_moneda: Optional[Decimal] = None,
) -> None:
    """Valida el invariante no-diferencia ANTES de ejecutar el pago (AD-5).

    Modelo net-item (fix over-imputación NC/DAC):
      El monto de cada item pedido/factura DEBE ser el monto NETO de créditos
      (NC y DAC) ya descontados por el frontend. Por lo tanto:

        monto_total = sum(pedido_compra/factura_erp NET items)
                    + sum(pago_a_cuenta items)   ← excedente real en cash

      NC y DAC NO son términos del balance. Ambos se aplican por separado
      (NC → imputar_nc_a_pedido, DAC → consumir) y su efecto ya está
      reflejado en el monto neto del item.

    Invariante:
      diferencia = sum(pedido/factura NET items) + sum(pago_a_cuenta) − monto_total = 0

    Si diferencia != 0 → HTTPException 422.

    Solo se llama desde `ejecutar_pago` — NUNCA desde `crear`
    (los drafts pendiente siguen editables sin gate).

    Args:
        session: sesión activa.
        op: instancia de OrdenPago ya cargada.
        items: lista de items del payload (de `_leer_items_de_op`).

    Raises:
        HTTPException 422: diferencia != 0 o item.monto > saldo_pendiente pedido.
    """
    # PR5 — Validar que ningún item excede el saldo_pendiente de su pedido.
    # Esto previene over-imputaciones silenciosas que dejan saldo negativo en
    # el pedido y habers incorrectos en la CC.
    _validar_items_saldo_pendiente(session, items, op_moneda=str(op.moneda))

    monto_total = Decimal(str(op.monto_total))
    op_moneda = str(op.moneda)

    # Cash coverage: sum of NET pedido/factura items + pago_a_cuenta excedente.
    # NC and DAC are NOT terms here — they are baked into the net item montos
    # by the frontend and applied separately (NC via imputar_nc_a_pedido,
    # DAC via consumir). dinero_a_cuenta items in the list are side payments
    # that do not count as OP cash output.
    base_items = Decimal("0")
    pago_a_cuenta_total = Decimal("0")

    for item in items:
        tipo = item.get("tipo", "")
        monto_item = Decimal(str(item.get("monto", "0")))
        if tipo in ("pedido_compra", "factura_erp"):
            base_items += monto_item
        elif tipo == "pago_a_cuenta":
            pago_a_cuenta_total += monto_item
        # dinero_a_cuenta items are intentionally excluded: they are not cash
        # output from the OP. Their coverage is reflected in the net item monto.

    # Cheques: cobertura adicional (valores), reduce el efectivo necesario.
    # La suma ya está derivada a moneda OP por el caller (ejecutar_pago).
    suma_cheques = cheques_op_moneda if cheques_op_moneda is not None else Decimal("0")

    # Invariant: monto_total = base_items + pago_a_cuenta + cheques
    # ⟺ diferencia = base_items + pago_a_cuenta + cheques − monto_total = 0
    diferencia = base_items + pago_a_cuenta_total + suma_cheques - monto_total

    # Tolerancia de medio centavo: la conversión cross-moneda (nativo×TC) puede
    # dejar un residuo sub-centavo (-0.00) que NO es exactamente 0 y bloqueaba
    # el pago indebidamente. Mismo criterio que el frontend (commit #778).
    if abs(diferencia) >= Decimal("0.005"):
        moneda = op_moneda
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La OP no balancea: diferencia = {diferencia:+.2f} {moneda}. "
                f"monto_total={monto_total:.2f}, "
                f"items={base_items:.2f}, pago_a_cuenta={pago_a_cuenta_total:.2f}, "
                f"cheques={suma_cheques:.2f}. "
                f"Revisá los ítems y el monto total. "
                f"Los créditos (NC, DAC) deben estar descontados del monto de cada ítem."
            ),
        )


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
    ncs_aplicadas: Optional[list[dict]] = None,
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

    # F7 — Aplicar NCs en la misma transacción que la creación de la OP.
    _aplicar_ncs_lista(
        session,
        op=op,
        ncs_aplicadas=ncs_aplicadas or [],
        creado_por_id=creado_por_id,
    )

    return op


def _aplicar_ncs_lista(
    session: Session,
    *,
    op: OrdenPago,
    ncs_aplicadas: list[dict],
    creado_por_id: int,
) -> None:
    """F7 — Aplica la lista de NCs al crear la OP.

    Para cada entrada en `ncs_aplicadas`:
      1. Carga la NC (404 si no existe).
      2. Valida que pertenezca al mismo proveedor que la OP (implícito en imputar_nc_a_pedido).
      3. Resuelve el pedido destino según la lógica AD-4:
         - `pedido_id` explícito en el item → usa ese pedido (404 si no existe).
         - `pedido_id` omitido + OP tiene un único pedido en sus items → infiere.
         - `pedido_id` omitido + OP a_cuenta (sin items de pedido) → 422.
         - `pedido_id` omitido + OP con múltiples pedidos → 422.
      4. Delega a `imputar_nc_a_pedido` (validaciones + imputación + CC + pedido state).

    NO hace commit — responsabilidad del caller.
    """
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    if not ncs_aplicadas:
        return

    # Pre-compute pedido_ids from op items (for inference when pedido_id is absent).
    # Items are stored in the op creation payload; use modo_imputacion to detect a_cuenta.
    # For items-based OPs, get pedido_ids from items_norm stored in the evento.
    items_norm = _leer_items_de_op(session, op.id)
    pedido_ids_items: list[int] = [
        item["id"] for item in items_norm if item.get("tipo") == "pedido_compra" and item.get("id") is not None
    ]

    for nc_item in ncs_aplicadas:
        nc_id: int = nc_item["nc_id"]
        monto: Decimal = Decimal(str(nc_item["monto"]))
        pedido_id: int | None = nc_item.get("pedido_id")

        # 1. Cargar NC.
        nc = session.get(NotaCreditoLocal, nc_id)
        if nc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"NotaCreditoLocal id={nc_id} no encontrada.",
            )

        # Validate NC belongs to same proveedor as OP (before resolving pedido).
        if nc.proveedor_id != op.proveedor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"La NC id={nc_id} pertenece al proveedor id={nc.proveedor_id}, "
                    f"pero la OP pertenece al proveedor id={op.proveedor_id}."
                ),
            )

        # 3. Resolver pedido destino.
        if pedido_id is not None:
            # Explicit pedido_id — load it.
            pedido = session.get(PedidoCompra, pedido_id)
            if pedido is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Pedido id={pedido_id} no encontrado.",
                )
        else:
            # Implicit resolution.
            if not pedido_ids_items:
                # OP a_cuenta or no pedido items.
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"pedido_id es requerido para NC id={nc_id}: la OP es a_cuenta o no tiene pedidos asociados."
                    ),
                )
            if len(pedido_ids_items) > 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"pedido_id es requerido para NC id={nc_id}: "
                        f"la OP imputa múltiples pedidos: {sorted(pedido_ids_items)}."
                    ),
                )
            pedido = session.get(PedidoCompra, pedido_ids_items[0])
            if pedido is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Pedido id={pedido_ids_items[0]} no encontrado.",
                )

        # 4. Imputar NC al pedido (shared helper).
        imputar_nc_a_pedido(
            session,
            nc=nc,
            pedido=pedido,
            monto=monto,
            creado_por_id=creado_por_id,
        )


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
    caja_id: Optional[int] = None,
    banco_id: Optional[int] = None,
    fecha_pago_real: date,
    user_id: int,
    tipo_cambio_override: Optional[Decimal] = None,
    cheques: Optional[list[dict]] = None,
) -> OrdenPago:
    """
    Ejecuta el pago de una OP en 9 pasos ATÓMICOS (design §2.3).

    F7 (PR#2b): acepta `caja_id` O `banco_id` como fuente de fondos (mutuamente
    excluyentes). Exactamente uno debe venir seteado al pagar (FR2.6 / AC-F2-7).

    1. SELECT FOR UPDATE sobre la OP + valida `estado='pendiente'`.
    2. Valida fuente de fondos (caja O banco):
       - Caja: `caja.moneda == op.moneda` O cross-moneda con TC (sub-batch 2.3).
       - Banco: activo, empresa_id seteado, empresa coincide con op.empresa_id.
         Banco con empresa_id=None → 422 (AC-F2-9).
    3. Calcula monto en la moneda de la fuente (cross-moneda idéntico para caja y banco).
    4. `_registrar_egreso_en_fuente(...)` → (movimiento_id, documento_id_o_None).
       - Caja: CajaMovimiento + CajaDocumento (existente).
       - Banco: BancoMovimiento; NO CajaDocumento (FR2.9 / AD-8).
    5-7. Imputaciones, CC, remanente — sin cambio.
    8. Set FKs de la fuente usada: `op.caja_*` OR `op.banco_*`.
       La FK no-usada permanece NULL (AC-F2-5 / AC-F2-6).
    9. Evento `op_pagada`.

    Propaga transiciones automáticas en pedidos vía
    `pedidos_service.aplicar_imputacion_a_pedido`.

    NO hace `session.commit()` — responsabilidad del caller.

    Args:
        session: tx activa.
        orden_pago_id: PK de la OP.
        caja_id: PK de la caja (mutuamente excluyente con banco_id).
        banco_id: PK del banco (mutuamente excluyente con caja_id).
        fecha_pago_real: fecha contable del pago.
        user_id: usuario que ejecuta el pago.
        tipo_cambio_override: TC al momento del pago (sub-batch 2.2).

    Returns:
        La OP en estado `pagado` con todas las FKs seteadas.

    Raises:
        HTTPException 400: OP en estado distinto a `pendiente`.
        HTTPException 404: OP o fuente inexistente.
        HTTPException 422: banco inactivo, sin empresa, fuente moneda mismatch sin TC, o sin fuente.
        HTTPException 409: fuente.empresa_id != op.empresa_id (caja o banco).
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

    # Service-level XOR guard (duplica la validación del schema para callers directos).
    if (caja_id is not None) and (banco_id is not None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo se puede especificar una fuente de fondos: caja_id O banco_id, no ambos.",
        )

    # Deep-copy cheque dicts to avoid mutating caller's data structures.
    cheques_norm: list[dict] = [dict(ch) for ch in (cheques or [])]

    # Aplicar tipo_cambio_override ANTES de validar cross-moneda.
    if tipo_cambio_override is not None:
        if Decimal(tipo_cambio_override) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"tipo_cambio_override debe ser > 0 (recibido: {tipo_cambio_override}).",
            )
        op.tipo_cambio = Decimal(tipo_cambio_override)

    tc_efectivo: Optional[Decimal] = op.tipo_cambio

    proveedor = session.get(Proveedor, op.proveedor_id)
    proveedor_nombre = proveedor.nombre if proveedor is not None else f"proveedor_id={op.proveedor_id}"

    # ── Paso 2-3: cargar fuente y calcular monto ──────────────────────────
    # fuente_moneda is the currency of the payment source (caja or banco).
    fuente_moneda: str = str(op.moneda)  # default: same as OP

    if caja_id is not None:
        # ── Caja branch (existing) ──
        caja = session.get(Caja, caja_id)
        if caja is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Caja id={caja_id} no encontrada.",
            )
        fuente_moneda = str(caja.moneda)
        if caja.moneda != op.moneda:
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

    elif banco_id is not None:
        # ── Banco branch (F7) ──
        banco = session.get(BancoEmpresa, banco_id)
        if banco is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"BancoEmpresa id={banco_id} no encontrado.",
            )
        if not banco.activo:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El banco id={banco_id} no está activo.",
            )
        if banco.empresa_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"El banco id={banco_id} no tiene empresa asignada y "
                    f"no puede usarse como fuente de fondos (AC-F2-9)."
                ),
            )
        if banco.empresa_id != op.empresa_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El banco (empresa_id={banco.empresa_id}) no pertenece a la misma empresa "
                    f"que la OP (empresa_id={op.empresa_id}) (AC-F2-10)."
                ),
            )
        fuente_moneda = str(banco.moneda)
        # Cross-moneda guard — idéntico al de la caja (AC-F2-7 extendido).
        if fuente_moneda != str(op.moneda):
            if tc_efectivo is None or Decimal(tc_efectivo) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "codigo": CODIGO_ERROR_CAJA_MONEDA,
                        "mensaje": (
                            f"La moneda del banco (id={banco_id}, moneda={banco.moneda}) no coincide "
                            f"con la de la OP ({op.moneda}). Para pagar cross-moneda, "
                            f"debés ingresar un tipo de cambio > 0."
                        ),
                    },
                )

    elif not cheques_norm:
        # No fund source AND no cheques — cannot pay.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Se requiere exactamente una fuente de fondos: caja_id, banco_id, o cheques.",
        )

    # ── Deriva cheques a moneda OP (para balance y para linkear) ──────────────
    # El caller pasa cada cheque en su moneda original. Derivamos a moneda OP
    # con el mismo TC que ya existe en la OP (derive-at-edge reutilizado).
    suma_cheques_op: Decimal = Decimal("0")
    for ch in cheques_norm:
        ch_monto = Decimal(str(ch["monto"]))
        ch_moneda = str(ch.get("moneda", op.moneda))
        if ch_moneda == str(op.moneda):
            monto_op = ch_monto
        elif op.moneda == "USD" and ch_moneda == "ARS":
            # Cheque ARS, OP USD: monto_op = ARS / TC
            if tc_efectivo is None or Decimal(tc_efectivo) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(f"Cheque en ARS con OP en USD requiere tipo_cambio > 0 (número={ch.get('numero')})."),
                )
            monto_op = q_usd(ch_monto / Decimal(tc_efectivo))
        else:
            # Cheque USD, OP ARS: monto_op = USD * TC
            if tc_efectivo is None or Decimal(tc_efectivo) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(f"Cheque en USD con OP en ARS requiere tipo_cambio > 0 (número={ch.get('numero')})."),
                )
            monto_op = q_ars(ch_monto * Decimal(tc_efectivo))
        ch["_monto_op_moneda"] = monto_op
        suma_cheques_op += monto_op

    # Monto de efectivo a registrar en la fuente (monto_total - cobertura por cheques).
    # Puede ser cero si los cheques cubren el total.
    monto_efectivo_op = Decimal(op.monto_total) - suma_cheques_op

    has_fuente = (caja_id is not None) or (banco_id is not None)

    movimiento_id: Optional[int] = None
    documento_id: Optional[int] = None
    monto_en_fuente: Decimal = Decimal("0")

    if has_fuente and monto_efectivo_op > Decimal("0"):
        # Monto en la moneda de la fuente (idéntica lógica para caja y banco):
        if fuente_moneda == str(op.moneda):
            monto_en_fuente = monto_efectivo_op
        elif op.moneda == "USD" and fuente_moneda == "ARS":
            monto_en_fuente = q_ars(monto_efectivo_op * Decimal(tc_efectivo))
        else:
            # op ARS → fuente USD: monto / TC.
            monto_en_fuente = q_usd(monto_efectivo_op / Decimal(tc_efectivo))

        # Paso 4-5: registrar egreso en la fuente elegida.
        detalle_base = f"OP {op.numero} - {proveedor_nombre}"
        movimiento_id, documento_id = _registrar_egreso_en_fuente(
            session,
            op=op,
            caja_id=caja_id,
            banco_id=banco_id,
            fecha_pago_real=fecha_pago_real,
            user_id=user_id,
            monto_en_fuente=monto_en_fuente,
            detalle=detalle_base,
            tc_efectivo=tc_efectivo if fuente_moneda != str(op.moneda) else None,
            proveedor_nombre=proveedor_nombre,
        )
    elif has_fuente and monto_efectivo_op <= Decimal("0"):
        # Cheques cubren todo o más — no se registra egreso en caja/banco.
        logger.info(
            "op=%s cheques cubren el total — no se registra egreso en fuente caja/banco",
            op.id,
        )
    # else: sin fuente Y sin efectivo (pure-cheque path) — OK.

    # Paso 6 + 7: crear imputaciones según modo + items
    items = _leer_items_de_op(session, op.id)

    # PR3 — Invariante no-diferencia (AD-5, design §3.4).
    # Verificar ANTES de tocar caja/banco: cobertura total debe == monto_total.
    validar_balance_op(session, op, items, cheques_op_moneda=suma_cheques_op if suma_cheques_op > 0 else None)

    # Defensa en profundidad: validar cross-moneda antes de imputar.
    # Con compras-cross-moneda-y-ncs-cc (FR-004), una OP cross-moneda DEBE
    # tener `tipo_cambio` > 0; en caso contrario abortar antes de grabar
    # imputaciones inválidas que rompen el saldo del pedido.
    # Excluir items pago_a_cuenta del chequeo cross-moneda (no tienen destino).
    _validar_items_cross_moneda_con_tc(
        session,
        items=[it for it in items if it.get("tipo") != "pago_a_cuenta"],
        op_moneda=str(op.moneda),
        op_tipo_cambio=op.tipo_cambio,
    )
    imputaciones_creadas: list[Imputacion] = []
    pedidos_afectados: set[int] = set()
    sum_items = Decimal("0")

    # Import acá para evitar ciclo con pedidos_service
    from app.services import cc_proveedor_service  # noqa: PLC0415

    for item in items:
        # PR3: items 'pago_a_cuenta' se procesan por separado después del loop
        # (crean DineroACuenta + imputacion dinero_a_cuenta). Se saltan acá.
        # PR4: items 'dinero_a_cuenta' se procesan por separado también
        # (consumen un DAC existente sin emitir CC — AD-4).
        if item.get("tipo") in ("pago_a_cuenta", "dinero_a_cuenta"):
            continue

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
                monto_imp = q_usd(monto_item_origen / tc_op)
            elif op.moneda == "USD" and pedido_destino.moneda == "ARS":
                # OP USD paga pedido ARS: ARS_imp = USD_item * TC.
                monto_imp = q_ars(monto_item_origen * tc_op)
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
            # AD-7 — persist the OP's explicit TC on same-moneda Caso-A
            # imputaciones so that calcular_tc_ponderado_caso_a (which filters
            # `tipo_cambio IS NOT NULL`) can include them in the weighted
            # average. Without this, the ARS projection of a USD pedido paid
            # by a USD OP at a different TC would stay pinned to
            # tipo_cambio_original (resolver mode 3 fallback) — wrong.
            #
            # Conditions for storing TC:
            #   • destination is a pedido_compra (pedido_destino is not None but
            #     same-moneda, so we reach this branch only when monedas match
            #     OR destination is not a pedido_compra).
            #   • OP has actualizar_tc_pedido = True (Caso A) AND op.tipo_cambio
            #     is not None — i.e., the OP carries an explicit exchange rate.
            #
            # Caso B (actualizar_tc_pedido=False): we could store tc_op here
            # harmlessly, but calcular_tc_ponderado_caso_a already filters by
            # `actualizar_tc_pedido=True` via JOIN, so it would never be used.
            # Storing it anyway for auditability; the filter is the guard.
            #
            # ARS–ARS payments: op.tipo_cambio is typically None for pure-ARS
            # flows; the `if` below evaluates False → tc_imp stays None, no
            # change in behavior.
            if pedido_destino is not None and op.tipo_cambio is not None:
                tc_imp = Decimal(op.tipo_cambio)
            else:
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

    # PR3 — Procesar items 'pago_a_cuenta' (AD-6, design §3.3).
    # Cada item pago_a_cuenta:
    #   1. Crea una fila DineroACuenta (monto, moneda OP, proveedor, disponible).
    #   2. Crea imputacion (orden_pago → dinero_a_cuenta) — emite HABER en CC
    #      vía aplicar_imputacion (el dinero real entra al CC del proveedor).
    # Reemplaza el viejo bloque "remanente → destino='saldo'" (retirado en PR3).
    from app.services import dinero_a_cuenta_service  # noqa: PLC0415

    for item in items:
        if item.get("tipo") != "pago_a_cuenta":
            continue
        monto_pac = Decimal(str(item["monto"]))
        dac = dinero_a_cuenta_service.crear(
            session,
            proveedor_id=op.proveedor_id,
            empresa_id=op.empresa_id,
            monto=monto_pac,
            moneda=str(op.moneda),
            origen_op_id=op.id,
            user_id=user_id,
        )
        imp_dac = imputaciones_service.crear_imputacion(
            session,
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="dinero_a_cuenta",
            destino_id=dac.id,
            monto_imputado=monto_pac,
            moneda_imputada=str(op.moneda),  # type: ignore[arg-type]
            tipo_cambio=None,
            proveedor_id=op.proveedor_id,
            creado_por_id=user_id,
        )
        cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp_dac.id)
        imputaciones_creadas.append(imp_dac)
        logger.info(
            "pago_a_cuenta procesado op=%s dac_id=%s monto=%s %s",
            op.id,
            dac.id,
            monto_pac,
            op.moneda,
        )

    # PR4 — Procesar items 'dinero_a_cuenta' (AD-4, T4.5, design §3.3).
    # Cada item dinero_a_cuenta:
    #   - id: PK del DineroACuenta a consumir.
    #   - monto: monto a consumir.
    #   - destino_tipo: 'pedido_compra' | 'factura_erp' (opcional, por defecto primer pedido).
    #   - destino_id: PK del destino (opcional, por defecto el primer pedido del OP).
    # consumir() crea imputacion (dinero_a_cuenta → destino) SIN emitir CC (AD-4).
    for item in items:
        if item.get("tipo") != "dinero_a_cuenta":
            continue
        dac_id = item.get("id")
        if not dac_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Item dinero_a_cuenta sin 'id' de DineroACuenta.",
            )
        monto_dac = Decimal(str(item["monto"]))

        # Resolver destino: usa el pedido/factura especificado en el item,
        # o bien el primer pedido_compra del OP como destino por defecto.
        destino_tipo_dac = item.get("destino_tipo") or "pedido_compra"
        destino_id_dac = item.get("destino_id")
        if destino_id_dac is None:
            # Buscar el primer item pedido_compra/factura_erp del OP como destino.
            destino_item = next(
                (it for it in items if it.get("tipo") in ("pedido_compra", "factura_erp") and it.get("id")),
                None,
            )
            if destino_item is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Item dinero_a_cuenta (dac_id={dac_id}) sin destino_id "
                        f"y la OP no tiene items pedido_compra/factura_erp para inferirlo."
                    ),
                )
            destino_tipo_dac = destino_item["tipo"]
            destino_id_dac = int(destino_item["id"])
        else:
            destino_id_dac = int(destino_id_dac)

        imp_dac_consumo = dinero_a_cuenta_service.consumir(
            session,
            dinero_a_cuenta_id=int(dac_id),
            destino_tipo=destino_tipo_dac,
            destino_id=destino_id_dac,
            monto=monto_dac,
            user_id=user_id,
            op_proveedor_id=op.proveedor_id,
            op_moneda=str(op.moneda),
            op_tipo_cambio=op.tipo_cambio,
        )
        imputaciones_creadas.append(imp_dac_consumo)
        logger.info(
            "dinero_a_cuenta consumido op=%s dac_id=%s monto=%s %s → %s:%s",
            op.id,
            dac_id,
            monto_dac,
            op.moneda,
            destino_tipo_dac,
            destino_id_dac,
        )

    # ── Cheques: emitir + linkear + imputar CC ────────────────────────────────
    # Para cada cheque del payload: emitir_cheque_propio (cheques_service),
    # crear OrdenPagoCheque (link OP↔cheque), e imputar haber en CC del proveedor.
    # TODO en la misma transacción (sin commit intermedio).
    if cheques_norm:
        from app.models.cheque import OrdenPagoCheque  # noqa: PLC0415
        from app.services import cheques_service  # noqa: PLC0415

        for ch in cheques_norm:
            cheque_emitido = cheques_service.emitir_cheque_propio(
                session,
                tipo="propio",
                instrumento=str(ch.get("instrumento", "fisico")),
                numero=str(ch["numero"]),
                monto=Decimal(str(ch["monto"])),
                moneda=str(ch.get("moneda", op.moneda)),
                fecha_emision=ch["fecha_emision"],
                fecha_pago=ch["fecha_pago"],
                banco_empresa_id=int(ch["banco_empresa_id"]),
                chequera_id=ch.get("chequera_id"),
                proveedor_id=op.proveedor_id,
                usuario_id=user_id,
            )

            # Denormalize FK to OP
            cheque_emitido.orden_pago_id = op.id
            session.flush()

            monto_op_moneda = ch["_monto_op_moneda"]

            # Tabla de enlace OP↔cheque
            link = OrdenPagoCheque(
                orden_pago_id=op.id,
                cheque_id=cheque_emitido.id,
                monto_op_moneda=monto_op_moneda,
            )
            session.add(link)
            session.flush()

            # Imputar haber en CC del proveedor (entregar un cheque ES un pago).
            # Caso A — con pedido_id: crear Imputacion cheque→pedido (espeja NC).
            #   La CC se actualiza vía aplicar_imputacion (NO haber directo → evita doble conteo).
            # Caso B — sin pedido_id ("a cuenta"): haber directo CC (camino original).
            pedido_id_cheque: Optional[int] = ch.get("pedido_id")
            if pedido_id_cheque is not None:
                # Validate pedido exists and belongs to the same provider.
                pedido_cheque = session.get(PedidoCompra, pedido_id_cheque)
                if pedido_cheque is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Pedido id={pedido_id_cheque} no encontrado (referenciado por cheque #{ch.get('numero')}).",
                    )
                if pedido_cheque.proveedor_id != op.proveedor_id:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"Pedido id={pedido_id_cheque} pertenece al proveedor id={pedido_cheque.proveedor_id}, "
                            f"distinto al de la OP (proveedor_id={op.proveedor_id})."
                        ),
                    )
                # Validate pedido saldo >= monto_op_moneda to prevent over-imputation.
                saldo_pedido = pedidos_service.calcular_saldo_pendiente_pedido(session, pedido_id_cheque)
                if monto_op_moneda > saldo_pedido:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"Cheque #{ch.get('numero')}: monto a imputar ({monto_op_moneda}) "
                            f"excede el saldo pendiente del pedido id={pedido_id_cheque} ({saldo_pedido})."
                        ),
                    )
                # Create Imputacion cheque→pedido_compra (mirrors imputar_nc_a_pedido).
                imp_cheque = imputaciones_service.crear_imputacion(
                    session,
                    origen_tipo="cheque",
                    origen_id=cheque_emitido.id,
                    destino_tipo="pedido_compra",
                    destino_id=pedido_id_cheque,
                    monto_imputado=monto_op_moneda,
                    moneda_imputada=str(op.moneda),  # type: ignore[arg-type]
                    proveedor_id=op.proveedor_id,
                    creado_por_id=user_id,
                )
                # CC haber is emitted by aplicar_imputacion (not a direct insertar_mov).
                cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp_cheque.id)
                # Recalculate pedido state (aprobado → pagado_parcial / pagado).
                pedidos_service.aplicar_imputacion_a_pedido(
                    session,
                    pedido_id=pedido_id_cheque,
                    monto_imputado=Decimal("0"),
                )
                logger.info(
                    "✅ Cheque id=%s imputado a pedido_id=%s monto=%s %s via Imputacion id=%s",
                    cheque_emitido.id,
                    pedido_id_cheque,
                    monto_op_moneda,
                    op.moneda,
                    imp_cheque.id,
                )
            else:
                # Caso B: "a cuenta" — haber directo CC (comportamiento previo).
                cc_proveedor_service.insertar_mov(
                    session,
                    proveedor_id=op.proveedor_id,
                    empresa_id=op.empresa_id,
                    fecha_movimiento=fecha_pago_real,
                    tipo="haber",
                    monto=monto_op_moneda,
                    moneda=str(op.moneda),
                    origen_tipo="cheque",
                    origen_id=cheque_emitido.id,
                    descripcion=(f"Cheque #{cheque_emitido.numero} emitido para OP {op.numero}"),
                    creado_por_id=user_id,
                )

            # Evento 'imputado_cc' en cheque_evento
            cheques_service._registrar_evento(
                session,
                cheque_id=cheque_emitido.id,
                tipo="imputado_cc",
                payload={
                    "orden_pago_id": op.id,
                    "monto_op_moneda": str(monto_op_moneda),
                    "moneda_op": str(op.moneda),
                    "pedido_id": pedido_id_cheque,
                },
                usuario_id=user_id,
            )

            logger.info(
                "✅ Cheque emitido y linkeado a OP op=%s cheque_id=%s numero=%s monto_op=%s %s",
                op.id,
                cheque_emitido.id,
                cheque_emitido.numero,
                monto_op_moneda,
                op.moneda,
            )

    # Paso 8: actualizar OP — set la FK de la fuente usada; la otra queda NULL.
    if caja_id is not None:
        op.caja_id = caja_id
        op.caja_movimiento_id = movimiento_id
        op.caja_documento_id = documento_id
        op.banco_id = None
        op.banco_movimiento_id = None
    else:
        op.banco_id = banco_id
        op.banco_movimiento_id = movimiento_id
        op.caja_id = None
        op.caja_movimiento_id = None
        op.caja_documento_id = None  # FR2.9 / AD-8: no CajaDocumento for banco
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
            "fuente": "caja" if caja_id is not None else "banco",
            "caja_id": caja_id,
            "caja_movimiento_id": movimiento_id if caja_id is not None else None,
            "caja_documento_id": documento_id,
            "banco_id": banco_id,
            "banco_movimiento_id": movimiento_id if banco_id is not None else None,
            "fecha_pago_real": fecha_pago_real.isoformat(),
            "imputaciones_creadas": [imp.id for imp in imputaciones_creadas],
            "pedidos_afectados": sorted(pedidos_afectados),
            "tipo_cambio_efectivo": str(tc_efectivo) if tc_efectivo is not None else None,
            "tipo_cambio_override_aplicado": tipo_cambio_override is not None,
            "monto_en_fuente": str(monto_en_fuente),
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
    _actualizar_tc_efectivo_pedidos_afectados(session, pedidos_afectados, user_id)

    logger.info(
        "op_pagada id=%s numero=%s fuente=%s fuente_id=%s mov_id=%s doc_id=%s imp_count=%d",
        op.id,
        op.numero,
        "caja" if caja_id is not None else "banco",
        caja_id if caja_id is not None else banco_id,
        movimiento_id,
        documento_id,
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

    # Paso 2: ingreso de compensación — caja o banco según la fuente original.
    # F7 (PR#2b): si op.banco_id está seteado → reverso va al banco (Risk #9).
    #             si op.caja_id está seteado → comportamiento existente.
    if op.banco_id is not None:
        # ── Banco reversal ──
        # Recuperamos el monto original del egreso para neutralizar cross-moneda:
        # ejecutar_pago pudo haber registrado monto_en_fuente != op.monto_total
        # (ej. OP USD pagada desde banco ARS: egreso = monto * TC, en ARS).
        # El ingreso de reverso DEBE usar el mismo monto que el egreso (invariante).
        egreso_original = session.get(BancoMovimiento, op.banco_movimiento_id)
        monto_reverso = Decimal(egreso_original.monto) if egreso_original is not None else Decimal(op.monto_total)
        banco_svc = BancoService(session)
        movimiento_reverso = banco_svc.registrar_movimiento(
            banco_id=op.banco_id,
            fecha=date.today(),
            detalle=f"Reverso OP {op.numero} - {motivo}",
            tipo="ingreso",
            monto=monto_reverso,
            user_id=user_id,
            observaciones=f"Anulación OP {op.numero}: {motivo}",
            origen="orden_pago",
        )
        # No CajaDocumento for banco reversals (FR2.9 / AD-8).
    else:
        # ── Caja reversal (existente) ──
        # Recuperamos el monto original del egreso para neutralizar cross-moneda
        # (idéntico al banco branch — invariante egreso=ingreso en la fuente).
        egreso_caja_original = session.get(CajaMovimiento, op.caja_movimiento_id)
        monto_reverso_caja = (
            Decimal(egreso_caja_original.monto) if egreso_caja_original is not None else Decimal(op.monto_total)
        )
        caja_svc = CajaService(session)
        movimiento_reverso = caja_svc.registrar_movimiento(
            caja_id=op.caja_id,
            fecha=date.today(),
            detalle=f"Reverso OP {op.numero} - {motivo}",
            tipo="ingreso",
            monto=monto_reverso_caja,
            user_id=user_id,
            observaciones=f"Anulación OP {op.numero}: {motivo}",
            origen="orden_pago",
        )

        # Paso 3: CajaDocumento tipo anulada (solo para pagos con caja)
        tipo_doc_anulada_id = _lookup_tipo_documento_id(session, TIPO_DOC_ORDEN_PAGO_ANULADA)
        caja_svc.crear_documento(
            tipo_documento_id=tipo_doc_anulada_id,
            user_id=user_id,
            numero=f"{op.numero}-ANUL",
            descripcion=f"Anulación OP {op.numero}: {motivo}",
            fecha_documento=date.today(),
            monto_documento=monto_reverso_caja,
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


def crear_y_pagar(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: int,
    moneda: Moneda,
    monto_total: Decimal,
    modo_imputacion: ModoImputacion,
    items: list[dict],
    caja_id: Optional[int] = None,
    banco_id: Optional[int] = None,
    fecha_pago_real: date,
    observaciones: Optional[str] = None,
    creado_por_id: int,
    confirmar_duplicado: bool = False,
    tipo_cambio: Optional[Decimal] = None,
    fecha_pago_estimada: Optional[date] = None,
    actualizar_tc_pedido: bool = False,
    tipo_cambio_override: Optional[Decimal] = None,
    ncs_aplicadas: Optional[list[dict]] = None,
    cheques: Optional[list[dict]] = None,
) -> OrdenPago:
    """Crea y paga una OP en una única transacción atómica (F3, design §3.5, AD-10).

    Thin orchestrator: llama a `crear()` + `ejecutar_pago()` dentro de la
    MISMA sesión sin new business logic. El caller NO hace commit — si el
    paso de pago falla, cualquier excepción propaga normalmente y el caller
    debe hacer rollback para revertir TODA la operación (crear + pagar).

    F7: `ncs_aplicadas` se aplican DESPUÉS de `ejecutar_pago` (AD-3 / FR1.4)
    para garantizar que las imputaciones OP→pedido existen antes de que la NC
    las referencie. Si la aplicación de NC falla, todo (OP + pago + NCs) se
    revierte.

    Args:
        session: tx activa.
        proveedor_id, empresa_id, moneda, monto_total, modo_imputacion, items:
            mismos que `crear()`.
        caja_id: caja donde se registra el egreso (mutuamente excluyente con banco_id).
        banco_id: banco empresa donde se registra el egreso (mutuamente excluyente con caja_id).
        fecha_pago_real: fecha contable del pago.
        observaciones, creado_por_id, confirmar_duplicado, tipo_cambio,
            fecha_pago_estimada, actualizar_tc_pedido: mismos que `crear()`.
        tipo_cambio_override: sobrescribe `op.tipo_cambio` al pagar (sub-batch 2.2).
        ncs_aplicadas: lista de NCs a imputar DESPUÉS del pago (F7).

    Returns:
        La OP en estado `pagado`.

    Raises:
        HTTPException 400/404/409/422: cualquier error de validación de
            `crear()`, `ejecutar_pago()`, o de la aplicación de NCs.
            El caller debe hacer rollback.
    """
    # Paso 1: crear la OP (sin NCs — se aplican después del pago).
    op = crear(
        session,
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        moneda=moneda,
        monto_total=monto_total,
        modo_imputacion=modo_imputacion,
        items=items,
        observaciones=observaciones,
        creado_por_id=creado_por_id,
        confirmar_duplicado=confirmar_duplicado,
        tipo_cambio=tipo_cambio,
        fecha_pago_estimada=fecha_pago_estimada,
        actualizar_tc_pedido=actualizar_tc_pedido,
        # NOTE: ncs_aplicadas NO se pasa a crear() para mantener el orden correcto:
        # crear → ejecutar_pago → aplicar NCs (AD-3 / FR1.4).
    )

    # Paso 2: ejecutar el pago (crea imputaciones OP→pedido y mueve fondos).
    # Las NCs se aplican en el paso 3 (post-pago); el item del pedido ya viene
    # neto de NC/DAC, así que no se pasan al balance.
    op = ejecutar_pago(
        session,
        orden_pago_id=op.id,
        caja_id=caja_id,
        banco_id=banco_id,
        fecha_pago_real=fecha_pago_real,
        user_id=creado_por_id,
        tipo_cambio_override=tipo_cambio_override,
        cheques=cheques,
    )

    # Paso 3: aplicar NCs (DESPUÉS del pago, en la misma transacción).
    _aplicar_ncs_lista(
        session,
        op=op,
        ncs_aplicadas=ncs_aplicadas or [],
        creado_por_id=creado_por_id,
    )

    return op


def imputar_nc_a_pedido(
    session: Session,
    *,
    nc: Any,
    pedido: PedidoCompra,
    monto: Decimal,
    creado_por_id: int,
) -> "Imputacion":
    """Helper compartido F7: imputa una NC a un pedido de compra.

    Contiene las reglas contables comunes usadas tanto al CREAR una OP
    (ncs_aplicadas en crear/crear_y_pagar) como al APLICAR una NC desde
    el detalle de una OP ya creada (aplicar_nc_desde_op).

    Pasos (design §1.7 F7):
      2. Valida que NC.proveedor_id == pedido.proveedor_id (403).
      3. Valida estado NC en {'aprobado', 'aplicada_parcial'} (409 si
         ya aplicada, 422 para estados no aplicables).
      5. Valida estado pedido imputable; valida NC.moneda == pedido.moneda (422).
      6. Valida saldo disponible NC >= monto (422).
      7. Crea imputación NC→pedido_compra.
      8. HABER en CC proveedor.
      9. Recalcula estado del pedido.

    NOTE: La resolución del pedido (paso 4 en aplicar_nc_desde_op) es
    responsabilidad del caller, que ya resolvió qué pedido usar antes de
    llamar a este helper.

    Args:
        session: tx activa — NO hace commit.
        nc: instancia cargada de NotaCreditoLocal.
        pedido: instancia cargada de PedidoCompra.
        monto: monto a imputar (>0, validado por schema antes de llegar aquí).
        creado_por_id: FK a usuarios.

    Returns:
        La `Imputacion` creada.

    Raises:
        HTTPException 403: NC pertenece a proveedor distinto al del pedido.
        HTTPException 409: NC en estado `aplicada` (totalmente consumida).
        HTTPException 422: NC en estado no aplicable, monto excede saldo,
                           pedido en estado no imputable, cross-moneda NC↔pedido.
    """
    from app.services import cc_proveedor_service  # noqa: PLC0415
    from app.services import ncs_locales_service  # noqa: PLC0415

    # 2. Validar ownership proveedor.
    if nc.proveedor_id != pedido.proveedor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"La NC id={nc.id} pertenece al proveedor id={nc.proveedor_id}, "
                f"pero el pedido id={pedido.id} pertenece al proveedor id={pedido.proveedor_id}. "
                f"No se puede imputar."
            ),
        )

    # 3. Validar que la NC esté en estado aplicable.
    if nc.estado == "aplicada":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"NC local id={nc.id} ya fue completamente aplicada (estado='aplicada').",
        )
    if nc.estado not in {"aprobado", "aplicada_parcial"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"NC local id={nc.id} en estado '{nc.estado}' no puede aplicarse. "
                f"Estados válidos: 'aprobado', 'aplicada_parcial'."
            ),
        )

    # 5. Validar estado pedido imputable.
    if pedido.estado not in {"aprobado", "pagado_parcial"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Pedido id={pedido.id} en estado '{pedido.estado}' no admite imputación.",
        )

    # 5b. Validar coherencia de moneda NC↔pedido (cross-moneda prohibido en v1).
    if nc.moneda != pedido.moneda:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cross-moneda no soportado en v1. NC moneda: {nc.moneda}, pedido moneda: {pedido.moneda}.",
        )

    # 6. Validar saldo disponible NC >= monto.
    saldo_nc = ncs_locales_service.calcular_saldo_pendiente(session, nc.id)
    if monto > saldo_nc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"monto={monto} excede el saldo disponible de la NC id={nc.id} ({saldo_nc}).",
        )

    # 7. Crear imputación NC→pedido_compra.
    imp = imputaciones_service.crear_imputacion(
        session,
        origen_tipo="nota_credito_local",
        origen_id=nc.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        monto_imputado=monto,
        moneda_imputada=nc.moneda,  # type: ignore[arg-type]
        proveedor_id=nc.proveedor_id,
        creado_por_id=creado_por_id,
    )

    # 8. HABER en CC proveedor.
    cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp.id)

    # 9. Recalcular estado del pedido.
    pedidos_service.aplicar_imputacion_a_pedido(
        session,
        pedido_id=pedido.id,
        monto_imputado=Decimal("0"),
    )

    session.flush()
    session.refresh(nc)

    logger.info(
        "imputar_nc_a_pedido nc_id=%s pedido_id=%s monto=%s imputacion_id=%s nc_estado=%s",
        nc.id,
        pedido.id,
        monto,
        imp.id,
        nc.estado,
    )

    return imp


def aplicar_nc_desde_op(
    session: Session,
    *,
    op_id: int,
    nc_id: int,
    monto: Decimal,
    pedido_id: int | None,
    creado_por_id: int,
) -> dict:
    """F4 — Imputa una NC local directamente desde el detalle de una OP.

    Orquestación (design §2.4):
      1. Carga OP (404 si inexistente) y NC (404 si inexistente).
      2. Valida que NC.proveedor_id == OP.proveedor_id (AC4.3 → 403).
      3. Valida estado NC en {'aprobado', 'aplicada_parcial'} (AC4.4 → 409 si
         ya está totalmente aplicada, 422 para estados no aplicables).
      4. Resuelve pedido destino desde imputaciones activas OP→pedido_compra
         (AC4.5): un único pedido → infer; varios sin pedido_id → 422 con lista.
      5–9. Delega a `imputar_nc_a_pedido` (validaciones + creación imputación
           + HABER CC + recálculo pedido).

    Nota sobre concurrencia: esta función no toma FOR UPDATE sobre la NC ni el
    pedido, consistente con el patrón actual de `aplicar_nc_local` en el router.
    `imputaciones_service.crear_imputacion` valida el saldo NC al momento de
    escribir, mitigando (no eliminando) la ventana de race condition.

    Returns:
        dict con `imputacion_id` (int) y `nc_estado` (str) tras la operación.

    Raises:
        HTTPException 404: OP o NC no encontrada; pedido destino no encontrado.
        HTTPException 403: NC pertenece a proveedor distinto (AC4.3).
        HTTPException 409: NC en estado `aplicada` (totalmente consumida, AC4.4).
        HTTPException 422: NC en estado no aplicable (AC4.4), monto excede saldo
                          (AC4.2), cross-moneda NC↔pedido, OP sin pedidos
                          imputados, o múltiples pedidos sin pedido_id (AC4.5).
    """
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    # 1. Cargar OP y NC.
    op = session.get(OrdenPago, op_id)
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={op_id} no encontrada.",
        )

    nc = session.get(NotaCreditoLocal, nc_id)
    if nc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NotaCreditoLocal id={nc_id} no encontrada.",
        )

    # 2. Validar ownership proveedor contra la OP (AC4.3).
    #    El helper imputar_nc_a_pedido valida nc.proveedor_id == pedido.proveedor_id,
    #    pero aquí además queremos el mensaje específico de "NC vs OP".
    if nc.proveedor_id != op.proveedor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"La NC id={nc_id} pertenece al proveedor id={nc.proveedor_id}, "
                f"pero la OP id={op_id} pertenece al proveedor id={op.proveedor_id}. "
                f"No se puede aplicar."
            ),
        )

    # 4. Resolver pedido destino desde imputaciones activas de la OP (AC4.5).
    #    Solo imputaciones OP→pedido_compra no-reversal.
    stmt_pedidos = (
        select(Imputacion.destino_id)
        .where(
            Imputacion.origen_tipo == "orden_pago",
            Imputacion.origen_id == op_id,
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.es_reversal.is_(False),
            Imputacion.destino_id.is_not(None),
        )
        .distinct()
    )
    pedido_ids_op: list[int] = list(session.execute(stmt_pedidos).scalars().all())

    if not pedido_ids_op:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La OP id={op_id} no tiene imputaciones a pedidos de compra.",
        )

    if pedido_id is not None:
        # El caller especificó un pedido: validar que esté en la lista.
        if pedido_id not in pedido_ids_op:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"pedido_id={pedido_id} no está entre los pedidos imputados "
                    f"por la OP id={op_id}. Opciones: {sorted(pedido_ids_op)}."
                ),
            )
        target_pedido_id = pedido_id
    elif len(pedido_ids_op) == 1:
        target_pedido_id = pedido_ids_op[0]
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La OP id={op_id} tiene múltiples pedidos: especificar pedido_id. Opciones: {sorted(pedido_ids_op)}."
            ),
        )

    # Cargar pedido destino.
    pedido = session.get(PedidoCompra, target_pedido_id)
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido destino id={target_pedido_id} no encontrado.",
        )

    # Delegar pasos 2/3/5-9 al helper compartido.
    imp = imputar_nc_a_pedido(
        session,
        nc=nc,
        pedido=pedido,
        monto=monto,
        creado_por_id=creado_por_id,
    )

    logger.info(
        "aplicar_nc_desde_op op_id=%s nc_id=%s pedido_id=%s monto=%s imputacion_id=%s nc_estado=%s",
        op_id,
        nc_id,
        target_pedido_id,
        monto,
        imp.id,
        nc.estado,
    )

    return {"imputacion_id": imp.id, "nc_estado": nc.estado}


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
    "aplicar_nc_desde_op",
    "cancelar_pendiente",
    "imputar_nc_a_pedido",
    "crear",
    "crear_y_pagar",
    "detectar_duplicado_erp",
    "editar",
    "ejecutar_pago",
    "registrar_evento_auditoria",
]
