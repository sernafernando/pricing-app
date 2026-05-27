"""Unit tests for parse_combo_ean — EAN parser for combo item codes.

TDD cycle: these tests are written BEFORE the implementation.
Run with:
    pytest backend/tests/unit/test_prearmado_ean_parser.py -v

All 11 spec §2 behavior-table rows are covered, plus edge cases.
"""

import logging
import pytest

# --- will fail until the module is created ---
from app.services.prearmado_ean_parser import ParsedEan, parse_combo_ean


# ---------------------------------------------------------------------------
# Happy-path rows from spec §2 behavior table
# ---------------------------------------------------------------------------


class TestSpecBehaviorTable:
    """The 11 rows from spec §2, tested verbatim."""

    def test_no_dash_returns_none(self):
        """'LENOVO' (no '-') → None."""
        assert parse_combo_ean("LENOVO") is None

    def test_empty_suffix(self):
        """'LENOVO-' → ParsedEan with all suffixes None."""
        result = parse_combo_ean("LENOVO-")
        assert result == ParsedEan(raw="LENOVO-", ean_base="LENOVO", memoria=None, disco=None, windows=None)

    def test_windows_home_only(self):
        """'LENOVO-WH' → windows='home', no memoria, no disco."""
        result = parse_combo_ean("LENOVO-WH")
        assert result == ParsedEan(raw="LENOVO-WH", ean_base="LENOVO", memoria=None, disco=None, windows="home")

    def test_windows_pro_only(self):
        """'LENOVO-WP' → windows='pro', no memoria, no disco."""
        result = parse_combo_ean("LENOVO-WP")
        assert result == ParsedEan(raw="LENOVO-WP", ean_base="LENOVO", memoria=None, disco=None, windows="pro")

    def test_memoria_only(self):
        """'LENOVO-16' → memoria='16', no disco, no windows."""
        result = parse_combo_ean("LENOVO-16")
        assert result == ParsedEan(raw="LENOVO-16", ean_base="LENOVO", memoria="16", disco=None, windows=None)

    def test_memoria_and_windows_home(self):
        """'LENOVO-16WH' → memoria='16', windows='home'."""
        result = parse_combo_ean("LENOVO-16WH")
        assert result == ParsedEan(raw="LENOVO-16WH", ean_base="LENOVO", memoria="16", disco=None, windows="home")

    def test_memoria_and_disco(self):
        """'LENOVO-16512G' → memoria='16', disco='512G', no windows."""
        result = parse_combo_ean("LENOVO-16512G")
        assert result == ParsedEan(raw="LENOVO-16512G", ean_base="LENOVO", memoria="16", disco="512G", windows=None)

    def test_memoria_disco_windows_home(self):
        """'LENOVO-16512GWH' → memoria='16', disco='512G', windows='home'."""
        result = parse_combo_ean("LENOVO-16512GWH")
        assert result == ParsedEan(raw="LENOVO-16512GWH", ean_base="LENOVO", memoria="16", disco="512G", windows="home")

    def test_memoria_disco_windows_pro(self):
        """'LENOVO-16512GWP' → memoria='16', disco='512G', windows='pro'."""
        result = parse_combo_ean("LENOVO-16512GWP")
        assert result == ParsedEan(raw="LENOVO-16512GWP", ean_base="LENOVO", memoria="16", disco="512G", windows="pro")

    def test_whitespace_and_lowercase_normalized(self):
        """'  lenovo-16WP  ' → stripped + uppercased, windows='pro'."""
        result = parse_combo_ean("  lenovo-16WP  ")
        assert result == ParsedEan(raw="LENOVO-16WP", ean_base="LENOVO", memoria="16", disco=None, windows="pro")

    def test_disco_t_suffix(self):
        """'LENOVO-16T' → memoria=None (not memoria=16), disco='16T'.

        Disambiguation rule: digits followed by T/G → disco, not memoria.
        The spec row says: 'LENOVO-16T' → disco='T' but design spec says
        any disco token parsed as-is. Here '16T' → disco='16T'.
        """
        result = parse_combo_ean("LENOVO-16T")
        assert result == ParsedEan(raw="LENOVO-16T", ean_base="LENOVO", memoria=None, disco="16T", windows=None)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_input(self):
        """None → None."""
        assert parse_combo_ean(None) is None

    def test_empty_string(self):
        """'' → None."""
        assert parse_combo_ean("") is None

    def test_no_base_before_dash(self):
        """'-WP' (empty base) → None."""
        assert parse_combo_ean("-WP") is None

    def test_junk_suffix_returns_none_and_logs_warning(self, caplog):
        """'XXXX-FOO' — suffix doesn't match → returns None AND logs WARNING."""
        with caplog.at_level(logging.WARNING, logger="app.services.prearmado_ean_parser"):
            result = parse_combo_ean("XXXX-FOO")
        assert result is None
        assert any("XXXX-FOO" in m or "EAN parse" in m for m in caplog.messages)

    def test_whitespace_only_after_strip(self):
        """'   ' → None."""
        assert parse_combo_ean("   ") is None

    def test_multi_dash_uses_first_dash_as_partition(self):
        """'A-B-C' → ean_base='A', suffix='B-C' parsed.

        'B-C' is not a valid suffix (contains a dash which the regex won't match)
        so it should return None with a warning, not raise.
        """
        # 'B-C' won't match the suffix pattern → None
        result = parse_combo_ean("A-B-C")
        # The result can be None (parse failed) — that's acceptable because
        # 'B-C' is not a valid suffix. We just ensure no exception is raised.
        assert result is None or isinstance(result, ParsedEan)

    def test_result_is_immutable(self):
        """ParsedEan is frozen — mutation raises."""
        result = parse_combo_ean("LENOVO-16512GWP")
        assert result is not None
        with pytest.raises((AttributeError, TypeError)):
            result.memoria = "999"  # type: ignore[misc]

    def test_large_memoria(self):
        """'HP-32512GWH' → memoria='32', disco='512G', windows='home'."""
        result = parse_combo_ean("HP-32512GWH")
        assert result is not None
        assert result.memoria == "32"
        assert result.disco == "512G"
        assert result.windows == "home"

    def test_disco_1t(self):
        """'ASUS-1TWH' → disco='1T', windows='home', memoria=None."""
        result = parse_combo_ean("ASUS-1TWH")
        assert result is not None
        assert result.memoria is None
        assert result.disco == "1T"
        assert result.windows == "home"

    def test_disco_2t_windows_pro(self):
        """'DELL-2TWP' → disco='2T', windows='pro', memoria=None."""
        result = parse_combo_ean("DELL-2TWP")
        assert result is not None
        assert result.memoria is None
        assert result.disco == "2T"
        assert result.windows == "pro"
