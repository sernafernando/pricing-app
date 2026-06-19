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
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.cheque import Cheque
from app.schemas.cheque import (
    AnularChequeRequest,
    ChequeraCreate,
    ChequeraResponse,
    ChequeResponse,
    EmitirChequePropio,
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
    response_model=List[ChequeraResponse],
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def listar_chequeras(
    banco_empresa_id: Optional[int] = Query(default=None),
    solo_activas: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> List[ChequeraResponse]:
    """Lista chequeras, opcionalmente filtradas por banco y activas.

    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    return cheques_service.listar_chequeras(db, banco_empresa_id=banco_empresa_id, solo_activas=solo_activas)


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
        return cheque
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("❌ Error anulando cheque id=%d: %s", cheque_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al anular cheque.") from exc


# ──────────────────────────────────────────────────────────────────────────
# Cheques — listado y detalle
# ──────────────────────────────────────────────────────────────────────────


@router.get(
    "/cheques",
    response_model=List[ChequeResponse],
    dependencies=[Depends(require_permiso(_PERMISO))],
)
def listar_cheques(
    tipo: Optional[str] = Query(default=None),
    estado: Optional[str] = Query(default=None),
    banco_empresa_id: Optional[int] = Query(default=None, alias="banco"),
    moneda: Optional[str] = Query(default=None),
    desde: Optional[date] = Query(default=None),
    hasta: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
) -> List[ChequeResponse]:
    """Lista cheques con filtros opcionales.

    Filtros: tipo (propio/tercero), estado, banco_empresa_id, moneda, rango de fecha_pago.
    Requiere permiso `tesoreria.gestionar_cheques`.
    """
    q = db.query(Cheque)
    if tipo:
        q = q.filter(Cheque.tipo == tipo)
    if estado:
        q = q.filter(Cheque.estado == estado)
    if banco_empresa_id:
        q = q.filter(Cheque.banco_empresa_id == banco_empresa_id)
    if moneda:
        q = q.filter(Cheque.moneda == moneda)
    if desde:
        q = q.filter(Cheque.fecha_pago >= desde)
    if hasta:
        q = q.filter(Cheque.fecha_pago <= hasta)
    return q.order_by(Cheque.id.desc()).all()


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
    return cheque
