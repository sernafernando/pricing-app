"""Read/upsert per-MLA hay_mejores application criteria."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.ml_hay_mejores_criterios import MlHayMejoresCriterios
from app.services.ml_hay_mejores_audit_service import record_auto_toggle

DEFAULT_C6_GAP_MIN = Decimal("5000")
DEFAULT_C6_DISTANCIA = Decimal("100")
# Catalog code; seeded with no role grants — assign only via usuario_permisos_override.
PERMISO_AUTO_APLICACION = "promos.auto_aplicacion"
# Session-scoped views after ``prefetch_criterios`` (orchestrator / recompute / sync batches).
_CRITERIOS_CACHE_KEY = "hay_mejores_criterios_cache"


@dataclass(frozen=True)
class CriteriosView:
    item_id: str
    c1_activo: bool
    c1_markup_min: Optional[Decimal]
    c1_markup_max: Optional[Decimal]
    c2_activo: bool
    c2_solo_markup_positivo: bool
    c6_activo: bool
    c6_solo_via_promo: bool
    c6_gap_min: Decimal
    c6_distancia_objetivo: Decimal
    auto_aplicacion: bool
    sellers_excluidos: list[str]
    updated_at: Optional[datetime]
    exists: bool  # False = defaults (no row yet)


def default_criterios(item_id: str) -> CriteriosView:
    return CriteriosView(
        item_id=item_id,
        c1_activo=False,
        c1_markup_min=None,
        c1_markup_max=None,
        c2_activo=False,
        c2_solo_markup_positivo=True,
        c6_activo=False,
        c6_solo_via_promo=False,
        c6_gap_min=DEFAULT_C6_GAP_MIN,
        c6_distancia_objetivo=DEFAULT_C6_DISTANCIA,
        auto_aplicacion=False,
        sellers_excluidos=[],
        updated_at=None,
        exists=False,
    )


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


def _row_to_view(row: MlHayMejoresCriterios) -> CriteriosView:
    excluded = row.sellers_excluidos if isinstance(row.sellers_excluidos, list) else []
    return CriteriosView(
        item_id=row.item_id,
        c1_activo=bool(row.c1_activo),
        c1_markup_min=_to_decimal(row.c1_markup_min),
        c1_markup_max=_to_decimal(row.c1_markup_max),
        c2_activo=bool(row.c2_activo),
        c2_solo_markup_positivo=bool(row.c2_solo_markup_positivo),
        c6_activo=bool(row.c6_activo),
        c6_solo_via_promo=bool(row.c6_solo_via_promo),
        c6_gap_min=_to_decimal(row.c6_gap_min) if row.c6_gap_min is not None else DEFAULT_C6_GAP_MIN,
        c6_distancia_objetivo=_to_decimal(row.c6_distancia_objetivo)
        if row.c6_distancia_objetivo is not None
        else DEFAULT_C6_DISTANCIA,
        auto_aplicacion=bool(row.auto_aplicacion),
        sellers_excluidos=[str(x) for x in excluded],
        updated_at=row.updated_at,
        exists=True,
    )


def _session_criterios_cache(db: Session) -> Dict[str, CriteriosView]:
    """Real Session.info dict only — MagicMock stubs get an ephemeral map (no cross-call cache)."""
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return {}
    return info.setdefault(_CRITERIOS_CACHE_KEY, {})


def prefetch_criterios(db: Session, item_ids: Sequence[str]) -> Dict[str, CriteriosView]:
    """One ``IN`` read for many MLAs; fills the session cache used by ``get_criterios``.

    Call once per orchestrator batch (recompute, boundaries worker, bulk include, ranking runs)
    so ranking N publications does not issue N criterios SELECTs (pool-exhaustion invariant).
    """
    ids = [item_id for item_id in dict.fromkeys(item_ids) if item_id]
    if not ids:
        return {}
    cache = _session_criterios_cache(db)
    rows = db.query(MlHayMejoresCriterios).filter(MlHayMejoresCriterios.item_id.in_(ids)).all()
    # MagicMock ``.all()`` is not a real list of ORM rows — treat as empty sparse table.
    if not isinstance(rows, list):
        rows = []
    by_id = {row.item_id: _row_to_view(row) for row in rows if isinstance(row, MlHayMejoresCriterios)}
    result = {item_id: by_id.get(item_id) or default_criterios(item_id) for item_id in ids}
    cache.update(result)
    return result


def get_criterios(db: Session, item_id: str) -> CriteriosView:
    cache = _session_criterios_cache(db)
    cached = cache.get(item_id)
    if cached is not None:
        return cached
    row = db.get(MlHayMejoresCriterios, item_id)
    # Unit tests often pass MagicMock sessions; only a real ORM row counts.
    if not isinstance(row, MlHayMejoresCriterios):
        view = default_criterios(item_id)
    else:
        view = _row_to_view(row)
    if isinstance(getattr(db, "info", None), dict):
        cache[item_id] = view
    return view


def markup_pasa_c1(
    markup: Optional[float],
    *,
    c1_activo: bool,
    c1_markup_min: Optional[Decimal],
    c1_markup_max: Optional[Decimal],
) -> bool:
    """When C1 is off, always True. When on, markup must sit inside the configured band."""
    if not c1_activo:
        return True
    if markup is None:
        return False
    if c1_markup_min is not None and Decimal(str(markup)) < c1_markup_min:
        return False
    if c1_markup_max is not None and Decimal(str(markup)) > c1_markup_max:
        return False
    return True


def catalog_win_con_precio(promo_price: Optional[float], min_rival_price: Optional[float]) -> bool:
    """True when the promo is strictly cheaper than every checked rival (same as is_cheaper_than_us)."""
    if promo_price is None or min_rival_price is None:
        return False
    return float(promo_price) < float(min_rival_price)


def markup_pasa_c2(
    markup: Optional[float],
    *,
    c2_activo: bool,
    c2_solo_markup_positivo: bool,
) -> bool:
    """C2 gate on markup: inactive → never; ON solo-positivo → markup must be &gt; 0; OFF → any markup."""
    if not c2_activo:
        return False
    if c2_solo_markup_positivo:
        return markup is not None and float(markup) > 0
    return markup is not None


def upsert_criterios(
    db: Session,
    item_id: str,
    *,
    updated_by: Optional[int],
    c1_activo: bool,
    c1_markup_min: Optional[Decimal],
    c1_markup_max: Optional[Decimal],
    c2_activo: bool,
    c2_solo_markup_positivo: bool,
    c6_activo: bool,
    c6_solo_via_promo: bool,
    c6_gap_min: Decimal,
    c6_distancia_objetivo: Decimal,
    auto_aplicacion: Optional[bool] = None,
    sellers_excluidos: Optional[Sequence[str]] = None,
    alcance: str = "item",
    # Fail-closed: callers must pass True only after checking promos.auto_aplicacion.
    puede_cambiar_auto: bool = False,
) -> CriteriosView:
    if c1_activo and c1_markup_min is not None and c1_markup_max is not None and c1_markup_min > c1_markup_max:
        raise ValueError("c1_markup_min no puede ser mayor que c1_markup_max")
    if c6_gap_min < 0 or c6_distancia_objetivo < 0:
        raise ValueError("gap y distancia de C6 deben ser ≥ 0")

    previous = get_criterios(db, item_id)
    # None = leave Auto unchanged (bulk omit). Without permiso, never change Auto.
    if auto_aplicacion is None or not puede_cambiar_auto:
        effective_auto = previous.auto_aplicacion
    else:
        effective_auto = auto_aplicacion
    row = db.get(MlHayMejoresCriterios, item_id)
    if row is None:
        row = MlHayMejoresCriterios(item_id=item_id)
        db.add(row)

    row.c1_activo = c1_activo
    row.c1_markup_min = c1_markup_min
    row.c1_markup_max = c1_markup_max
    row.c2_activo = c2_activo
    row.c2_solo_markup_positivo = c2_solo_markup_positivo
    row.c6_activo = c6_activo
    row.c6_solo_via_promo = c6_solo_via_promo
    row.c6_gap_min = c6_gap_min
    row.c6_distancia_objetivo = c6_distancia_objetivo
    row.auto_aplicacion = effective_auto
    if sellers_excluidos is not None:
        row.sellers_excluidos = list(sellers_excluidos)
    row.updated_by = updated_by
    row.updated_at = datetime.now(UTC)
    db.flush()
    record_auto_toggle(
        db,
        item_id,
        old=previous.auto_aplicacion,
        new=effective_auto,
        usuario_id=updated_by,
        alcance=alcance,
    )
    view = _row_to_view(row)
    if isinstance(getattr(db, "info", None), dict):
        _session_criterios_cache(db)[item_id] = view
    return view


def upsert_criterios_bulk(
    db: Session,
    item_ids: Sequence[str],
    *,
    updated_by: Optional[int],
    c1_activo: bool,
    c1_markup_min: Optional[Decimal],
    c1_markup_max: Optional[Decimal],
    c2_activo: bool,
    c2_solo_markup_positivo: bool,
    c6_activo: bool,
    c6_solo_via_promo: bool,
    c6_gap_min: Decimal,
    c6_distancia_objetivo: Decimal,
    auto_aplicacion: Optional[bool] = None,
    sellers_excluidos: Optional[Sequence[str]] = None,
    # Fail-closed: callers must pass True only after checking promos.auto_aplicacion.
    puede_cambiar_auto: bool = False,
) -> list[str]:
    """Upsert the same criterios onto many MLAs. Unknown ``ml_items`` ids are skipped; order preserved."""
    from app.models.ml_publications import MlItem

    ids = [item_id for item_id in dict.fromkeys(item_ids) if item_id]
    if not ids:
        return []
    known = {row[0] for row in db.query(MlItem.item_id).filter(MlItem.item_id.in_(ids)).all()}
    touched: list[str] = []
    for item_id in ids:
        if item_id not in known:
            continue
        upsert_criterios(
            db,
            item_id,
            updated_by=updated_by,
            c1_activo=c1_activo,
            c1_markup_min=c1_markup_min,
            c1_markup_max=c1_markup_max,
            c2_activo=c2_activo,
            c2_solo_markup_positivo=c2_solo_markup_positivo,
            c6_activo=c6_activo,
            c6_solo_via_promo=c6_solo_via_promo,
            c6_gap_min=c6_gap_min,
            c6_distancia_objetivo=c6_distancia_objetivo,
            auto_aplicacion=auto_aplicacion,
            sellers_excluidos=sellers_excluidos,
            alcance="bulk",
            puede_cambiar_auto=puede_cambiar_auto,
        )
        touched.append(item_id)
    return touched


def count_auto_aplicacion_on(db: Session, item_ids: Sequence[str]) -> int:
    """How many of the ids currently have Auto-aplicación ON (for bulk-dialog warning)."""
    ids = [item_id for item_id in dict.fromkeys(item_ids) if item_id]
    if not ids:
        return 0
    rows = db.query(MlHayMejoresCriterios).filter(MlHayMejoresCriterios.item_id.in_(ids)).all()
    return sum(1 for row in rows if bool(row.auto_aplicacion))
