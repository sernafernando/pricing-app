"""Alejandro's criteria for AI writes: the C1 markup band (L13 Q4).

The band comes from #2333's criteria (`ml_hay_mejores_criterios`) once it is merged; until then `band_for` answers
UNAVAILABLE and every row that needs a band is blocked (`banda_no_disponible`). This is the ONE place the guard layer
asks; tests replace `band_for` with a double.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from sqlalchemy.orm import Session

UNAVAILABLE: Literal["unavailable"] = "unavailable"

Band = Union[tuple[float, float], None, Literal["unavailable"]]

# Version of the criteria a plan was checked against (stored with every audited row); None until #2333.
CRITERIA_VERSION: str | None = None


def band_for(db: Session, target: dict[str, Any]) -> Band:
    """(min, max) markup band for `target` ({"accion", "objetivo"}), None when no band applies, or UNAVAILABLE."""
    return UNAVAILABLE
