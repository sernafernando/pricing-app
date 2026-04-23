"""
Router para el control de bajada a depósito de items RMA.

Endpoints:
- GET  /rma-control-deposito/         — listar items (paginado, filtrado)
- GET  /rma-control-deposito/stats    — contadores por estado
- POST /rma-control-deposito/scan     — escanear serie/EAN
- POST /rma-control-deposito/{id}/no-baja — marcar excepción "no baja"
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.services.control_deposito_service import ControlDepositoService
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rma-control-deposito", tags=["rma-control-deposito"])


# ── Permission helper ─────────────────────────────────


def _check_permiso(db: Session, user: Usuario, codigo: str) -> None:
    """Check permission or raise 403."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, codigo):
        raise HTTPException(403, f"Sin permiso: {codigo}")


# ── Schemas ───────────────────────────────────────────


class ScanRequest(BaseModel):
    codigo: str = Field(min_length=1, max_length=200, description="Serie o EAN a escanear")
    operador_id: Optional[int] = Field(None, description="ID de operador (requerido para scan de depósito)")


class NoBajaRequest(BaseModel):
    motivo: str = Field(min_length=3, max_length=1000, description="Motivo por el que no baja a depósito")


# ── Endpoints ─────────────────────────────────────────


@router.get("/")
def listar_control_deposito(
    fecha_desde: Optional[date] = Query(None, description="Filtrar desde fecha (inclusive)"),
    fecha_hasta: Optional[date] = Query(None, description="Filtrar hasta fecha (inclusive)"),
    estado: Optional[str] = Query(None, description="Filtrar por estado: pendiente, rma, deposito, no_baja"),
    search: Optional[str] = Query(None, description="Buscar por serie, EAN, caso o producto"),
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=200, description="Items por página"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Listar items de control de depósito con filtros y paginación."""
    _check_permiso(db, current_user, "rma.control_deposito")

    svc = ControlDepositoService(db)
    items, total = svc.listar(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=estado,
        search=search,
        page=page,
        page_size=page_size,
    )

    return {
        "items": [svc._serialize(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
    }


@router.get("/stats")
def stats_control_deposito(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Contadores por estado, opcionalmente filtrado por rango de fechas."""
    _check_permiso(db, current_user, "rma.control_deposito")

    svc = ControlDepositoService(db)
    return svc.stats(fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)


@router.post("/scan")
def scan_control_deposito(
    data: ScanRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Escanear serie o EAN para avanzar el estado del item.

    Si el item está en 'pendiente' → pasa a 'rma' (scan de RMA).
    Si el item está en 'rma' → requiere operador_id, pasa a 'deposito' (scan de depósito).
    """
    _check_permiso(db, current_user, "rma.control_deposito")

    svc = ControlDepositoService(db)
    result = svc.scan(
        codigo=data.codigo,
        user=current_user,
        operador_id=data.operador_id,
    )

    db.commit()
    return result


@router.post("/{item_id}/no-baja")
def marcar_no_baja(
    item_id: int,
    data: NoBajaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Marcar un item como 'no baja a depósito' (excepción, ej: Outlet).

    Requiere permiso especial rma.control_deposito_no_baja.
    Solo aplica a items en estado pendiente o rma.
    """
    _check_permiso(db, current_user, "rma.control_deposito")
    _check_permiso(db, current_user, "rma.control_deposito_no_baja")

    svc = ControlDepositoService(db)
    entry = svc.marcar_no_baja(
        item_id=item_id,
        user=current_user,
        motivo=data.motivo,
    )

    db.commit()
    return {
        "ok": True,
        "item": svc._serialize(entry),
        "message": f"Item #{item_id} marcado como 'no baja a depósito'",
    }
