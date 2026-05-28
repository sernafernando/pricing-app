"""EAN parser for combo item codes.

This is the SINGLE source of truth for decomposing a combo item_code into its
structured components: ``ean_base``, ``memoria``, ``disco``, and ``windows``.

Expected suffix format (everything after the first ``-``):
    {memoria}{disco}{windows}

Where:
    - memoria : digits that precede a disco token  (e.g. "8", "16", "32", "64")
    - disco   : digits followed by G or T           (e.g. "256G", "512G", "1T", "2T")
    - windows : WH (home) or WP (pro)

Disambiguation rules:
  1. Strip windows token (WH|WP) from the end first.
  2. Strip disco token (digits + G/T) from the remaining suffix.
  3. Whatever digits remain are memoria.

Example::

    "16512GWP"
     → strip WP → "16512G"
     → strip disco "512G" from end → "16"
     → memoria = "16"

    "1TWH"
     → strip WH → "1T"
     → strip disco "1T" → ""
     → memoria = None

    "16T"
     → no windows
     → strip disco "16T" → ""
     → memoria = None

Examples::

    >>> parse_combo_ean("LENOVO-16512GWP")
    ParsedEan(raw='LENOVO-16512GWP', ean_base='LENOVO', memoria='16', disco='512G', windows='pro')

    >>> parse_combo_ean("ASUS-1TWH")
    ParsedEan(raw='ASUS-1TWH', ean_base='ASUS', memoria=None, disco='1T', windows='home')

    >>> parse_combo_ean("LENOVO")  # no dash → not a combo
    None

    >>> parse_combo_ean(None)
    None
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional

logger = logging.getLogger(__name__)

WindowsLiteral = Literal["home", "pro"]

# Match a windows token at the END of the suffix: WH or WP.
_WIN_RE = re.compile(r"(?P<windows>WH|WP)$")

# Match a disco token at the END of the remaining suffix (after stripping windows):
# 1-3 digits followed by exactly one G or T.  The 1-3 digit limit ensures that when
# a suffix like "16512G" is present, we capture "512G" as disco (the trailing 3-digit
# block), leaving "16" as memoria.  Values with 4+ numeric digits before G/T (e.g.
# "1024G") are unusual in real data; if encountered, the leading extra digits will be
# parsed as memoria.
_DISCO_RE = re.compile(r"(?P<disco>\d{1,3}[GT])$")

# After stripping both disco and windows, what remains must be all digits (memoria)
# or empty (no memoria). Anything else is a parse error.
_MEMORIA_RE = re.compile(r"^(?P<memoria>\d+)$")


@dataclass(frozen=True)
class ParsedEan:
    """Immutable result of parsing a combo item_code.

    Fields
    ------
    raw      : stripped + uppercased version of the original input.
    ean_base : everything before the first '-'.
    memoria  : RAM string (e.g. "8", "16") or None.
    disco    : storage string (e.g. "256G", "1T") or None.
    windows  : "home" (WH), "pro" (WP), or None.
    """

    raw: str
    ean_base: str
    memoria: Optional[str]
    disco: Optional[str]
    windows: Optional[WindowsLiteral]


def parse_combo_ean(item_code: Optional[str]) -> Optional[ParsedEan]:
    """Decompose a combo item_code into its EAN components.

    The parser never raises. Malformed suffixes are logged at WARNING level and
    return ``None`` so callers can handle them gracefully (count as 0 in stats).

    Parameters
    ----------
    item_code:
        Raw item code string (e.g. ``"LENOVO-16512GWP"``). May be None or empty.

    Returns
    -------
    ParsedEan
        Structured representation of the item code.
    None
        When item_code is None, empty, has no '-', has an empty base before '-',
        or the suffix after '-' does not match the expected pattern.
    """
    if not item_code:
        return None

    raw = item_code.strip().upper()

    if not raw:
        return None

    if "-" not in raw:
        return None

    base, _, suffix = raw.partition("-")

    if not base:
        return None

    if suffix == "":
        return ParsedEan(raw=raw, ean_base=base, memoria=None, disco=None, windows=None)

    # Step 1: strip windows token from the end
    windows: Optional[WindowsLiteral] = None
    remaining = suffix
    m_win = _WIN_RE.search(remaining)
    if m_win:
        win_raw = m_win.group("windows")
        windows = "home" if win_raw == "WH" else "pro"
        remaining = remaining[: m_win.start()]

    # Step 2: strip disco token from the end of remaining
    disco: Optional[str] = None
    m_disco = _DISCO_RE.search(remaining)
    if m_disco:
        disco = m_disco.group("disco")
        remaining = remaining[: m_disco.start()]

    # Step 3: whatever is left must be memoria (all digits) or empty
    memoria: Optional[str] = None
    if remaining:
        m_mem = _MEMORIA_RE.match(remaining)
        if not m_mem:
            logger.warning("EAN parse failed for item_code=%s (suffix=%r)", raw, suffix)
            return None
        memoria = m_mem.group("memoria")

    return ParsedEan(
        raw=raw,
        ean_base=base,
        memoria=memoria or None,
        disco=disco,
        windows=windows,
    )
