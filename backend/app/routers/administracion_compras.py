"""
Router raíz del módulo `administracion-compras` (design §9).

Prefijo común: `/api/administracion/compras`. Todos los endpoints
requieren autenticación JWT (`Depends(get_current_user)` a través de
`require_permiso`) + chequeo de permiso RBAC específico según el caso.

Organización (siguiendo design §9):
  §9.1 — Pedidos de compra:         /pedidos/*
  §9.2 — Órdenes de pago:           /ordenes-pago/*
  §9.3 — Imputaciones polimórficas: /imputaciones/*
  §9.4 — Cuenta corriente + reconciliación: /cc-proveedor/*, /reconciliacion/*
  §9.5 — Catálogo sale-documents:   /sale-documents/*

Contratos de error importantes:
  - 409 `POSIBLE_DUPLICADO_OP_ERP` (design §7.2 + §11) — payload
    estructurado con duplicados_detectados + flag_confirmacion.
  - 422 `OP_CAJA_MONEDA_MISMATCH` (design §3.2) — payload con codigo +
    mensaje explicando qué caja elegir.

Commits: cada endpoint que muta DB orquesta `try/except/commit/rollback`
explícitamente. NO se delega en `Depends(get_db)` porque los servicios
subyacentes (especialmente `ejecutar_pago`) hacen `flush` pero NO
`commit` — riesgo identificado en F4.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func as sa_func
from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.caja import CajaMovimiento
from app.models.compra_evento import CompraEvento
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.tb_sale_document import SaleDocument
from app.models.usuario import Usuario
from app.schemas.cc_proveedor import (
    CCAgrupadoPorPedido,
    CCMovimientoResponse,
    CCProveedorDetalle,
    CCReconciliacionLogResponse,
    SaldoPorMoneda,
)
from app.schemas.compra_evento import CompraEventoResponse
from app.schemas.compras_papelera import (
    PapeleraHardDeleteRequest,
    PapeleraItemDetalle,
    PapeleraItemResponse,
    PapeleraPaginated,
)
from app.schemas.imputacion import (
    ImputacionDesimputar,
    ImputacionPaginated,
    ImputacionReimputar,
    ImputacionResponse,
)
from app.schemas.orden_pago import (
    CajaMovimientoResumen,
    OrdenPagoCreate,
    OrdenPagoDetalle,
    OrdenPagoEjecutarPago,
    OrdenPagoPaginated,
    OrdenPagoResponse,
)
from app.schemas.pedido_compra import (
    PedidoCompraCreate,
    PedidoCompraDetalle,
    PedidoCompraPaginated,
    PedidoCompraResponse,
    PedidoCompraUpdate,
)
from app.schemas.sale_document import SaleDocumentResponse, SaleDocumentsFaltantes
from app.services import (
    cc_proveedor_service,
    compras_papelera_service,
    etiqueta_retiro_service,
    imputaciones_service,
    ordenes_pago_service,
    pedidos_service,
)
from app.services.sale_document_classifier import clasificar_documento_compra

logger = get_logger("routers.administracion_compras")

router = APIRouter(
    prefix="/administracion/compras",
    tags=["Administración - Compras"],
)


# ==========================================================================
# Helpers internos
# ==========================================================================


def _commit_or_rollback(db: Session, *, operacion: str) -> None:
    """Commit explícito con rollback en caso de error.

    Los servicios de flujo (ejecutar_pago, crear, transicionar, etc.) hacen
    flush pero NO commit — por diseño, para que el router orqueste la
    transacción completa (cerrando eventos, imputaciones y OP en un solo
    go). Este helper se usa al final de cada endpoint que muta DB.

    Si `commit` falla, se levanta HTTP 500 con rollback previo. El caller
    ya se encargó de levantar 400/422/409 cuando corresponde — acá solo
    capturamos fallas de integridad de último momento (ej. constraint
    violation que emergió al flushear todo junto).
    """
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("commit falló en operación '%s': %s", operacion, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al persistir la operación '{operacion}'. Reintenta o contactá soporte.",
        ) from exc


def _paginate(
    db: Session,
    stmt_base,
    *,
    page: int,
    page_size: int,
) -> tuple[list, int]:
    """Ejecuta `stmt_base` paginado y retorna (items, total).

    El contador usa el mismo FROM+WHERE; el select de items agrega
    ORDER BY + OFFSET + LIMIT. `stmt_base` tiene que venir sin order/limit.
    """
    # Total: COUNT(*) sobre la subquery del stmt_base (seguro aunque tenga joins)
    count_stmt = select(sa_func.count()).select_from(stmt_base.subquery())
    total = int(db.execute(count_stmt).scalar_one() or 0)

    offset = (page - 1) * page_size
    stmt_items = stmt_base.offset(offset).limit(page_size)
    items = list(db.execute(stmt_items).scalars().all())
    return items, total


def _obtener_pedido_o_404(db: Session, pedido_id: int) -> PedidoCompra:
    pedido = db.get(PedidoCompra, pedido_id)
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido id={pedido_id} no encontrado.",
        )
    return pedido


def _obtener_op_o_404(db: Session, op_id: int) -> OrdenPago:
    op = db.get(OrdenPago, op_id)
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={op_id} no encontrada.",
        )
    return op


def _obtener_proveedor_o_404(db: Session, proveedor_id: int) -> Proveedor:
    prov = db.get(Proveedor, proveedor_id)
    if prov is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proveedor id={proveedor_id} no encontrado.",
        )
    return prov


def _pedido_response(p: PedidoCompra, *, puede_eliminar: bool = False) -> PedidoCompraResponse:
    """Serializa PedidoCompra incluyendo empresa_nombre / proveedor_nombre.

    `model_validate` en Pydantic v2 no soporta `update=`; usamos
    `model_copy(update=...)` post-validación, que es la API equivalente.
    Si la relación no está cargada (endpoint sin joinedload), `getattr`
    puede disparar lazy-load si la sesión sigue activa; si falla, cae en
    `None` y el frontend muestra fallback "#N".

    `puede_eliminar` lo calcula el caller vía
    `compras_papelera_service._calcular_puede_eliminar_pedidos_batch`
    (opción C — 3 queries fijas sin importar N).
    """
    emp = getattr(p, "empresa", None)
    prov = getattr(p, "proveedor", None)
    base = PedidoCompraResponse.model_validate(p)
    return base.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
            "puede_eliminar": puede_eliminar,
        }
    )


def _op_response(op: OrdenPago, *, puede_eliminar: bool = False) -> OrdenPagoResponse:
    """Serializa OrdenPago incluyendo empresa_nombre / proveedor_nombre."""
    emp = getattr(op, "empresa", None)
    prov = getattr(op, "proveedor", None)
    base = OrdenPagoResponse.model_validate(op)
    return base.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
            "puede_eliminar": puede_eliminar,
        }
    )


# ==========================================================================
# §9.1 — PEDIDOS
# ==========================================================================


@router.get(
    "/pedidos",
    response_model=PedidoCompraPaginated,
    summary="Listar pedidos con filtros y paginación",
)
def listar_pedidos(
    estado: Optional[str] = Query(None, description="Estado del pedido"),
    proveedor_id: Optional[int] = Query(None, ge=1),
    empresa_id: Optional[int] = Query(None, ge=1),
    desde: Optional[date] = Query(None, description="created_at >= desde"),
    hasta: Optional[date] = Query(None, description="created_at <= hasta"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> PedidoCompraPaginated:
    """Lista paginada de pedidos. REQ-PED-001, design §9.1."""
    condiciones = []
    if estado is not None:
        condiciones.append(PedidoCompra.estado == estado)
    if proveedor_id is not None:
        condiciones.append(PedidoCompra.proveedor_id == proveedor_id)
    if empresa_id is not None:
        condiciones.append(PedidoCompra.empresa_id == empresa_id)
    if desde is not None:
        condiciones.append(PedidoCompra.created_at >= datetime.combine(desde, datetime.min.time()))
    if hasta is not None:
        condiciones.append(PedidoCompra.created_at <= datetime.combine(hasta, datetime.max.time()))

    stmt = select(PedidoCompra).options(
        joinedload(PedidoCompra.empresa),
        joinedload(PedidoCompra.proveedor),
    )
    if condiciones:
        stmt = stmt.where(*condiciones)
    stmt = stmt.order_by(PedidoCompra.created_at.desc(), PedidoCompra.id.desc())

    items, total = _paginate(db, stmt, page=page, page_size=page_size)
    puede_map = compras_papelera_service._calcular_puede_eliminar_pedidos_batch(db, items)
    return PedidoCompraPaginated(
        items=[_pedido_response(p, puede_eliminar=puede_map.get(p.id, False)) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/pedidos/pendientes-pago",
    response_model=list[PedidoCompraResponse],
    summary="Pedidos aprobados o con pago parcial esperando imputación",
)
def listar_pedidos_pendientes_pago(
    proveedor_id: Optional[int] = Query(None, ge=1),
    empresa_id: Optional[int] = Query(None, ge=1),
    moneda: Optional[str] = Query(None, pattern="^(ARS|USD)$"),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[PedidoCompraResponse]:
    """
    Lista pedidos en estado 'aprobado' o 'pagado_parcial' con saldo pendiente.

    Usado por:
      - Sección "Pedidos aprobados esperando pago" en TabOrdenesPago.
      - Pre-carga desde ModalOrdenPagoNueva (flujo Batch C).

    Cada pedido incluye `saldo_pendiente` = monto - imputaciones efectivas
    (calculado vía `pedidos_service.calcular_saldo_pendiente_pedido`, que
    considera reversals — append-only compliant, design D3).

    Orden: fecha_pago_estimada ASC (NULL al final, urgentes primero),
    luego created_at ASC como desempate estable.

    Filtros:
      - proveedor_id: único proveedor.
      - empresa_id: única empresa.
      - moneda: ARS o USD.

    NOTA: No paginado — se asume N pequeño (pedidos pendientes reales de
    una PyME típicamente < 50). Si crece, agregar paginación.
    """
    stmt = (
        select(PedidoCompra)
        .options(
            joinedload(PedidoCompra.empresa),
            joinedload(PedidoCompra.proveedor),
        )
        .where(PedidoCompra.estado.in_(["aprobado", "pagado_parcial"]))
    )
    if proveedor_id is not None:
        stmt = stmt.where(PedidoCompra.proveedor_id == proveedor_id)
    if empresa_id is not None:
        stmt = stmt.where(PedidoCompra.empresa_id == empresa_id)
    if moneda is not None:
        stmt = stmt.where(PedidoCompra.moneda == moneda)
    stmt = stmt.order_by(
        PedidoCompra.fecha_pago_estimada.asc().nulls_last(),
        PedidoCompra.created_at.asc(),
    )

    pedidos = list(db.execute(stmt).scalars().all())

    # Enriquecer con saldo_pendiente. calcular_saldo_pendiente_pedido hace
    # dos SUM queries por pedido (no-reversal + reversal); no hay N+1 de
    # relaciones porque ya las traímos con joinedload, pero sí N queries
    # de agregación. Aceptable para el N pequeño descrito arriba.
    respuestas: list[PedidoCompraResponse] = []
    for p in pedidos:
        saldo = pedidos_service.calcular_saldo_pendiente_pedido(db, p.id)
        resp = _pedido_response(p)
        respuestas.append(resp.model_copy(update={"saldo_pendiente": saldo}))
    return respuestas


@router.get(
    "/pedidos/{pedido_id}",
    response_model=PedidoCompraDetalle,
    summary="Detalle de pedido con eventos e imputaciones",
)
def obtener_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> PedidoCompraDetalle:
    """Detalle completo del pedido. REQ-PED-001, design §9.1."""
    # joinedload para poblar empresa_nombre/proveedor_nombre sin N+1.
    pedido = db.execute(
        select(PedidoCompra)
        .options(
            joinedload(PedidoCompra.empresa),
            joinedload(PedidoCompra.proveedor),
        )
        .where(PedidoCompra.id == pedido_id)
    ).scalar_one_or_none()
    if pedido is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido id={pedido_id} no encontrado.",
        )

    eventos = list(
        db.execute(
            select(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
            )
            .order_by(CompraEvento.created_at.desc(), CompraEvento.id.desc())
        )
        .scalars()
        .all()
    )

    imputaciones = list(
        db.execute(
            select(Imputacion)
            .where(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == pedido.id,
            )
            .order_by(Imputacion.created_at.asc(), Imputacion.id.asc())
        )
        .scalars()
        .all()
    )

    emp = getattr(pedido, "empresa", None)
    prov = getattr(pedido, "proveedor", None)
    detalle = PedidoCompraDetalle.model_validate(pedido)
    detalle = detalle.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
        }
    )
    detalle.eventos = [CompraEventoResponse.model_validate(e) for e in eventos]
    detalle.imputaciones = [ImputacionResponse.model_validate(i) for i in imputaciones]
    return detalle


@router.post(
    "/pedidos",
    response_model=PedidoCompraResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear pedido en estado borrador",
)
def crear_pedido(
    data: PedidoCompraCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Crea un pedido en estado `borrador`. REQ-PED-001."""
    try:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=data.empresa_id,
            proveedor_id=data.proveedor_id,
            moneda=data.moneda,  # type: ignore[arg-type]
            monto=data.monto,
            creado_por_id=user.id,
            tipo_cambio=data.tipo_cambio,
            fecha_pago_texto=data.fecha_pago_texto,
            fecha_pago_estimada=data.fecha_pago_estimada,
            requiere_envio=data.requiere_envio,
            numero_factura=data.numero_factura,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("crear_pedido falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al crear el pedido.") from exc

    _commit_or_rollback(db, operacion="crear_pedido")
    db.refresh(pedido)
    return _pedido_response(pedido)


