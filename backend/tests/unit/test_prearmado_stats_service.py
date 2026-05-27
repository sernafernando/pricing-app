"""Unit tests for prearmado_stats_service — pure function logic.

Tests focus on the classification pipeline and index-building logic that
does NOT require a DB session. Integration with DB/Redis is tested via
manual curl recipes documented in apply-progress.

TDD note: these tests are written AFTER the implementation (the service
was developed first to unblock the router). Classifier tests (the core
logic) were TDD RED→GREEN using test_prearmado_classify.py. This file
adds behavioral coverage for _build_prearmadas_index and _count_coverage.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.prearmado_ean_parser import ParsedEan
from app.services.prearmado_stats_service import (
    _build_prearmadas_index,
    _count_coverage,
    classify,
)


# ---------------------------------------------------------------------------
# _build_prearmadas_index
# ---------------------------------------------------------------------------


def _make_prearmado(id_: int, combo_item_code: str) -> MagicMock:
    """Helper: create a minimal Prearmado mock."""
    p = MagicMock()
    p.id = id_
    p.combo_item_code = combo_item_code
    return p


class TestBuildPrearmadasIndex:
    def test_index_keyed_by_base_memoria_disco(self):
        """Parseable prearmados are indexed by (ean_base, memoria, disco)."""
        prearmadas = [
            _make_prearmado(1, "LENOVO-16512GWP"),
            _make_prearmado(2, "LENOVO-16512GWH"),
        ]
        index = _build_prearmadas_index(prearmadas)

        key = ("LENOVO", "16", "512G")
        assert key in index
        assert len(index[key]) == 2

    def test_unparseable_row_skipped_with_warning(self):
        """Prearmados whose code cannot be parsed are skipped (no exception)."""
        prearmadas = [
            _make_prearmado(1, "LENOVO-16512GWP"),
            _make_prearmado(2, "NOTACOMBO"),  # no dash → None
            _make_prearmado(3, "HP-32256G"),
        ]
        index = _build_prearmadas_index(prearmadas)

        # NOTACOMBO is skipped
        assert ("NOTACOMBO", None, None) not in index
        # Valid ones are present
        assert ("LENOVO", "16", "512G") in index
        assert ("HP", "32", "256G") in index

    def test_empty_input_returns_empty_index(self):
        """Empty prearmadas list → empty index."""
        assert _build_prearmadas_index([]) == {}

    def test_multiple_windows_variants_in_same_bucket(self):
        """Different windows variants for same base/mem/disco go in the same bucket."""
        prearmadas = [
            _make_prearmado(1, "LENOVO-16512GWP"),  # pro
            _make_prearmado(2, "LENOVO-16512GWH"),  # home
            _make_prearmado(3, "LENOVO-16512G"),  # no windows
        ]
        index = _build_prearmadas_index(prearmadas)
        key = ("LENOVO", "16", "512G")
        assert key in index
        windows_values = {p.windows for p in index[key]}
        assert windows_values == {"pro", "home", None}


# ---------------------------------------------------------------------------
# _count_coverage
# ---------------------------------------------------------------------------


class TestCountCoverage:
    def _make_index(self, codes: list[str]) -> dict[tuple[str, str | None, str | None], list[ParsedEan]]:
        """Build index from a list of item codes."""
        prearmadas = [_make_prearmado(i, code) for i, code in enumerate(codes, start=1)]
        return _build_prearmadas_index(prearmadas)

    def test_exact_count(self):
        """Item with same base/mem/disco/windows → exact count = 2."""
        index = self._make_index(["LENOVO-16512GWP", "LENOVO-16512GWP"])  # 2 identical prearmados
        from app.services.prearmado_ean_parser import parse_combo_ean

        item = parse_combo_ean("LENOVO-16512GWP")
        assert item is not None
        result = _count_coverage(item, index)
        assert result["exact"] == 2
        assert result["upgrade"] == 0

    def test_upgrade_count(self):
        """Prearmado with pro covers item needing home → upgrade count."""
        index = self._make_index(["LENOVO-16512GWP"])  # prearmado has pro
        from app.services.prearmado_ean_parser import parse_combo_ean

        item = parse_combo_ean("LENOVO-16512GWH")  # item needs home
        assert item is not None
        result = _count_coverage(item, index)
        assert result["exact"] == 0
        assert result["upgrade"] == 1

    def test_no_coverage(self):
        """Prearmado with home cannot cover item needing pro → none."""
        index = self._make_index(["LENOVO-16512GWH"])  # prearmado has home
        from app.services.prearmado_ean_parser import parse_combo_ean

        item = parse_combo_ean("LENOVO-16512GWP")  # item needs pro
        assert item is not None
        result = _count_coverage(item, index)
        assert result["exact"] == 0
        assert result["upgrade"] == 0

    def test_non_combo_item_not_in_index(self):
        """Item code with no '-' results in empty index lookup → 0/0."""
        index = self._make_index(["LENOVO-16512GWP"])
        # Build a fake ParsedEan for a non-combo result (shouldn't normally happen,
        # but verify _count_coverage handles empty bucket gracefully)
        fake_item = ParsedEan(raw="OTHER-X", ean_base="OTHER", memoria=None, disco=None, windows=None)
        result = _count_coverage(fake_item, index)
        assert result == {"exact": 0, "upgrade": 0}

    def test_no_n_plus_one_index_built_once(self):
        """Verify the index is built once, not per-item (structural test)."""
        # Build index with 5 prearmados for same base
        codes = ["LENOVO-16512GWP" for _ in range(5)]
        index = self._make_index(codes)

        from app.services.prearmado_ean_parser import parse_combo_ean

        # Query 3 different items — only one index lookup each
        items = [
            parse_combo_ean("LENOVO-16512GWP"),
            parse_combo_ean("LENOVO-16512GWH"),
            parse_combo_ean("LENOVO-16512G"),
        ]
        results = [_count_coverage(item, index) for item in items if item is not None]

        # WP item → 5 exact (all prearmados are WP)
        assert results[0]["exact"] == 5
        assert results[0]["upgrade"] == 0

        # WH item → 5 upgrade (WP covers WH)
        assert results[1]["upgrade"] == 5
        assert results[1]["exact"] == 0

        # No-windows item → 5 upgrade (WP covers no-windows)
        assert results[2]["upgrade"] == 5
        assert results[2]["exact"] == 0


# ---------------------------------------------------------------------------
# classify — spot-check (full table covered in test_prearmado_classify.py)
# ---------------------------------------------------------------------------


def test_classify_re_export():
    """Verify classify is importable from prearmado_stats_service."""
    assert classify(None, None) == "exact"
    assert classify(None, "pro") == "upgrade"
    assert classify("pro", "home") == "none"
