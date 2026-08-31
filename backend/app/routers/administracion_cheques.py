"""
Router — Módulo de Cheques (Slice 1 backend core).

Prefijo: /api/administracion/cheques
Permiso requerido en todos los endpoints: tesoreria.gestionar_cheques

Endpoints Slice 1:
  POST   /chequeras                     — crear chequera
  GET    /chequeras                     — listar chequeras (filtro banco_empresa_id)
  POST   /cheques/propio                — emitir cheque propio (standalone)
  GET    /cheques                       — listar cheques (filtros tipo/estado/banco/moneda/desde/hasta)
  GET    /cheques/{id}                  — detalle + eventos
  POST   /cheques/{id}/anular           — anular con motivo

Integración OP (Slice 1 PR2): se extiende el payload de pago en administracion_compras.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_permiso
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.cheque import Cheque, Chequera
from app.schemas.cheque import (
    AcreditarChequeRequest,
    AnularChequeRequest,
    ChequePaginated,
    ChequeListResponse,
    ChequeraCreate,
    ChequeraPaginated,
    ChequeraResponse,
    ChequeraUpdate,
    ChequeReporteResponse,
    ChequeResponse,
    DebitarChequeRequest,
    DepositarChequeRequest,
    EmitirChequePropio,
    RecibirChequeTercero,
    TransicionEcheqRequest,
)
from app.services import cheques_service

logger = get_logger("routers.administracion_cheques")

router = APIRouter(
    prefix="/administracion/cheques",
    tags=["Administración - Cheques"],
)

_PERMISO = "tesoreria.gestionar_cheques"


# ──────────────────────────────────────────────────────────────────────────
# Chequeras
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/chequeras",
    response_model=ChequeraResponse,
    status_code=status.HTTP_201_CREATED,
)
def crear_chequera(
    payload: ChequeraCreate,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeraResponse:
    """Registra una nueva chequera asociada a un banco propio.

    Requiere permiso `tesoreria.gestionar_cheques`.
    El proximo_numero se inicializa en numero_desde.
    """
    try:
        chequera = cheques_service.crear_chequera(
            db,
            banco_empresa_id=payload.banco_empresa_id,
            descripcion=payload.descripcion,
            instrumento=payload.instrumento,
            numero_desde=payload.numero_desde,
            numero_hasta=payload.numero_hasta,
            usuario_id=current_user.id,
        )
        db.commit()
        db.refresh(chequera)
        return chequera
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error creando chequera: %s", exc)
        raise HTTPException(status_code=500, detail="Error interno al crear chequera.") from exc


@router.get(
    "/chequeras",
    response_model=ChequeraPaginated,
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def listar_chequeras(
    banco_empresa_id: Optional[int] = Query(default=None),
    solo_activas: bool = Query(default=False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ChequeraPaginated:
    """Lista chequeras paginadas, opcionalmente filtradas por banco y activas.

    Paginación: ?page=1&page_size=50 (máx 200).
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    q = db.query(Chequera)
    if banco_empresa_id is not None:
        q = q.filter(Chequera.banco_empresa_id == banco_empresa_id)
    if solo_activas:
        q = q.filter(Chequera.activa.is_(True))
    total = q.with_entities(func.count(Chequera.id)).scalar() or 0
    items = q.order_by(Chequera.id).offset((page - 1) * page_size).limit(page_size).all()
    return ChequeraPaginated(items=items, total=total, page=page, page_size=page_size)