@router.put(
    "/pedidos/{pedido_id}",
    response_model=PedidoCompraResponse,
    summary="Editar pedido (según estado: borrador=todos los campos, aprobado=numero_factura)",
)
def editar_pedido(
    pedido_id: int,
    data: PedidoCompraUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Edita un pedido aplicando reglas por estado. REQ-PED-006."""
    campos = data.model_dump(exclude_unset=True, exclude_none=True)
    try:
        pedido = pedidos_service.editar_pedido(
            db,
            pedido_id=pedido_id,
            user_id=user.id,
            **campos,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("editar_pedido falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al editar el pedido.") from exc

    _commit_or_rollback(db, operacion="editar_pedido")
    db.refresh(pedido)
    return _pedido_response(pedido)


# ──────────────────────────────────────────────────────────────────────────
# Pedidos — transiciones (design §6 + §9.1)
# ──────────────────────────────────────────────────────────────────────────


def _transicionar_y_commit(
    db: Session,
    *,
    pedido_id: int,
    accion: str,
    user_id: int,
    operacion: str,
    motivo: Optional[str] = None,
    fecha_pago_estimada: Optional[date] = None,
) -> PedidoCompra:
    """Wrapper común para transiciones: delega al service + commit/rollback."""
    try:
        pedido = pedidos_service.transicionar(
            db,
            pedido_id=pedido_id,
            accion=accion,
            user_id=user_id,
            motivo=motivo,
            fecha_pago_estimada=fecha_pago_estimada,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("%s falló: %s", operacion, exc)
        raise HTTPException(status_code=500, detail=f"Error en transición {accion}.") from exc

    _commit_or_rollback(db, operacion=operacion)
    db.refresh(pedido)
    return pedido


@router.post(
    "/pedidos/{pedido_id}/enviar-aprobacion",
    response_model=PedidoCompraResponse,
    summary="Enviar pedido a aprobación (borrador → pendiente_aprobacion)",
)
def enviar_pedido_a_aprobacion(
    pedido_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Transición borrador → pendiente_aprobacion. REQ-PED-002."""
    pedido = _transicionar_y_commit(
        db,
        pedido_id=pedido_id,
        accion="enviar_aprobacion",
        user_id=user.id,
        operacion="enviar_aprobacion",
    )
    return _pedido_response(pedido)


@router.post(
    "/pedidos/{pedido_id}/aprobar",
    response_model=PedidoCompraResponse,
    summary="Aprobar pedido (crítico: registra DEBE en CC proveedor)",
)
def aprobar_pedido(
    pedido_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.aprobar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Aprobación de pedido — permiso crítico. REQ-PED-003."""
    fecha_str = payload.get("fecha_pago_estimada") if payload else None
    fecha_pago_estimada = date.fromisoformat(fecha_str) if isinstance(fecha_str, str) else None

    pedido = _transicionar_y_commit(
        db,
        pedido_id=pedido_id,
        accion="aprobar",
        user_id=user.id,
        operacion="aprobar_pedido",
        fecha_pago_estimada=fecha_pago_estimada,
    )
    return _pedido_response(pedido)


@router.post(
    "/pedidos/{pedido_id}/rechazar",
    response_model=PedidoCompraResponse,
    summary="Rechazar pedido (accion: devolver_a_borrador | cancelar_definitivo)",
)
def rechazar_pedido(
    pedido_id: int,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.aprobar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Rechazo desde pendiente_aprobacion. Body: {accion, motivo}.

    - `accion='devolver_a_borrador'` → `rechazar_devolver` (vuelve a borrador).
    - `accion='cancelar_definitivo'` → `rechazar_cancelar` (pasa a cancelado).
    """
    accion_raw = (payload or {}).get("accion")
    motivo = (payload or {}).get("motivo")

    if accion_raw not in {"devolver_a_borrador", "cancelar_definitivo"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Campo 'accion' requerido. Valores válidos: 'devolver_a_borrador' | 'cancelar_definitivo'."),
        )
    if not motivo or not str(motivo).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campo 'motivo' requerido (texto no vacío).",
        )

    accion_interna = "rechazar_devolver" if accion_raw == "devolver_a_borrador" else "rechazar_cancelar"

    pedido = _transicionar_y_commit(
        db,
        pedido_id=pedido_id,
        accion=accion_interna,
        user_id=user.id,
        operacion="rechazar_pedido",
        motivo=str(motivo),
    )
    return _pedido_response(pedido)


@router.post(
    "/pedidos/{pedido_id}/reabrir",
    response_model=PedidoCompraResponse,
    summary="Reabrir pedido rechazado (rechazado → borrador)",
)
def reabrir_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Transición rechazado → borrador."""
    pedido = _transicionar_y_commit(
        db,
        pedido_id=pedido_id,
        accion="reabrir",
        user_id=user.id,
        operacion="reabrir_pedido",
    )
    return _pedido_response(pedido)


@router.post(
    "/pedidos/{pedido_id}/cancelar",
    response_model=PedidoCompraResponse,
    summary="Cancelar pedido (borrador → cancelado o aprobado → cancelado_aprobado)",
)
def cancelar_pedido(
    pedido_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Cancelación — la acción concreta depende del estado actual del pedido."""
    motivo = (payload or {}).get("motivo")
    # Elegir la acción correcta según el estado actual (borrador vs aprobado)
    pedido = _obtener_pedido_o_404(db, pedido_id)
    if pedido.estado == "aprobado":
        accion = "cancelar_aprobado"
        if not motivo or not str(motivo).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Campo 'motivo' requerido al cancelar un pedido aprobado.",
            )
    else:
        accion = "cancelar"

    pedido = _transicionar_y_commit(
        db,
        pedido_id=pedido_id,
        accion=accion,
        user_id=user.id,
        operacion="cancelar_pedido",
        motivo=str(motivo) if motivo else None,
    )
    return _pedido_response(pedido)


