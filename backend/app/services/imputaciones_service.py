"""
imputaciones_service — operaciones base sobre la tabla `imputaciones`.

Esta tabla es **polimórfica** (design §1.4): `origen_tipo` y `destino_tipo`
son VARCHAR abiertos, pero la whitelist v1 limita las combinaciones a los
10 pares de `COMBOS_VALIDOS_V1`. Cross-moneda está prohibido (D3).

**Append-only** (D9): ni `desimputar` ni `reimputar` modifican filas
existentes — insertan filas con `es_reversal=True` y `reimputada_desde_id`
apuntando a la original. Esto preserva trazabilidad contable.

Esta F2 implementa sólo las funciones BASE:
  - `crear_imputacion`  — INSERT validando whitelist + moneda + monto.
  - `listar_por_origen` — lookup por origen.
  - `listar_por_destino` — lookup por destino.
  - `monto_imputado_total_al_destino` — suma neta para un destino/moneda.

`distribuir_fifo` y `reimputar` se implementan en F4 (COMPRAS-4.*).

Sin side-effects en CC: este servicio NO invoca `cc_proveedor_service`.
El caller (ordenes_pago_service en F4) es el que orquesta la transacción
completa.

Referencias:
  - design.md §2.2
  - tasks.md COMPRAS-2.3
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.imputacion import Imputacion

logger = get_logger("services.imputaciones_service")


# ──────────────────────────────────────────────────────────────────────────
# Whitelist v1 — los 10 combos permitidos (design §1.4 + Cierre post-spec)
# ──────────────────────────────────────────────────────────────────────────

COMBOS_VALIDOS_V1: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("orden_pago", "pedido_compra"),
        ("orden_pago", "factura_erp"),
        ("orden_pago", "saldo"),
        ("nota_credito_erp", "pedido_compra"),
        ("nota_credito_erp", "factura_erp"),
        ("nota_credito_erp", "saldo"),
        # Compras v2 — NCs locales como origen.
        # Semántica idéntica a NCs ERP: el HABER se proyecta a CC al imputar
        # (no al aprobar la NC) — análogo a OPs (no tocan caja al crearse).
        ("nota_credito_local", "pedido_compra"),
        ("nota_credito_local", "factura_erp"),
        ("nota_credito_local", "saldo"),
        # PR2 — dinero a cuenta como destino de OP (pago_a_cuenta crea DAC).
        # El HABER lo emite aplicar_imputacion (origen=orden_pago → CC haber).
        ("orden_pago", "dinero_a_cuenta"),
        # PR4 — dinero a cuenta como ORIGEN (consumo como medio de pago).
        # AD-4: aplicar_imputacion retorna [] para este origen (sin CC nuevo —
        # el haber ya entró al CC cuando se creó el DAC).
        ("dinero_a_cuenta", "pedido_compra"),
        ("dinero_a_cuenta", "factura_erp"),
        # Slice 1 cheques — cheque propio imputado a un pedido específico.
        # Espeja el camino de nota_credito_local: crear_imputacion → aplicar_imputacion
        # (CC haber) → aplicar_imputacion_a_pedido (recalcula estado pedido).
        ("cheque", "pedido_compra"),
    }
)


Moneda = Literal["ARS", "USD"]


# ──────────────────────────────────────────────────────────────────────────
# Validadores internos
# ──────────────────────────────────────────────────────────────────────────


def _validar_whitelist(origen_tipo: str, destino_tipo: str) -> None:
    """
    Valida que `(origen_tipo, destino_tipo)` esté en `COMBOS_VALIDOS_V1`.

    Raises:
        HTTPException 400: con detalle del combo inválido y de los combos
        permitidos (útil para debugging desde el frontend).
    """
    if (origen_tipo, destino_tipo) not in COMBOS_VALIDOS_V1:
        combos_ordenados = sorted(COMBOS_VALIDOS_V1)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Combinación origen/destino no soportada en v1: "
                f"('{origen_tipo}', '{destino_tipo}'). "
                f"Combos válidos: {combos_ordenados}"
            ),
        )


def _validar_moneda_consistente(
    origen_moneda: str,
    destino_moneda: str,
    tipo_cambio: Optional[Decimal] = None,
) -> None:
    """
    Valida coherencia de monedas entre origen y destino.

    - Same-moneda (origen == destino): siempre OK (tipo_cambio ignorado).
    - Cross-moneda (origen != destino): requiere `tipo_cambio > 0`; sin TC válido
      lanza 400.

    Raises:
        HTTPException 400 si cross-moneda sin TC > 0.
    """
    if origen_moneda == destino_moneda:
        return
    if tipo_cambio is None or Decimal(tipo_cambio) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cross-moneda requiere tipo_cambio > 0. "
                f"Origen: {origen_moneda}, destino: {destino_moneda}, TC recibido: {tipo_cambio}."
            ),
        )


def _validar_monto_positivo(monto: Decimal) -> None:
    if monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"monto_imputado debe ser > 0 (recibido: {monto}).",
        )


def _validar_saldo_destino_id(destino_tipo: str, destino_id: Optional[int]) -> None:
    """
    Enforce en aplicación la misma regla que el CHECK de la DB
    (chk_imputacion_saldo_id): si destino_tipo='saldo' entonces
    destino_id IS NULL; en caso contrario destino_id es requerido.
    """
    if destino_tipo == "saldo":
        if destino_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Con destino_tipo='saldo', destino_id debe ser NULL.",
            )
    else:
        if destino_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Con destino_tipo='{destino_tipo}', destino_id es requerido.",
            )


# ──────────────────────────────────────────────────────────────────────────
# Operaciones públicas
# ──────────────────────────────────────────────────────────────────────────


def crear_imputacion(
    session: Session,
    *,
    origen_tipo: str,
    origen_id: int,
    destino_tipo: str,
    destino_id: Optional[int],
    monto_imputado: Decimal,
    moneda_imputada: Moneda,
    proveedor_id: int,
    creado_por_id: int,
    tipo_cambio: Optional[Decimal] = None,
    es_reversal: bool = False,
    reimputada_desde_id: Optional[int] = None,
) -> Imputacion:
    """
    Inserta una fila en `imputaciones` validando:
      - `(origen_tipo, destino_tipo)` ∈ COMBOS_VALIDOS_V1.
      - `monto_imputado > 0`.
      - `moneda_imputada ∈ {'ARS','USD'}` (nominal — Literal en el signature).
      - Coherencia `destino_tipo='saldo' <=> destino_id IS NULL`.

    NO dispara side-effects en CC. El caller (p. ej. `ejecutar_pago` en F4)
    es responsable de invocar `cc_proveedor_service.aplicar_imputacion`
    dentro de la misma transacción.

    Args:
        session: sesión SQLAlchemy.
        origen_tipo: uno de los tipos del lado "izquierdo" de los combos.
        origen_id: ID polimórfico del origen (p. ej. `orden_pago.id`).
        destino_tipo: uno de los tipos del lado "derecho".
        destino_id: ID polimórfico del destino. `None` solo si destino='saldo'.
        monto_imputado: monto > 0.
        moneda_imputada: 'ARS' o 'USD'. En cross-moneda (origen ≠ destino) DEBE
            coincidir con la moneda del destino — el caller convierte el monto
            usando `tipo_cambio` antes de invocar este método.
        proveedor_id: FK a `proveedores`.
        creado_por_id: FK a `usuarios`.
        tipo_cambio: TC origen↔destino. Obligatorio cuando origen.moneda ≠
            destino.moneda; opcional (y típicamente `None`) cuando coinciden.
        es_reversal: si es True, apunta a una imputación previa.
        reimputada_desde_id: id de la imputación original que esta reimputa
            (sólo seteado por `reimputar` en F4).

    Returns:
        La instancia `Imputacion` recién insertada (con `id` asignado tras
        `flush`).

    Raises:
        HTTPException 400: por cualquiera de las validaciones.
    """
    _validar_whitelist(origen_tipo, destino_tipo)
    _validar_monto_positivo(monto_imputado)
    _validar_saldo_destino_id(destino_tipo, destino_id)

    # La moneda del destino sólo se puede verificar si el caller la provee
    # por separado. A este nivel confiamos en que el caller haya validado
    # moneda + TC antes (vía `_validar_moneda_consistente`, que ahora admite
    # cross-moneda cuando viene `tipo_cambio > 0`).

    # Validación específica para origen NCs locales (v2):
    #   - La NC origen debe existir y estar en estado 'aprobado' o 'aplicada_parcial'.
    #   - El monto imputado no puede superar el saldo pendiente de la NC.
    # No aplicamos esta validación a reversals (los reversals nunca crean
    # imputaciones nuevas más allá del saldo previo — el saldo lo administra
    # el caller del reversal).
    if origen_tipo == "nota_credito_local" and not es_reversal:
        _validar_origen_nc_local_disponible(
            session,
            nc_id=origen_id,
            monto_imputado=monto_imputado,
        )

    imp = Imputacion(
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        destino_tipo=destino_tipo,
        destino_id=destino_id,
        monto_imputado=monto_imputado,
        moneda_imputada=moneda_imputada,
        tipo_cambio=tipo_cambio,
        proveedor_id=proveedor_id,
        es_reversal=es_reversal,
        reimputada_desde_id=reimputada_desde_id,
        creado_por_id=creado_por_id,
    )
    session.add(imp)
    session.flush()

    # Side effect post-creación para origen NCs locales (no-reversal):
    # actualizar el estado de la NC vía `ncs_locales_service.aplicar_imputacion_a_nc`
    # (aprobado → aplicada_parcial → aplicada según el saldo restante).
    if origen_tipo == "nota_credito_local" and not es_reversal:
        from app.services import ncs_locales_service  # noqa: PLC0415

        ncs_locales_service.aplicar_imputacion_a_nc(
            session,
            nc_id=origen_id,
            monto_imputado=monto_imputado,
        )

    logger.info(
        "imputacion_creada id=%s origen=%s:%s destino=%s:%s monto=%s %s reversal=%s proveedor_id=%s",
        imp.id,
        origen_tipo,
        origen_id,
        destino_tipo,
        destino_id,
        monto_imputado,
        moneda_imputada,
        es_reversal,
        proveedor_id,
    )
    return imp


def _validar_origen_nc_local_disponible(
    session: Session,
    *,
    nc_id: int,
    monto_imputado: Decimal,
) -> None:
    """
    Valida que la NC local esté en un estado que permita ser origen de una
    imputación y que el monto no exceda el saldo pendiente.

    Estados válidos: 'aprobado', 'aplicada_parcial'.

    Raises:
        HTTPException 404: NC inexistente.
        HTTPException 409: NC en estado no aplicable (borrador, pendiente,
            rechazado, cancelado, aplicada).
        HTTPException 400: monto_imputado supera el saldo pendiente.
    """
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    nc = session.get(NotaCreditoLocal, nc_id)
    if nc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NotaCreditoLocal id={nc_id} no encontrada (origen de imputación).",
        )
    if nc.estado not in {"aprobado", "aplicada_parcial"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"NC local id={nc_id} en estado '{nc.estado}' no puede ser origen de "
                f"imputación. Estados válidos: 'aprobado', 'aplicada_parcial'."
            ),
        )

    # Calcular saldo pendiente: monto - SUM(imputaciones no-reversal de esta NC)
    # + SUM(imputaciones reversal). Reusamos la query inline para evitar import
    # circular con ncs_locales_service.
    imputado_no_reversal = session.execute(
        select(func.coalesce(func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.origen_id == nc_id,
            Imputacion.es_reversal.is_(False),
        )
    ).scalar_one()
    imputado_reversal = session.execute(
        select(func.coalesce(func.sum(Imputacion.monto_imputado), 0)).where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.origen_id == nc_id,
            Imputacion.es_reversal.is_(True),
        )
    ).scalar_one()
    imputado_efectivo = Decimal(imputado_no_reversal) - Decimal(imputado_reversal)
    saldo_pendiente = Decimal(nc.monto) - imputado_efectivo

    if monto_imputado > saldo_pendiente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"monto_imputado={monto_imputado} excede el saldo pendiente "
                f"({saldo_pendiente}) de la NC local id={nc_id} "
                f"(monto={nc.monto}, ya imputado={imputado_efectivo})."
            ),
        )


def revertir_imputaciones_de_origen(
    session: Session,
    *,
    origen_tipo: str,
    origen_id: int,
    user_id: int,
    motivo: str,
) -> list[Imputacion]:
    """
    Genera reversals (`es_reversal=True`) para todas las imputaciones activas
    no-reversal de un origen específico.

    Casos de uso:
      - Cancelar una NC local aprobada que ya tiene imputaciones aplicadas.
      - (Futuro) Anular una OP — hoy `ordenes_pago_service.anular` duplica
        este patrón inline; refactor diferido para no expandir el scope de
        este batch.

    Append-only: los reversals son INSERTs nuevos con `es_reversal=True` y
    `reimputada_desde_id = imp_original.id`. NUNCA se hace UPDATE de las
    imputaciones existentes.

    Para cada reversal:
      - Se invoca `cc_proveedor_service.aplicar_imputacion` que crea el
        movimiento `debe` compensatorio en CC.
      - Si la imputación original tenía destino `pedido_compra`, el caller
        debería luego invocar `pedidos_service.aplicar_imputacion_a_pedido`
        sobre cada pedido afectado para recalcular su estado (al estilo del
        flujo de `ordenes_pago_service.anular`).

    NO commitea — responsabilidad del caller.

    Args:
        session: tx activa.
        origen_tipo: 'nota_credito_local' | 'orden_pago' | 'nota_credito_erp'.
        origen_id: PK del documento origen.
        user_id: usuario que ejecuta la cancelación/anulación (auditoría).
        motivo: texto libre, se loggea (no se persiste en `imputaciones`).

    Returns:
        Lista de imputaciones-reversal creadas. Vacía si no había imputaciones
        activas.
    """
    stmt = select(Imputacion).where(
        Imputacion.origen_tipo == origen_tipo,
        Imputacion.origen_id == origen_id,
        Imputacion.es_reversal.is_(False),
    )
    activas = list(session.execute(stmt).scalars().all())

    reversals: list[Imputacion] = []
    for imp in activas:
        # Saltear si esta imputación ya fue desimputada/reimputada previamente
        # (ya hay otra fila con reimputada_desde_id=imp.id).
        ya_desimputada = session.execute(
            select(Imputacion.id).where(Imputacion.reimputada_desde_id == imp.id).limit(1)
        ).first()
        if ya_desimputada:
            continue
        reversal = desimputar(
            session,
            imputacion_id=imp.id,
            user_id=user_id,
            motivo=motivo,
        )
        reversals.append(reversal)

    logger.info(
        "revertir_imputaciones_de_origen origen=%s:%s reversals_creados=%d motivo=%s",
        origen_tipo,
        origen_id,
        len(reversals),
        motivo,
    )
    return reversals


def distribuir_fifo(
    session: Session,
    *,
    orden_pago_id: int,
    user_id: int,
) -> list[Imputacion]:
    """
    Distribución FIFO de una OP `a_cuenta` sobre las deudas pendientes del
    proveedor (COMPRAS-4.4 / design §2.2).

    Semántica:
      - Lista las deudas pendientes ordenadas por `created_at ASC`:
          (a) Pedidos de compra en estados `aprobado` / `pagado_parcial`
              del mismo proveedor y **misma moneda que la OP**, con saldo
              pendiente (monto - sum(imputaciones no-reversal al pedido)).
          (b) Facturas ERP vigentes (desde `v_facturas_compra_vigentes`)
              del mismo proveedor y misma moneda, sin imputación previa.
      - Aplica el monto de la OP a cada deuda en orden.
      - Si sobra remanente → crea imputación `(orden_pago, saldo)` por el
        excedente.
      - Cada imputación dispara `cc_proveedor_service.aplicar_imputacion`.

    Args:
        session: tx activa.
        orden_pago_id: PK de la OP a distribuir. Debe ser `modo='a_cuenta'`
            y estar en estado `pendiente` (validación del caller).
        user_id: usuario que ejecuta la distribución.

    Returns:
        Lista de imputaciones creadas en orden de aplicación.

    Raises:
        ValueError: si `orden_pago_id` no existe.
    """
    # Imports locales para evitar ciclos (orden_pago_service importa este módulo).
    from app.models.orden_pago import OrdenPago  # noqa: PLC0415
    from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415
    from app.services import cc_proveedor_service  # noqa: PLC0415

    op = session.get(OrdenPago, orden_pago_id)
    if op is None:
        raise ValueError(f"orden_pago_id={orden_pago_id} no existe.")

    remanente = Decimal(op.monto_total)
    creadas: list[Imputacion] = []

    # (a) Pedidos aprobados / pagado_parcial del mismo proveedor + moneda
    stmt_pedidos = (
        select(PedidoCompra)
        .where(
            PedidoCompra.proveedor_id == op.proveedor_id,
            PedidoCompra.moneda == op.moneda,
            PedidoCompra.estado.in_(["aprobado", "pagado_parcial"]),
        )
        .order_by(PedidoCompra.created_at.asc(), PedidoCompra.id.asc())
    )
    pedidos_pendientes = list(session.execute(stmt_pedidos).scalars().all())

    for pedido in pedidos_pendientes:
        if remanente <= Decimal("0"):
            break
        imputado = monto_imputado_total_al_destino(
            session,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            moneda=op.moneda,  # type: ignore[arg-type]
        )
        saldo_pendiente = Decimal(pedido.monto) - imputado
        if saldo_pendiente <= Decimal("0"):
            continue

        aplicar = min(saldo_pendiente, remanente)
        imp = crear_imputacion(
            session,
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=aplicar,
            moneda_imputada=op.moneda,  # type: ignore[arg-type]
            proveedor_id=op.proveedor_id,
            creado_por_id=user_id,
        )
        cc_proveedor_service.aplicar_imputacion(session, imputacion_id=imp.id)
        creadas.append(imp)
        remanente -= aplicar

    # (b) Facturas ERP vigentes sin imputación previa (mismo proveedor+moneda).
    #     En v1 no tenemos monto en la vista por moneda ARS/USD unificada
    #     (la vista trae ct_total sin distinción de moneda local). Usamos
    #     ct_total con curr_id_transaction para filtrar. Simplificación v1:
    #     si el FIFO no cubre con pedidos, y todavía sobra remanente, se
    #     registra como saldo a cuenta (punto c). La distribución a factura
    #     ERP quedará como refinement futuro cuando haya la columna moneda.
    #
    # TODO(F4+): aplicar a facturas ERP vigentes una vez definida la política
    # de moneda local en la vista (RD6 del design §11).

    # (c) Remanente → saldo a cuenta
    if remanente > Decimal("0"):
        imp_saldo = crear_imputacion(
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
        creadas.append(imp_saldo)

    logger.info(
        "distribuir_fifo op_id=%s: %d imputaciones creadas (pedidos=%d, saldo_remanente=%s)",
        op.id,
        len(creadas),
        len(creadas) - (1 if remanente > 0 else 0),
        "si" if remanente > 0 else "no",
    )
    return creadas


def desimputar(
    session: Session,
    *,
    imputacion_id: int,
    user_id: int,
    motivo: Optional[str] = None,
) -> Imputacion:
    """
    Genera un reversal de una imputación existente (append-only, D9).

    Inserta una nueva fila en `imputaciones` con:
      - `es_reversal=True`
      - mismo origen/destino/monto/moneda/proveedor que la original
      - `reimputada_desde_id = imputacion_id`
      - `creado_por_id = user_id`

    Dispara `cc_proveedor_service.aplicar_imputacion` que registrará un
    `debe` en CC compensando el `haber` original.

    Args:
        session: tx activa.
        imputacion_id: PK de la imputación a desimputar.
        user_id: FK a usuarios.
        motivo: texto opcional — no se persiste en `imputaciones` (append
            only, no hay columna). Se puede guardar como evento del caller
            (OP o pedido) en `compras_eventos`.

    Returns:
        La imputación-reversal recién creada.

    Raises:
        ValueError: si `imputacion_id` no existe.
        HTTPException 400: si la imputación a desimputar ya es un reversal
            (no se desimputa un reversal — el append-only debe ser lineal).
    """
    from app.services import cc_proveedor_service  # noqa: PLC0415

    original = session.get(Imputacion, imputacion_id)
    if original is None:
        raise ValueError(f"imputacion_id={imputacion_id} no existe.")
    if original.es_reversal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"No se puede desimputar un reversal (imputacion_id={imputacion_id} ya tiene es_reversal=True)."),
        )

    reversal = crear_imputacion(
        session,
        origen_tipo=original.origen_tipo,
        origen_id=original.origen_id,
        destino_tipo=original.destino_tipo,
        destino_id=original.destino_id,
        monto_imputado=original.monto_imputado,
        moneda_imputada=original.moneda_imputada,  # type: ignore[arg-type]
        proveedor_id=original.proveedor_id,
        creado_por_id=user_id,
        tipo_cambio=original.tipo_cambio,
        es_reversal=True,
        reimputada_desde_id=original.id,
    )
    cc_proveedor_service.aplicar_imputacion(session, imputacion_id=reversal.id)

    # Si la imputación original era de origen NC local, recalcular el estado
    # de la NC: al revertir, el saldo pendiente sube → la NC puede pasar
    # de 'aplicada' a 'aplicada_parcial', o de 'aplicada_parcial' a 'aprobado'.
    if original.origen_tipo == "nota_credito_local":
        from app.services import ncs_locales_service  # noqa: PLC0415

        ncs_locales_service.recalcular_estado_por_imputaciones(
            session,
            nc_id=int(original.origen_id),
        )

    # Si la imputación original tenía destino `pedido_compra`, recalcular el
    # estado del pedido. Al revertir, el saldo pendiente sube → el pedido
    # puede pasar de 'pagado' a 'pagado_parcial' o 'aprobado', o de
    # 'pagado_parcial' a 'aprobado'. Sin este recálculo, desimputar aislado
    # dejaba el pedido en un estado inconsistente con su saldo contable.
    if original.destino_tipo == "pedido_compra" and original.destino_id is not None:
        from app.services import pedidos_service  # noqa: PLC0415

        pedidos_service.recalcular_estado_por_imputaciones(
            session,
            pedido_id=int(original.destino_id),
        )

    logger.info(
        "desimputar: imputacion_original_id=%s → reversal_id=%s (motivo=%s)",
        original.id,
        reversal.id,
        motivo,
    )
    return reversal


def reimputar(
    session: Session,
    *,
    imputacion_id: int,
    nuevo_destino_tipo: str,
    nuevo_destino_id: Optional[int],
    user_id: int,
) -> tuple[Imputacion, Imputacion]:
    """
    Reimputa una imputación a un nuevo destino (append-only, D9 + D13).

    Inserta DOS filas en la misma transacción:
      (a) Reversal de la original (es_reversal=True, destino = el original).
      (b) Nueva imputación con destino nuevo (es_reversal=False).

    Ambas con `reimputada_desde_id = imputacion_id`. El efecto contable
    neto sobre el proveedor es cero (debe al destino viejo + haber al
    nuevo), pero el destino efectivo cambia.

    D13: PROHIBIDO reimputar una imputación que ya fue reimputada
    (`reimputada_desde_id IS NOT NULL` o `es_reversal=True`). El histórico
    debe ser una cadena plana, no un árbol.

    Args:
        session: tx activa.
        imputacion_id: PK de la imputación original.
        nuevo_destino_tipo: nuevo destino (debe formar combo válido).
        nuevo_destino_id: PK del nuevo destino (None solo si 'saldo').
        user_id: usuario que ejecuta la acción.

    Returns:
        `(reversal, nueva)` — el reversal de la original y la nueva
        imputación con el destino nuevo.

    Raises:
        ValueError: si `imputacion_id` no existe.
        HTTPException 400: si la imputación ya fue reimputada o ya es
            reversal (D13), o si el nuevo combo no es válido.
    """
    from app.services import cc_proveedor_service  # noqa: PLC0415

    original = session.get(Imputacion, imputacion_id)
    if original is None:
        raise ValueError(f"imputacion_id={imputacion_id} no existe.")

    if original.es_reversal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede reimputar un reversal (imputacion_id={imputacion_id}).",
        )
    if original.reimputada_desde_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"imputacion_id={imputacion_id} ya fue reimputada desde "
                f"{original.reimputada_desde_id}. D13: reimputación en cadena prohibida."
            ),
        )

    # También: si YA existe un reversal apuntando a esta imputación, no
    # permitimos reimputar tampoco (el origen ya fue "consumido" por
    # desimputar/reimputar previos).
    ya_reimputada = session.execute(
        select(func.count(Imputacion.id)).where(
            Imputacion.reimputada_desde_id == imputacion_id,
        )
    ).scalar_one()
    if ya_reimputada > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"imputacion_id={imputacion_id} ya tiene {ya_reimputada} "
                f"fila(s) que apuntan a ella (desimputada/reimputada). "
                f"D13: no se permite reimputar más de una vez."
            ),
        )

    # Validar el nuevo combo
    _validar_whitelist(original.origen_tipo, nuevo_destino_tipo)
    _validar_saldo_destino_id(nuevo_destino_tipo, nuevo_destino_id)

    # (a) Reversal de la original — mismo destino que la original
    reversal = crear_imputacion(
        session,
        origen_tipo=original.origen_tipo,
        origen_id=original.origen_id,
        destino_tipo=original.destino_tipo,
        destino_id=original.destino_id,
        monto_imputado=original.monto_imputado,
        moneda_imputada=original.moneda_imputada,  # type: ignore[arg-type]
        proveedor_id=original.proveedor_id,
        creado_por_id=user_id,
        tipo_cambio=original.tipo_cambio,
        es_reversal=True,
        reimputada_desde_id=original.id,
    )
    cc_proveedor_service.aplicar_imputacion(session, imputacion_id=reversal.id)

    # (b) Nueva imputación con destino nuevo
    nueva = crear_imputacion(
        session,
        origen_tipo=original.origen_tipo,
        origen_id=original.origen_id,
        destino_tipo=nuevo_destino_tipo,
        destino_id=nuevo_destino_id,
        monto_imputado=original.monto_imputado,
        moneda_imputada=original.moneda_imputada,  # type: ignore[arg-type]
        proveedor_id=original.proveedor_id,
        creado_por_id=user_id,
        tipo_cambio=original.tipo_cambio,
        es_reversal=False,
        reimputada_desde_id=original.id,
    )
    cc_proveedor_service.aplicar_imputacion(session, imputacion_id=nueva.id)

    logger.info(
        "reimputar: original_id=%s → reversal_id=%s + nueva_id=%s (destino %s:%s → %s:%s)",
        original.id,
        reversal.id,
        nueva.id,
        original.destino_tipo,
        original.destino_id,
        nuevo_destino_tipo,
        nuevo_destino_id,
    )
    return reversal, nueva


def listar_por_origen(
    session: Session,
    *,
    origen_tipo: str,
    origen_id: int,
) -> list[Imputacion]:
    """
    Retorna todas las imputaciones (incluyendo reversals) originadas por
    `(origen_tipo, origen_id)`, ordenadas por `created_at ASC`.
    """
    stmt = (
        select(Imputacion)
        .where(
            Imputacion.origen_tipo == origen_tipo,
            Imputacion.origen_id == origen_id,
        )
        .order_by(Imputacion.created_at.asc(), Imputacion.id.asc())
    )
    return list(session.execute(stmt).scalars().all())


def listar_por_destino(
    session: Session,
    *,
    destino_tipo: str,
    destino_id: int,
) -> list[Imputacion]:
    """
    Retorna todas las imputaciones (incluyendo reversals) que apuntan a
    `(destino_tipo, destino_id)`, ordenadas por `created_at ASC`.
    """
    stmt = (
        select(Imputacion)
        .where(
            Imputacion.destino_tipo == destino_tipo,
            Imputacion.destino_id == destino_id,
        )
        .order_by(Imputacion.created_at.asc(), Imputacion.id.asc())
    )
    return list(session.execute(stmt).scalars().all())


def monto_imputado_total_al_destino(
    session: Session,
    *,
    destino_tipo: str,
    destino_id: int,
    moneda: Moneda,
) -> Decimal:
    """
    Suma el `monto_imputado` de las imputaciones no-reversal hacia
    `(destino_tipo, destino_id)` en la `moneda` indicada.

    Por qué excluimos reversals:
      - Las imputaciones son append-only. Un reversal no "deshace" la
        imputación — la compensación se ve en el libro mayor (CC) con el
        movimiento opuesto, no acá. Para saber "cuánto tiene imputado este
        destino efectivamente" se cuentan únicamente las imputaciones vivas
        (es_reversal=False) y luego, si se reimputó, la nueva imputación
        (también es_reversal=False) ya suma en su nuevo destino.

    Returns:
        Decimal total (>= 0). Si no hay imputaciones, retorna Decimal('0').
    """
    stmt = select(func.coalesce(func.sum(Imputacion.monto_imputado), 0)).where(
        Imputacion.destino_tipo == destino_tipo,
        Imputacion.destino_id == destino_id,
        Imputacion.moneda_imputada == moneda,
        Imputacion.es_reversal.is_(False),
    )
    total = session.execute(stmt).scalar_one()
    return Decimal(total) if not isinstance(total, Decimal) else total


__all__ = [
    "COMBOS_VALIDOS_V1",
    "Moneda",
    "crear_imputacion",
    "desimputar",
    "distribuir_fifo",
    "listar_por_destino",
    "listar_por_origen",
    "monto_imputado_total_al_destino",
    "reimputar",
    "revertir_imputaciones_de_origen",
]
