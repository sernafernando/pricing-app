"""Text normalization helpers for ERP-sourced strings."""

import html
from typing import Optional


def decode_html_entities(value: Optional[str]) -> Optional[str]:
    """Decode HTML entities in ERP text fields (e.g. ``&AMP;`` -> ``&``).

    The ERP mirror stores some free-text fields HTML-encoded (and uppercased),
    so values arrive as ``BLACK &AMP; DECKER``. ``html.unescape`` decodes both
    the canonical lowercase entities (``&amp;``) and the HTML5 legacy uppercase
    variants (``&AMP;``, ``&LT;``, ``&GT;``, ``&QUOT;``), and is idempotent on
    already-clean text.

    Returns the value unchanged when it is ``None`` or not a string.
    """
    if not isinstance(value, str):
        return value
    return html.unescape(value)
