"""sale_price (and promotions) mirror writes recompute hay_mejores via subresource_store."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.ml_publications.subresource_store import _refresh_hay_mejores_after_write


def test_promotions_write_passes_raw_to_actualizar(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.services.ml_promotions_hay_mejores.actualizar_hay_mejores_ofertas",
        lambda db, item_id, **kwargs: calls.append((item_id, kwargs)),
    )
    raw = [{"id": "C-1", "status": "candidate"}]
    _refresh_hay_mejores_after_write(MagicMock(), SimpleNamespace(name="promotions"), "MLA1", raw)
    assert calls == [("MLA1", {"raw_promotions": raw})]


def test_sale_price_write_recomputes_without_raw_promotions(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.services.ml_promotions_hay_mejores.actualizar_hay_mejores_ofertas",
        lambda db, item_id, **kwargs: calls.append((item_id, kwargs)),
    )
    _refresh_hay_mejores_after_write(
        MagicMock(), SimpleNamespace(name="sale_price"), "MLA1", {"amount": 999}
    )
    assert calls == [("MLA1", {})]


def test_other_resources_do_not_touch_hay_mejores(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "app.services.ml_promotions_hay_mejores.actualizar_hay_mejores_ofertas",
        lambda *_a, **_k: calls.append("hit"),
    )
    _refresh_hay_mejores_after_write(MagicMock(), SimpleNamespace(name="prices"), "MLA1", {})
    assert calls == []
