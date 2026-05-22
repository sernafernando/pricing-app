"""
cc_proveedor_service — operaciones base sobre `cc_proveedor_movimientos`.

Libro mayor append-only de la cuenta corriente con proveedores (design §1.5).
Cada movimiento guarda moneda original + TC a ARS vigente al momento del
movimiento (estrategia multi-moneda C del design — moneda original es la
fuente de verdad, ARS es proyección para comparar).

F2 cubre:
  - `insertar_mov`           — INSERT con validaciones + resolución de TC.
  - `calcular_saldo_por_moneda` — saldo neto por moneda.
  - `listar_movimientos`     — listado con filtros.

`aplicar_imputacion` (disparado desde imputaciones_service) va en F4.
`reconciliar_diario` (cron diario vs snapshot ERP) va en F3 (COMPRAS-3.6).

Responsabilidad del caller:
  - Apertura/cierre de transacción.
  - Invocar al service dentro de la misma tx que el origen (OP, imputación,
    etc.) para que rollbackee consistentemente si falla.

Referencias:
  - design.md §2.4
  - tasks.md COMPRAS-2.4
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, select, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.cc_reconciliacion_log import CCReconciliacionLog
from app.models.imputacion import Imputacion
from app.models.tipo_cambio import TipoCambio

if TYPE_CHECKING:
    from app.models.pedido_compra import PedidoCompra

logger = get_logger("services.cc_proveedor_service")


TipoMovimiento = Literal["debe", "haber", "ajuste"]
Moneda = Literal["ARS", "USD"]


# Nombre canónico de la moneda USD en la tabla `tipo_cambio`. El modelo
# actual guarda `moneda=VARCHAR(10)`; ajustar acá si en producción se usa
# otro literal (p. ej. "DOLAR").
_TC_MONEDA_USD: Final[str] = "USD"


# ──────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────


def _resolver_tipo_cambio_a_ars(
    session: Session,
    *,
    moneda: str,
    fecha_movimiento: date,
) -> Optional[Decimal]:
    """
    Resuelve el TC a ARS vigente al `fecha_movimiento` para `moneda`.

    Patrón estándar del proyecto:
        `SELECT venta FROM tipo_cambio
         WHERE moneda = :moneda AND fecha <= :fecha
         ORDER BY fecha DESC LIMIT 1`

    Reglas:
      - Si `moneda == 'ARS'` → retorna `Decimal('1')` (TC trivial).
      - Si `moneda == 'USD'` → busca en `tipo_cambio`. Si no hay fila
        previa al `fecha_movimiento` → retorna `None` con log WARNING
        (no bloquea la inserción; la auditoría de TC se hace en el cron).

    Returns:
        `Decimal` del TC a ARS, `None` si no se encuentra.
    """
    if moneda == "ARS":
        return Decimal("1")

    stmt = (
        select(TipoCambio.venta)
        .where(
            TipoCambio.moneda == _TC_MONEDA_USD,
            TipoCambio.fecha <= fecha_movimiento,
        )
        .order_by(TipoCambio.fecha.desc())
        .limit(1)
    )
    venta = session.execute(stmt).scalar_one_or_none()
    if venta is None:
        logger.warning(
            "No hay tipo_cambio para moneda=%s en fecha<=%s — mov se registra sin TC.",
            moneda,
            fecha_movimiento,
        )
        return None

    # El modelo guarda `venta` como Float — convertimos a Decimal para
    # evitar arrastrar floats en cálculos financieros.
    return Decimal(str(venta))


def _validar_entrada_mov(
    *,
    tipo: str,
    monto: Decimal,
    moneda: str,
    signo_ajuste: Optional[int],
) -> None:
    if tipo not in {"debe", "haber", "ajuste"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"tipo inválido: '{tipo}'. Valores: 'debe', 'haber', 'ajuste'.",
        )
    if moneda not in {"ARS", "USD"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"moneda inválida: '{moneda}'. Valores: 'ARS', 'USD'.",
        )
    if monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"monto debe ser > 0 (recibido: {monto}).",
        )

    if tipo == "ajuste":
        if signo_ajuste not in {1, -1}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"tipo='ajuste' requiere signo_ajuste ∈ {{+1, -1}} (recibido: {signo_ajuste})."),
            )
    else:
        if signo_ajuste is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="signo_ajuste solo se setea cuando tipo='ajuste'.",
            )


# ──────────────────────────────────────────────────────────────────────────
# Operaciones públicas
# ──────────────────────────────────────────────────────────────────────────


def insertar_mov(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: int,
    fecha_movimiento: date,
    tipo: TipoMovimiento,
    monto: Decimal,
    moneda: Moneda,
    origen_tipo: str,
    origen_id: Optional[int],
    descripcion: Optional[str] = None,
    creado_por_id: Optional[int] = None,
    signo_ajuste: Optional[int] = None,
) -> CCProveedorMovimiento:
    """
    Inserta un movimiento en `cc_proveedor_movimientos`.

    Resuelve `tipo_cambio_a_ars` automáticamente con el patrón estándar
    `fecha <= fecha_movimiento ORDER BY fecha DESC LIMIT 1`.

    Validaciones (espejo de los CHECK de la DB):
      - `tipo ∈ {'debe','haber','ajuste'}`.
      - `moneda ∈ {'ARS','USD'}`.
      - `monto > 0`.
      - Si `tipo='ajuste'` → `signo_ajuste ∈ {+1, -1}` (requerido).
      - Si `tipo!='ajuste'` → `signo_ajuste` debe ser None.

    Args:
        session: sesión SQLAlchemy (tx del caller).
        proveedor_id: FK a proveedores.
        empresa_id: FK a empresas.
        fecha_movimiento: fecha contable del movimiento.
        tipo: 'debe' (incrementa deuda), 'haber' (paga), 'ajuste'
            (correccion con signo explícito).
        monto: siempre positivo; el tipo define la dirección.
        moneda: 'ARS' o 'USD'.
        origen_tipo: string libre (p. ej. 'orden_pago', 'imputacion',
            'factura_erp', 'ajuste_manual').
        origen_id: ID polimórfico del origen (opcional para ajustes manuales).
        descripcion: texto libre opcional (máx 500 chars en DB).
        creado_por_id: FK a usuarios (nullable).
        signo_ajuste: requerido solo si tipo='ajuste'.

    Returns:
        El `CCProveedorMovimiento` recién insertado con `id` asignado.

    Raises:
        HTTPException 400 por cualquiera de las validaciones.
    """
    _validar_entrada_mov(
        tipo=tipo,
        monto=monto,
        moneda=moneda,
        signo_ajuste=signo_ajuste,
    )

    tipo_cambio_a_ars = _resolver_tipo_cambio_a_ars(
        session,
        moneda=moneda,
        fecha_movimiento=fecha_movimiento,
    )

    mov = CCProveedorMovimiento(
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        fecha_movimiento=fecha_movimiento,
        tipo=tipo,
        signo_ajuste=signo_ajuste,
        monto=monto,
        moneda=moneda,
        tipo_cambio_a_ars=tipo_cambio_a_ars,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        descripcion=descripcion,
        creado_por_id=creado_por_id,
    )
    session.add(mov)
    session.flush()

    logger.info(
        "cc_mov_creado id=%s proveedor_id=%s empresa_id=%s tipo=%s monto=%s %s origen=%s:%s",
        mov.id,
        proveedor_id,
        empresa_id,
        tipo,
        monto,
        moneda,
        origen_tipo,
        origen_id,
    )
    return mov


def _resolver_tipo_nc_local(session: Session, origen_id: int, context: str) -> str:
    """F2 — Resolve the tipo ('credito'|'debito') of a NotaCreditoLocal by PK.

    Returns 'credito' as safe fallback and emits a warning when the NC is missing
    (should not happen in a healthy DB but guards against data-integrity failures).

    Args:
        session: active ORM session.
        origen_id: PK of the NotaCreditoLocal to look up.
        context: descriptive string for the warning message (e.g. 'reversal').
    """
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    nc = session.get(NotaCreditoLocal, origen_id)
    if nc is None:
        logger.warning(
            "aplicar_imputacion %s: NotaCreditoLocal id=%s no encontrada; "
            "asumiendo tipo='credito' para determinar dirección CC.",
            context,
            origen_id,
        )
        return "credito"
    return nc.tipo


def aplicar_imputacion(
    session: Session,
    *,
    imputacion_id: int,
) -> list[CCProveedorMovimiento]:
    """
    Genera los movimientos de CC derivados de una imputación (F4 — COMPRAS-4.7).

    La tabla `imputaciones` es append-only (D9). `aplicar_imputacion` es
    el **único** lugar donde las imputaciones se proyectan al libro mayor
    de cuenta corriente. Lo invoca `imputaciones_service` (vía el caller
    orquestador — típicamente `ordenes_pago_service.ejecutar_pago`) dentro
    de la misma transacción que crea la imputación.

    Semántica contable (design §2.4):
      - **Imputación normal** (`es_reversal=False`):
          - origen `'orden_pago'`         → `haber` (pagamos al proveedor, baja la deuda).
          - origen `'nota_credito_erp'`   → `haber` (la NC reduce la deuda).
      - **Imputación reversal** (`es_reversal=True`):
          - `debe` en el destino del reversal (se anula el efecto anterior
            del pago/NC). Origen contable registrado como `'reimputacion'`
            para distinguir de imputaciones primarias al agrupar.

    Cross-moneda (compras-cross-moneda-y-ncs-cc, FR-002):
        El movimiento CC se proyecta SIEMPRE en `imp.moneda_imputada`, que
        en cross-moneda equivale a la **moneda destino** (la del pedido),
        NO a la moneda origen (la de la OP). Ejemplo:
          - OP ARS paga pedido USD por 1.000 USD (1.500.000 ARS / TC 1500).
          - `imp.moneda_imputada = 'USD'`, `imp.monto_imputado = 1000`.
          - `aplicar_imputacion` emite un HABER de 1.000 USD en el CC.
          - El egreso real de plata (1.500.000 ARS) queda registrado en
            `caja_movimientos` (NO en CC).
        Resultado: cada moneda del CC del proveedor cuadra de forma
        independiente — el USD se cancela en USD, el ARS se cancela en
        ARS. La conversión OP↔pedido vive en la imputación
        (`monto_imputado` + `tipo_cambio`) y en el documento de caja.

    Nota: para imputaciones a `destino='saldo'` (saldo a cuenta del
    proveedor) NO se emite movimiento CC — el saldo a cuenta es una
    anticipación que todavía no se aplicó a una deuda concreta. Se proyecta
    a CC cuando se reimputa a `pedido_compra` o `factura_erp`. v1 difiere
    esta política: el `haber` se registra igual porque el proveedor recibió
    el dinero (el saldo a cuenta del lado propio queda visible en el
    listado de imputaciones). Ver design §2.4 y RD3.

    Args:
        session: tx activa del caller.
        imputacion_id: PK de la imputación ya insertada en la tx.

    Returns:
        Lista de `CCProveedorMovimiento` creados. Normalmente es 1 fila.
        Si la imputación es a `destino='saldo'` y se decide NO proyectar,
        puede ser `[]` (ver notas arriba — v1 siempre emite 1).

    Raises:
        ValueError: si `imputacion_id` no existe.
        HTTPException 400: si el `origen_tipo` de la imputación no tiene
            política de proyección definida (combo fuera de whitelist —
            defensa en profundidad).
    """
    imp = session.get(Imputacion, imputacion_id)
    if imp is None:
        raise ValueError(f"imputacion_id={imputacion_id} no existe.")

    # Determinar dirección contable y origen_tipo en CC.
    # Convención:
    #   - haber → pago/reducción de deuda al proveedor.
    #   - debe  → aumento de deuda o reversal de un haber previo.
    if imp.es_reversal:
        # Reversal inverts the original movement's direction.
        # Normal NC credito emits HABER → its reversal is DEBE.
        # ND (tipo='debito') emits DEBE → its reversal is HABER.
        # orden_pago / nota_credito_erp always emit HABER → reversal is DEBE.
        if imp.origen_tipo == "nota_credito_local":
            nc_tipo = _resolver_tipo_nc_local(session, imp.origen_id, "reversal")
            tipo_mov: TipoMovimiento = "haber" if nc_tipo == "debito" else "debe"
        else:
            tipo_mov = "debe"
        origen_cc = "reimputacion"
        descripcion = f"Reversal imputación id={imp.id} ({imp.destino_tipo}:{imp.destino_id})"
    else:
        # Imputación normal — origen produce un haber en CC (pagamos o
        # descontamos deuda al proveedor).
        # Compras v2: agregamos `nota_credito_local` a la whitelist con
        # idéntica semántica que `nota_credito_erp`. La NC local NO impactó
        # CC al aprobarse (decisión de diseño T.6 — análogo a OPs); el HABER
        # se materializa acá, al imputarse a un destino concreto.
        if imp.origen_tipo not in {"orden_pago", "nota_credito_erp", "nota_credito_local"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"aplicar_imputacion: origen_tipo='{imp.origen_tipo}' "
                    f"no tiene política de proyección a CC definida."
                ),
            )
        # F2 — directional sign for nota_credito_local (AD §3.6).
        # tipo='credito' → HABER (reduces debt, identical to pre-F2 behaviour).
        # tipo='debito'  → DEBE  (increases debt, used for ND/variance notes).
        # nota_credito_erp and orden_pago always emit HABER.
        if imp.origen_tipo == "nota_credito_local":
            nc_tipo = _resolver_tipo_nc_local(session, imp.origen_id, "normal")
            tipo_mov = "debe" if nc_tipo == "debito" else "haber"
        else:
            tipo_mov = "haber"
        origen_cc = "imputacion"
        descripcion = f"Imputación id={imp.id} → {imp.destino_tipo}:{imp.destino_id}"

    # Fecha del movimiento: fecha de creación de la imputación.
    # Si es naive date, usamos la parte date de created_at. En tests SQLite
    # `created_at` puede no estar aún seteado tras flush en algunos casos —
    # usamos fallback a today().
    fecha_mov = imp.created_at.date() if imp.created_at is not None else date.today()

    # Empresa: la imputación no tiene empresa_id propia. Se resuelve vía
    # el proveedor_id y el destino. Para v1 y simplificando: buscamos un
    # movimiento CC previo del proveedor para obtener empresa_id, o caemos
    # en el destino (pedido_compra → empresa_id). Si no hay forma de
    # resolver → usamos empresa_id=1 con log WARNING.
    empresa_id = _resolver_empresa_id_para_imputacion(session, imp)

    mov = insertar_mov(
        session,
        proveedor_id=imp.proveedor_id,
        empresa_id=empresa_id,
        fecha_movimiento=fecha_mov,
        tipo=tipo_mov,
        monto=imp.monto_imputado,
        moneda=imp.moneda_imputada,  # type: ignore[arg-type]
        origen_tipo=origen_cc,
        origen_id=imp.id,
        descripcion=descripcion,
        creado_por_id=imp.creado_por_id,
    )

    logger.info(
        "aplicar_imputacion imp_id=%s → cc_mov_id=%s tipo=%s monto=%s %s",
        imp.id,
        mov.id,
        tipo_mov,
        imp.monto_imputado,
        imp.moneda_imputada,
    )
    return [mov]


def _resolver_empresa_id_para_imputacion(session: Session, imp: Imputacion) -> int:
    """
    Resuelve el `empresa_id` a usar al proyectar una imputación al libro
    mayor. Prioridad:
      1. Si destino es `pedido_compra` → leer `empresa_id` del pedido.
      2. Si origen es `orden_pago` → leer `empresa_id` de la OP.
      3. Si origen es `nota_credito_local` → leer `empresa_id` de la NC local
         (compras v2).
      4. Si destino es `factura_erp` → resolver vía `(comp_id, bra_id)` del
         `ct_transaction` usando `COMP_BRA_A_EMPRESA`
         (`app.core.compras_empresa_erp_map`). Empresa 1 ← (1,1),
         Empresa 2 ← (1,45).
      5. Fallback: empresa_id=1 con log WARNING (p. ej. `(comp_id, bra_id)`
         sin mapear — sucursales internas 35-42 no son empresas comerciales).
    """
    from app.core.compras_empresa_erp_map import bra_a_empresa_o_ignorar  # noqa: PLC0415
    from app.models.commercial_transaction import CommercialTransaction  # noqa: PLC0415
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415
    from app.models.orden_pago import OrdenPago  # noqa: PLC0415
    from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415

    if imp.destino_tipo == "pedido_compra" and imp.destino_id is not None:
        pedido = session.get(PedidoCompra, imp.destino_id)
        if pedido is not None:
            return int(pedido.empresa_id)

    if imp.origen_tipo == "orden_pago" and imp.origen_id is not None:
        op = session.get(OrdenPago, imp.origen_id)
        if op is not None:
            return int(op.empresa_id)

    if imp.origen_tipo == "nota_credito_local" and imp.origen_id is not None:
        nc = session.get(NotaCreditoLocal, imp.origen_id)
        if nc is not None:
            return int(nc.empresa_id)

    # Prioridad 4: destino factura_erp via (comp_id, bra_id).
    # Cuando `destino_tipo='factura_erp'`, `destino_id` es el `ct_transaction`
    # de `tb_commercial_transactions` (convención del módulo compras).
    # Resolvemos la empresa local con `bra_a_empresa_o_ignorar`:
    #   - (comp_id=1, bra_id=1)  → empresa_id=1 (sucursal principal)
    #   - (comp_id=1, bra_id=45) → empresa_id=2 (Grupo Gauss)
    #   - otros (incl. sucursales internas 35-42) → None → fallback a 1.
    if imp.destino_tipo == "factura_erp" and imp.destino_id is not None:
        ct = session.get(CommercialTransaction, int(imp.destino_id))
        if ct is None:
            logger.warning(
                "aplicar_imputacion: imp_id=%s destino factura_erp ct_transaction=%s no existe en tb_commercial_transactions. Fallback a 1.",
                imp.id,
                imp.destino_id,
            )
        elif ct.comp_id is None or ct.bra_id is None:
            logger.warning(
                "aplicar_imputacion: imp_id=%s ct_transaction=%s tiene comp_id/bra_id nulos. Fallback a 1.",
                imp.id,
                imp.destino_id,
            )
        else:
            empresa_id = bra_a_empresa_o_ignorar(int(ct.comp_id), int(ct.bra_id))
            if empresa_id is not None:
                return empresa_id
            # `bra_a_empresa_o_ignorar` ya loggea WARNING con (comp_id, bra_id)
            # si no está en el mapeo (ej: sucursales internas 35-42).

    logger.warning(
        "aplicar_imputacion: no pude resolver empresa_id para imp_id=%s (origen=%s:%s destino=%s:%s). Fallback a 1.",
        imp.id,
        imp.origen_tipo,
        imp.origen_id,
        imp.destino_tipo,
        imp.destino_id,
    )
    return 1


def calcular_saldo_por_moneda(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: Optional[int] = None,
    hasta_fecha: Optional[date] = None,
) -> dict[str, Decimal]:
    """
    Calcula el saldo neto por moneda del proveedor (estrategia C del design).

    Fórmula por moneda:
        SUM(CASE tipo
              WHEN 'debe'   THEN  monto
              WHEN 'haber'  THEN -monto
              WHEN 'ajuste' THEN  signo_ajuste * monto
            END)

    Args:
        proveedor_id: FK a proveedores.
        empresa_id: si se pasa, filtra por empresa (multi-empresa CC).
        hasta_fecha: si se pasa, excluye movimientos con
            `fecha_movimiento > hasta_fecha` (útil para saldo histórico).

    Returns:
        dict[moneda, saldo]. Sólo incluye monedas que tengan al menos un
        movimiento en la ventana consultada (aunque la suma dé 0).

    Notes:
        Signo: saldo positivo → le debo al proveedor; negativo → el
        proveedor me debe (saldo a favor).
    """
    importe_signado = case(
        (CCProveedorMovimiento.tipo == "debe", CCProveedorMovimiento.monto),
        (CCProveedorMovimiento.tipo == "haber", -CCProveedorMovimiento.monto),
        (
            CCProveedorMovimiento.tipo == "ajuste",
            CCProveedorMovimiento.signo_ajuste * CCProveedorMovimiento.monto,
        ),
        else_=0,
    )

    condiciones = [CCProveedorMovimiento.proveedor_id == proveedor_id]
    if empresa_id is not None:
        condiciones.append(CCProveedorMovimiento.empresa_id == empresa_id)
    if hasta_fecha is not None:
        condiciones.append(CCProveedorMovimiento.fecha_movimiento <= hasta_fecha)

    stmt = (
        select(
            CCProveedorMovimiento.moneda,
            func.coalesce(func.sum(importe_signado), 0).label("saldo"),
        )
        .where(and_(*condiciones))
        .group_by(CCProveedorMovimiento.moneda)
    )

    resultado: dict[str, Decimal] = {}
    for moneda, saldo in session.execute(stmt).all():
        resultado[moneda] = saldo if isinstance(saldo, Decimal) else Decimal(str(saldo))
    return resultado


def listar_movimientos(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: Optional[int] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    moneda: Optional[Moneda] = None,
) -> list[CCProveedorMovimiento]:
    """
    Lista movimientos de CC de un proveedor con filtros opcionales.

    Ordenado por `fecha_movimiento ASC, id ASC` (orden de inserción dentro
    de la misma fecha, consistente con el índice `ix_ccpm_proveedor_fecha`).
    """
    condiciones = [CCProveedorMovimiento.proveedor_id == proveedor_id]
    if empresa_id is not None:
        condiciones.append(CCProveedorMovimiento.empresa_id == empresa_id)
    if desde is not None:
        condiciones.append(CCProveedorMovimiento.fecha_movimiento >= desde)
    if hasta is not None:
        condiciones.append(CCProveedorMovimiento.fecha_movimiento <= hasta)
    if moneda is not None:
        condiciones.append(CCProveedorMovimiento.moneda == moneda)

    stmt = (
        select(CCProveedorMovimiento)
        .where(and_(*condiciones))
        .order_by(
            CCProveedorMovimiento.fecha_movimiento.asc(),
            CCProveedorMovimiento.id.asc(),
        )
    )
    return list(session.execute(stmt).scalars().all())


def _proveedores_con_movimientos_recientes(
    session: Session,
    *,
    ventana_dias: int,
    hasta_fecha: date,
) -> list[int]:
    """
    Lista `proveedor_id` distintos con al menos un movimiento en
    `cc_proveedor_movimientos` dentro de la ventana
    `[hasta_fecha - ventana_dias, hasta_fecha]`.

    Usado por `reconciliar_diario` para no procesar proveedores inactivos.
    """
    desde = hasta_fecha.replace() if hasta_fecha else date.today()
    stmt = (
        select(CCProveedorMovimiento.proveedor_id)
        .where(CCProveedorMovimiento.fecha_movimiento >= _fecha_menos_dias(desde, ventana_dias))
        .where(CCProveedorMovimiento.fecha_movimiento <= desde)
        .distinct()
    )
    return [row[0] for row in session.execute(stmt).all()]


def _fecha_menos_dias(base: date, dias: int) -> date:
    from datetime import timedelta

    return base - timedelta(days=dias)


def _leer_snapshot_cc(
    session: Session,
    *,
    proveedor_id: int,
    moneda: str,
) -> Optional[Decimal]:
    """
    Lee el saldo pendiente del snapshot `cuentas_corrientes_proveedores`
    del ERP para `(proveedor_id, moneda)`.

    El modelo actual (`cuenta_corriente_proveedor`) NO tiene columna
    `moneda` — el ERP sincroniza saldos totales por proveedor. Para v1,
    usamos:
      - ARS → columna `pendiente` (asumimos que el snapshot ya está en ARS
        al ser importado).
      - USD → `None` (el snapshot no diferencia moneda; si hay saldo USD,
        hay que esperar a que el ERP sincronice esa columna).

    Esta función es el UNICO lugar donde se define la política de mapeo
    snapshot → moneda, así que cuando el ERP agregue el split puede
    actualizarse acá sin tocar `reconciliar_diario`.
    """
    if moneda != "ARS":
        return None

    # Query directo (el modelo usa `id_proveedor`, no `proveedor_id`).
    stmt = text(
        """
        SELECT pendiente
        FROM cuentas_corrientes_proveedores
        WHERE id_proveedor = :pid
        ORDER BY synced_at DESC
        LIMIT 1
        """
    )
    valor = session.execute(stmt, {"pid": proveedor_id}).scalar_one_or_none()
    if valor is None:
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def reconciliar_diario(
    session: Session,
    *,
    fecha_corrida: date,
    tolerancias: dict[str, Decimal],
    ventana_dias: int = 365,
) -> dict[str, int]:
    """
    Cron diario de reconciliación CC libro mayor vs snapshot ERP (design §8.2).

    Flujo:
      1. Lista proveedores con mov en últimos `ventana_dias` días.
      2. Por cada (proveedor, moneda_con_mov):
         - `saldo_mayor = calcular_saldo_por_moneda(proveedor_id=p)[moneda]`
         - `saldo_snap = leer_snapshot_cc(p, moneda)`
         - Si `saldo_snap is None` → skip (no hay con qué comparar).
         - `diferencia = abs(saldo_mayor - saldo_snap)`
         - `tolerancia = tolerancias[moneda]` (cierre 2 del usuario:
           tolerancia distinta por moneda — NO una única ARS).
         - `estado = 'ok' | 'divergencia'` según `diferencia <= tolerancia`.
         - INSERT en `cc_reconciliacion_log` con (UNIQUE constraint
           `(fecha_corrida, proveedor_id, moneda)` — si se re-corre con
           la misma fecha rollbackeamos sólo esa fila).

      3. Si hay ≥1 divergencia:
         - Crea 1 fila en `alertas` (banner agregado diario para ADMIN).
         - Crea N filas en `notificaciones` (una por divergencia, para
           cada usuario con rol ADMIN).
         - Setea `log.alerta_id` y `log.notificacion_id` por trazabilidad.

    No commitea — es responsabilidad del script caller.

    Args:
        session: tx activa.
        fecha_corrida: fecha de la corrida (para UNIQUE constraint).
        tolerancias: dict `{'ARS': Decimal, 'USD': Decimal}` — requerido.
            Debe venir cargado con las claves de `configuracion`.
        ventana_dias: filtro de proveedores activos (default 365).

    Returns:
        dict con totales:
          - `proveedores_procesados`
          - `comparaciones`: cuántas (proveedor, moneda) se compararon
          - `divergencias`
          - `alertas_creadas` (0|1)
          - `notificaciones_creadas`

    Raises:
        ValueError: si `tolerancias` no tiene claves `ARS` y `USD`.
    """
    if not {"ARS", "USD"}.issubset(tolerancias.keys()):
        raise ValueError(f"tolerancias debe incluir claves 'ARS' y 'USD' (recibidas: {set(tolerancias.keys())})")

    proveedores_ids = _proveedores_con_movimientos_recientes(
        session,
        ventana_dias=ventana_dias,
        hasta_fecha=fecha_corrida,
    )

    divergencias_logs: list[CCReconciliacionLog] = []
    comparaciones = 0

    for prov_id in proveedores_ids:
        saldos = calcular_saldo_por_moneda(
            session,
            proveedor_id=prov_id,
            hasta_fecha=fecha_corrida,
        )
        for moneda, saldo_mayor in saldos.items():
            saldo_snap = _leer_snapshot_cc(session, proveedor_id=prov_id, moneda=moneda)
            if saldo_snap is None:
                continue  # sin snapshot para comparar

            comparaciones += 1
            diferencia = abs(Decimal(saldo_mayor) - Decimal(saldo_snap))
            tolerancia = tolerancias.get(moneda, Decimal("0"))
            estado = (
                CCReconciliacionLog.ESTADO_OK if diferencia <= tolerancia else CCReconciliacionLog.ESTADO_DIVERGENCIA
            )

            log = CCReconciliacionLog(
                fecha_corrida=fecha_corrida,
                proveedor_id=prov_id,
                moneda=moneda,
                saldo_libro_mayor=saldo_mayor,
                saldo_snapshot=saldo_snap,
                diferencia=diferencia,
                tolerancia_aplicada=tolerancia,
                estado=estado,
            )
            session.add(log)
            if estado == CCReconciliacionLog.ESTADO_DIVERGENCIA:
                divergencias_logs.append(log)

    # Flush para que las logs entries tengan PK antes de armar alertas/notifs
    session.flush()

    alertas_creadas = 0
    notificaciones_creadas = 0
    if divergencias_logs:
        alerta_id, notif_ids = _crear_alerta_y_notificaciones_divergencia(
            session,
            fecha_corrida=fecha_corrida,
            divergencias=divergencias_logs,
        )
        alertas_creadas = 1 if alerta_id is not None else 0

        # Vincular cada log con su notificacion (una notif por log)
        for log, notif_id in zip(divergencias_logs, notif_ids, strict=False):
            log.alerta_id = alerta_id
            log.notificacion_id = notif_id
            notificaciones_creadas += 1

        session.flush()

    return {
        "proveedores_procesados": len(proveedores_ids),
        "comparaciones": comparaciones,
        "divergencias": len(divergencias_logs),
        "alertas_creadas": alertas_creadas,
        "notificaciones_creadas": notificaciones_creadas,
    }


def _crear_alerta_y_notificaciones_divergencia(
    session: Session,
    *,
    fecha_corrida: date,
    divergencias: list[CCReconciliacionLog],
) -> tuple[Optional[int], list[Optional[int]]]:
    """Crea 1 alerta banner + N notificaciones (una por log divergente)
    siguiendo design §8.3 (reuso de tablas `alertas` y `notificaciones`).

    Returns:
        (alerta_id, [notificacion_ids en mismo orden que divergencias]).
        Cada elemento de la lista puede ser None si no hubo admins con
        permisos (el log queda sin notificacion_id vinculada, pero se
        persiste igualmente para trazabilidad).

    Si falla la creación de alerta/notif, NO rompe — retorna (None, []).
    La reconciliación puede persistir logs aunque el sistema de alertas
    esté caído.
    """
    # Imports locales — evitamos tocar a nivel módulo para no cargar
    # modelos ajenos al CC cuando solo se usa insertar_mov.
    from app.models.alerta import Alerta  # noqa: PLC0415
    from app.services.notificacion_service import (  # noqa: PLC0415
        crear_notificaciones_para_permisos,
    )

    try:
        # 1 Alerta banner agregada
        alerta = Alerta(
            titulo=f"Reconciliación CC {fecha_corrida}: {len(divergencias)} divergencias",
            mensaje=(
                f"El libro mayor y el snapshot ERP difieren en "
                f"{len(divergencias)} casos. Ver /administracion/compras/reconciliacion"
            ),
            variant="warning",
            roles_destinatarios=["ADMIN"],
            action_label="Ver detalle",
            action_url="/administracion/compras/reconciliacion",
            activo=True,
            dismissible=True,
            persistent=False,
            fecha_desde=datetime.now(timezone.utc),
        )
        session.add(alerta)
        session.flush()
        alerta_id = int(alerta.id)

        # N notificaciones: una por divergencia, fan-out a TODOS los usuarios
        # con permiso de gestionar la reconciliación (no solo al primer admin,
        # como hacía la versión anterior). Usamos el helper centralizado que
        # reemplaza el antipatrón `Notificacion(user_id=None)` y además evita
        # que la notif se pierda si no hay admins (cae a log WARNING).
        notif_ids: list[int | None] = []  # type: ignore[assignment]
        for log in divergencias:
            notifs = crear_notificaciones_para_permisos(
                session,
                permisos_requeridos=[
                    "administracion.gestionar_ordenes_compra",
                    "administracion.ver_cuentas_corrientes",
                ],
                tipo="cc_reconciliacion_divergencia",
                mensaje=(
                    f"Divergencia CC proveedor_id={log.proveedor_id} "
                    f"moneda={log.moneda}: mayor={log.saldo_libro_mayor} "
                    f"snap={log.saldo_snapshot} dif={log.diferencia}"
                ),
            )
            session.flush()
            # El log apunta al ID de la PRIMERA notificación creada (una de
            # las N por divergencia) — suficiente para audit trail, el resto
            # son copias idénticas en la UI de cada admin. Si nadie tenía
            # permisos → None (el helper ya loggeó WARNING).
            notif_ids.append(int(notifs[0].id) if notifs else None)  # type: ignore[arg-type]

        return alerta_id, notif_ids  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Falló la creación de alerta/notif de reconciliación (pero los logs se mantienen): %s",
            exc,
        )
        return None, []


def registrar_ajuste_revaluacion_tc(
    session: Session,
    *,
    pedido: "PedidoCompra",
    tc_anterior: Decimal,
    tc_nuevo: Decimal,
    user_id: int,
    motivo: str,
) -> Optional[CCProveedorMovimiento]:
    """
    Emits an append-only CC `ajuste` movement for a TC re-valuation delta.

    Implements AD-9: re-valuation of the pedido's ARS debt NEVER mutates
    existing `cc_proveedor_movimientos` rows — it creates a NEW row.

    The movement amount is: abs(tc_nuevo - tc_anterior) * pedido.monto (USD).
    Sign:
      - `signo_ajuste=+1` if TC rose (debt increased in ARS).
      - `signo_ajuste=-1` if TC fell (debt decreased in ARS).

    Moneda of the adjustment: always ARS (the re-valuation is an ARS delta).

    Args:
        session: active tx.
        pedido: the PedidoCompra being re-valued.
        tc_anterior: effective TC before this operation.
        tc_nuevo: effective TC after this operation.
        user_id: user triggering the re-valuation.
        motivo: short description for the adjustment record.

    Returns:
        The created `CCProveedorMovimiento`, or None if delta is zero
        (no-op, no row created).
    """

    delta_tc = Decimal(tc_nuevo) - Decimal(tc_anterior)
    if delta_tc == 0:
        return None

    # ARS delta = |tc_diff| * monto_usd. `pedido.monto` is always the
    # USD face-value of the pedido (stored as Numeric(18,2)).
    monto_ajuste = (abs(delta_tc) * Decimal(pedido.monto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    signo = 1 if delta_tc > 0 else -1

    fecha_mov = date.today()

    mov = insertar_mov(
        session,
        proveedor_id=pedido.proveedor_id,
        empresa_id=pedido.empresa_id,
        fecha_movimiento=fecha_mov,
        tipo="ajuste",
        monto=monto_ajuste,
        moneda="ARS",
        origen_tipo="revaluacion_tc",
        origen_id=pedido.id,
        descripcion=f"Revaluación TC pedido #{pedido.numero}: {tc_anterior} → {tc_nuevo} ({motivo})",
        creado_por_id=user_id,
        signo_ajuste=signo,
    )

    logger.info(
        "ajuste_revaluacion_tc pedido_id=%s tc_anterior=%s tc_nuevo=%s delta=%s signo=%s monto_ars=%s",
        pedido.id,
        tc_anterior,
        tc_nuevo,
        delta_tc,
        signo,
        monto_ajuste,
    )
    return mov


# ──────────────────────────────────────────────────────────────────────────
# calcular_saldo_a_favor_breakdown (PR2 — AD-8)
# ──────────────────────────────────────────────────────────────────────────


def calcular_saldo_a_favor_breakdown(
    session: Session,
    *,
    proveedor_id: int,
    empresa_id: Optional[int] = None,
) -> dict:
    """
    Calcula el breakdown del saldo a favor del CC en componentes (AD-8).

    El saldo a favor total sigue siendo `calcular_saldo_por_moneda` (negativo
    = a favor). El breakdown clasifica ese saldo en:
      - `componente_dinero_a_cuenta`: real-money overpay disponible (DACs)
      - `componente_nc`: crédito documental (NCs locales/ERP pendientes)

    Todo derivado — sin columnas extra en cc_proveedor_movimientos (AD-8).

    Returns:
        dict con claves:
          proveedor_id, saldo_a_favor_total_ars,
          componente_dinero_a_cuenta_ars, componente_nc_ars, por_moneda.
    """
    from app.services.dinero_a_cuenta_service import calcular_componente_dinero_a_cuenta  # noqa: PLC0415

    saldos_por_moneda = calcular_saldo_por_moneda(session, proveedor_id=proveedor_id, empresa_id=empresa_id)

    # calcular_saldo_por_moneda devuelve negativo cuando el CC es a favor del
    # proveedor (haber > debe). En el breakdown exponemos la MAGNITUD: valor
    # positivo = cuánto le debemos al proveedor. Cero cuando el proveedor nos
    # debe a nosotros (saldo_bruto >= 0).
    saldo_bruto = saldos_por_moneda.get("ARS", Decimal("0"))
    saldo_ars = max(Decimal("0"), -saldo_bruto)

    # Compute componentes for all currencies that appear in CC movements.
    # ARS is always computed (DACs and NCs can exist even without CC entries).
    monedas_a_calcular = set(saldos_por_moneda.keys()) | {"ARS"}

    por_moneda: dict = {}
    for moneda_key in monedas_a_calcular:
        saldo_moneda = saldos_por_moneda.get(moneda_key, Decimal("0"))
        comp_dac_m = calcular_componente_dinero_a_cuenta(
            session, proveedor_id=proveedor_id, moneda=moneda_key, empresa_id=empresa_id
        )
        comp_nc_m = _calcular_componente_nc(
            session, proveedor_id=proveedor_id, moneda=moneda_key, empresa_id=empresa_id
        )
        por_moneda[moneda_key] = {
            "moneda": moneda_key,
            # Magnitud positiva; 0 cuando el proveedor tiene deuda con nosotros.
            "saldo_a_favor_total": max(Decimal("0"), -saldo_moneda),
            "componente_dinero_a_cuenta": comp_dac_m,
            "componente_nc": comp_nc_m,
        }

    # ARS totals: reuse from por_moneda (always present after the loop above).
    ars_entry = por_moneda["ARS"]
    comp_dac_ars = ars_entry["componente_dinero_a_cuenta"]
    comp_nc_ars = ars_entry["componente_nc"]

    return {
        "proveedor_id": proveedor_id,
        "saldo_a_favor_total_ars": saldo_ars,
        "componente_dinero_a_cuenta_ars": comp_dac_ars,
        "componente_nc_ars": comp_nc_ars,
        "por_moneda": por_moneda,
    }


def _calcular_componente_nc(
    session: Session,
    *,
    proveedor_id: int,
    moneda: str,
    empresa_id: Optional[int] = None,
) -> Decimal:
    """
    Suma saldos pendientes de NCs locales tipo='credito' en estados aplicables
    para el proveedor y moneda dados.

    Saldo pendiente de cada NC = monto - SUM(imputaciones origen=nc no-reversal)
                                        + SUM(reversals).
    Misma fórmula que _validar_origen_nc_local_disponible en imputaciones_service.

    empresa_id: si se provee, filtra por empresa (coherencia con saldo CC).
    NCs ERP no se calculan aquí (sin acceso a tabla ERP local en tests SQLite);
    en producción se extiende con nota_credito_erp.
    """
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    filters = [
        NotaCreditoLocal.proveedor_id == proveedor_id,
        NotaCreditoLocal.moneda == moneda,
        NotaCreditoLocal.tipo == "credito",
        NotaCreditoLocal.estado.in_(["aprobado", "aplicada_parcial"]),
    ]
    if empresa_id is not None:
        filters.append(NotaCreditoLocal.empresa_id == empresa_id)

    stmt = select(NotaCreditoLocal.id, NotaCreditoLocal.monto).where(*filters)
    ncs = session.execute(stmt).all()

    if not ncs:
        return Decimal("0")

    nc_ids = [nc_id for nc_id, _ in ncs]
    nc_montos = {nc_id: Decimal(nc_monto) for nc_id, nc_monto in ncs}

    # Batch: saldo neto de imputaciones por NC en 2 queries en lugar de 2N.
    nc_origen_tipos = ["nota_credito_local", "nota_credito_erp"]
    neto_no_reversal: dict[int, Decimal] = {
        row.origen_id: Decimal(row.total)
        for row in session.execute(
            select(Imputacion.origen_id, func.sum(Imputacion.monto_imputado).label("total"))
            .where(
                Imputacion.origen_tipo.in_(nc_origen_tipos),
                Imputacion.origen_id.in_(nc_ids),
                Imputacion.es_reversal.is_(False),
            )
            .group_by(Imputacion.origen_id)
        ).all()
    }
    neto_reversal: dict[int, Decimal] = {
        row.origen_id: Decimal(row.total)
        for row in session.execute(
            select(Imputacion.origen_id, func.sum(Imputacion.monto_imputado).label("total"))
            .where(
                Imputacion.origen_tipo.in_(nc_origen_tipos),
                Imputacion.origen_id.in_(nc_ids),
                Imputacion.es_reversal.is_(True),
            )
            .group_by(Imputacion.origen_id)
        ).all()
    }

    total = Decimal("0")
    for nc_id in nc_ids:
        consumido = neto_no_reversal.get(nc_id, Decimal("0"))
        reversal = neto_reversal.get(nc_id, Decimal("0"))
        saldo_nc = nc_montos[nc_id] - (consumido - reversal)
        if saldo_nc > Decimal("0"):
            total += saldo_nc

    return total


__all__ = [
    "Moneda",
    "TipoMovimiento",
    "aplicar_imputacion",
    "calcular_saldo_a_favor_breakdown",
    "calcular_saldo_por_moneda",
    "insertar_mov",
    "listar_movimientos",
    "reconciliar_diario",
    "registrar_ajuste_revaluacion_tc",
]
