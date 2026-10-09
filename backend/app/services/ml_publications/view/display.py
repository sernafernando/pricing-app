"""Display helpers shared by the view's serializers (pure)."""

from __future__ import annotations

from typing import Optional


def round_display(value: Optional[float]) -> Optional[float]:
    """A figure as the screen shows it: two decimals (`Decimal` and `float` alike), `None` stays `None`. Sorting and
    filtering use the exact figures, never this one."""
    return None if value is None else round(float(value), 2)
