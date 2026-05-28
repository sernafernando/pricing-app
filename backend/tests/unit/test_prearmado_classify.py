"""Unit tests for classify() — coverage classifier for prearmado stats.

TDD cycle: written BEFORE the implementation in prearmado_stats_service.py.
Run with:
    pytest backend/tests/unit/test_prearmado_classify.py -v

Full 3x3 decision table for classify(req_windows, have_windows):
  req ∈ {None, "home", "pro"}
  have ∈ {None, "home", "pro"}

Windows hierarchy: None < home < pro
- exact   → req == have
- upgrade → have > req  (prearmado has more capability than needed)
- none    → have < req  (prearmado cannot satisfy the requirement)
"""

# Will fail until prearmado_stats_service.py is created
from app.services.prearmado_stats_service import classify


class TestClassifyDecisionTable:
    """Full 3x3 matrix of (req, have) combinations."""

    # ── req=None ────────────────────────────────────────────────────────────
    def test_none_none(self):
        """(None, None) → exact: prearmado has no windows, pedido needs none."""
        assert classify(None, None) == "exact"

    def test_none_home(self):
        """(None, home) → upgrade: prearmado has more capability than needed."""
        assert classify(None, "home") == "upgrade"

    def test_none_pro(self):
        """(None, pro) → upgrade: prearmado has more capability than needed."""
        assert classify(None, "pro") == "upgrade"

    # ── req=home ────────────────────────────────────────────────────────────
    def test_home_none(self):
        """(home, None) → none: prearmado has no windows but pedido needs home."""
        assert classify("home", None) == "none"

    def test_home_home(self):
        """(home, home) → exact: same level."""
        assert classify("home", "home") == "exact"

    def test_home_pro(self):
        """(home, pro) → upgrade: prearmado has pro, pedido only needs home."""
        assert classify("home", "pro") == "upgrade"

    # ── req=pro ─────────────────────────────────────────────────────────────
    def test_pro_none(self):
        """(pro, None) → none: prearmado has no windows but pedido needs pro."""
        assert classify("pro", None) == "none"

    def test_pro_home(self):
        """(pro, home) → none: prearmado only has home but pedido needs pro."""
        assert classify("pro", "home") == "none"

    def test_pro_pro(self):
        """(pro, pro) → exact: same level."""
        assert classify("pro", "pro") == "exact"


class TestClassifyBoundaries:
    """Boundary checks beyond the 9-cell table."""

    def test_classify_none_home_is_upgrade(self):
        """Explicit boundary: req=None, have=home → upgrade (home > None)."""
        assert classify(None, "home") == "upgrade"

    def test_classify_pro_none_is_none(self):
        """Explicit boundary: req=pro, have=None → none (None < pro)."""
        assert classify("pro", None) == "none"

    def test_return_type_is_string_literal(self):
        """Return value must be exactly one of: exact, upgrade, none."""
        for result in [
            classify(None, None),
            classify(None, "home"),
            classify("home", "pro"),
            classify("pro", "home"),
        ]:
            assert result in {"exact", "upgrade", "none"}
