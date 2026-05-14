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

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func as sa_func
from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_permiso
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.caja import CajaMovimiento
from app.models.compra_adjunto import CompraAdjunto
from app.models.compra_evento import CompraEvento
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.tb_sale_document import SaleDocument
from app.models.usuario import Usuario
from app.schemas.cc_proveedor import (  # noqa: I001
    AjusteCCManualRequest,
    PagoRapidoRequest,
    CCAgrupadoPorPedido,
    CCMovimientoResponse,
    CCProveedorDetalle,
    CCReconciliacionLogResponse,
    SaldoPorMoneda,
)
from app.schemas.compra_adjunto import CompraAdjuntoResponse
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
from app.schemas.nota_credito_local import (
    AplicarNCRequest,
    NCDisponibleSummary,
    NCErpCandidataResponse,
    NotaCreditoLocalCreate,
    NotaCreditoLocalDetalle,
    NotaCreditoLocalPaginated,
    NotaCreditoLocalResponse,
    NotaCreditoLocalUpdate,
    VincularFacturaNCRequest,
)
from app.schemas.orden_pago import (
    CajaMovimientoResumen,
    OrdenPagoCancelarPendiente,
    OrdenPagoCreate,
    OrdenPagoDetalle,
    OrdenPagoEditar,
    OrdenPagoEjecutarPago,
    OrdenPagoPaginated,
    OrdenPagoResponse,
)
from app.schemas.pedido_compra import (
    CorreccionPedidoRequest,
    DocumentoERPImputado,
    FacturaCandidataResponse,
    PedidoCompraCreate,
    PedidoCompraDetalle,
    PedidoCompraPaginated,
    PedidoCompraResponse,
    PedidoCompraUpdate,
    VincularFacturaRequest,
)
from app.schemas.sale_document import SaleDocumentResponse, SaleDocumentsFaltantes
from app.services import (
    cc_proveedor_service,
    compras_adjuntos_service,
    compras_papelera_service,
    etiqueta_retiro_service,
    imputaciones_service,
    ncs_locales_service,
    ordenes_pago_service,
    pedidos_service,
)
from app.models.nota_credito_local import NotaCreditoLocal
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


def _pedido_response(
    p: PedidoCompra,
    *,
    puede_eliminar: bool = False,
    saldo_pendiente: Optional[Decimal] = None,
    tipo_cambio_ponderado: Optional[Decimal] = None,
) -> PedidoCompraResponse:
    """Serializa PedidoCompra incluyendo empresa_nombre / proveedor_nombre.

    `model_validate` en Pydantic v2 no soporta `update=`; usamos
    `model_copy(update=...)` post-validación, que es la API equivalente.
    Si la relación no está cargada (endpoint sin joinedload), `getattr`
    puede disparar lazy-load si la sesión sigue activa; si falla, cae en
    `None` y el frontend muestra fallback "#N".

    `puede_eliminar` lo calcula el caller vía
    `compras_papelera_service._calcular_puede_eliminar_pedidos_batch`
    (opción C — 3 queries fijas sin importar N).

    `saldo_pendiente` lo calcula el caller vía
    `pedidos_service.calcular_saldos_pendientes_batch` (1 query agregada
    sin importar N). Si no se pasa → queda None.

    `tipo_cambio_ponderado` lo calcula el caller vía
    `pedidos_service.calcular_tc_ponderado_pedido_batch` (1 query agregada
    sin importar N). None si el pedido no tiene imps cross-moneda.
    """
    emp = getattr(p, "empresa", None)
    prov = getattr(p, "proveedor", None)
    base = PedidoCompraResponse.model_validate(p)
    return base.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
            "puede_eliminar": puede_eliminar,
            "saldo_pendiente": saldo_pendiente,
            "tipo_cambio_ponderado": tipo_cambio_ponderado,
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
    # Saldo pendiente batch (1 query agregada — sin N+1).
    pedido_ids = [p.id for p in items]
    saldo_imp_map = pedidos_service.calcular_saldos_pendientes_batch(db, pedido_ids)
    # TC ponderado batch (1 query agregada — sin N+1, NFR-001).
    tc_pond_map = pedidos_service.calcular_tc_ponderado_pedido_batch(db, pedido_ids)
    return PedidoCompraPaginated(
        items=[
            _pedido_response(
                p,
                puede_eliminar=puede_map.get(p.id, False),
                saldo_pendiente=Decimal(p.monto) - saldo_imp_map.get(p.id, Decimal(0)),
                tipo_cambio_ponderado=tc_pond_map.get(p.id),
            )
            for p in items
        ],
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
    saldo = pedidos_service.calcular_saldo_pendiente_pedido(db, pedido.id)
    tc_ponderado = pedidos_service.calcular_tc_ponderado_pedido(db, pedido.id)
    detalle = PedidoCompraDetalle.model_validate(pedido)
    detalle = detalle.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
            "saldo_pendiente": saldo,
            "tipo_cambio_ponderado": tc_ponderado,
        }
    )
    detalle.eventos = [CompraEventoResponse.model_validate(e) for e in eventos]
    detalle.imputaciones = _enriquecer_imputaciones(db, list(imputaciones))
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