@router.patch(
    "/chequeras/{chequera_id}",
    response_model=ChequeraResponse,
)
def actualizar_chequera(
    chequera_id: int,
    payload: ChequeraUpdate,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeraResponse:
    """Edita una chequera: descripción, rango, próximo número y activa/inactiva.

    PATCH real: sólo se aplica lo enviado. El banco y el instrumento NO son
    editables — definen la identidad del talonario y los cheques emitidos
    cuelgan de ella (ver `ChequeraUpdate`).

    Desactivar no borra nada: los cheques ya emitidos siguen igual, pero la
    chequera deja de admitir nuevos (`emitir_cheque_propio` la rechaza).

    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    try:
        chequera = cheques_service.actualizar_chequera(
            db,
            chequera_id=chequera_id,
            descripcion=payload.descripcion,
            numero_hasta=payload.numero_hasta,
            proximo_numero_nuevo=payload.proximo_numero,
            activa=payload.activa,
        )
        db.commit()
        db.refresh(chequera)
        return chequera
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error actualizando chequera %s: %s", chequera_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al actualizar chequera.") from exc


# ──────────────────────────────────────────────────────────────────────────
# Cheques — emisión
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/cheques/propio",
    response_model=ChequeResponse,
    status_code=status.HTTP_201_CREATED,
)
def emitir_cheque_propio(
    payload: EmitirChequePropio,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Emite un cheque propio (standalone, sin OP).

    Estado resultante: `emitido` si fecha_pago == fecha_emision, `diferido` si fecha_pago > fecha_emision.
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    try:
        cheque = cheques_service.emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento=payload.instrumento,
            numero=payload.numero,
            monto=payload.monto,
            moneda=payload.moneda,
            fecha_emision=payload.fecha_emision,
            fecha_pago=payload.fecha_pago,
            banco_empresa_id=payload.banco_empresa_id,
            chequera_id=payload.chequera_id,
            proveedor_id=payload.proveedor_id,
            usuario_id=current_user.id,
        )
        db.commit()
        db.refresh(cheque)
        return cheque
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error emitiendo cheque propio: %s", exc)
        raise HTTPException(status_code=500, detail="Error interno al emitir cheque.") from exc


# ──────────────────────────────────────────────────────────────────────────
# Cheques de tercero — alta a cartera (Slice 2)
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/cheques/tercero",
    response_model=ChequeResponse,
    status_code=status.HTTP_201_CREATED,
)
def recibir_cheque_tercero(
    payload: RecibirChequeTercero,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Da de alta un cheque de tercero a la cartera (estado `en_cartera`).

    El cheque queda disponible para ser endosado a un proveedor en una OP.
    Los campos banco_nombre y cuit_librador son obligatorios para identificar
    al librador externo.
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    try:
        cheque = cheques_service.recibir_cheque_tercero(
            db,
            banco_nombre=payload.banco_nombre,
            cuit_librador=payload.cuit_librador,
            librador_nombre=payload.librador_nombre,
            numero=payload.numero,
            monto=payload.monto,
            moneda=payload.moneda,
            fecha_emision=payload.fecha_emision,
            fecha_pago=payload.fecha_pago,
            instrumento=payload.instrumento,
            usuario_id=current_user.id,
        )
        db.commit()
        db.refresh(cheque)
        return ChequeResponse.model_validate(cheque)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error recibiendo cheque de tercero: %s", exc)
        raise HTTPException(status_code=500, detail="Error interno al registrar cheque de tercero.") from exc


# ──────────────────────────────────────────────────────────────────────────
# Cheques — transiciones
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/cheques/{cheque_id}/anular",
    response_model=ChequeResponse,
)
def anular_cheque(
    cheque_id: int,
    payload: AnularChequeRequest,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Anula un cheque (estado emitido o diferido → anulado).

    Requiere motivo. Registra evento `anulado` en cheque_evento.
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    cheque = db.query(Cheque).filter(Cheque.id == cheque_id).first()
    if cheque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cheque {cheque_id} no encontrado.")

    try:
        cheques_service.transicionar_cheque(
            db,
            cheque,
            "anular",
            usuario_id=current_user.id,
            motivo=payload.motivo,
        )
        db.commit()
        db.refresh(cheque)
        return ChequeResponse.model_validate(cheque).model_copy(
            update={
                "banco_nombre": cheque.banco_empresa.banco if cheque.banco_empresa else cheque.banco_nombre,
                "proveedor_nombre": cheque.proveedor.nombre if cheque.proveedor else None,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error anulando cheque id=%d: %s", cheque_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al anular cheque.") from exc


# ──────────────────────────────────────────────────────────────────────────
# e-cheq — transiciones manuales (Slice 3)
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/cheques/{cheque_id}/echeq",
    response_model=ChequeResponse,
)
def transicionar_echeq(
    cheque_id: int,
    payload: TransicionEcheqRequest,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Aplica una transición manual de e-cheq.

    Acciones admitidas:
      - aceptar:           en_cartera → aceptado (banco aceptó el e-cheq).
      - rechazar_emision:  en_cartera | aceptado → rechazado_emision (banco rechaza).
      - poner_en_custodia: emitido | diferido | aceptado | en_cartera → en_custodia.

    Requiere instrumento == 'echeq'; devuelve 422 si el cheque es físico.
    Requiere permiso `tesoreria.gestionar_cheques`.

    NOTE: sin integración bancaria automática (Slice 4); estas transiciones son
    exclusivamente manuales (el operador actualiza el estado según lo informa el banco).
    """
    cheque = db.query(Cheque).filter(Cheque.id == cheque_id).first()
    if cheque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cheque {cheque_id} no encontrado.")

    try:
        cheques_service.transicionar_cheque(
            db,
            cheque,
            payload.accion,
            usuario_id=current_user.id,
            motivo=payload.motivo,
        )
        db.commit()
        db.refresh(cheque)
        return ChequeResponse.model_validate(cheque).model_copy(
            update={
                "banco_nombre": cheque.banco_empresa.banco if cheque.banco_empresa else cheque.banco_nombre,
                "proveedor_nombre": cheque.proveedor.nombre if cheque.proveedor else None,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error transición e-cheq id=%d accion=%s: %s", cheque_id, payload.accion, exc)
        raise HTTPException(status_code=500, detail="Error interno al procesar transición e-cheq.") from exc


# ──────────────────────────────────────────────────────────────────────────
# Cheques — listado y detalle
# ──────────────────────────────────────────────────────────────────────────


@router.get(
    "/cheques",
    response_model=ChequePaginated,
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def listar_cheques(
    tipo: Optional[str] = Query(default=None),
    estado: Optional[str] = Query(default=None),
    banco_empresa_id: Optional[int] = Query(default=None, alias="banco"),
    moneda: Optional[str] = Query(default=None),
    desde: Optional[date] = Query(default=None),
    hasta: Optional[date] = Query(default=None),
    proveedor_id: Optional[int] = Query(default=None),
    sin_orden_pago: Optional[bool] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ChequePaginated:
    """Lista cheques paginados con filtros opcionales.

    Filtros: tipo (propio/tercero), estado, banco_empresa_id, moneda, rango
    de fecha_pago, proveedor_id, sin_orden_pago.

    `proveedor_id`: semántica `proveedor_id IS NULL OR proveedor_id = X`
    (S3b R8) — el picker de "aplicar cheque propio" necesita ver también los
    cheques sin beneficiario asignado, no solo los ya asignados a ese
    proveedor.
    `sin_orden_pago`: True → solo cheques SIN fila en `orden_pago_cheque`
    (ni reservados ni pagados con ellos).

    Paginación: ?page=1&page_size=50 (máx 200).
    Los eventos NO se incluyen en el listado (usar GET /cheques/{id} para detalle completo).
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    q = db.query(Cheque)
    if tipo:
        q = q.filter(Cheque.tipo == tipo)
    if estado:
        q = q.filter(Cheque.estado == estado)
    if banco_empresa_id is not None:
        q = q.filter(Cheque.banco_empresa_id == banco_empresa_id)
    if moneda:
        q = q.filter(Cheque.moneda == moneda)
    if desde:
        q = q.filter(Cheque.fecha_pago >= desde)
    if hasta:
        q = q.filter(Cheque.fecha_pago <= hasta)
    if proveedor_id is not None:
        q = q.filter(or_(Cheque.proveedor_id.is_(None), Cheque.proveedor_id == proveedor_id))
    if sin_orden_pago is not None:
        from app.models.cheque import OrdenPagoCheque  # noqa: PLC0415

        linkeados = select(OrdenPagoCheque.cheque_id)
        if sin_orden_pago:
            q = q.filter(~Cheque.id.in_(linkeados))
        else:
            q = q.filter(Cheque.id.in_(linkeados))
    total = q.with_entities(func.count(Cheque.id)).scalar() or 0
    rows = (
        q.options(
            selectinload(Cheque.banco_empresa),
            selectinload(Cheque.proveedor),
        )
        .order_by(Cheque.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    # R11 — resolve the linked OPs' estado for this page in ONE query. A link
    # to an OP does NOT mean the cheque was paid: a link row on a non-`pagado`
    # OP is a RESERVATION (no CC movement), the same row on a `pagado` OP is an
    # IMPUTATION. Consumers cannot render that distinction from
    # `orden_pago_id` alone, so serving it here is what keeps them from
    # fetching GET /ordenes-pago/{id} once per row.
    op_ids = {ch.orden_pago_id for ch in rows if ch.orden_pago_id is not None}
    op_estados: dict[int, str] = {}
    if op_ids:
        from app.models.orden_pago import OrdenPago  # noqa: PLC0415

        op_estados = {
            op_id: estado
            for op_id, estado in db.query(OrdenPago.id, OrdenPago.estado).filter(OrdenPago.id.in_(op_ids)).all()
        }
    items = [
        ChequeListResponse.model_validate(ch).model_copy(
            update={
                "banco_nombre": ch.banco_empresa.banco if ch.banco_empresa else ch.banco_nombre,
                "proveedor_nombre": ch.proveedor.nombre if ch.proveedor else None,
                "orden_pago_estado": (op_estados.get(ch.orden_pago_id) if ch.orden_pago_id is not None else None),
            }
        )
        for ch in rows
    ]
    return ChequePaginated(items=items, total=total, page=page, page_size=page_size)


# ──────────────────────────────────────────────────────────────────────────
# Slice 4 — Conciliación bancaria
# ──────────────────────────────────────────────────────────────────────────


@router.get(
    "/cheques/reporte",
    response_model=ChequeReporteResponse,
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def reporte_cheques(
    db: Session = Depends(get_db),
) -> ChequeReporteResponse:
    """Reporte FR-4.4 — cheques agrupados por segmento.

    Segmentos:
      - en_cartera: terceros en_cartera|aceptado disponibles para depositar/endosar.
      - a_debitar: propios emitidos/diferidos con fecha_pago <= hoy.
      - vencidos: cheques activos con fecha_pago < hoy sin debitar/acreditar.

    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    import datetime  # noqa: PLC0415

    hoy = datetime.date.today()
    data = cheques_service.get_reporte_cheques(db, hoy=hoy)

    def _to_list(cheques: list) -> list[ChequeListResponse]:
        return [
            ChequeListResponse.model_validate(ch).model_copy(
                update={
                    "banco_nombre": ch.banco_empresa.banco if ch.banco_empresa else ch.banco_nombre,
                    "proveedor_nombre": ch.proveedor.nombre if ch.proveedor else None,
                }
            )
            for ch in cheques
        ]

    return ChequeReporteResponse(
        en_cartera=_to_list(data["en_cartera"]),
        a_debitar=_to_list(data["a_debitar"]),
        vencidos=_to_list(data["vencidos"]),
    )


@router.post(
    "/cheques/{cheque_id}/debitar",
    response_model=ChequeResponse,
)
def debitar_cheque(
    cheque_id: int,
    payload: DebitarChequeRequest,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Debita un cheque propio (emitido|diferido → debitado).

    Genera un BancoMovimiento de EGRESO en el banco del cheque por el monto total.
    No permite debitar antes de fecha_pago (FR-4.3).
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    import datetime  # noqa: PLC0415

    cheque = db.query(Cheque).filter(Cheque.id == cheque_id).with_for_update().first()
    if cheque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cheque {cheque_id} no encontrado.")

    fecha = payload.fecha or datetime.date.today()

    try:
        cheques_service.debitar_cheque(db, cheque, fecha=fecha, usuario_id=current_user.id)
        db.commit()
        db.refresh(cheque)
        return ChequeResponse.model_validate(cheque).model_copy(
            update={
                "banco_nombre": cheque.banco_empresa.banco if cheque.banco_empresa else cheque.banco_nombre,
                "proveedor_nombre": cheque.proveedor.nombre if cheque.proveedor else None,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error debitando cheque id=%d: %s", cheque_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al debitar cheque.") from exc


@router.post(
    "/cheques/{cheque_id}/depositar",
    response_model=ChequeResponse,
)
def depositar_cheque(
    cheque_id: int,
    payload: DepositarChequeRequest,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Deposita un cheque de tercero (en_cartera|aceptado → depositado).

    No genera movimiento bancario todavía (depositado ≠ acreditado).
    Registra el banco_empresa_id destino para usar al acreditar.
    No permite depositar antes de fecha_pago (FR-4.3).
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    import datetime  # noqa: PLC0415

    cheque = db.query(Cheque).filter(Cheque.id == cheque_id).with_for_update().first()
    if cheque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cheque {cheque_id} no encontrado.")

    fecha = payload.fecha or datetime.date.today()

    try:
        cheques_service.depositar_cheque(
            db,
            cheque,
            banco_empresa_id=payload.banco_empresa_id,
            fecha=fecha,
            usuario_id=current_user.id,
        )
        db.commit()
        db.refresh(cheque)
        return ChequeResponse.model_validate(cheque).model_copy(
            update={
                "banco_nombre": cheque.banco_deposito.banco if cheque.banco_deposito else cheque.banco_nombre,
                "proveedor_nombre": cheque.proveedor.nombre if cheque.proveedor else None,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error depositando cheque id=%d: %s", cheque_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al depositar cheque.") from exc


@router.post(
    "/cheques/{cheque_id}/acreditar",
    response_model=ChequeResponse,
)
def acreditar_cheque(
    cheque_id: int,
    payload: AcreditarChequeRequest,
    current_user=Depends(require_permiso(_PERMISO)),
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Acredita un cheque (depositado|en_custodia → acreditado).

    Genera un BancoMovimiento de INGRESO en el banco destino por el monto total.
    Para cheques depositados usa el banco registrado al depositar.
    Para e-cheq en_custodia usa banco_deposito_id o banco_empresa_id.
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    import datetime  # noqa: PLC0415

    cheque = db.query(Cheque).filter(Cheque.id == cheque_id).with_for_update().first()
    if cheque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cheque {cheque_id} no encontrado.")

    fecha = payload.fecha or datetime.date.today()

    try:
        cheques_service.acreditar_cheque(db, cheque, fecha=fecha, usuario_id=current_user.id)
        db.commit()
        db.refresh(cheque)
        banco_rel = cheque.banco_deposito or cheque.banco_empresa
        return ChequeResponse.model_validate(cheque).model_copy(
            update={
                "banco_nombre": banco_rel.banco if banco_rel else cheque.banco_nombre,
                "proveedor_nombre": cheque.proveedor.nombre if cheque.proveedor else None,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error acreditando cheque id=%d: %s", cheque_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al acreditar cheque.") from exc


@router.get(
    "/cheques/{cheque_id}",
    response_model=ChequeResponse,
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def obtener_cheque(
    cheque_id: int,
    db: Session = Depends(get_db),
) -> ChequeResponse:
    """Retorna el detalle de un cheque incluyendo sus eventos.

    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    cheque = db.query(Cheque).filter(Cheque.id == cheque_id).first()
    if cheque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cheque {cheque_id} no encontrado.")
    # Poblar nombres derivados (igual que el listado) para que el detalle no los
    # muestre en None.
    return ChequeResponse.model_validate(cheque).model_copy(
        update={
            "banco_nombre": cheque.banco_empresa.banco if cheque.banco_empresa else cheque.banco_nombre,
            "proveedor_nombre": cheque.proveedor.nombre if cheque.proveedor else None,
        }
    )
