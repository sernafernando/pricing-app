"""Tests for app.utils.text.decode_html_entities.

The ERP mirror stores some free-text fields HTML-encoded (and uppercased), so
values arrive like 'BLACK &AMP; DECKER'. These tests pin the decode behaviour:
  - uppercase HTML5 legacy entities (&AMP;, &LT;, &GT;, &QUOT;) are decoded
  - canonical lowercase entities are decoded
  - clean text is returned unchanged (idempotent)
  - None / non-str inputs pass through untouched
"""

from __future__ import annotations

from app.utils.text import decode_html_entities


def test_decodes_uppercase_amp() -> None:
    assert decode_html_entities("BLACK &AMP; DECKER") == "BLACK & DECKER"


def test_decodes_lowercase_amp() -> None:
    assert decode_html_entities("Black &amp; Decker") == "Black & Decker"


def test_decodes_mixed_entities() -> None:
    assert decode_html_entities("A &LT;x&GT; &QUOT;y&QUOT; &amp; z") == 'A <x> "y" & z'


def test_clean_text_unchanged() -> None:
    assert decode_html_entities("BLACK & DECKER") == "BLACK & DECKER"


def test_idempotent() -> None:
    once = decode_html_entities("BLACK &AMP; DECKER")
    assert decode_html_entities(once) == once


def test_none_passes_through() -> None:
    assert decode_html_entities(None) is None


def test_non_str_passes_through() -> None:
    assert decode_html_entities(123) == 123
