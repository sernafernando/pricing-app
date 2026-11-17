"""Read/upsert per-MLA hay_mejores application criteria."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.ml_hay_mejores_criterios import MlHayMejoresCriterios
from app.services.ml_hay_mejores_audit_service import record_auto_toggle

DEFAULT_C6_GAP_MIN = Decimal("5000")
DEFAULT_C6_DISTANCIA = Decimal("100")


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
        c6_gap_min=_to_decimal(row.c6_gap_min) or DEFAULT_C6_GAP_MIN,
        c6_distancia_objetivo=_to_decimal(row.c6_distancia_objetivo) or DEFAULT_C6_DISTANCIA,
        auto_aplicacion=bool(row.auto_aplicacion),
        sellers_excluidos=[str(x) for x in excluded],
        updated_at=row.updated_at,
        exists=True,
    )


def get_criterios(db: Session, item_id: str) -> CriteriosView:
    row = db.get(MlHayMejoresCriterios, item_id)
    # Unit tests often pass MagicMock sessions; only a real ORM row counts.
    if not isinstance(row, MlHayMejoresCriterios):
        return default_criterios(item_id)
    return _row_to_view(row)


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
    auto_aplicacion: bool,
    sellers_excluidos: Optional[Sequence[str]] = None,
) -> CriteriosView:
    if c1_activo and c1_markup_min is not None and c1_markup_max is not None and c1_markup_min > c1_markup_max:
        raise ValueError("c1_markup_min no puede ser mayor que c1_markup_max")
    if c6_gap_min < 0 or c6_distancia_objetivo < 0:
        raise ValueError("gap y distancia de C6 deben ser ≥ 0")

    previous = get_criterios(db, item_id)
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
    row.auto_aplicacion = auto_aplicacion
    if sellers_excluidos is not None:
        row.sellers_excluidos = list(sellers_excluidos)
    row.updated_by = updated_by
    row.updated_at = datetime.now(UTC)
    db.flush()
    record_auto_toggle(
        db,
        item_id,
        old=previous.auto_aplicacion,
        new=auto_aplicacion,
        usuario_id=updated_by,
        alcance="item",
    )
    return _row_to_view(row)
