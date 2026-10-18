"""Cells for CSV files people open in a spreadsheet."""

from __future__ import annotations

import math
from typing import Optional

# A cell starting with one of these is run as a formula by Excel/Sheets
# (`=HYPERLINK(...)`, `+cmd|...`), or shifts into one (tab/CR).
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def csv_text(value: Optional[str]) -> str:
    """Free text (titles from Mercado Libre, the ERP, buyer names...) for a
    CSV cell: defused with a leading quote when it would start a formula.
    Standard CSV-injection guard; every free-text cell of every export goes
    through here."""
    if value is None:
        return ""
    return "'" + value if value[:1] in _FORMULA_TRIGGERS else value


def csv_money(value: Optional[float]) -> str:
    """An amount or a percentage with two decimals and a decimal comma (the Spanish locale's spreadsheet reads it
    as a number); empty when there is none or it is not a finite number. A value that rounds to zero prints
    `0,00`, never `-0,00`."""
    if value is None or not math.isfinite(value):
        return ""
    text = f"{value:.2f}"
    if text == "-0.00":
        text = "0.00"
    return text.replace(".", ",")
