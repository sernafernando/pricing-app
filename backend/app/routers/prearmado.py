"""
Router para el feature de Prearmado de Combos.

Endpoints (todos protegidos por permiso `produccion.prearmar_combos`):
- GET    /prearmado/componentes/{combo_item_id}   — BOM filtrada + sufijo Win11
- POST   /prearmado/validar-serial                — valida serial contra tb_item_serials
- POST   /prearmado                                — crea cabecera de prearmado
- GET    /prearmado                                — lista filtrada/paginada
- GET    /prearmado/{id}                           — detalle con seriales
- PATCH  /prearmado/{id}                           — cambio manual de estado / notas
- POST   /prearmado/{id}/seriales                  — agrega/upserta seriales
- DELETE /prearmado/{id}/seriales/{serial_id}      — quita un serial
- POST   /prearmado/rematch                        — corre matcher manualmente
"""

from datetime import datetime
from typing import List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.prearmado import Prearmado, PrearmadoSerial
from app.models.tb_item import TBItem
from app.models.tb_item_association import TbItemAssociation
from app.models.tb_item_serials import TbItemSerial
from app.models.usuario import Usuario
from app.schemas.prearmado import (
    ComponenteForPrearmado,
    ComponentesForCombo,
    PrearmadoCreate,
    PrearmadoDetail,
    PrearmadoListItem,
    PrearmadoPatch,
    RematchResponse,
    SerialDetail,
    SerialesPayload,
    SerialInput,
    ValidateSerialRequest,
    ValidateSerialResponse,
)
from app.services.prearmado_helpers import generar_codigo_prearmado, parse_windows_suffix
from app.services.prearmado_matcher import match_prearmados_with_sales_orders


router = APIRouter()

PERMISO = "produccion.prearmar_combos"

# State machine para transiciones manuales (consumido y anulado son terminales)
_VALID_TRANSITIONS: dict[str, Set[str]] = {
    "pendiente": {"en_proceso", "anulado"},
    "en_proceso": {"pendiente", "armado", "anulado"},
    "armado": {"en_proceso", "anulado"},
    "consumido": set(),
    "anulado": set(),
}


# --- Helpers internos ---


def _validar_serial_core(db: Session, serial: str, item_id_esperado: int) -> ValidateSerialResponse:
    """Lógica de validación reutilizable (endpoint + POST /seriales)."""
    if not serial or not serial.strip():
        return ValidateSerialResponse(valid=False, motivo="SerialNotFound")

    ts: Optional[TbItemSerial] = (
        db.query(TbItemSerial).filter(func.upper(TbItemSerial.is_serial) == serial.strip().upper()).first()
    )
    if not ts:
        return ValidateSerialResponse(valid=False, motivo="SerialNotFound")

    real_item: Optional[TBItem] = db.query(TBItem).filter(TBItem.item_id == ts.item_id).first()
    item_code_real = real_item.item_code if real_item else None
    item_desc_real = real_item.item_desc if real_item else None

    if ts.item_id != item_id_esperado:
        return ValidateSerialResponse(
            valid=False,
            motivo="ItemMismatch",
            is_id=ts.is_id,
            item_id_real=ts.item_id,
            item_code_real=item_code_real,
            item_desc_real=item_desc_real,
        )

    return ValidateSerialResponse(
        valid=True,
        is_id=ts.is_id,
        item_id_real=ts.item_id,
        item_code_real=item_code_real,
        item_desc_real=item_desc_real,
    )


def _compute_list_fields(seriales: List[PrearmadoSerial]) -> dict:
    """Calcula seriales_total / validados / completos para un prearmado."""
    total = len(seriales)
    validados = sum(1 for s in seriales if s.validado)
    serializables = [s for s in seriales if s.requiere_serie]
    serializables_completos = len(serializables) > 0 and all(s.validado and s.is_id is not None for s in serializables)
    return {
        "seriales_total": total,
        "seriales_validados": validados,
        "seriales_completos": serializables_completos,
    }


def _to_list_item(p: Prearmado) -> PrearmadoListItem:
    return PrearmadoListItem(
        id=p.id,
        codigo=p.codigo,
        combo_item_id=p.combo_item_id,
        combo_item_code=p.combo_item_code,
        combo_item_desc=p.combo_item_desc,
        incluye_windows=p.incluye_windows,
        estado=p.estado,
        consumido_por_soh_id=p.consumido_por_soh_id,
        consumido_at=p.consumido_at,
        created_by_user_id=p.created_by_user_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
        **_compute_list_fields(p.seriales),
    )


