"""hay_mejores enqueues catalog competition refresh on new flag / fingerprint novelty."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.ml_promotions_hay_mejores import FlagDecision


def _run_actualizar(monkeypatch, *, prev_flag: bool, prev_fp: str | None, decision: FlagDecision) -> list[str]:
    enqueued: list[str] = []
    row = SimpleNamespace(
        hay_mejores_ofertas=prev_flag,
        hay_mejores_fingerprint=prev_fp,
        hay_mejores_descartado_fingerprint=None,
        raw=[],
    )
    sale = SimpleNamespace(amount=1000.0)

    class _Nested:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    db = MagicMock()
    db.begin_nested.return_value = _Nested()
    db.query.return_value.filter.return_value.one_or_none.side_effect = [row, sale]

    monkeypatch.setattr(
        hay_mejores,
        "decidir_flag_hay_mejores",
        lambda **kwargs: decision,
    )
    monkeypatch.setattr(hay_mejores, "listar_mejores_candidatas", lambda *a, **k: [("C-1", 900.0)])
    monkeypatch.setattr(
        hay_mejores,
        "_candidate_entries",
        lambda raw, now: [{"id": "C-1", "status": "candidate"}],
    )
    monkeypatch.setattr(
        hay_mejores,
        "_enqueue_catalog_competition_refresh",
        lambda _db, item_id: enqueued.append(item_id),
    )

    result = hay_mejores.actualizar_hay_mejores_ofertas(
        db, "MLA1", raw_promotions=[{"id": "C-1", "status": "candidate"}]
    )
    assert result == decision
    assert row.hay_mejores_ofertas is decision.hay_mejores
    return enqueued


class TestEnqueueOnHayMejores:
    def test_enqueues_when_newly_flagged(self, monkeypatch) -> None:
        decision = FlagDecision(hay_mejores=True, fingerprint="C-1:900", descartado_fingerprint=None)
        assert _run_actualizar(monkeypatch, prev_flag=False, prev_fp=None, decision=decision) == ["MLA1"]

    def test_enqueues_when_fingerprint_changes(self, monkeypatch) -> None:
        decision = FlagDecision(hay_mejores=True, fingerprint="C-1:900|C-2:850", descartado_fingerprint=None)
        assert _run_actualizar(monkeypatch, prev_flag=True, prev_fp="C-1:900", decision=decision) == ["MLA1"]

    def test_does_not_enqueue_when_flag_unchanged(self, monkeypatch) -> None:
        decision = FlagDecision(hay_mejores=True, fingerprint="C-1:900", descartado_fingerprint=None)
        assert _run_actualizar(monkeypatch, prev_flag=True, prev_fp="C-1:900", decision=decision) == []

    def test_does_not_enqueue_when_cleared(self, monkeypatch) -> None:
        decision = FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)
        assert _run_actualizar(monkeypatch, prev_flag=True, prev_fp="C-1:900", decision=decision) == []


class TestEnqueueResolvesCatalogTarget:
    def test_skips_when_no_catalog_target(self, monkeypatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            "app.services.catalog_competition_target.mla_for_catalog_competition_refresh",
            lambda _db, _mla: None,
        )
        monkeypatch.setattr(
            "app.services.catalog_competition_refresh_queue.enqueue",
            lambda _db, ids, _now: calls.extend(ids),
        )
        hay_mejores._enqueue_catalog_competition_refresh(MagicMock(), "MLA-CLASSIC")
        assert calls == []

    def test_enqueues_resolved_catalog_mla(self, monkeypatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            "app.services.catalog_competition_target.mla_for_catalog_competition_refresh",
            lambda _db, _mla: "MLA-CAT",
        )
        monkeypatch.setattr(
            "app.services.catalog_competition_refresh_queue.enqueue",
            lambda _db, ids, _now: calls.extend(ids),
        )
        hay_mejores._enqueue_catalog_competition_refresh(MagicMock(), "MLA-CLASSIC")
        assert calls == ["MLA-CAT"]
