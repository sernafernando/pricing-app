"""Permanent hay_mejores exclusion: actualizar never re-flags while opted out; include recomputes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.ml_promotions_hay_mejores import FlagDecision


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _db_with_row(row, sale=None):
    db = MagicMock()
    db.begin_nested.return_value = _Nested()
    sale = sale if sale is not None else SimpleNamespace(amount=1000.0)
    db.query.return_value.filter.return_value.one_or_none.side_effect = [row, sale]
    return db


def test_actualizar_keeps_flag_false_while_excluido(monkeypatch) -> None:
    row = SimpleNamespace(
        hay_mejores_ofertas=True,
        hay_mejores_fingerprint="C-1:900",
        hay_mejores_descartado_fingerprint=None,
        hay_mejores_excluido=True,
        raw=[{"id": "C-1", "status": "candidate"}],
    )
    called = {"listar": 0}
    monkeypatch.setattr(
        hay_mejores,
        "listar_mejores_candidatas",
        lambda *a, **k: called.__setitem__("listar", called["listar"] + 1) or [("C-1", 900.0)],
    )
    monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "notify_hay_mejores_changed", lambda *_a, **_k: None)

    decision = hay_mejores.actualizar_hay_mejores_ofertas(_db_with_row(row), "MLA1")
    assert decision == FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)
    assert row.hay_mejores_ofertas is False
    assert row.hay_mejores_fingerprint is None
    assert called["listar"] == 0


def test_set_excluido_true_clears_flag(monkeypatch) -> None:
    row = SimpleNamespace(
        hay_mejores_ofertas=True,
        hay_mejores_fingerprint="C-1:900",
        hay_mejores_descartado_fingerprint=None,
        hay_mejores_excluido=False,
        raw=[],
    )
    notified = []
    monkeypatch.setattr(hay_mejores, "_ensure_promotions_row", lambda _db, _id: row)
    monkeypatch.setattr(hay_mejores, "notify_hay_mejores_changed", lambda _db: notified.append(1))

    assert hay_mejores.set_hay_mejores_excluido(MagicMock(), "MLA1", excluido=True) is True
    assert row.hay_mejores_excluido is True
    assert row.hay_mejores_ofertas is False
    assert row.hay_mejores_fingerprint is None
    assert notified == [1]


def test_set_excluido_false_recomputes(monkeypatch) -> None:
    row = SimpleNamespace(
        hay_mejores_ofertas=False,
        hay_mejores_fingerprint=None,
        hay_mejores_descartado_fingerprint=None,
        hay_mejores_excluido=True,
        raw=[],
    )
    recomputed = []
    monkeypatch.setattr(hay_mejores, "_ensure_promotions_row", lambda _db, _id: row)
    monkeypatch.setattr(
        hay_mejores,
        "actualizar_hay_mejores_ofertas",
        lambda db, item_id, **k: recomputed.append(item_id),
    )

    assert hay_mejores.set_hay_mejores_excluido(MagicMock(), "MLA1", excluido=False) is True
    assert row.hay_mejores_excluido is False
    assert recomputed == ["MLA1"]


def test_set_excluido_unknown_mla_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(hay_mejores, "_ensure_promotions_row", lambda *_a, **_k: None)
    assert hay_mejores.set_hay_mejores_excluido(MagicMock(), "MLA1", excluido=True) is False