@router.post(
    "/pedidos/{pedido_id}/corregir",
    response_model=PedidoCompraResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Corregir pedido aprobado/pagado creando un clon (feature D)",
)
def corregir_pedido_endpoint(
    pedido_id: int,
    body: CorreccionPedidoRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Crea un clon del pedido aplicando los `cambios` del body y cancela el
    original. Clonación append-only bidireccional (feature D).

    El clon nace en:
      - `aprobado` si los cambios son cosméticos (factura, fechas, envío,
        observaciones) → transferencia inmediata de imputaciones.
      - `pendiente_aprobacion` si cambia `monto` o `tipo_cambio` →
        imputaciones quedan congeladas en el original hasta que se apruebe
        el clon (opción Z).

    La moneda es inmutable al corregir. Para cambiarla hay que cancelar y
    crear un pedido nuevo.

    Permisos: `administracion.gestionar_ordenes_compra` (quien puede
    gestionar pedidos puede corregirlos).
    """
    cambios = body.model_dump(
        exclude_unset=True,
        exclude={"motivo_correccion"},
    )
    try:
        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=pedido_id,
            cambios=cambios,
            motivo_correccion=body.motivo_correccion,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    db.commit()
    db.refresh(clon)
    return _pedido_response(clon)


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


@router.get(
    "/pedidos/{pedido_id}/documentos-erp-imputados",
    response_model=list[DocumentoERPImputado],
    summary="Lista de documentos (facturas ERP, NCs) imputados al pedido",
)
def listar_documentos_erp_imputados(
    pedido_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[DocumentoERPImputado]:
    """Lista los documentos ERP/locales imputados al pedido (sub-batch 3.1).

    Fuente de verdad: tabla `imputaciones`. Filtra por
    `destino_tipo='pedido_compra' AND destino_id=pedido_id AND es_reversal=False`.

    Enriquece con datos del documento origen:
      - `origen_tipo='orden_pago'` → numero de OP + fecha pago + estado.
      - `origen_tipo='nota_credito_local'` → numero NC + fecha emisión + estado.
      - `origen_tipo='factura_erp'` o si hay ct_transaction en el origen
        → ct_docnumber + ct_date + ct_total.
    """
    from app.models.commercial_transaction import CommercialTransaction  # noqa: PLC0415

    _obtener_pedido_o_404(db, pedido_id)

    # Imputaciones vivas al pedido.
    imps = list(
        db.execute(
            select(Imputacion)
            .where(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == pedido_id,
                Imputacion.es_reversal.is_(False),
            )
            .order_by(Imputacion.created_at.asc(), Imputacion.id.asc())
        )
        .scalars()
        .all()
    )

    # Resolver en batch por tipo de origen para evitar N+1.
    op_ids = {int(i.origen_id) for i in imps if i.origen_tipo == "orden_pago"}
    nc_ids = {int(i.origen_id) for i in imps if i.origen_tipo == "nota_credito_local"}
    ct_ids: set[int] = set()
    for imp in imps:
        if imp.origen_tipo in ("factura_erp", "nota_credito_erp") and imp.origen_id is not None:
            ct_ids.add(int(imp.origen_id))

    ops_map: dict[int, OrdenPago] = {}
    if op_ids:
        for row in db.execute(select(OrdenPago).where(OrdenPago.id.in_(op_ids))).scalars().all():
            ops_map[int(row.id)] = row

    ncs_map: dict[int, NotaCreditoLocal] = {}
    if nc_ids:
        for row in db.execute(select(NotaCreditoLocal).where(NotaCreditoLocal.id.in_(nc_ids))).scalars().all():
            ncs_map[int(row.id)] = row

    cts_map: dict[int, CommercialTransaction] = {}
    if ct_ids:
        try:
            for row in (
                db.execute(select(CommercialTransaction).where(CommercialTransaction.ct_transaction.in_(ct_ids)))
                .scalars()
                .all()
            ):
                cts_map[int(row.ct_transaction)] = row
        except Exception as exc:  # noqa: BLE001
            # Tabla ERP puede no existir en tests: degradamos gracefully.
            logger.debug("listar_documentos_erp_imputados: query ERP falló: %s", exc)

    resultado: list[DocumentoERPImputado] = []
    for imp in imps:
        numero: Optional[str] = None
        fecha: Optional[datetime] = None
        estado: Optional[str] = None
        descripcion: Optional[str] = None
        origen_id_int = int(imp.origen_id) if imp.origen_id is not None else 0

        if imp.origen_tipo == "orden_pago":
            op = ops_map.get(origen_id_int)
            if op is not None:
                numero = op.numero
                if op.fecha_pago_real:
                    fecha = datetime.combine(op.fecha_pago_real, datetime.min.time())
                estado = op.estado
                descripcion = f"OP {op.numero}"
        elif imp.origen_tipo == "nota_credito_local":
            nc = ncs_map.get(origen_id_int)
            if nc is not None:
                numero = nc.numero
                if nc.fecha_emision:
                    fecha = datetime.combine(nc.fecha_emision, datetime.min.time())
                estado = nc.estado
                descripcion = f"NC local {nc.numero}"
        elif imp.origen_tipo in ("factura_erp", "nota_credito_erp"):
            ct = cts_map.get(origen_id_int)
            if ct is not None:
                numero = ct.ct_docNumber
                fecha = ct.ct_date
                descripcion = (
                    f"Factura ERP {ct.ct_docNumber}"
                    if imp.origen_tipo == "factura_erp"
                    else f"NC ERP {ct.ct_docNumber}"
                )
            else:
                numero = f"#{origen_id_int}"
                descripcion = f"{imp.origen_tipo} id={origen_id_int}"

        resultado.append(
            DocumentoERPImputado(
                origen_tipo=imp.origen_tipo,
                origen_id=origen_id_int,
                numero=numero,
                fecha=fecha,
                monto_imputado=Decimal(imp.monto_imputado),
                moneda_imputada=str(imp.moneda_imputada),
                estado=estado,
                descripcion=descripcion,
            )
        )

    return resultado


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
    detalle.imputaciones = _enriquecer_imputaciones(db, list(imputaciones))
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


@router.put(
    "/ordenes-pago/{op_id}",
    response_model=OrdenPagoResponse,
    summary="Editar OP en estado 'pendiente' (409 si ya fue pagada/anulada/cancelada)",
)
def editar_orden_pago(
    op_id: int,
    data: OrdenPagoEditar,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> OrdenPagoResponse:
    """Editar OP pendiente — sub-batch 1.1.

    Reglas:
      - 409 si OP no está en estado 'pendiente'.
      - Body idéntico a create pero todo opcional.
      - Items se revalidan contra whitelist + modo + suma.
      - Registra evento 'op_editada' con diff y, si cambian items,
        evento 'items_editados' (append-only).
    """
    items_norm: Optional[list[dict]]
    if data.items is None:
        items_norm = None
    else:
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
        op = ordenes_pago_service.editar(
            db,
            op_id=op_id,
            monto_total=data.monto_total,
            moneda=data.moneda,  # type: ignore[arg-type]
            modo_imputacion=data.modo_imputacion,  # type: ignore[arg-type]
            items=items_norm,
            observaciones=data.observaciones,
            tipo_cambio=data.tipo_cambio,
            fecha_pago_estimada=data.fecha_pago_estimada,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("editar_orden_pago falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al editar la OP.") from exc

    _commit_or_rollback(db, operacion="editar_orden_pago")
    db.refresh(op)
    return _op_response(op)


@router.post(
    "/ordenes-pago/{op_id}/cancelar-pendiente",
    response_model=OrdenPagoResponse,
    summary="Cancelar OP pendiente (estado terminal, sin efectos colaterales)",
)
def cancelar_orden_pago_pendiente(
    op_id: int,
    data: OrdenPagoCancelarPendiente,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> OrdenPagoResponse:
    """Cancelar OP pendiente — sub-batch 1.2.

    Transición segura `pendiente → cancelado` porque no hay imputaciones
    físicas, caja ni CC. Solo UPDATE + evento auditado.

    Raises:
        409 si OP no está en estado 'pendiente'.
        404 si OP inexistente.
        400 si motivo vacío.
    """
    try:
        op = ordenes_pago_service.cancelar_pendiente(
            db,
            op_id=op_id,
            motivo=data.motivo,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("cancelar_orden_pago_pendiente falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al cancelar la OP.") from exc

    _commit_or_rollback(db, operacion="cancelar_orden_pago_pendiente")
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
            tipo_cambio_override=data.tipo_cambio_override,
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


def _enriquecer_imputaciones(db: Session, imps: list[Imputacion]) -> list[ImputacionResponse]:
    """Enriquece imputaciones con nombres + descripciones legibles (batch, NO N+1).

    Carga en 4-6 queries agrupadas todos los proveedores, empresas, pedidos,
    OPs y NCs locales referenciados por el conjunto de imputaciones. Si una
    referencia es huérfana (origen/destino apuntando a un recurso
    inexistente), se cae al ID crudo como fallback.

    Para empresas, la imputación NO tiene FK directa — resolvemos via:
      - destino pedido_compra → pedido.empresa_id
      - origen orden_pago → op.empresa_id
      - origen nota_credito_local → nc.empresa_id
      - destino factura_erp → (comp_id, bra_id) del ct_transaction mapeado
        vía `compras_empresa_erp_map.bra_a_empresa_o_ignorar`.
    """
    if not imps:
        return []

    from app.core.compras_empresa_erp_map import bra_a_empresa_o_ignorar  # noqa: PLC0415
    from app.models.commercial_transaction import CommercialTransaction  # noqa: PLC0415
    from app.models.empresa import Empresa  # noqa: PLC0415
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    # ── 1. Proveedores ──────────────────────────────────────────────────
    proveedor_ids = {imp.proveedor_id for imp in imps if imp.proveedor_id is not None}
    proveedores: dict[int, str] = {}
    if proveedor_ids:
        rows = db.execute(select(Proveedor.id, Proveedor.nombre).where(Proveedor.id.in_(proveedor_ids))).all()
        proveedores = {int(r[0]): str(r[1]) for r in rows}

    # ── 2. Pedidos (para destino=pedido_compra y resolver empresa) ──────
    pedido_ids = {
        int(imp.destino_id) for imp in imps if imp.destino_tipo == "pedido_compra" and imp.destino_id is not None
    }
    pedidos: dict[int, tuple[str, int]] = {}  # {id: (numero, empresa_id)}
    if pedido_ids:
        rows = db.execute(
            select(PedidoCompra.id, PedidoCompra.numero, PedidoCompra.empresa_id).where(PedidoCompra.id.in_(pedido_ids))
        ).all()
        pedidos = {int(r[0]): (str(r[1]), int(r[2])) for r in rows}

    # ── 3. OPs (para origen=orden_pago y resolver empresa) ──────────────
    op_ids = {int(imp.origen_id) for imp in imps if imp.origen_tipo == "orden_pago" and imp.origen_id is not None}
    ops: dict[int, tuple[str, int]] = {}  # {id: (numero, empresa_id)}
    if op_ids:
        rows = db.execute(
            select(OrdenPago.id, OrdenPago.numero, OrdenPago.empresa_id).where(OrdenPago.id.in_(op_ids))
        ).all()
        ops = {int(r[0]): (str(r[1]), int(r[2])) for r in rows}

    # ── 4. NCs locales (para origen=nota_credito_local y resolver empresa)
    nc_local_ids = {
        int(imp.origen_id) for imp in imps if imp.origen_tipo == "nota_credito_local" and imp.origen_id is not None
    }
    ncs_locales: dict[int, tuple[str, int]] = {}  # {id: (numero, empresa_id)}
    if nc_local_ids:
        rows = db.execute(
            select(NotaCreditoLocal.id, NotaCreditoLocal.numero, NotaCreditoLocal.empresa_id).where(
                NotaCreditoLocal.id.in_(nc_local_ids)
            )
        ).all()
        ncs_locales = {int(r[0]): (str(r[1]), int(r[2])) for r in rows}

    # ── 5. CommercialTransaction (factura_erp como destino, nota_credito_erp
    #      como origen) — para numero y empresa_id via (comp_id, bra_id).
    ct_ids: set[int] = set()
    for imp in imps:
        if imp.destino_tipo == "factura_erp" and imp.destino_id is not None:
            ct_ids.add(int(imp.destino_id))
        if imp.origen_tipo == "nota_credito_erp" and imp.origen_id is not None:
            ct_ids.add(int(imp.origen_id))
    cts: dict[int, tuple[str | None, int | None, int | None]] = {}  # {ct: (doc, comp, bra)}
    if ct_ids:
        try:
            rows = db.execute(
                select(
                    CommercialTransaction.ct_transaction,
                    CommercialTransaction.ct_docNumber,
                    CommercialTransaction.comp_id,
                    CommercialTransaction.bra_id,
                ).where(CommercialTransaction.ct_transaction.in_(ct_ids))
            ).all()
            cts = {
                int(r[0]): (
                    str(r[1]) if r[1] is not None else None,
                    int(r[2]) if r[2] is not None else None,
                    int(r[3]) if r[3] is not None else None,
                )
                for r in rows
            }
        except Exception:  # noqa: BLE001 — ERP no disponible (SQLite tests / tabla faltante)
            # Fallback silencioso: sin metadata ERP. Se caerá al ID crudo.
            cts = {}

    # ── 6. Empresas (nombres, resolvemos IDs abajo vía los dicts de arriba)
    empresa_ids_a_cargar: set[int] = set()
    for imp in imps:
        # Prioridad idéntica a `_resolver_empresa_id_para_imputacion`:
        if imp.destino_tipo == "pedido_compra" and imp.destino_id is not None:
            ped = pedidos.get(int(imp.destino_id))
            if ped is not None:
                empresa_ids_a_cargar.add(ped[1])
                continue
        if imp.origen_tipo == "orden_pago" and imp.origen_id is not None:
            op_tuple = ops.get(int(imp.origen_id))
            if op_tuple is not None:
                empresa_ids_a_cargar.add(op_tuple[1])
                continue
        if imp.origen_tipo == "nota_credito_local" and imp.origen_id is not None:
            nc_tuple = ncs_locales.get(int(imp.origen_id))
            if nc_tuple is not None:
                empresa_ids_a_cargar.add(nc_tuple[1])
                continue
        if imp.destino_tipo == "factura_erp" and imp.destino_id is not None:
            ct_tuple = cts.get(int(imp.destino_id))
            if ct_tuple is not None and ct_tuple[1] is not None and ct_tuple[2] is not None:
                emp = bra_a_empresa_o_ignorar(ct_tuple[1], ct_tuple[2])
                if emp is not None:
                    empresa_ids_a_cargar.add(emp)

    empresas_nombres: dict[int, str] = {}
    if empresa_ids_a_cargar:
        rows = db.execute(select(Empresa.id, Empresa.nombre).where(Empresa.id.in_(empresa_ids_a_cargar))).all()
        empresas_nombres = {int(r[0]): str(r[1]) for r in rows}

    # ── 7. Construcción de respuestas enriquecidas ──────────────────────
    def _resolver_empresa_id(imp: Imputacion) -> int | None:
        if imp.destino_tipo == "pedido_compra" and imp.destino_id is not None:
            ped = pedidos.get(int(imp.destino_id))
            if ped is not None:
                return ped[1]
        if imp.origen_tipo == "orden_pago" and imp.origen_id is not None:
            op_tuple = ops.get(int(imp.origen_id))
            if op_tuple is not None:
                return op_tuple[1]
        if imp.origen_tipo == "nota_credito_local" and imp.origen_id is not None:
            nc_tuple = ncs_locales.get(int(imp.origen_id))
            if nc_tuple is not None:
                return nc_tuple[1]
        if imp.destino_tipo == "factura_erp" and imp.destino_id is not None:
            ct_tuple = cts.get(int(imp.destino_id))
            if ct_tuple is not None and ct_tuple[1] is not None and ct_tuple[2] is not None:
                return bra_a_empresa_o_ignorar(ct_tuple[1], ct_tuple[2])
        return None

    def _descripcion_origen(imp: Imputacion) -> str:
        if imp.origen_tipo == "orden_pago" and imp.origen_id is not None:
            tup = ops.get(int(imp.origen_id))
            if tup is not None:
                return f"OP {tup[0]}"
            return f"OP #{imp.origen_id}"
        if imp.origen_tipo == "nota_credito_local" and imp.origen_id is not None:
            tup = ncs_locales.get(int(imp.origen_id))
            if tup is not None:
                return f"NC {tup[0]}"
            return f"NC #{imp.origen_id}"
        if imp.origen_tipo == "nota_credito_erp" and imp.origen_id is not None:
            ct_tuple = cts.get(int(imp.origen_id))
            if ct_tuple is not None and ct_tuple[0]:
                return f"NC ERP {ct_tuple[0]}"
            return f"NC ERP {imp.origen_id}"
        return f"{imp.origen_tipo} #{imp.origen_id}"

    def _descripcion_destino(imp: Imputacion) -> str:
        if imp.destino_tipo == "saldo":
            return "Saldo a cuenta"
        if imp.destino_tipo == "pedido_compra" and imp.destino_id is not None:
            tup = pedidos.get(int(imp.destino_id))
            if tup is not None:
                return f"Pedido {tup[0]}"
            return f"Pedido #{imp.destino_id}"
        if imp.destino_tipo == "factura_erp" and imp.destino_id is not None:
            ct_tuple = cts.get(int(imp.destino_id))
            if ct_tuple is not None and ct_tuple[0]:
                return f"Factura {ct_tuple[0]}"
            return f"Factura {imp.destino_id}"
        return f"{imp.destino_tipo} #{imp.destino_id}"

    resultado: list[ImputacionResponse] = []
    for imp in imps:
        emp_id = _resolver_empresa_id(imp)
        resp = ImputacionResponse.model_validate(imp)
        resp.proveedor_nombre = proveedores.get(int(imp.proveedor_id)) if imp.proveedor_id else None
        resp.empresa_nombre = empresas_nombres.get(emp_id) if emp_id is not None else None
        resp.origen_descripcion = _descripcion_origen(imp)
        resp.destino_descripcion = _descripcion_destino(imp)
        resultado.append(resp)
    return resultado


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
    """Imputaciones paginadas, con nombres derivados + descripciones legibles."""
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
    enriquecidos = _enriquecer_imputaciones(db, list(items))
    return ImputacionPaginated(
        items=enriquecidos,
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


def _enriquecer_movimientos_cc(db: Session, movs: list[Any]) -> list[CCMovimientoResponse]:
    """Enriquece movimientos de CC proveedor con `origen_descripcion` legible.

    Batch (0 N+1): hace 4-5 queries agrupadas por origen_tipo y resuelve los
    nombres/numeros de documento en memoria. Mapping:

      - orden_pago          → "OP {numero}"
      - nota_credito_local  → "NC {numero}"
      - ajuste_pedido       → "Ajuste pedido {numero}"    (origen_id = pedido)
      - ajuste_manual       → "Ajuste manual"
      - nota_credito_erp    → "NC ERP {ct_docnumber}"
      - pedido_compra       → "Pedido {numero}"           (legacy, si aplica)

    Fallback: `"{origen_tipo} #{id}"` si la FK está huérfana o el tipo es
    desconocido (p.ej. tipos nuevos todavía no mapeados acá).
    """
    if not movs:
        return []

    from app.models.commercial_transaction import CommercialTransaction  # noqa: PLC0415
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    # ── Recolectar IDs por origen_tipo ───────────────────────────────────
    # IMPORTANTE: los movimientos "haber" generados por `aplicar_imputacion`
    # llegan con `origen_tipo='imputacion'` y `origen_id=imputacion.id`. Para
    # resolver a "OP {numero}" / "NC {numero}" hay que hacer un hop: buscar
    # la imputacion y usar su `origen_tipo`/`origen_id` como referencia
    # real. Los reversales (tipo='debe', origen_tipo='reimputacion') siguen
    # el mismo patrón.
    op_ids: set[int] = set()
    nc_local_ids: set[int] = set()
    pedido_ids: set[int] = set()  # ajuste_pedido + pedido_compra (legacy)
    ct_ids: set[int] = set()  # nota_credito_erp + facturas
    imp_ids: set[int] = set()  # imputacion / reimputacion — hop al origen real

    for m in movs:
        oid = getattr(m, "origen_id", None)
        if oid is None:
            continue
        otipo = getattr(m, "origen_tipo", None)
        if otipo == "orden_pago":
            op_ids.add(int(oid))
        elif otipo == "nota_credito_local":
            nc_local_ids.add(int(oid))
        elif otipo in ("ajuste_pedido", "pedido_compra"):
            pedido_ids.add(int(oid))
        elif otipo == "nota_credito_erp":
            ct_ids.add(int(oid))
        elif otipo in ("imputacion", "reimputacion"):
            imp_ids.add(int(oid))

    # ── Hop: cargar imputaciones referenciadas y propagar sus origenes ───
    # Una imputacion puede tener origen orden_pago, nota_credito_local o
    # nota_credito_erp. Recolectamos esos IDs secundarios para batch fetch.
    imps_resueltos: dict[int, tuple[str, int]] = {}  # imp_id → (origen_tipo, origen_id)
    if imp_ids:
        rows = db.execute(
            select(Imputacion.id, Imputacion.origen_tipo, Imputacion.origen_id).where(Imputacion.id.in_(imp_ids))
        ).all()
        for r in rows:
            imps_resueltos[int(r[0])] = (str(r[1]), int(r[2]))
            otipo2, oid2 = str(r[1]), int(r[2])
            if otipo2 == "orden_pago":
                op_ids.add(oid2)
            elif otipo2 == "nota_credito_local":
                nc_local_ids.add(oid2)
            elif otipo2 == "nota_credito_erp":
                ct_ids.add(oid2)

    # ── Batch fetch: numeros por ID ──────────────────────────────────────
    ops_numeros: dict[int, str] = {}
    if op_ids:
        rows = db.execute(select(OrdenPago.id, OrdenPago.numero).where(OrdenPago.id.in_(op_ids))).all()
        ops_numeros = {int(r[0]): str(r[1]) for r in rows}

    ncs_numeros: dict[int, str] = {}
    if nc_local_ids:
        rows = db.execute(
            select(NotaCreditoLocal.id, NotaCreditoLocal.numero).where(NotaCreditoLocal.id.in_(nc_local_ids))
        ).all()
        ncs_numeros = {int(r[0]): str(r[1]) for r in rows}

    pedidos_numeros: dict[int, str] = {}
    if pedido_ids:
        rows = db.execute(select(PedidoCompra.id, PedidoCompra.numero).where(PedidoCompra.id.in_(pedido_ids))).all()
        pedidos_numeros = {int(r[0]): str(r[1]) for r in rows}

    ct_docnumbers: dict[int, str | None] = {}
    if ct_ids:
        try:
            rows = db.execute(
                select(CommercialTransaction.ct_transaction, CommercialTransaction.ct_docNumber).where(
                    CommercialTransaction.ct_transaction.in_(ct_ids)
                )
            ).all()
            ct_docnumbers = {int(r[0]): (str(r[1]) if r[1] is not None else None) for r in rows}
        except Exception:  # noqa: BLE001 — ERP no disponible (SQLite tests)
            ct_docnumbers = {}

    # ── Resolver descripción por movimiento ─────────────────────────────
    def _describir_ref(otipo: str, oid: int) -> str:
        """Resuelve un par (tipo, id) a texto humano — sin hop de imputacion."""
        if otipo == "orden_pago":
            num = ops_numeros.get(oid)
            return f"OP {num}" if num else f"OP #{oid}"
        if otipo == "nota_credito_local":
            num = ncs_numeros.get(oid)
            return f"NC {num}" if num else f"NC #{oid}"
        if otipo == "ajuste_pedido":
            num = pedidos_numeros.get(oid)
            return f"Ajuste pedido {num}" if num else f"Ajuste pedido #{oid}"
        if otipo == "pedido_compra":
            num = pedidos_numeros.get(oid)
            return f"Pedido {num}" if num else f"Pedido #{oid}"
        if otipo == "nota_credito_erp":
            doc = ct_docnumbers.get(oid)
            return f"NC ERP {doc}" if doc else f"NC ERP #{oid}"
        if otipo == "factura_erp":
            doc = ct_docnumbers.get(oid)
            return f"Factura {doc}" if doc else f"Factura #{oid}"
        return f"{otipo} #{oid}"

    def _descripcion(m: Any) -> str:
        otipo = getattr(m, "origen_tipo", None)
        oid = getattr(m, "origen_id", None)
        if otipo == "ajuste_manual":
            return "Ajuste manual"
        # Hop: imputacion/reimputacion → usar origen real de la imputacion.
        if otipo in ("imputacion", "reimputacion") and oid is not None:
            ref = imps_resueltos.get(int(oid))
            if ref is not None:
                prefijo = "Reversal " if otipo == "reimputacion" else ""
                return prefijo + _describir_ref(ref[0], ref[1])
            return f"{otipo} #{oid}"
        if oid is not None and otipo:
            return _describir_ref(otipo, int(oid))
        # Fallback: tipo desconocido o sin origen_id
        return f"{otipo} #{oid}" if oid is not None else (otipo or "—")

    resultado: list[CCMovimientoResponse] = []
    for m in movs:
        resp = CCMovimientoResponse.model_validate(m)
        resp.origen_descripcion = _descripcion(m)
        resultado.append(resp)
    return resultado


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
        movimientos=_enriquecer_movimientos_cc(db, list(movimientos)),
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
    """CC agrupada por pedido — TODOS los movimientos vinculados a cada pedido.

    Resuelve el `pedido_compra_id` desde múltiples fuentes para no perder movs:
      - Directo por `origen_id`, cuando `origen_tipo` ∈
        `{pedido_compra, cancelacion_pedido, ajuste_pedido,
        cancelacion_pedido_por_correccion}` (DEBE inicial / re-aprobación clon,
        cancelaciones, ajustes por factura ERP, cancelación por corrección).
      - Vía imputación, cuando `origen_tipo` ∈ `{imputacion, reimputacion}`:
        se carga la `Imputacion` por `origen_id` y se agrupa por su
        `destino_id` si `destino_tipo='pedido_compra'` (HABER de pagos/NCs y
        DEBE de reversals).

    Quedan fuera por diseño los movimientos sin vínculo a pedido (ej.
    `ajuste_manual` con `origen_id=None`).
    """
    _obtener_proveedor_o_404(db, proveedor_id)

    movimientos = cc_proveedor_service.listar_movimientos(
        db,
        proveedor_id=proveedor_id,
    )

    # origen_tipo cuyo origen_id apunta DIRECTAMENTE al pedido_compra.
    ORIGEN_DIRECTO_PEDIDO = {
        "pedido_compra",
        "cancelacion_pedido",
        "ajuste_pedido",
        "cancelacion_pedido_por_correccion",
    }

    # Resolver imputaciones referenciadas en un solo query (batch).
    imp_ids = {
        int(m.origen_id)
        for m in movimientos
        if m.origen_tipo in ("imputacion", "reimputacion") and m.origen_id is not None
    }
    imps_por_id: dict[int, Imputacion] = {}
    if imp_ids:
        imps_por_id = {
            i.id: i for i in db.execute(select(Imputacion).where(Imputacion.id.in_(imp_ids))).scalars().all()
        }

    # Agrupar por pedido_compra_id resuelto desde origen directo o vía imputación.
    grupos: dict[int, list] = {}
    for m in movimientos:
        pedido_id: Optional[int] = None
        if m.origen_tipo in ORIGEN_DIRECTO_PEDIDO and m.origen_id is not None:
            pedido_id = int(m.origen_id)
        elif m.origen_tipo in ("imputacion", "reimputacion") and m.origen_id is not None:
            imp = imps_por_id.get(int(m.origen_id))
            if imp is not None and imp.destino_tipo == "pedido_compra" and imp.destino_id is not None:
                pedido_id = int(imp.destino_id)

        if pedido_id is not None:
            grupos.setdefault(pedido_id, []).append(m)

    if not grupos:
        return []

    # Traer los pedidos en un solo query
    pedido_ids = list(grupos.keys())
    pedidos = {p.id: p for p in db.execute(select(PedidoCompra).where(PedidoCompra.id.in_(pedido_ids))).scalars().all()}

    # Saldos pendientes batch (1 query agregada — sin N+1).
    saldo_imp_map = pedidos_service.calcular_saldos_pendientes_batch(db, pedido_ids)
    # TC ponderado batch (1 query agregada — sin N+1, NFR-001).
    tc_pond_map = pedidos_service.calcular_tc_ponderado_pedido_batch(db, pedido_ids)

    resultado: list[CCAgrupadoPorPedido] = []
    for pid, movs in grupos.items():
        pedido = pedidos.get(pid)
        if pedido is None:
            continue  # pedido fue borrado: skip
        saldo_pendiente = Decimal(pedido.monto) - saldo_imp_map.get(pid, Decimal(0))
        resultado.append(
            CCAgrupadoPorPedido(
                pedido_compra_id=pid,
                pedido_numero=pedido.numero,
                pedido_estado=pedido.estado,
                pedido_monto=Decimal(pedido.monto),
                pedido_moneda=pedido.moneda,
                pedido_tipo_cambio=Decimal(pedido.tipo_cambio) if pedido.tipo_cambio is not None else None,
                pedido_saldo_pendiente=saldo_pendiente,
                tc_ponderado=tc_pond_map.get(pid),
                movimientos=_enriquecer_movimientos_cc(db, list(movs)),
            )
        )
    # Orden: por fecha desc del primer movimiento de cada grupo
    resultado.sort(
        key=lambda g: g.movimientos[0].fecha_movimiento if g.movimientos else date.min,
        reverse=True,
    )
    return resultado


@router.get(
    "/cc-proveedor/{proveedor_id}/facturas-erp-vigentes",
    response_model=list[FacturaCandidataResponse],
    summary="Facturas ERP vigentes del proveedor (para aplicar NC local a factura_erp)",
)
def listar_facturas_erp_vigentes_proveedor(
    proveedor_id: int,
    moneda: Optional[str] = Query(None, pattern="^(ARS|USD)$"),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> list[FacturaCandidataResponse]:
    """Lista facturas del ERP vigentes del proveedor (v_facturas_compra_vigentes),
    sin filtrar por pedido.

    Uso: el modal `ModalAplicarNC` necesita mostrar facturas ERP del proveedor
    cuando el usuario elige destino `factura_erp` (sub-batch 3). La vista ya
    excluye contrapartes/anuladas. Filtra por `supp_id` del proveedor y,
    opcionalmente, por moneda (vía `curr_id_transaction`: 1=ARS, 2=USD por
    convención ERP).

    Si el proveedor no tiene `supp_id` ERP → lista vacía + log WARNING.
    En SQLite (tests sin vista ERP) → lista vacía silenciosa.
    """
    _obtener_proveedor_o_404(db, proveedor_id)
    supp_id = db.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": proveedor_id},
    ).scalar_one_or_none()
    if supp_id is None:
        logger.warning(
            "facturas-erp-vigentes: proveedor_id=%s sin supp_id ERP → lista vacía",
            proveedor_id,
        )
        return []

    params: dict[str, Any] = {"supp_id": int(supp_id)}
    # Filtro opcional por moneda — convención: curr_id=1 ARS, curr_id=2 USD
    # (es el mapping de tb_currency en el ERP). Si no matchea, simplemente no
    # aplica el where y la UI muestra todas.
    moneda_where = ""
    if moneda == "ARS":
        moneda_where = "AND v.curr_id_transaction = 1"
    elif moneda == "USD":
        moneda_where = "AND v.curr_id_transaction = 2"

    stmt = text(
        f"""
        SELECT v.ct_transaction,
               v.ct_docnumber,
               v.ct_date,
               v.ct_total,
               v.curr_id_transaction
        FROM v_facturas_compra_vigentes v
        WHERE v.supp_id = :supp_id
          {moneda_where}
        ORDER BY v.ct_date DESC NULLS LAST, v.ct_transaction DESC
        LIMIT 200
        """
    )
    try:
        filas = db.execute(stmt, params).all()
    except Exception as exc:  # noqa: BLE001 — vista ERP ausente (SQLite tests)
        logger.warning(
            "facturas-erp-vigentes: vista ERP no disponible (probablemente tests): %s",
            exc,
        )
        return []

    return [
        FacturaCandidataResponse(
            ct_transaction=int(row[0]),
            ct_docnumber=str(row[1] or ""),
            ct_date=row[2],
            ct_total=Decimal(str(row[3] or 0)),
            curr_id_transaction=int(row[4]) if row[4] is not None else None,
        )
        for row in filas
    ]


@router.post(
    "/cc-proveedor/{proveedor_id}/ajuste-manual",
    response_model=CCMovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajuste manual de CC del proveedor (sub-batch 5.H — permiso crítico)",
)
def crear_ajuste_cc_manual(
    proveedor_id: int,
    data: AjusteCCManualRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.ajustar_cc_proveedor_manual")),
) -> CCMovimientoResponse:
    """Inserta un movimiento de ajuste manual en la CC del proveedor.

    Append-only: NO modifica movimientos existentes. Genera un movimiento
    `tipo='ajuste'` con `origen_tipo='ajuste_manual'`, `origen_id=None` y
    `descripcion` con el motivo + metadata de usuario para auditoría.

    Valida signo_ajuste ∈ {+1, -1}.
    """
    _obtener_proveedor_o_404(db, proveedor_id)
    if data.signo_ajuste not in (1, -1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="signo_ajuste debe ser +1 (debe) o -1 (haber).",
        )
    try:
        mov = cc_proveedor_service.insertar_mov(
            db,
            proveedor_id=proveedor_id,
            empresa_id=data.empresa_id,
            fecha_movimiento=data.fecha_movimiento,
            tipo="ajuste",
            signo_ajuste=data.signo_ajuste,
            monto=data.monto,
            moneda=data.moneda,  # type: ignore[arg-type]
            origen_tipo="ajuste_manual",
            origen_id=None,
            descripcion=f"[AJUSTE MANUAL user_id={user.id}] {data.motivo.strip()}",
            creado_por_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("crear_ajuste_cc_manual falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al crear el ajuste manual.") from exc

    _commit_or_rollback(db, operacion="crear_ajuste_cc_manual")
    db.refresh(mov)
    # Enriquecer con origen_descripcion (batch de 1) para consistencia con el
    # listado cronológico — la UI puede renderizar sin re-fetchear.
    enriquecidos = _enriquecer_movimientos_cc(db, [mov])
    return enriquecidos[0]


@router.post(
    "/cc-proveedor/{proveedor_id}/pago-rapido",
    response_model=OrdenPagoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Pago rápido: crea OP a_cuenta + ejecuta pago en un solo request (sub-batch 5.G)",
)
def pago_rapido_cc_proveedor(
    proveedor_id: int,
    data: PagoRapidoRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.ejecutar_pagos")),
) -> OrdenPagoResponse:
    """Pago rápido desde el tab CC Proveedores.

    Atomic: crea OP modo `a_cuenta` + ejecuta pago en la misma transacción.
    Si cualquier paso falla, rollbackea todo. Deja trazabilidad completa
    (número OP, evento, caja_movimiento, imputación a saldo).
    """
    _obtener_proveedor_o_404(db, proveedor_id)

    try:
        # Step 1: crear OP a_cuenta
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor_id,
            empresa_id=data.empresa_id,
            moneda=data.moneda,  # type: ignore[arg-type]
            monto_total=data.monto,
            modo_imputacion="a_cuenta",
            items=[],
            observaciones=(f"[PAGO RÁPIDO user_id={user.id}] {data.observaciones or ''}".strip()),
            creado_por_id=user.id,
            confirmar_duplicado=True,  # flow rápido, no bloqueamos por ERP duplicate check
        )
        # Setear TC si vino (se persiste por ejecutar_pago como tipo_cambio_override)
        # Step 2: ejecutar pago
        op = ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=data.caja_id,
            fecha_pago_real=data.fecha_pago_real,
            user_id=user.id,
            tipo_cambio_override=data.tipo_cambio,
        )

        # Evento extra para distinguir este flow en auditoría
        ordenes_pago_service.registrar_evento_auditoria(
            db,
            op_id=op.id,
            tipo="op_creada_y_pagada_rapido",
            usuario_id=user.id,
            payload={
                "motivo": "Pago rápido sin pedido específico desde tab CC Proveedores.",
                "monto": str(data.monto),
                "moneda": data.moneda,
            },
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("pago_rapido_cc_proveedor falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al ejecutar el pago rápido.") from exc

    _commit_or_rollback(db, operacion="pago_rapido_cc_proveedor")
    db.refresh(op)
    return _op_response(op)


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

    # Batch-enriquecer con proveedor_nombre (1 query WHERE IN).
    proveedor_ids = {int(log.proveedor_id) for log in logs if log.proveedor_id is not None}
    nombres: dict[int, str] = {}
    if proveedor_ids:
        rows = db.execute(select(Proveedor.id, Proveedor.nombre).where(Proveedor.id.in_(proveedor_ids))).all()
        nombres = {int(r[0]): str(r[1]) for r in rows}

    resultado: list[CCReconciliacionLogResponse] = []
    for log in logs:
        resp = CCReconciliacionLogResponse.model_validate(log)
        resp.proveedor_nombre = nombres.get(int(log.proveedor_id)) if log.proveedor_id else None
        resultado.append(resp)
    return resultado


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


# ==========================================================================
# Batch H — Adjuntos polimórficos (pedidos + OPs)
# ==========================================================================
#
# Layout de endpoints:
#   POST   /pedidos/{id}/adjuntos          ← multipart upload
#   GET    /pedidos/{id}/adjuntos          ← listar
#   POST   /ordenes-pago/{id}/adjuntos     ← multipart upload (OP)
#   GET    /ordenes-pago/{id}/adjuntos     ← listar (OP)
#   GET    /adjuntos/{id}/descargar        ← stream archivo
#   DELETE /adjuntos/{id}                  ← hard-delete
#
# Validaciones: magic bytes (whitelist PDF/JPG/PNG/WebP/DOC(X)/XLS(X)),
# tamaño máx 20 MB (settings.COMPRAS_MAX_FILE_SIZE_MB).
# Permisos: ver=ver_ordenes_compra; subir/borrar=gestionar_ordenes_compra.


def _adjunto_response(adj: CompraAdjunto) -> CompraAdjuntoResponse:
    """Serializa un CompraAdjunto incluyendo `subido_por_nombre` sin N+1."""
    subio = getattr(adj, "subido_por", None)
    base = CompraAdjuntoResponse.model_validate(adj)
    return base.model_copy(update={"subido_por_nombre": subio.nombre if subio is not None else None})


@router.post(
    "/pedidos/{pedido_id}/adjuntos",
    response_model=CompraAdjuntoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir adjunto a un pedido (factura/presupuesto/comprobante)",
)
async def subir_adjunto_pedido(
    pedido_id: int,
    file: UploadFile = File(...),
    tipo: Optional[str] = Form(
        default=None,
        pattern="^(factura|presupuesto|comprobante|otro)$",
    ),
    descripcion: Optional[str] = Form(default=None, max_length=500),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> CompraAdjuntoResponse:
    """Adjunta un archivo al pedido. Batch H."""
    _obtener_pedido_o_404(db, pedido_id)
    try:
        adj = await compras_adjuntos_service.subir_adjunto(
            db,
            entidad_tipo="pedido_compra",
            entidad_id=pedido_id,
            file=file,
            tipo=tipo,  # type: ignore[arg-type]
            descripcion=descripcion,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 — log + 500 limpio
        db.rollback()
        logger.exception("subir_adjunto_pedido falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al subir el adjunto.",
        ) from exc

    _commit_or_rollback(db, operacion="subir_adjunto_pedido")
    db.refresh(adj)
    return _adjunto_response(adj)


@router.get(
    "/pedidos/{pedido_id}/adjuntos",
    response_model=list[CompraAdjuntoResponse],
    summary="Listar adjuntos de un pedido",
)
def listar_adjuntos_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[CompraAdjuntoResponse]:
    """Lista de adjuntos ordenada por `created_at DESC`. Batch H."""
    _obtener_pedido_o_404(db, pedido_id)
    items = compras_adjuntos_service.listar_adjuntos(db, entidad_tipo="pedido_compra", entidad_id=pedido_id)
    return [_adjunto_response(a) for a in items]


@router.post(
    "/ordenes-pago/{op_id}/adjuntos",
    response_model=CompraAdjuntoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir adjunto a una orden de pago",
)
async def subir_adjunto_op(
    op_id: int,
    file: UploadFile = File(...),
    tipo: Optional[str] = Form(
        default=None,
        pattern="^(factura|presupuesto|comprobante|otro)$",
    ),
    descripcion: Optional[str] = Form(default=None, max_length=500),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> CompraAdjuntoResponse:
    """Adjunta un archivo a la OP. Batch H."""
    _obtener_op_o_404(db, op_id)
    try:
        adj = await compras_adjuntos_service.subir_adjunto(
            db,
            entidad_tipo="orden_pago",
            entidad_id=op_id,
            file=file,
            tipo=tipo,  # type: ignore[arg-type]
            descripcion=descripcion,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("subir_adjunto_op falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al subir el adjunto.",
        ) from exc

    _commit_or_rollback(db, operacion="subir_adjunto_op")
    db.refresh(adj)
    return _adjunto_response(adj)


@router.get(
    "/ordenes-pago/{op_id}/adjuntos",
    response_model=list[CompraAdjuntoResponse],
    summary="Listar adjuntos de una OP",
)
def listar_adjuntos_op(
    op_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[CompraAdjuntoResponse]:
    """Lista de adjuntos ordenada por `created_at DESC`. Batch H."""
    _obtener_op_o_404(db, op_id)
    items = compras_adjuntos_service.listar_adjuntos(db, entidad_tipo="orden_pago", entidad_id=op_id)
    return [_adjunto_response(a) for a in items]


@router.get(
    "/adjuntos/{adjunto_id}/descargar",
    summary="Descargar un archivo adjunto (auth-gated, no StaticFiles)",
)
def descargar_adjunto(
    adjunto_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> FileResponse:
    """Devuelve el archivo físico via FileResponse. Batch H."""
    adj = compras_adjuntos_service.obtener_adjunto(db, adjunto_id)
    import os as _os  # noqa: PLC0415

    full_path = _os.path.join(settings.COMPRAS_UPLOADS_DIR, adj.path_archivo)
    if not _os.path.exists(full_path):
        logger.warning(
            "descargar_adjunto: archivo físico ausente id=%s path=%s",
            adj.id,
            full_path,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado en disco.",
        )
    return FileResponse(
        path=full_path,
        filename=adj.nombre_archivo,
        media_type=adj.mime_type or "application/octet-stream",
    )


@router.delete(
    "/adjuntos/{adjunto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Eliminar un adjunto (hard-delete, borra archivo físico)",
)
def eliminar_adjunto(
    adjunto_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> Response:
    """Hard-delete del adjunto (archivo + registro). Batch H."""
    try:
        compras_adjuntos_service.eliminar_adjunto(db, adjunto_id=adjunto_id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("eliminar_adjunto falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar el adjunto.",
        ) from exc

    _commit_or_rollback(db, operacion="eliminar_adjunto")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ==========================================================================
# Batch I — Vincular factura del ERP al pedido (manual) + ajuste monto
# ==========================================================================
#
# Flujo:
#   GET  /pedidos/{id}/facturas-candidatas  → lista facturas vigentes del proveedor
#                                             sin vincular a otros pedidos.
#   POST /pedidos/{id}/vincular-factura     → vincula (opcionalmente ajusta monto).
#   POST /pedidos/{id}/desvincular-factura  → limpia ct_transaction_id.


@router.get(
    "/pedidos/{pedido_id}/facturas-candidatas",
    response_model=list[FacturaCandidataResponse],
    summary="Listar facturas del ERP candidatas a vincular al pedido",
)
def listar_facturas_candidatas(
    pedido_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> list[FacturaCandidataResponse]:
    """
    Devuelve facturas vigentes del ERP (v_facturas_compra_vigentes) para el
    `supp_id` del proveedor del pedido, excluyendo las que ya están vinculadas
    a OTRO pedido.

    Si el proveedor no tiene `supp_id` ERP → lista vacía (y log WARNING).

    Batch I.2.
    """
    pedido = _obtener_pedido_o_404(db, pedido_id)
    supp_id = db.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": pedido.proveedor_id},
    ).scalar_one_or_none()
    if supp_id is None:
        logger.warning(
            "facturas-candidatas: proveedor_id=%s sin supp_id ERP → lista vacía",
            pedido.proveedor_id,
        )
        return []

    stmt = text(
        """
        SELECT v.ct_transaction,
               v.ct_docnumber,
               v.ct_date,
               v.ct_total,
               v.curr_id_transaction
        FROM v_facturas_compra_vigentes v
        WHERE v.supp_id = :supp_id
          AND v.ct_transaction NOT IN (
              SELECT ct_transaction_id
              FROM pedidos_compra
              WHERE ct_transaction_id IS NOT NULL
                AND id <> :pedido_id
          )
        ORDER BY v.ct_date DESC NULLS LAST, v.ct_transaction DESC
        LIMIT 100
        """
    )
    filas = db.execute(stmt, {"supp_id": int(supp_id), "pedido_id": pedido.id}).all()
    return [
        FacturaCandidataResponse(
            ct_transaction=int(row[0]),
            ct_docnumber=str(row[1] or ""),
            ct_date=row[2],
            ct_total=Decimal(str(row[3] or 0)),
            curr_id_transaction=int(row[4]) if row[4] is not None else None,
        )
        for row in filas
    ]


@router.post(
    "/pedidos/{pedido_id}/vincular-factura",
    response_model=PedidoCompraResponse,
    summary="Vincular factura ERP al pedido (opcional: ajustar monto)",
)
def vincular_factura_pedido(
    pedido_id: int,
    body: VincularFacturaRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """
    Vincula manualmente un pedido a una ct del ERP.

    Si `body.ajustar_monto=True`:
      - Requiere permiso adicional `administracion.ajustar_monto_pedido`.
      - Requiere `body.nuevo_monto` y `body.motivo_ajuste`.
      - Crea un movimiento `ajuste` en CC por la diferencia.

    Si `body.ajustar_monto=False`: solo setea `ct_transaction_id`.

    Batch I.3.
    """
    try:
        if body.ajustar_monto:
            # Permiso adicional — import inline para evitar duplicar import arriba.
            from app.services.permisos_service import PermisosService  # noqa: PLC0415

            if not PermisosService(db).tiene_permiso(user, "administracion.ajustar_monto_pedido"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Sin permiso: administracion.ajustar_monto_pedido "
                        "(requerido para ajustar el monto del pedido al vincular factura)."
                    ),
                )
            if body.nuevo_monto is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ajustar_monto=true requiere 'nuevo_monto'.",
                )
            if not body.motivo_ajuste:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ajustar_monto=true requiere 'motivo_ajuste' no vacío.",
                )
            pedido = pedidos_service.ajustar_monto_con_factura(
                db,
                pedido_id=pedido_id,
                ct_transaction=body.ct_transaction,
                nuevo_monto=body.nuevo_monto,
                motivo=body.motivo_ajuste,
                user_id=user.id,
            )
        else:
            pedido = pedidos_service.vincular_factura(
                db,
                pedido_id=pedido_id,
                ct_transaction=body.ct_transaction,
                user_id=user.id,
            )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("vincular_factura_pedido falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al vincular la factura.",
        ) from exc

    _commit_or_rollback(db, operacion="vincular_factura_pedido")
    db.refresh(pedido)
    return _pedido_response(pedido)


@router.post(
    "/pedidos/{pedido_id}/desvincular-factura",
    response_model=PedidoCompraResponse,
    summary="Desvincular factura ERP del pedido (no revierte ajustes previos)",
)
def desvincular_factura_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> PedidoCompraResponse:
    """Limpia `ct_transaction_id`. Los ajustes de CC NO se revierten. Batch I.4."""
    try:
        pedido = pedidos_service.desvincular_factura(db, pedido_id=pedido_id, user_id=user.id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("desvincular_factura_pedido falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al desvincular la factura.",
        ) from exc

    _commit_or_rollback(db, operacion="desvincular_factura_pedido")
    db.refresh(pedido)
    return _pedido_response(pedido)


# ==========================================================================
# Compras v2 — NCs locales
# ==========================================================================
#
# Layout:
#   GET    /ncs-locales                                 → paginado + filtros
#   GET    /ncs-locales/{id}                            → detalle (eventos + imps)
#   POST   /ncs-locales                                 → crear (gestionar)
#   PUT    /ncs-locales/{id}                            → editar (solo borrador)
#   POST   /ncs-locales/{id}/enviar-aprobacion          → transición
#   POST   /ncs-locales/{id}/aprobar                    → permiso aprobar_ncs_locales
#   POST   /ncs-locales/{id}/rechazar                   → body {accion, motivo}
#   POST   /ncs-locales/{id}/reabrir                    → desde rechazado
#   POST   /ncs-locales/{id}/cancelar                   → con motivo si aprobado
#   GET    /ncs-locales/{id}/eventos                    → log de auditoría
#   GET    /ncs-locales/{id}/candidatas-erp             → NCs ERP del proveedor
#   POST   /ncs-locales/{id}/vincular-factura           → vincular ± ajuste
#   POST   /ncs-locales/{id}/desvincular-factura        → limpiar ct_transaction_id
#   POST   /ncs-locales/{id}/aplicar                    → imputar a pedido/factura/saldo
#   POST   /ncs-locales/{id}/adjuntos                   → upload (gestionar)
#   GET    /ncs-locales/{id}/adjuntos                   → listar


def _obtener_nc_o_404(db: Session, nc_id: int) -> NotaCreditoLocal:
    nc = db.get(NotaCreditoLocal, nc_id)
    if nc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NC local id={nc_id} no encontrada.",
        )
    return nc


def _nc_local_response(
    nc: NotaCreditoLocal,
    *,
    saldo_pendiente: Optional[Decimal] = None,
) -> NotaCreditoLocalResponse:
    """Serializa NC local con nombres derivados + saldo opcional."""
    emp = getattr(nc, "empresa", None)
    prov = getattr(nc, "proveedor", None)
    base = NotaCreditoLocalResponse.model_validate(nc)
    return base.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
            "saldo_pendiente": saldo_pendiente,
        }
    )


@router.get(
    "/ncs-locales",
    response_model=NotaCreditoLocalPaginated,
    summary="Listar NCs locales con filtros y paginación",
)
def listar_ncs_locales(
    estado: Optional[str] = Query(None),
    proveedor_id: Optional[int] = Query(None, ge=1),
    empresa_id: Optional[int] = Query(None, ge=1),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> NotaCreditoLocalPaginated:
    """Lista paginada de NCs locales (compras v2)."""
    condiciones = []
    if estado is not None:
        condiciones.append(NotaCreditoLocal.estado == estado)
    if proveedor_id is not None:
        condiciones.append(NotaCreditoLocal.proveedor_id == proveedor_id)
    if empresa_id is not None:
        condiciones.append(NotaCreditoLocal.empresa_id == empresa_id)
    if desde is not None:
        condiciones.append(NotaCreditoLocal.created_at >= datetime.combine(desde, datetime.min.time()))
    if hasta is not None:
        condiciones.append(NotaCreditoLocal.created_at <= datetime.combine(hasta, datetime.max.time()))

    stmt = select(NotaCreditoLocal).options(
        joinedload(NotaCreditoLocal.empresa),
        joinedload(NotaCreditoLocal.proveedor),
    )
    if condiciones:
        stmt = stmt.where(*condiciones)
    stmt = stmt.order_by(NotaCreditoLocal.created_at.desc(), NotaCreditoLocal.id.desc())

    items, total = _paginate(db, stmt, page=page, page_size=page_size)

    # Calcular saldo pendiente solo para NCs en estados aplicables
    # (aprobado / aplicada_parcial). Para listados rápidos: 1 query agregada
    # por NC en esos estados (típicamente N pequeño en una página).
    responses: list[NotaCreditoLocalResponse] = []
    for nc in items:
        saldo: Optional[Decimal] = None
        if nc.estado in {"aprobado", "aplicada_parcial", "aplicada"}:
            saldo = ncs_locales_service.calcular_saldo_pendiente(db, nc.id)
        responses.append(_nc_local_response(nc, saldo_pendiente=saldo))

    return NotaCreditoLocalPaginated(
        items=responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/ncs-locales/disponibles",
    response_model=list[NCDisponibleSummary],
    summary="NCs locales con saldo disponible para imputar (por proveedor)",
)
def listar_ncs_disponibles(
    proveedor_id: int = Query(..., ge=1, description="ID del proveedor"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[NCDisponibleSummary]:
    """NCs locales del proveedor en estados `aprobado` / `aplicada_parcial`
    con saldo pendiente > 0 (FR-007).

    El saldo NO está persistido en `NotaCreditoLocal` — se calcula como
    `monto - (imps no-reversal - imps reversal)`. Para evitar N+1, se hace
    UN batch query agregada sobre `imputaciones` con `GROUP BY origen_id`.

    Orden: `created_at DESC, id DESC` (NFR-002 — recientes primero).

    Como el `saldo > 0` se aplica POST-fetch (no en SQL — requiere agregación
    derivada), la página devuelta puede tener menos de `limit` filas si hay
    NCs con saldo=0 en el rango. Aceptable v1 (proveedores típicos < 50 NCs).

    Filtros aplicados:
      - `proveedor_id` (requerido, 422 si falta).
      - `estado IN ('aprobado','aplicada_parcial')`.
      - `saldo_pendiente > 0` (post-filter).
    """
    _obtener_proveedor_o_404(db, proveedor_id)

    candidatas = list(
        db.execute(
            select(NotaCreditoLocal)
            .where(
                NotaCreditoLocal.proveedor_id == proveedor_id,
                NotaCreditoLocal.estado.in_(("aprobado", "aplicada_parcial")),
            )
            .order_by(NotaCreditoLocal.created_at.desc(), NotaCreditoLocal.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if not candidatas:
        return []

    # Batch: saldo neto por NC = SUM(no-reversal) - SUM(reversal). Una sola
    # query agregada con case() (mismo patrón que calcular_saldos_pendientes_batch).
    from sqlalchemy import case  # noqa: PLC0415

    nc_ids = [nc.id for nc in candidatas]
    signed_sum = sa_func.sum(
        case(
            (Imputacion.es_reversal.is_(True), -Imputacion.monto_imputado),
            else_=Imputacion.monto_imputado,
        )
    )
    rows = db.execute(
        select(Imputacion.origen_id, signed_sum)
        .where(
            Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.origen_id.in_(nc_ids),
        )
        .group_by(Imputacion.origen_id)
    ).all()
    imputado_por_nc: dict[int, Decimal] = {int(oid): Decimal(total or 0) for oid, total in rows}

    resultado: list[NCDisponibleSummary] = []
    for nc in candidatas:
        saldo = Decimal(nc.monto) - imputado_por_nc.get(int(nc.id), Decimal(0))
        if saldo <= 0:
            continue
        resultado.append(
            NCDisponibleSummary(
                id=int(nc.id),
                numero=nc.numero,
                fecha=nc.created_at.date() if nc.created_at is not None else nc.fecha_emision,
                importe=Decimal(nc.monto),
                moneda=nc.moneda,
                saldo_pendiente=saldo,
                estado=nc.estado,
            )
        )
    return resultado


@router.get(
    "/ncs-locales/{nc_id}",
    response_model=NotaCreditoLocalDetalle,
    summary="Detalle de NC local con eventos + imputaciones + saldo",
)
def obtener_nc_local(
    nc_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> NotaCreditoLocalDetalle:
    """Detalle completo de una NC local."""
    nc = db.execute(
        select(NotaCreditoLocal)
        .options(
            joinedload(NotaCreditoLocal.empresa),
            joinedload(NotaCreditoLocal.proveedor),
        )
        .where(NotaCreditoLocal.id == nc_id)
    ).scalar_one_or_none()
    if nc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NC local id={nc_id} no encontrada.",
        )

    eventos = list(
        db.execute(
            select(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_NC_LOCAL,
                CompraEvento.entidad_id == nc.id,
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
                Imputacion.origen_tipo == "nota_credito_local",
                Imputacion.origen_id == nc.id,
            )
            .order_by(Imputacion.created_at.asc(), Imputacion.id.asc())
        )
        .scalars()
        .all()
    )

    saldo = ncs_locales_service.calcular_saldo_pendiente(db, nc.id)

    emp = getattr(nc, "empresa", None)
    prov = getattr(nc, "proveedor", None)
    detalle = NotaCreditoLocalDetalle.model_validate(nc)
    detalle = detalle.model_copy(
        update={
            "empresa_nombre": emp.nombre if emp is not None else None,
            "proveedor_nombre": prov.nombre if prov is not None else None,
            "saldo_pendiente": saldo,
        }
    )
    detalle.eventos = [CompraEventoResponse.model_validate(e) for e in eventos]
    detalle.imputaciones = _enriquecer_imputaciones(db, list(imputaciones))
    return detalle


@router.post(
    "/ncs-locales",
    response_model=NotaCreditoLocalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear NC local en estado borrador",
)
def crear_nc_local(
    data: NotaCreditoLocalCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """Crea NC local en `borrador`."""
    try:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=data.empresa_id,
            proveedor_id=data.proveedor_id,
            moneda=data.moneda,  # type: ignore[arg-type]
            monto=data.monto,
            tipo_cambio=data.tipo_cambio,
            fecha_emision=data.fecha_emision,
            numero_nc_proveedor=data.numero_nc_proveedor,
            motivo=data.motivo,
            observaciones=data.observaciones,
            creado_por_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("crear_nc_local falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al crear la NC local.") from exc

    _commit_or_rollback(db, operacion="crear_nc_local")
    db.refresh(nc)
    return _nc_local_response(nc)


@router.put(
    "/ncs-locales/{nc_id}",
    response_model=NotaCreditoLocalResponse,
    summary="Editar NC local (solo en estado borrador)",
)
def editar_nc_local(
    nc_id: int,
    data: NotaCreditoLocalUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """Edita NC local. Solo borrador admite cambios."""
    campos = data.model_dump(exclude_unset=True, exclude_none=True)
    try:
        nc = ncs_locales_service.editar(db, nc_id=nc_id, user_id=user.id, **campos)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("editar_nc_local falló: %s", exc)
        raise HTTPException(status_code=500, detail="Error al editar la NC local.") from exc

    _commit_or_rollback(db, operacion="editar_nc_local")
    db.refresh(nc)
    return _nc_local_response(nc)


def _transicionar_nc_y_commit(
    db: Session,
    *,
    nc_id: int,
    accion: str,
    user_id: int,
    operacion: str,
    motivo: Optional[str] = None,
) -> NotaCreditoLocal:
    """Wrapper común para transiciones de NC: delega + commit/rollback."""
    try:
        nc = ncs_locales_service.transicionar(
            db,
            nc_id=nc_id,
            accion=accion,
            user_id=user_id,
            motivo=motivo,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("%s falló: %s", operacion, exc)
        raise HTTPException(status_code=500, detail=f"Error en transición {accion}.") from exc

    _commit_or_rollback(db, operacion=operacion)
    db.refresh(nc)
    return nc


@router.post(
    "/ncs-locales/{nc_id}/enviar-aprobacion",
    response_model=NotaCreditoLocalResponse,
    summary="Enviar NC a aprobación (borrador → pendiente_aprobacion)",
)
def enviar_nc_a_aprobacion(
    nc_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """Transición borrador → pendiente_aprobacion."""
    nc = _transicionar_nc_y_commit(
        db,
        nc_id=nc_id,
        accion="enviar_aprobacion",
        user_id=user.id,
        operacion="enviar_nc_aprobacion",
    )
    return _nc_local_response(nc)


@router.post(
    "/ncs-locales/{nc_id}/aprobar",
    response_model=NotaCreditoLocalResponse,
    summary="Aprobar NC local — permiso crítico aprobar_ncs_locales",
)
def aprobar_nc_local(
    nc_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.aprobar_ncs_locales")),
) -> NotaCreditoLocalResponse:
    """Aprobación — permiso separado de pedidos (separación de funciones).

    NO impacta CC al aprobar (decisión T.6 — la NC es crédito disponible).
    """
    nc = _transicionar_nc_y_commit(
        db,
        nc_id=nc_id,
        accion="aprobar",
        user_id=user.id,
        operacion="aprobar_nc_local",
    )
    return _nc_local_response(nc)


@router.post(
    "/ncs-locales/{nc_id}/rechazar",
    response_model=NotaCreditoLocalResponse,
    summary="Rechazar NC local (accion: devolver_a_borrador | cancelar_definitivo)",
)
def rechazar_nc_local(
    nc_id: int,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.aprobar_ncs_locales")),
) -> NotaCreditoLocalResponse:
    """Rechazo desde pendiente_aprobacion. Body: {accion, motivo}."""
    accion_raw = (payload or {}).get("accion")
    motivo = (payload or {}).get("motivo")

    if accion_raw not in {"devolver_a_borrador", "cancelar_definitivo"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campo 'accion' requerido. Valores: 'devolver_a_borrador' | 'cancelar_definitivo'.",
        )
    if not motivo or not str(motivo).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campo 'motivo' requerido.",
        )

    accion_interna = "rechazar_devolver" if accion_raw == "devolver_a_borrador" else "rechazar_cancelar"
    nc = _transicionar_nc_y_commit(
        db,
        nc_id=nc_id,
        accion=accion_interna,
        user_id=user.id,
        operacion="rechazar_nc_local",
        motivo=str(motivo),
    )
    return _nc_local_response(nc)


@router.post(
    "/ncs-locales/{nc_id}/reabrir",
    response_model=NotaCreditoLocalResponse,
    summary="Reabrir NC rechazada (rechazado → borrador)",
)
def reabrir_nc_local(
    nc_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """Transición rechazado → borrador."""
    nc = _transicionar_nc_y_commit(
        db,
        nc_id=nc_id,
        accion="reabrir",
        user_id=user.id,
        operacion="reabrir_nc_local",
    )
    return _nc_local_response(nc)


@router.post(
    "/ncs-locales/{nc_id}/cancelar",
    response_model=NotaCreditoLocalResponse,
    summary="Cancelar NC local (con motivo si aprobada — revierte imputaciones)",
)
def cancelar_nc_local(
    nc_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """Cancelación — la acción concreta depende del estado actual."""
    motivo = (payload or {}).get("motivo")
    nc = _obtener_nc_o_404(db, nc_id)

    if nc.estado in {"aprobado", "aplicada_parcial"}:
        accion = "cancelar_aprobado"
        if not motivo or not str(motivo).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Campo 'motivo' requerido al cancelar una NC aprobada o aplicada parcialmente.",
            )
    else:
        accion = "cancelar"

    nc = _transicionar_nc_y_commit(
        db,
        nc_id=nc_id,
        accion=accion,
        user_id=user.id,
        operacion="cancelar_nc_local",
        motivo=str(motivo) if motivo else None,
    )
    return _nc_local_response(nc)


@router.get(
    "/ncs-locales/{nc_id}/eventos",
    response_model=list[CompraEventoResponse],
    summary="Listar eventos de auditoría de la NC local",
)
def listar_eventos_nc_local(
    nc_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[CompraEventoResponse]:
    """Eventos append-only de la NC local."""
    _obtener_nc_o_404(db, nc_id)
    eventos = list(
        db.execute(
            select(CompraEvento)
            .where(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_NC_LOCAL,
                CompraEvento.entidad_id == nc_id,
            )
            .order_by(CompraEvento.created_at.desc(), CompraEvento.id.desc())
        )
        .scalars()
        .all()
    )
    return [CompraEventoResponse.model_validate(e) for e in eventos]


@router.get(
    "/ncs-locales/{nc_id}/candidatas-erp",
    response_model=list[NCErpCandidataResponse],
    summary="Listar NCs del ERP candidatas a vincular a la NC local",
)
def listar_ncs_erp_candidatas(
    nc_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> list[NCErpCandidataResponse]:
    """
    Devuelve NCs vigentes del ERP (sd_iscreditnote=true AND sd_ispurchase=true)
    para el `supp_id` del proveedor de la NC local, excluyendo las que ya
    están vinculadas a OTRA NC local.

    Si el proveedor no tiene `supp_id` ERP → lista vacía.
    """
    nc = _obtener_nc_o_404(db, nc_id)
    supp_id = db.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": nc.proveedor_id},
    ).scalar_one_or_none()
    if supp_id is None:
        logger.warning(
            "ncs-locales/candidatas-erp: proveedor_id=%s sin supp_id ERP → lista vacía",
            nc.proveedor_id,
        )
        return []

    stmt = text(
        """
        SELECT ct.ct_transaction,
               ct.ct_docnumber,
               ct.ct_date,
               ct.ct_total,
               ct.curr_id_transaction
        FROM tb_commercial_transactions ct
        JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
        WHERE ct.supp_id = :supp_id
          AND sd.sd_iscreditnote = TRUE
          AND sd.sd_ispurchase = TRUE
          AND COALESCE(ct.ct_iscancelled, FALSE) = FALSE
          AND ct.ct_transaction NOT IN (
              SELECT ct_transaction_id
              FROM notas_credito_local
              WHERE ct_transaction_id IS NOT NULL
                AND id <> :nc_id
          )
        ORDER BY ct.ct_date DESC NULLS LAST, ct.ct_transaction DESC
        LIMIT 100
        """
    )
    try:
        filas = db.execute(stmt, {"supp_id": int(supp_id), "nc_id": nc.id}).all()
    except Exception as exc:  # noqa: BLE001 — fallback en tests sin tabla ERP
        logger.debug("ncs-locales/candidatas-erp query falló: %s", exc)
        return []

    return [
        NCErpCandidataResponse(
            ct_transaction=int(row[0]),
            ct_docnumber=str(row[1] or ""),
            ct_date=row[2],
            ct_total=Decimal(str(row[3] or 0)),
            curr_id_transaction=int(row[4]) if row[4] is not None else None,
        )
        for row in filas
    ]


@router.post(
    "/ncs-locales/{nc_id}/vincular-factura",
    response_model=NotaCreditoLocalResponse,
    summary="Vincular NC local con NC del ERP (opcional: ajustar monto)",
)
def vincular_nc_factura(
    nc_id: int,
    body: VincularFacturaNCRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """
    Vincula la NC local con una NC del ERP. Si `ajustar_monto=True`, requiere
    permiso adicional `administracion.ajustar_monto_pedido` (reusamos el mismo
    permiso para NCs por política de seguridad).
    """
    try:
        if body.ajustar_monto:
            from app.services.permisos_service import PermisosService  # noqa: PLC0415

            if not PermisosService(db).tiene_permiso(user, "administracion.ajustar_monto_pedido"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Sin permiso: administracion.ajustar_monto_pedido "
                        "(requerido para ajustar monto de NC al vincular ERP)."
                    ),
                )
        nc = ncs_locales_service.vincular_factura_erp(
            db,
            nc_local_id=nc_id,
            ct_transaction=body.ct_transaction,
            user_id=user.id,
            ajustar_monto=body.ajustar_monto,
            nuevo_monto=body.nuevo_monto,
            motivo_ajuste=body.motivo_ajuste,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("vincular_nc_factura falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al vincular la NC con el ERP.",
        ) from exc

    _commit_or_rollback(db, operacion="vincular_nc_factura")
    db.refresh(nc)
    return _nc_local_response(nc)


@router.post(
    "/ncs-locales/{nc_id}/desvincular-factura",
    response_model=NotaCreditoLocalResponse,
    summary="Desvincular NC del ERP (no revierte ajustes previos)",
)
def desvincular_nc_factura(
    nc_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """Limpia `ct_transaction_id`. Los ajustes de monto NO se revierten."""
    try:
        nc = ncs_locales_service.desvincular_factura_erp(
            db,
            nc_local_id=nc_id,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("desvincular_nc_factura falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al desvincular la factura ERP.",
        ) from exc

    _commit_or_rollback(db, operacion="desvincular_nc_factura")
    db.refresh(nc)
    return _nc_local_response(nc)


@router.post(
    "/ncs-locales/{nc_id}/aplicar",
    response_model=NotaCreditoLocalResponse,
    summary="Imputar NC local a pedido/factura/saldo (crea imputación + dispara CC)",
)
def aplicar_nc_local(
    nc_id: int,
    body: AplicarNCRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> NotaCreditoLocalResponse:
    """
    Imputa (total o parcial) el crédito de una NC local aprobada contra:
      - `pedido_compra`: reduce saldo pendiente del pedido (auto-transición
        aprobado → pagado_parcial → pagado).
      - `factura_erp`: aplica a una factura vigente del ERP (origen NC local,
        destino factura ERP por ct_transaction).
      - `saldo`: crédito a favor del proveedor (cuenta corriente).

    Orquestación (análogo al step 6-7 de `ejecutar_pago`):
      1) Validaciones (estado NC, existencia/moneda/proveedor destino, saldo).
      2) `imputaciones_service.crear_imputacion` — valida whitelist, inserta
         imputación, dispara auto-transición de la NC (aplicada_parcial/aplicada).
      3) `cc_proveedor_service.aplicar_imputacion` — inserta movimiento HABER
         en CC proveedor.
      4) Si destino es pedido: `pedidos_service.aplicar_imputacion_a_pedido`
         recalcula estado (pagado_parcial / pagado).

    Errores:
      - 404: NC inexistente, pedido destino inexistente.
      - 409: NC en estado no aplicable (delegado al service).
      - 400: monto > saldo pendiente, moneda inconsistente, proveedor distinto,
        combinación destino/id inválida.
    """
    nc = _obtener_nc_o_404(db, nc_id)

    # Estado aplicable (defensivo — el service también lo valida).
    if nc.estado not in {"aprobado", "aplicada_parcial"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"NC local id={nc_id} en estado '{nc.estado}' no puede aplicarse. "
                f"Estados válidos: 'aprobado', 'aplicada_parcial'."
            ),
        )

    # Validar coherencia destino_tipo / destino_id.
    if body.destino_tipo == "saldo":
        if body.destino_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Con destino_tipo='saldo', destino_id debe ser NULL.",
            )
    else:
        if body.destino_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Con destino_tipo='{body.destino_tipo}', destino_id es requerido.",
            )

    # Validaciones específicas por tipo de destino (pre-chequeos de integridad
    # de negocio que el service de imputaciones no hace por ser polimórfico).
    if body.destino_tipo == "pedido_compra":
        pedido = db.get(PedidoCompra, body.destino_id)
        if pedido is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pedido destino id={body.destino_id} no encontrado.",
            )
        if pedido.proveedor_id != nc.proveedor_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Proveedor del pedido destino ({pedido.proveedor_id}) no coincide "
                    f"con el de la NC ({nc.proveedor_id})."
                ),
            )
        if pedido.moneda != nc.moneda:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Cross-moneda no soportado en v1. NC: {nc.moneda}, pedido: {pedido.moneda}."),
            )
        if pedido.estado not in {"aprobado", "pagado_parcial"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Pedido id={pedido.id} en estado '{pedido.estado}' no admite "
                    f"imputación. Estados válidos: 'aprobado', 'pagado_parcial'."
                ),
            )

    # factura_erp: validación liviana — el service valida que el monto no exceda
    # el saldo de la NC. Chequear que ct_transaction exista y pertenezca al
    # proveedor queda para un refinamiento futuro (el sync ERP es del sistema,
    # el frontend solo ofrece candidatas ya filtradas del mismo proveedor).

    try:
        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo=body.destino_tipo,
            destino_id=body.destino_id,
            monto_imputado=body.monto_imputado,
            moneda_imputada=nc.moneda,  # type: ignore[arg-type]
            proveedor_id=nc.proveedor_id,
            creado_por_id=user.id,
        )
        # HABER en CC proveedor (requerido — el service base no lo dispara).
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)

        # Recalcular estado del pedido destino (si corresponde).
        if body.destino_tipo == "pedido_compra" and body.destino_id is not None:
            pedidos_service.aplicar_imputacion_a_pedido(
                db,
                pedido_id=body.destino_id,
                monto_imputado=body.monto_imputado,
            )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("aplicar_nc_local falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al aplicar la NC local.",
        ) from exc

    _commit_or_rollback(db, operacion="aplicar_nc_local")
    db.refresh(nc)
    saldo = ncs_locales_service.calcular_saldo_pendiente(db, nc.id)
    return _nc_local_response(nc, saldo_pendiente=saldo)


@router.post(
    "/ncs-locales/{nc_id}/adjuntos",
    response_model=CompraAdjuntoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir adjunto a una NC local",
)
async def subir_adjunto_nc_local(
    nc_id: int,
    file: UploadFile = File(...),
    tipo: Optional[str] = Form(
        default=None,
        pattern="^(factura|presupuesto|comprobante|otro)$",
    ),
    descripcion: Optional[str] = Form(default=None, max_length=500),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permiso("administracion.gestionar_ordenes_compra")),
) -> CompraAdjuntoResponse:
    """Adjunta un archivo (PDF de la NC del proveedor, etc.)."""
    _obtener_nc_o_404(db, nc_id)
    try:
        adj = await compras_adjuntos_service.subir_adjunto(
            db,
            entidad_tipo="nota_credito_local",
            entidad_id=nc_id,
            file=file,
            tipo=tipo,  # type: ignore[arg-type]
            descripcion=descripcion,
            user_id=user.id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("subir_adjunto_nc_local falló: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al subir el adjunto.",
        ) from exc

    _commit_or_rollback(db, operacion="subir_adjunto_nc_local")
    db.refresh(adj)
    return _adjunto_response(adj)


@router.get(
    "/ncs-locales/{nc_id}/adjuntos",
    response_model=list[CompraAdjuntoResponse],
    summary="Listar adjuntos de una NC local",
)
def listar_adjuntos_nc_local(
    nc_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.ver_ordenes_compra")),
) -> list[CompraAdjuntoResponse]:
    """Lista de adjuntos ordenada por created_at DESC."""
    _obtener_nc_o_404(db, nc_id)
    items = compras_adjuntos_service.listar_adjuntos(db, entidad_tipo="nota_credito_local", entidad_id=nc_id)
    return [_adjunto_response(a) for a in items]


__all__ = ["router"]
