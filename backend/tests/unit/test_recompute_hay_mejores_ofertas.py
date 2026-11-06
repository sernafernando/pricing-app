"""Unit tests for the offline hay_mejores recompute script."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.scripts import recompute_hay_mejores_ofertas as script
from app.services.ml_promotions_hay_mejores import FlagDecision


class TestRecomputeStats:
    def test_cleared_and_fingerprint_change(self) -> None:
        stats = script.RecomputeStats()
        stats.record(
            "MLA1",
            prev_flag=True,
            prev_fp="C-1:100",
            decision=FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None),
        )
        assert stats.considered == 1
        assert stats.cleared == 1
        assert stats.fingerprint_changed == 1
        assert stats.sample_cleared == ["MLA1"]

    def test_still_flagged_same_fingerprint(self) -> None:
        stats = script.RecomputeStats()
        decision = FlagDecision(hay_mejores=True, fingerprint="C-1:90", descartado_fingerprint=None)
        stats.record("MLA2", prev_flag=True, prev_fp="C-1:90", decision=decision)
        assert stats.still_flagged == 1
        assert stats.fingerprint_changed == 0

    def test_failed_when_decision_none(self) -> None:
        stats = script.RecomputeStats()
        stats.record("MLA3", prev_flag=True, prev_fp="x", decision=None)
        assert stats.failed == 1
        assert stats.cleared == 0


class TestSelectItemIds:
    def test_explicit_ids_dedupe_and_limit(self) -> None:
        db = MagicMock()
        ids = script.select_item_ids(
            db,
            flagged_only=True,
            item_ids=["MLA2", "MLA1", "MLA2"],
            limit=2,
        )
        assert ids == ["MLA2", "MLA1"]
        db.query.assert_not_called()

    def test_flagged_only_query(self) -> None:
        db = MagicMock()
        q = db.query.return_value
        filtered = q.filter.return_value
        ordered = filtered.order_by.return_value
        ordered.all.return_value = [("MLA9",), ("MLA8",)]
        ids = script.select_item_ids(db, flagged_only=True, item_ids=None, limit=None)
        assert ids == ["MLA9", "MLA8"]
        q.filter.assert_called_once()


class TestRecomputeItems:
    def test_dry_run_rolls_back(self, monkeypatch) -> None:
        row = SimpleNamespace(hay_mejores_ofertas=True, hay_mejores_fingerprint="old")
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = row
        monkeypatch.setattr(
            script,
            "actualizar_hay_mejores_ofertas",
            lambda _db, _id, **_kw: FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None),
        )
        stats = script.recompute_items(db, ["MLA1"], dry_run=True, commit_every=10)
        assert stats.cleared == 1
        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_commits_in_batches(self, monkeypatch) -> None:
        row = SimpleNamespace(hay_mejores_ofertas=True, hay_mejores_fingerprint="old")
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = row
        monkeypatch.setattr(
            script,
            "actualizar_hay_mejores_ofertas",
            lambda _db, _id, **_kw: FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None),
        )
        stats = script.recompute_items(db, ["MLA1", "MLA2", "MLA3"], dry_run=False, commit_every=2)
        assert stats.cleared == 3
        assert db.commit.call_count == 2  # after 2, then final flush of 1

    def test_sell_in_out_is_resolved_once_per_commit_batch_not_per_item(self, monkeypatch) -> None:
        """S5: the ranking reads sell in / sell out; a recompute of many items must not read it item by item."""
        row = SimpleNamespace(hay_mejores_ofertas=True, hay_mejores_fingerprint="old")
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = row
        resueltos: list = []
        usados: list = []

        def _resolver(_db, mlas):
            resueltos.append(list(mlas))
            return f"batch-{len(resueltos)}"

        def _actualizar(_db, item_id, *, sell_in_out_batch=None):
            usados.append((item_id, sell_in_out_batch))
            return FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)

        monkeypatch.setattr(script, "resolver_sell_in_out_para_mlas", _resolver)
        monkeypatch.setattr(script, "actualizar_hay_mejores_ofertas", _actualizar)

        script.recompute_items(db, ["MLA1", "MLA2", "MLA3"], dry_run=False, commit_every=2)

        assert resueltos == [["MLA1", "MLA2"], ["MLA3"]]
        assert usados == [("MLA1", "batch-1"), ("MLA2", "batch-1"), ("MLA3", "batch-2")]

    def test_missing_row_counts_failed(self, monkeypatch) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.one_or_none.return_value = None
        monkeypatch.setattr(
            script,
            "actualizar_hay_mejores_ofertas",
            lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not call")),
        )
        stats = script.recompute_items(db, ["MLA_MISSING"], dry_run=False, commit_every=10)
        assert stats.failed == 1
        assert stats.considered == 1
        db.commit.assert_not_called()  # nothing written — no empty commit


class TestParseArgs:
    def test_default_scope_is_flagged_only(self) -> None:
        args = script._parse_args([])
        assert args.all is False
        assert not args.dry_run

    def test_all_flag(self) -> None:
        args = script._parse_args(["--all", "--dry-run", "--limit", "5"])
        assert args.all is True
        assert args.dry_run is True
        assert args.limit == 5