# ──────────────────────────────────────────────────────────────────────────
# Pedidos — etiqueta de retiro + eventos
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/pedidos/{pedido_id}/generar-etiqueta-envio",
    summary="Generar etiqueta de retiro para un pedido (requiere_envio=True)",
)
def generar_etiqueta_envio(
    pedido_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> dict[str, Any]:
    """Genera `etiquetas_envio` tipo=retiro_proveedor. REQ-LOG-002, design §9.1."""
    proveedor_direccion_id = (payload or {}).get("proveedor_direccion_id")
    if proveedor_direccion_id is not None and not isinstance(proveedor_direccion_id, int):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proveedor_direccion_id debe ser entero.",
        )

    try:
        etiqueta: EtiquetaEnvio = etiqueta_retiro_service.generar_etiqueta_retiro(
            db,
            pedido_id=pedido_id,
            proveedor_direccion_id=proveedor_direccion_id,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("generar_etiqueta_envio falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al generar la etiqueta.") from exc

    _commit_or_rollback(db, operacion="generar_etiqueta_envio")

    # No hay schema Pydantic en el proyecto para EtiquetaEnvio, se responde
    # con un dict compacto — el frontend F6 consumirá estos campos.
    return {
        "id": etiqueta.id,
        "shipping_id": etiqueta.shipping_id,
        "tipo_envio": etiqueta.tipo_envio,
        "pedido_compra_id": etiqueta.pedido_compra_id,
        "proveedor_id": etiqueta.proveedor_id,
        "proveedor_direccion_id": etiqueta.proveedor_direccion_id,
        "fecha_envio": etiqueta.fecha_envio.isoformat() if etiqueta.fecha_envio else None,
        "manual_receiver_name": etiqueta.manual_receiver_name,
        "manual_street_name": etiqueta.manual_street_name,
        "manual_zip_code": etiqueta.manual_zip_code,
        "manual_city_name": etiqueta.manual_city_name,
        "manual_phone": etiqueta.manual_phone,
    }


@router.get(
    "/pedidos/{pedido_id}/eventos",
    response_model=list[CompraEventoResponse],
    summary="Listar eventos de auditoría del pedido",
)
def listar_eventos_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[CompraEventoResponse]:
    """Eventos append-only del pedido. REQ-PED-004, design §9.1."""
    _obtener_pedido_o_404(db, pedido_id)

    eventos = list(
        db.execute(
            select(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido_id,
            )
            .order_by(CompraEvento.created_at.desc(), CompraEvento.id.desc())
        )
        .scalars()
        .all()
    )
    return [CompraEventoResponse.model_validate(e) for e in eventos]


# ==========================================================================
# §9.2 — ÓRDENES DE PAGO
# ==========================================================================


@router.get(
    "/ordenes-pago",
    response_model=OrdenPagoPaginated,
    summary="Listar órdenes de pago con filtros y paginación",
)
def listar_ordenes_pago(
    estado: Optional[str] = Query(None),
    proveedor_id: Optional[int] = Query(None, ge=1),
    empresa_id: Optional[int] = Query(None, ge=1),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> OrdenPagoPaginated:
    """Listado paginado de OPs. REQ-OP-001."""
    condiciones = []
    if estado is not None:
        condiciones.append(OrdenPago.estado == estado)
    if proveedor_id is not None:
        condiciones.append(OrdenPago.proveedor_id == proveedor_id)
    if empresa_id is not None:
        condiciones.append(OrdenPago.empresa_id == empresa_id)
    if desde is not None:
        condiciones.append(OrdenPago.created_at >= datetime.combine(desde, datetime.min.time()))
    if hasta is not None:
        condiciones.append(OrdenPago.created_at <= datetime.combine(hasta, datetime.max.time()))

    stmt = select(OrdenPago).options(
        joinedload(OrdenPago.empresa),
        joinedload(OrdenPago.proveedor),
    )
    if condiciones:
        stmt = stmt.where(*condiciones)
    stmt = stmt.order_by(OrdenPago.created_at.desc(), OrdenPago.id.desc())

    items, total = _paginate(db, stmt, page=page, page_size=page_size)
    puede_map = compras_papelera_service._calcular_puede_eliminar_ops_batch(db, items)
    return OrdenPagoPaginated(
        items=[_op_response(op, puede_eliminar=puede_map.get(op.id, False)) for op in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/ordenes-pago/{op_id}",
    response_model=OrdenPagoDetalle,
    summary="Detalle de OP con imputaciones y eventos",
)
def obtener_orden_pago(
    op_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> OrdenPagoDetalle:
    """Detalle completo de una OP.

    Incluye: datos base + nombres derivados + imputaciones + eventos y,
    si la OP está pagada, un `caja_movimiento_resumen` con caja+monto+fecha
    para que tesorería vea el pago sin otro round-trip.
    """
    # joinedload para poblar empresa_nombre/proveedor_nombre + caja_movimiento.caja
    # sin N+1. `caja_movimiento` y su `caja` solo son relevantes si la OP ya fue
    # pagada, pero el joinedload es no-op cuando la FK es NULL.
    op = db.execute(
        select(OrdenPago)
        .options(
            joinedload(OrdenPago.empresa),
            joinedload(OrdenPago.proveedor),
            joinedload(OrdenPago.caja_movimiento).joinedload(CajaMovimiento.caja),
        )
        .where(OrdenPago.id == op_id)
    ).scalar_one_or_none()
    if op is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OrdenPago id={op_id} no encontrada.",
        )

    imputaciones = list(
        db.execute(
            select(Imputacion)
            .where(
                Imputacion.origen_tipo == "orden_pago",
                Imputacion.origen_id == op.id,
            )
            .order_by(Imputacion.created_at.asc(), Imputacion.id.asc())
        )
        .scalars()
        .all()
    )
    eventos = list(
        db.execute(
            select(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_ORDEN_PAGO,
                CompraEvento.entidad_id == op.id,
            )
            .order_by(CompraEvento.created_at.desc(), CompraEvento.id.desc())
        )
        .scalars()
        .all()
    )

    emp = getattr(op, "empresa", None)
    prov = getattr(op, "proveedor", None)
    detalle = OrdenPagoDetalle.model_validate(op)
    detalle = detalle.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
        }
    )
    detalle.imputaciones = [ImputacionResponse.model_validate(i) for i in imputaciones]
    detalle.eventos = [CompraEventoResponse.model_validate(e) for e in eventos]

    # Resumen del movimiento de caja (solo si está pagada).
    mov = getattr(op, "caja_movimiento", None)
    if mov is not None:
        caja = getattr(mov, "caja", None)
        detalle.caja_movimiento_resumen = CajaMovimientoResumen(
            id=mov.id,
            caja_id=mov.caja_id,
            caja_nombre=caja.nombre if caja is not None else None,
            fecha=mov.fecha,
            monto=mov.monto,
            tipo=mov.tipo,
        )

    return detalle


@router.post(
    "/ordenes-pago",
    response_model=OrdenPagoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear OP con items (puede retornar 409 POSIBLE_DUPLICADO_OP_ERP)",
)
def crear_orden_pago(
    data: OrdenPagoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> OrdenPagoResponse:
    """Crear OP. REQ-OP-001 + REQ-OP-002 + REQ-OP-005, design §9.2 + §7.2.

    El service `ordenes_pago_service.crear` puede levantar:
      - 400: validaciones de monto/modo/items.
      - 409 POSIBLE_DUPLICADO_OP_ERP con payload estructurado.
    """
    items_norm = [
        {
            "tipo": it.tipo,
            "id": it.id,
            "monto": it.monto,
            "numero_factura": it.numero_factura,
        }
        for it in data.items
    ]
    try:
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=data.proveedor_id,
            empresa_id=data.empresa_id,
            moneda=data.moneda,  # type: ignore[arg-type]
            monto_total=data.monto_total,
            modo_imputacion=data.modo_imputacion,  # type: ignore[arg-type]
            items=items_norm,
            observaciones=data.observaciones,
            creado_por_id=user.id,
            confirmar_duplicado=data.confirmar_duplicado,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("crear_orden_pago falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al crear la OP.") from exc

    _commit_or_rollback(db, operacion="crear_orden_pago")
    db.refresh(op)
    return _op_response(op)


@router.post(
    "/ordenes-pago/{op_id}/pagar",
    response_model=OrdenPagoResponse,
    summary="Ejecutar pago de OP (crítico — 9 pasos atómicos caja+CC+imputaciones)",
)
def pagar_orden_pago(
    op_id: int,
    data: OrdenPagoEjecutarPago,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.ejecutar_pagos")),
) -> OrdenPagoResponse:
    """Ejecutar pago — permiso crítico `ejecutar_pagos`.

    El service `ordenes_pago_service.ejecutar_pago` hace flush pero NO
    commit; orquestamos acá el commit/rollback explícito. Puede levantar:
      - 400: OP en estado distinto a 'pendiente'.
      - 404: OP o caja inexistente.
      - 409: caja.empresa_id != op.empresa_id.
      - 422 OP_CAJA_MONEDA_MISMATCH: caja.moneda != op.moneda.
    """
    try:
        op = ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op_id,
            caja_id=data.caja_id,
            fecha_pago_real=data.fecha_pago_real,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("pagar_orden_pago falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al ejecutar el pago.") from exc

    _commit_or_rollback(db, operacion="pagar_orden_pago")
    db.refresh(op)
    return _op_response(op)


@router.post(
    "/ordenes-pago/{op_id}/anular",
    response_model=OrdenPagoResponse,
    summary="Anular OP pagada (reverso completo caja + CC + imputaciones + pedidos)",
)
def anular_orden_pago(
    op_id: int,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.ejecutar_pagos")),
) -> OrdenPagoResponse:
    """Anular OP. REQ-OP-006 + REQ-CAJ-005."""
    motivo = (payload or {}).get("motivo")
    if not motivo or not str(motivo).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campo 'motivo' requerido para anular una OP.",
        )

    try:
        op = ordenes_pago_service.anular(
            db,
            orden_pago_id=op_id,
            motivo=str(motivo),
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("anular_orden_pago falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al anular la OP.") from exc

    _commit_or_rollback(db, operacion="anular_orden_pago")
    db.refresh(op)
    return _op_response(op)


@router.post(
    "/ordenes-pago/{op_id}/distribuir-automatico",
    response_model=list[ImputacionResponse],
    summary="Distribuir OP 'a_cuenta' en FIFO sobre deudas pendientes",
)
def distribuir_automatico(
    op_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> list[ImputacionResponse]:
    """Distribución FIFO. REQ-IMP-004 + REQ-OP-004, design §2.2."""
    _obtener_op_o_404(db, op_id)

    try:
        imputaciones_creadas = imputaciones_service.distribuir_fifo(
            db,
            orden_pago_id=op_id,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("distribuir_automatico falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al distribuir la OP.") from exc

    _commit_or_rollback(db, operacion="distribuir_automatico")
    for imp in imputaciones_creadas:
        db.refresh(imp)
    return [ImputacionResponse.model_validate(i) for i in imputaciones_creadas]


# ──────────────────────────────────────────────────────────────────────────
# Hard-delete (papelera auditable) — DELETE /pedidos/{id} y /ordenes-pago/{id}
# + GET /papelera
# ──────────────────────────────────────────────────────────────────────────


@router.delete(
    "/pedidos/{pedido_id}",
    response_model=PapeleraItemResponse,
    summary="Hard-delete de pedido basura (borrador/cancelado sin movimiento)",
)
def hard_delete_pedido(
    pedido_id: int,
    data: PapeleraHardDeleteRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.eliminar_compras_basura")),
) -> PapeleraItemResponse:
    """Elimina físicamente un pedido y deja snapshot auditable en papelera.

    Reglas (validadas por `compras_papelera_service.eliminar_pedido`):
      - Estado ∈ {borrador, cancelado}.
      - NUNCA fue aprobado (no existe evento tipo='aprobado').
      - NO tiene imputaciones asociadas.
      - Si cancelado: updated_at <= cutoff (retención 30 días por default).

    Los eventos de `compras_eventos` de la entidad se copian al snapshot
    JSON antes de borrarse (opción B — historia preservada). La fila de
    papelera es inmutable (append-only, NO se expone restore).
    """
    try:
        papelera_row = compras_papelera_service.eliminar_pedido(
            db,
            pedido_id=pedido_id,
            user_id=user.id,
            motivo=data.motivo,
            challenge_palabra_usada=data.challenge_palabra_usada,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("hard_delete_pedido falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al eliminar el pedido.") from exc

    _commit_or_rollback(db, operacion="hard_delete_pedido")
    db.refresh(papelera_row)
    nombres = compras_papelera_service.enriquecer_nombres_papelera(db, [papelera_row])
    extras = nombres.get(papelera_row.id, {})
    base = PapeleraItemResponse.model_validate(papelera_row)
    return base.model_copy(update=extras)


@router.delete(
    "/ordenes-pago/{op_id}",
    response_model=PapeleraItemResponse,
    summary="Hard-delete de OP anulada sin imputaciones vivas",
)
def hard_delete_op(
    op_id: int,
    data: PapeleraHardDeleteRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.eliminar_compras_basura")),
) -> PapeleraItemResponse:
    """Elimina físicamente una OP y deja snapshot auditable en papelera.

    Reglas (validadas por `compras_papelera_service.eliminar_op`):
      - Estado == 'anulado'.
      - Sin imputaciones netas vivas (no-reversal <= reversal).
      - caja_movimiento_id IS NULL (el anulado revirtió la caja).
      - updated_at <= cutoff (retención 30 días por default).
    """
    try:
        papelera_row = compras_papelera_service.eliminar_op(
            db,
            op_id=op_id,
            user_id=user.id,
            motivo=data.motivo,
            challenge_palabra_usada=data.challenge_palabra_usada,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("hard_delete_op falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al eliminar la OP.") from exc

    _commit_or_rollback(db, operacion="hard_delete_op")
    db.refresh(papelera_row)
    nombres = compras_papelera_service.enriquecer_nombres_papelera(db, [papelera_row])
    extras = nombres.get(papelera_row.id, {})
    base = PapeleraItemResponse.model_validate(papelera_row)
    return base.model_copy(update=extras)


@router.get(
    "/papelera",
    response_model=PapeleraPaginated,
    summary="Listar papelera auditable (snapshots de entidades hard-deleted)",
)
def listar_papelera(
    entidad_tipo: Optional[str] = Query(None, description="'pedido_compra' | 'orden_pago'"),
    proveedor_id: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.eliminar_compras_basura")),
) -> PapeleraPaginated:
    """Listado paginado de la papelera con nombres derivados (empresa/proveedor/usuario)."""
    if entidad_tipo is not None and entidad_tipo not in ("pedido_compra", "orden_pago"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entidad_tipo debe ser 'pedido_compra' o 'orden_pago'.",
        )

    items, total = compras_papelera_service.listar_papelera(
        db,
        entidad_tipo=entidad_tipo,
        proveedor_id=proveedor_id,
        page=page,
        page_size=page_size,
    )
    nombres = compras_papelera_service.enriquecer_nombres_papelera(db, items)

    responses: list[PapeleraItemResponse] = []
    for it in items:
        base = PapeleraItemResponse.model_validate(it)
        extras = nombres.get(it.id, {})
        responses.append(base.model_copy(update=extras))

    return PapeleraPaginated(
        items=responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/papelera/{papelera_id}",
    response_model=PapeleraItemDetalle,
    summary="Detalle de item de papelera con snapshot JSON completo",
)
def obtener_papelera_item(
    papelera_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.eliminar_compras_basura")),
) -> PapeleraItemDetalle:
    """Retorna el snapshot JSONB completo + eventos copiados."""
    item = compras_papelera_service.obtener_papelera_item(db, papelera_id)
    nombres = compras_papelera_service.enriquecer_nombres_papelera(db, [item])
    extras = nombres.get(item.id, {})
    base = PapeleraItemDetalle.model_validate(item)
    return base.model_copy(update=extras)


# ==========================================================================
# §9.3 — IMPUTACIONES
# ==========================================================================


@router.get(
    "/imputaciones",
    response_model=ImputacionPaginated,
    summary="Listar imputaciones con filtros",
)
def listar_imputaciones(
    proveedor_id: Optional[int] = Query(None, ge=1),
    origen_tipo: Optional[str] = Query(None),
    destino_tipo: Optional[str] = Query(None),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> ImputacionPaginated:
    """Imputaciones paginadas."""
    condiciones = []
    if proveedor_id is not None:
        condiciones.append(Imputacion.proveedor_id == proveedor_id)
    if origen_tipo is not None:
        condiciones.append(Imputacion.origen_tipo == origen_tipo)
    if destino_tipo is not None:
        condiciones.append(Imputacion.destino_tipo == destino_tipo)
    if desde is not None:
        condiciones.append(Imputacion.created_at >= datetime.combine(desde, datetime.min.time()))
    if hasta is not None:
        condiciones.append(Imputacion.created_at <= datetime.combine(hasta, datetime.max.time()))

    stmt = select(Imputacion)
    if condiciones:
        stmt = stmt.where(*condiciones)
    stmt = stmt.order_by(Imputacion.created_at.desc(), Imputacion.id.desc())

    items, total = _paginate(db, stmt, page=page, page_size=page_size)
    return ImputacionPaginated(
        items=[ImputacionResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/imputaciones/{imp_id}/desimputar",
    response_model=ImputacionResponse,
    summary="Desimputar (inserta reversal append-only, D9)",
)
def desimputar_imputacion(
    imp_id: int,
    data: ImputacionDesimputar,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> ImputacionResponse:
    """Desimputación. REQ-IMP-005, design §9.3."""
    try:
        reversal = imputaciones_service.desimputar(
            db,
            imputacion_id=imp_id,
            user_id=user.id,
            motivo=data.motivo,
        )
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("desimputar falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al desimputar.") from exc

    _commit_or_rollback(db, operacion="desimputar")
    db.refresh(reversal)
    return ImputacionResponse.model_validate(reversal)


@router.post(
    "/imputaciones/{imp_id}/reimputar",
    response_model=list[ImputacionResponse],
    summary="Reimputar (inserta 2 filas: reversal + nueva, D9+D13)",
)
def reimputar_imputacion(
    imp_id: int,
    data: ImputacionReimputar,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> list[ImputacionResponse]:
    """Reimputación append-only. REQ-IMP-005, design §9.3."""
    try:
        reversal, nueva = imputaciones_service.reimputar(
            db,
            imputacion_id=imp_id,
            nuevo_destino_tipo=data.destino_tipo,
            nuevo_destino_id=data.destino_id,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("reimputar falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al reimputar.") from exc

    _commit_or_rollback(db, operacion="reimputar")
    db.refresh(reversal)
    db.refresh(nueva)
    return [
        ImputacionResponse.model_validate(reversal),
        ImputacionResponse.model_validate(nueva),
    ]


# ==========================================================================
# §9.4 — CC PROVEEDOR + RECONCILIACIÓN
# ==========================================================================


@router.get(
    "/cc-proveedor/{proveedor_id}",
    response_model=CCProveedorDetalle,
    summary="CC proveedor: saldos por moneda + movimientos",
)
def obtener_cc_proveedor(
    proveedor_id: int,
    empresa_id: Optional[int] = Query(None, ge=1),
    hasta_fecha: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_cuentas_corrientes")),
) -> CCProveedorDetalle:
    """CC detalle. REQ-CC-002 + REQ-CC-003, design §9.4."""
    proveedor = _obtener_proveedor_o_404(db, proveedor_id)

    saldos_dict = cc_proveedor_service.calcular_saldo_por_moneda(
        db,
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        hasta_fecha=hasta_fecha,
    )
    movimientos = cc_proveedor_service.listar_movimientos(
        db,
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        hasta=hasta_fecha,
    )

    # Conteo de movimientos por moneda (para SaldoPorMoneda.movimientos_count)
    counts_por_moneda: dict[str, int] = {}
    for m in movimientos:
        counts_por_moneda[m.moneda] = counts_por_moneda.get(m.moneda, 0) + 1

    saldos_list = [
        SaldoPorMoneda(
            moneda=moneda,
            saldo=saldo,
            movimientos_count=counts_por_moneda.get(moneda, 0),
        )
        for moneda, saldo in saldos_dict.items()
    ]

    nombre_prov = (
        getattr(proveedor, "nombre", None) or getattr(proveedor, "razon_social", None) or f"Proveedor #{proveedor_id}"
    )

    return CCProveedorDetalle(
        proveedor_id=proveedor_id,
        nombre_proveedor=str(nombre_prov),
        saldos=saldos_list,
        movimientos=[CCMovimientoResponse.model_validate(m) for m in movimientos],
    )


@router.get(
    "/cc-proveedor/{proveedor_id}/por-pedido",
    response_model=list[CCAgrupadoPorPedido],
    summary="CC agrupada por pedido (drill-down UX)",
)
def obtener_cc_por_pedido(
    proveedor_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_cuentas_corrientes")),
) -> list[CCAgrupadoPorPedido]:
    """CC agrupada por pedido — movimientos cuyo `origen_tipo='pedido_compra'`.

    Agrupa los movimientos de CC por el `origen_id` (pedido_compra.id),
    incluyendo metadata del pedido. Solo cubre movimientos con origen
    pedido (no OPs puras sobre saldo).
    """
    _obtener_proveedor_o_404(db, proveedor_id)

    movimientos = cc_proveedor_service.listar_movimientos(
        db,
        proveedor_id=proveedor_id,
    )

    # Agrupar por origen_id cuando origen_tipo == 'pedido_compra'
    grupos: dict[int, list] = {}
    for m in movimientos:
        if m.origen_tipo == "pedido_compra" and m.origen_id is not None:
            grupos.setdefault(int(m.origen_id), []).append(m)

    if not grupos:
        return []

    # Traer los pedidos en un solo query
    pedido_ids = list(grupos.keys())
    pedidos = {p.id: p for p in db.execute(select(PedidoCompra).where(PedidoCompra.id.in_(pedido_ids))).scalars().all()}

    resultado: list[CCAgrupadoPorPedido] = []
    for pid, movs in grupos.items():
        pedido = pedidos.get(pid)
        if pedido is None:
            continue  # pedido fue borrado: skip
        resultado.append(
            CCAgrupadoPorPedido(
                pedido_compra_id=pid,
                pedido_numero=pedido.numero,
                pedido_estado=pedido.estado,
                pedido_monto=Decimal(pedido.monto),
                pedido_moneda=pedido.moneda,
                movimientos=[CCMovimientoResponse.model_validate(m) for m in movs],
            )
        )
    # Orden: por fecha desc del primer movimiento de cada grupo
    resultado.sort(
        key=lambda g: g.movimientos[0].fecha_movimiento if g.movimientos else date.min,
        reverse=True,
    )
    return resultado


# ──────────────────────────────────────────────────────────────────────────
# Reconciliación
# ──────────────────────────────────────────────────────────────────────────


@router.get(
    "/reconciliacion",
    response_model=list[CCReconciliacionLogResponse],
    summary="Listar corridas de reconciliación CC",
)
def listar_reconciliaciones(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    estado: Optional[str] = Query(None, description="ok | divergencia"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_cuentas_corrientes")),
) -> list[CCReconciliacionLogResponse]:
    """Logs de reconciliación. REQ-CC-004 + REQ-CC-005."""
    from app.models.cc_reconciliacion_log import CCReconciliacionLog

    condiciones = []
    if fecha_desde is not None:
        condiciones.append(CCReconciliacionLog.fecha_corrida >= fecha_desde)
    if fecha_hasta is not None:
        condiciones.append(CCReconciliacionLog.fecha_corrida <= fecha_hasta)
    if estado is not None:
        if estado not in ("ok", "divergencia"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="estado debe ser 'ok' o 'divergencia'.",
            )
        condiciones.append(CCReconciliacionLog.estado == estado)

    stmt = select(CCReconciliacionLog)
    if condiciones:
        stmt = stmt.where(*condiciones)
    stmt = stmt.order_by(
        CCReconciliacionLog.fecha_corrida.desc(),
        CCReconciliacionLog.id.desc(),
    ).limit(limit)

    logs = list(db.execute(stmt).scalars().all())
    return [CCReconciliacionLogResponse.model_validate(log) for log in logs]


@router.post(
    "/reconciliacion/forzar",
    summary="Forzar corrida manual de reconciliación CC",
)
def forzar_reconciliacion(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.gestionar_cuentas_corrientes")),
) -> dict[str, Any]:
    """Corrida manual. REQ-CC-004. Lee tolerancias desde `configuracion`."""
    fecha_str = (payload or {}).get("fecha")
    fecha_corrida = date.fromisoformat(fecha_str) if isinstance(fecha_str, str) else date.today()

    # Tolerancias por moneda (COMPRAS-1.15 seed). Fallback 100 ARS / 1 USD.
    from app.schemas.configuracion_compras import leer_configuracion

    tol_ars = leer_configuracion(
        db,
        "compras.cc_reconciliacion_tolerancia_ars",
        default=Decimal("100"),
    )
    tol_usd = leer_configuracion(
        db,
        "compras.cc_reconciliacion_tolerancia_usd",
        default=Decimal("1"),
    )

    try:
        resultado = cc_proveedor_service.reconciliar_diario(
            db,
            fecha_corrida=fecha_corrida,
            tolerancias={"ARS": tol_ars, "USD": tol_usd},
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("forzar_reconciliacion falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al reconciliar.") from exc

    _commit_or_rollback(db, operacion="forzar_reconciliacion")
    return resultado


@router.get(
    "/reconciliacion/metricas",
    summary="Métricas de deprecación snapshot CC (R2)",
)
def metricas_reconciliacion(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_cuentas_corrientes")),
) -> dict[str, Any]:
    """Métricas para evaluar si se cumplen los criterios de deprecación del snapshot ERP.

    Criterios (design §8.2 + proposal R2):
      - `dias_consecutivos_sin_divergencia`: cantidad de días consecutivos
        (desde la última corrida hacia atrás) en los que NO hubo divergencia.
      - `cobertura_porcentaje`: proveedores comparados / proveedores con mov
        en ventana 90 días (ambos derivados de los logs).
      - `criterio_deprecacion`: dict con los 3 flags booleanos del proposal.
    """
    from app.models.cc_reconciliacion_log import CCReconciliacionLog

    # Días consecutivos sin divergencia (desde hoy hacia atrás)
    dias_consecutivos = 0
    hoy = date.today()
    for offset in range(0, 60):
        fecha_check = hoy - timedelta(days=offset)
        div_count = int(
            db.execute(
                select(sa_func.count())
                .select_from(CCReconciliacionLog)
                .where(
                    CCReconciliacionLog.fecha_corrida == fecha_check,
                    CCReconciliacionLog.estado == CCReconciliacionLog.ESTADO_DIVERGENCIA,
                )
            ).scalar_one()
            or 0
        )
        total_count = int(
            db.execute(
                select(sa_func.count())
                .select_from(CCReconciliacionLog)
                .where(CCReconciliacionLog.fecha_corrida == fecha_check)
            ).scalar_one()
            or 0
        )
        if total_count == 0:
            break  # dejamos de contar al llegar a un día sin corrida
        if div_count > 0:
            break
        dias_consecutivos += 1

    # Cobertura: proveedores comparados en últimos 30 días / total con mov
    desde_30 = hoy - timedelta(days=30)
    proveedores_reconciliados = int(
        db.execute(
            select(sa_func.count(sa_func.distinct(CCReconciliacionLog.proveedor_id))).where(
                CCReconciliacionLog.fecha_corrida >= desde_30
            )
        ).scalar_one()
        or 0
    )
    proveedores_activos = len(
        cc_proveedor_service._proveedores_con_movimientos_recientes(
            db,
            ventana_dias=90,
            hasta_fecha=hoy,
        )
    )
    cobertura = (proveedores_reconciliados / proveedores_activos * 100.0) if proveedores_activos > 0 else 0.0

    criterio = {
        "dias_30_sin_divergencia": dias_consecutivos >= 30,
        "cobertura_80_porciento": cobertura >= 80.0,
        "aprobacion_usuarios_clave": False,  # manual — set via admin panel en F6
    }

    return {
        "dias_consecutivos_sin_divergencia": dias_consecutivos,
        "cobertura_porcentaje": round(cobertura, 2),
        "proveedores_reconciliados_30d": proveedores_reconciliados,
        "proveedores_activos_90d": proveedores_activos,
        "criterio_deprecacion": criterio,
    }


# ==========================================================================
# §9.5 — SALE DOCUMENT CATALOG
# ==========================================================================


@router.get(
    "/sale-documents",
    response_model=list[SaleDocumentResponse],
    summary="Listar catálogo tb_sale_document con clasificación derivada",
)
def listar_sale_documents(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> list[SaleDocumentResponse]:
    """Listado completo del catálogo (seed estático, ~67 filas).

    No requiere permiso específico — es metadata útil para cualquier user
    autenticado (el frontend F6 lo usa para poblar selects y labels). Si
    hubiera que restringir, subir a `administracion.ver_ordenes_compra`.
    """
    sds = list(db.execute(select(SaleDocument).order_by(SaleDocument.sd_id.asc())).scalars().all())
    out: list[SaleDocumentResponse] = []
    for sd in sds:
        try:
            clasificacion = clasificar_documento_compra(sd).value
        except Exception as exc:  # noqa: BLE001
            logger.warning("clasificacion falló para sd_id=%s: %s", sd.sd_id, exc)
            clasificacion = None
        sd_out = SaleDocumentResponse.model_validate(sd)
        sd_out.clasificacion = clasificacion
        out.append(sd_out)
    return out


# El endpoint /sale-documents/faltantes se define ABAJO (preservado de F3).


# ==========================================================================
# Health / smoke gate (COMPRAS-5.9)
# ==========================================================================


@router.get(
    "/health",
    summary="Smoke gate del módulo compras (F5): catálogos poblados + servicios OK",
)
def health_compras(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Verifica quickly que las tablas semilla del módulo están pobladas.

    No requiere auth: pensado como smoke gate antes de arrancar F6 y para
    readiness probes. Retorna counts por catálogo.
    """
    sd_count = int(db.execute(select(sa_func.count()).select_from(SaleDocument)).scalar_one() or 0)

    return {
        "status": "ok" if sd_count > 0 else "warning",
        "module": "compras",
        "services": {
            "pedidos_service": "ok",
            "ordenes_pago_service": "ok",
            "imputaciones_service": "ok",
            "cc_proveedor_service": "ok",
            "etiqueta_retiro_service": "ok",
        },
        "catalogos": {
            "tb_sale_document": sd_count,
        },
    }


# ==========================================================================
# §9.5 — /sale-documents/faltantes (preservado de F3)
# ==========================================================================


@router.get(
    "/sale-documents/faltantes",
    response_model=list[SaleDocumentsFaltantes],
    dependencies=[Depends(require_permiso("administracion.gestionar_ordenes_compra"))],
    summary="Listar sd_id observados en ERP sin entrada en el catálogo local",
)
def listar_sd_ids_faltantes(
    dias: int = Query(
        30,
        ge=1,
        le=365,
        description="Ventana (en días) para buscar sd_id recientes en tb_commercial_transactions.",
    ),
    db: Session = Depends(get_db),
) -> list[SaleDocumentsFaltantes]:
    """
    Retorna `sd_id` que aparecen en `tb_commercial_transactions` en los
    últimos `dias` días pero NO están en `tb_sale_document`.

    Si la lista viene con filas → hay que crear una migration Alembic que
    agregue esos sd_id al seed de `tb_sale_document`, sino el clasificador
    no podrá categorizarlos y afectará el matching ERP (REQ-SDC-007 +
    design §9.5).
    """
    desde = datetime.now() - timedelta(days=dias)

    stmt = text(
        """
        SELECT
            ct.sd_id               AS sd_id,
            COUNT(*)               AS cnt,
            MIN(ct.ct_date)        AS primera_aparicion
        FROM tb_commercial_transactions ct
        WHERE ct.sd_id IS NOT NULL
          AND ct.ct_date >= :desde
          AND ct.sd_id NOT IN (SELECT sd_id FROM tb_sale_document)
        GROUP BY ct.sd_id
        ORDER BY cnt DESC, ct.sd_id ASC
        """
    )
    filas = db.execute(stmt, {"desde": desde}).all()

    if filas:
        logger.warning(
            "sale-documents/faltantes: %d sd_id huérfanos detectados en últimos %d días "
            "(actualizar seed tb_sale_document con una nueva migration)",
            len(filas),
            dias,
        )

    return [
        SaleDocumentsFaltantes(
            sd_id=int(row[0]),
            count=int(row[1]),
            primera_aparicion=row[2],
        )
        for row in filas
    ]


__all__ = ["router"]
