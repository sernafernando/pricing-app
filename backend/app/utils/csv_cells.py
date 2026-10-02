"""Cells for CSV files people open in a spreadsheet."""

from __future__ import annotations

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