def _to_detail(p: Prearmado) -> PrearmadoDetail:
    seriales = [SerialDetail.model_validate(s) for s in p.seriales]
    return PrearmadoDetail(
        id=p.id,
        codigo=p.codigo,
        combo_item_id=p.combo_item_id,
        combo_item_code=p.combo_item_code,
        combo_item_desc=p.combo_item_desc,
        incluye_windows=p.incluye_windows,
        estado=p.estado,
        consumido_por_soh_id=p.consumido_por_soh_id,
        consumido_at=p.consumido_at,
        created_by_user_id=p.created_by_user_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
        notas=p.notas,
        seriales=seriales,
        **_compute_list_fields(p.seriales),
    )


def _get_prearmado_or_404(db: Session, prearmado_id: int) -> Prearmado:
    p = db.query(Prearmado).filter(Prearmado.id == prearmado_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prearmado no encontrado")
    return p


# --- Endpoints ---


@router.get(
    "/prearmado/componentes/{combo_item_id}",
    response_model=ComponentesForCombo,
    dependencies=[Depends(require_permiso(PERMISO))],
)
def obtener_componentes_para_prearmado(
    combo_item_id: int,
    db: Session = Depends(get_db),
) -> ComponentesForCombo:
    """
    Devuelve la BOM del combo filtrada por `iasso_qty > 0`, con `requiere_serie`
    resuelto via items_config_serializable (default true si no hay override).

    Detecta sufijo `WH`/`WP` del item_code del combo y retorna metadata
    `incluye_windows` ('home' | 'pro' | None). Win11 NO se agrega como componente:
    se maneja como info derivada en el FE.
    """
    combo: Optional[TBItem] = db.query(TBItem).filter(TBItem.item_id == combo_item_id).first()
    if not combo:
        raise HTTPException(status_code=404, detail="Item no encontrado")

    es_combo = (
        db.query(TbItemAssociation)
        .filter(
            TbItemAssociation.itema_id == combo_item_id,
            TbItemAssociation.iasso_qty > 0,
        )
        .first()
    )
    if not es_combo:
        raise HTTPException(
            status_code=400,
            detail="El item no es un combo (sin componentes positivos en BOM)",
        )

    rows = (
        db.execute(
            text(
                """
            SELECT
                ia.item_id,
                COALESCE(ti.item_code, '') AS item_code,
                COALESCE(ti.item_desc, '') AS item_desc,
                ia.iasso_qty,
                COALESCE(ics.requiere_serie, TRUE) AS requiere_serie
            FROM tb_item_association ia
            LEFT JOIN tb_item ti
                ON ti.item_id = ia.item_id AND ti.comp_id = ia.comp_id
            LEFT JOIN items_config_serializable ics
                ON ics.item_id = ia.item_id
            WHERE ia.itema_id = :combo_id
              AND ia.iasso_qty > 0
            ORDER BY ia.item_id
            """
            ),
            {"combo_id": combo_item_id},
        )
        .mappings()
        .all()
    )

    componentes = [
        ComponenteForPrearmado(
            item_id=r["item_id"],
            item_code=r["item_code"] or "",
            item_desc=r["item_desc"],
            cantidad_esperada=max(int(r["iasso_qty"]), 1),
            requiere_serie=bool(r["requiere_serie"]),
            origen="bom",
        )
        for r in rows
    ]

    return ComponentesForCombo(
        combo_item_id=combo.item_id,
        combo_item_code=combo.item_code,
        combo_item_desc=combo.item_desc,
        incluye_windows=parse_windows_suffix(combo.item_code),
        componentes=componentes,
    )


@router.post(
    "/prearmado/validar-serial",
    response_model=ValidateSerialResponse,
    dependencies=[Depends(require_permiso(PERMISO))],
)
def validar_serial(
    body: ValidateSerialRequest,
    db: Session = Depends(get_db),
) -> ValidateSerialResponse:
    """Verifica que el serial exista en tb_item_serials y matchee el item esperado."""
    return _validar_serial_core(db, body.serial, body.item_id_esperado)


@router.post(
    "/prearmado",
    response_model=PrearmadoDetail,
    status_code=201,
)
def crear_prearmado(
    body: PrearmadoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso(PERMISO)),
) -> PrearmadoDetail:
    """Crea cabecera de prearmado para un combo existente."""
    combo: Optional[TBItem] = db.query(TBItem).filter(TBItem.item_id == body.combo_item_id).first()
    if not combo:
        raise HTTPException(status_code=404, detail="Item del combo no encontrado")

    es_combo = (
        db.query(TbItemAssociation)
        .filter(
            TbItemAssociation.itema_id == body.combo_item_id,
            TbItemAssociation.iasso_qty > 0,
        )
        .first()
    )
    if not es_combo:
        raise HTTPException(
            status_code=400,
            detail="El item no es un combo (sin componentes positivos en BOM)",
        )

    codigo = generar_codigo_prearmado(db)

    p = Prearmado(
        codigo=codigo,
        comp_id=getattr(combo, "comp_id", 1) or 1,
        bra_id=1,
        combo_item_id=combo.item_id,
        combo_item_code=combo.item_code or "",
        combo_item_desc=combo.item_desc,
        incluye_windows=parse_windows_suffix(combo.item_code),
        estado="pendiente",
        created_by_user_id=current_user.id,
        notas=body.notas,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    return _to_detail(p)


@router.get(
    "/prearmado",
    response_model=List[PrearmadoListItem],
    dependencies=[Depends(require_permiso(PERMISO))],
)
def listar_prearmados(
    db: Session = Depends(get_db),
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    combo_item_id: Optional[int] = Query(None, description="Filtrar por item del combo"),
    codigo: Optional[str] = Query(None, description="Búsqueda parcial de código"),
    desde: Optional[datetime] = Query(None, description="created_at >= desde"),
    hasta: Optional[datetime] = Query(None, description="created_at <= hasta"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> List[PrearmadoListItem]:
    """Lista prearmados con filtros opcionales y paginación."""
    q = db.query(Prearmado)
    if estado:
        if estado not in _VALID_TRANSITIONS:
            raise HTTPException(status_code=400, detail=f"Estado inválido: {estado}")
        q = q.filter(Prearmado.estado == estado)
    if combo_item_id is not None:
        q = q.filter(Prearmado.combo_item_id == combo_item_id)
    if codigo:
        q = q.filter(Prearmado.codigo.ilike(f"%{codigo}%"))
    if desde:
        q = q.filter(Prearmado.created_at >= desde)
    if hasta:
        q = q.filter(Prearmado.created_at <= hasta)

    rows = q.order_by(Prearmado.created_at.desc()).offset(offset).limit(limit).all()
    return [_to_list_item(p) for p in rows]


@router.get(
    "/prearmado/{prearmado_id}",
    response_model=PrearmadoDetail,
    dependencies=[Depends(require_permiso(PERMISO))],
)
def obtener_prearmado(
    prearmado_id: int,
    db: Session = Depends(get_db),
) -> PrearmadoDetail:
    """Detalle de un prearmado con todos sus seriales."""
    p = _get_prearmado_or_404(db, prearmado_id)
    return _to_detail(p)


@router.patch(
    "/prearmado/{prearmado_id}",
    response_model=PrearmadoDetail,
    dependencies=[Depends(require_permiso(PERMISO))],
)
def actualizar_prearmado(
    prearmado_id: int,
    body: PrearmadoPatch,
    db: Session = Depends(get_db),
) -> PrearmadoDetail:
    """Cambio manual de estado y/o notas. Aplica state machine."""
    p = _get_prearmado_or_404(db, prearmado_id)

    if body.estado is not None and body.estado != p.estado:
        permitidas = _VALID_TRANSITIONS.get(p.estado, set())
        if body.estado not in permitidas:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Transición no permitida: {p.estado} → {body.estado}. "
                    f"Permitidas desde {p.estado}: {sorted(permitidas) or '(terminal)'}"
                ),
            )
        p.estado = body.estado

    if body.notas is not None:
        p.notas = body.notas

    db.commit()
    db.refresh(p)
    return _to_detail(p)


@router.post(
    "/prearmado/{prearmado_id}/seriales",
    response_model=PrearmadoDetail,
    dependencies=[Depends(require_permiso(PERMISO))],
)
def cargar_seriales(
    prearmado_id: int,
    body: SerialesPayload,
    db: Session = Depends(get_db),
) -> PrearmadoDetail:
    """
    Agrega seriales al prearmado. Cada item se valida; si inválido y `force=false`
    lanza 422 con detail. Si `force=true` se guarda con `validado=false` para
    revisión posterior. Items con `requiere_serie=false` se guardan con
    `serial=null` y `validado=true` automáticamente.

    Append semantics: cada llamada agrega rows. Usar DELETE para corregir.
    """
    p = _get_prearmado_or_404(db, prearmado_id)
    if p.estado in ("consumido", "anulado"):
        raise HTTPException(
            status_code=400,
            detail=f"No se puede modificar un prearmado en estado {p.estado}",
        )

    errores: List[dict] = []
    a_insertar: List[PrearmadoSerial] = []

    for idx, item in enumerate(body.items):
        item_meta = _resolver_meta_componente(db, item)

        if not item.requiere_serie:
            # No-serializable: registra sin serie, auto-validado
            a_insertar.append(
                PrearmadoSerial(
                    prearmado_id=p.id,
                    componente_item_id=item.componente_item_id,
                    componente_item_code=item_meta["item_code"],
                    componente_item_desc=item_meta["item_desc"],
                    serial=None,
                    is_id=None,
                    cantidad_esperada=max(item.cantidad_esperada, 1),
                    requiere_serie=False,
                    validado=True,
                    validado_at=func.now(),
                    origen=item.origen,
                    sufijo=item.sufijo,
                )
            )
            continue

        # Serializable: requiere serial
        if not item.serial or not item.serial.strip():
            errores.append({"index": idx, "motivo": "SerialFaltante"})
            continue

        validacion = _validar_serial_core(db, item.serial, item.componente_item_id)
        if not validacion.valid and not item.force:
            errores.append(
                {
                    "index": idx,
                    "componente_item_id": item.componente_item_id,
                    "serial": item.serial,
                    "motivo": validacion.motivo,
                    "item_id_real": validacion.item_id_real,
                    "item_code_real": validacion.item_code_real,
                }
            )
            continue

        a_insertar.append(
            PrearmadoSerial(
                prearmado_id=p.id,
                componente_item_id=item.componente_item_id,
                componente_item_code=item_meta["item_code"],
                componente_item_desc=item_meta["item_desc"],
                serial=item.serial.strip().upper(),
                is_id=validacion.is_id if validacion.valid else None,
                cantidad_esperada=max(item.cantidad_esperada, 1),
                requiere_serie=True,
                validado=validacion.valid,
                validado_at=func.now() if validacion.valid else None,
                origen=item.origen,
                sufijo=item.sufijo,
            )
        )

    if errores:
        raise HTTPException(
            status_code=422,
            detail={"message": "Seriales inválidos (usá force=true por item)", "errores": errores},
        )

    db.add_all(a_insertar)
    db.commit()
    db.refresh(p)
    return _to_detail(p)


def _resolver_meta_componente(db: Session, item: SerialInput) -> dict:
    """Resuelve snapshot de item_code/desc del componente para el insert."""
    if item.componente_item_code:
        return {
            "item_code": item.componente_item_code,
            "item_desc": item.componente_item_desc,
        }
    ti = db.query(TBItem).filter(TBItem.item_id == item.componente_item_id).first()
    return {
        "item_code": (ti.item_code if ti else "") or "",
        "item_desc": ti.item_desc if ti else None,
    }


@router.delete(
    "/prearmado/{prearmado_id}/seriales/{serial_id}",
    response_model=PrearmadoDetail,
    dependencies=[Depends(require_permiso(PERMISO))],
)
def borrar_serial(
    prearmado_id: int,
    serial_id: int,
    db: Session = Depends(get_db),
) -> PrearmadoDetail:
    """Quita un row de prearmados_seriales (no se permite si el prearmado está consumido/anulado)."""
    p = _get_prearmado_or_404(db, prearmado_id)
    if p.estado in ("consumido", "anulado"):
        raise HTTPException(
            status_code=400,
            detail=f"No se puede modificar un prearmado en estado {p.estado}",
        )

    s = (
        db.query(PrearmadoSerial)
        .filter(
            PrearmadoSerial.id == serial_id,
            PrearmadoSerial.prearmado_id == prearmado_id,
        )
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Serial no encontrado")

    db.delete(s)
    db.commit()
    db.refresh(p)
    return _to_detail(p)


@router.post(
    "/prearmado/rematch",
    response_model=RematchResponse,
    dependencies=[Depends(require_permiso(PERMISO))],
)
def rematch_manual(
    db: Session = Depends(get_db),
) -> RematchResponse:
    """Dispara el matcher de prearmados contra tb_sale_order_serials on-demand."""
    result = match_prearmados_with_sales_orders(db)
    return RematchResponse(**result)
