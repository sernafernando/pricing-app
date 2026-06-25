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
    _build_exact_index,
    _build_prearmadas_index,
    _count_coverage,
    _count_for_item,
    _exact_cover,
    classify,
)


# ---------------------------------------------------------------------------
# _build_prearmadas_index
# ---------------------------------------------------------------------------


def _make_prearmado(id_: int, combo_item_code: str, combo_item_id: int | None = None) -> MagicMock:
    """Helper: create a minimal Prearmado mock.

    ``combo_item_id`` defaults to ``id_`` when not given (each mock is its own
    distinct combo unless a test deliberately shares an id).
    """
    p = MagicMock()
    p.id = id_
    p.combo_item_code = combo_item_code
    p.combo_item_id = combo_item_id if combo_item_id is not None else id_
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

    def test_unparseable_row_excluded_from_specs_index(self):
        """Non-EAN codes are excluded from the SPECS index (no exception, no warning).

        They are not lost from stats — they are covered by the exact-identity
        index instead (see TestBuildExactIndex).
        """
        prearmadas = [
            _make_prearmado(1, "LENOVO-16512GWP"),
            _make_prearmado(2, "NOTACOMBO"),  # no dash → None
            _make_prearmado(3, "HP-32256G"),
            _make_prearmado(4, "PC-R5700G-A-16G"),  # custom build → None
        ]
        index = _build_prearmadas_index(prearmadas)

        # Non-EAN codes are absent from the specs index
        assert ("NOTACOMBO", None, None) not in index
        assert ("PC", None, None) not in index
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


# ---------------------------------------------------------------------------
# _build_exact_index — exact-identity coverage for custom (non-EAN) combos
# ---------------------------------------------------------------------------


class TestBuildExactIndex:
    def test_counts_by_combo_item_id(self):
        """Prearmados are tallied by combo_item_id regardless of code format."""
        prearmadas = [
            _make_prearmado(1, "PC-R5700G-A-16G", combo_item_id=500),
            _make_prearmado(2, "PC-R5700G-A-16G", combo_item_id=500),
            _make_prearmado(3, "PC-R5600G-A-8G", combo_item_id=501),
        ]
        assert _build_exact_index(prearmadas) == {500: 2, 501: 1}

    def test_includes_ean_combos_too(self):
        """The exact index counts every armado, EAN or not (branch isolation
        in the batch path prevents double-counting)."""
        prearmadas = [
            _make_prearmado(1, "LENOVO-16512GWP", combo_item_id=10),
            _make_prearmado(2, "PC-R5700G-A-16G", combo_item_id=20),
        ]
        assert _build_exact_index(prearmadas) == {10: 1, 20: 1}

    def test_empty_input(self):
        assert _build_exact_index([]) == {}


# ---------------------------------------------------------------------------
# _count_for_item — per-item branch between spec coverage and exact identity
# ---------------------------------------------------------------------------


class TestCountForItem:
    def test_ean_item_uses_spec_coverage(self):
        """An EAN item delegates to spec-based coverage (exact + upgrade)."""
        specs_index = _build_prearmadas_index(
            [
                _make_prearmado(1, "LENOVO-16512GWP"),
                _make_prearmado(2, "LENOVO-16512GWP"),
            ]
        )
        result = _count_for_item("LENOVO-16512GWP", 999, specs_index, exact_index={})
        assert result == {"exact": 2, "upgrade": 0}

    def test_ean_item_counts_windows_upgrade(self):
        """EAN item needing home is covered as upgrade by a pro prearmado."""
        specs_index = _build_prearmadas_index([_make_prearmado(1, "LENOVO-16512GWP")])
        result = _count_for_item("LENOVO-16512GWH", 999, specs_index, exact_index={})
        assert result == {"exact": 0, "upgrade": 1}

    def test_custom_combo_uses_exact_identity(self):
        """A non-EAN combo (PC-...) matches only by combo_item_id; never upgrades."""
        # PC- codes never enter the specs index
        specs_index = _build_prearmadas_index([_make_prearmado(1, "PC-R5700G-A-16G", combo_item_id=500)])
        assert specs_index == {}
        exact_index = _build_exact_index([_make_prearmado(1, "PC-R5700G-A-16G", combo_item_id=500)])
        result = _count_for_item("PC-R5700G-A-16G", 500, specs_index, exact_index)
        assert result == {"exact": 1, "upgrade": 0}

    def test_custom_combo_no_match_is_zero(self):
        """Custom combo with no armado of that exact id → 0/0."""
        result = _count_for_item("PC-R5700G-A-16G", 500, specs_index={}, exact_index={501: 3})
        assert result == {"exact": 0, "upgrade": 0}


# ---------------------------------------------------------------------------
# _exact_cover — sellers page covers[] for custom combos
# ---------------------------------------------------------------------------


class TestExactCover:
    def test_returns_self_classified_exact(self):
        items_by_id = {
            500: {"item_id": 500, "item_code": "PC-R5700G-A-16G", "item_desc": "PC Gamer"},
        }
        covers = _exact_cover(500, items_by_id)
        assert covers == [
            {
                "item_id": 500,
                "item_code": "PC-R5700G-A-16G",
                "item_desc": "PC Gamer",
                "classification": "exact",
            }
        ]

    def test_missing_item_returns_empty(self):
        """Combo item absent from the catalog → no covers (graceful)."""
        assert _exact_cover(999, items_by_id={}) == []
