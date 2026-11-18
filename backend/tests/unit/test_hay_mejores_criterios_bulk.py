"""Bulk criterios upsert + discard open suggestions (skip Auto-fail)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.ml_hay_mejores_criterios_service import upsert_criterios_bulk
from app.services import ml_promotions_hay_mejores as hay_mejores


def test_upsert_criterios_bulk_skips_unknown_and_sets_alcance_bulk(monkeypatch) -> None:
    calls: list[dict] = []

    def _upsert(db, item_id, **kwargs):
        calls.append({"item_id": item_id, **kwargs})
        return SimpleNamespace(item_id=item_id)

    monkeypatch.setattr(
        "app.services.ml_hay_mejores_criterios_service.upsert_criterios",
        _upsert,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [("MLA1",), ("MLA3",)]

    touched = upsert_criterios_bulk(
        db,
        ["MLA1", "MLA2", "MLA1", "MLA3"],
        updated_by=9,
        c1_activo=True,
        c1_markup_min=Decimal("1"),
        c1_markup_max=Decimal("5"),
        c2_activo=False,
        c2_solo_markup_positivo=True,
        auto_aplicacion=True,
        sellers_excluidos=None,
    )
    assert touched == ["MLA1", "MLA3"]
    assert [c["item_id"] for c in calls] == ["MLA1", "MLA3"]
    assert all(c["alcance"] == "bulk" for c in calls)
    assert all(c["auto_aplicacion"] is True for c in calls)


def test_descartar_bulk_skips_auto_fail(monkeypatch) -> None:
    flagged = SimpleNamespace(
        item_id="MLA-FAIL",
        hay_mejores_ofertas=True,
        hay_mejores_fingerprint="A:900",
        hay_mejores_descartado_fingerprint=None,
    )
    normal = SimpleNamespace(
        item_id="MLA-OK",
        hay_mejores_ofertas=True,
        hay_mejores_fingerprint="B:800",
        hay_mejores_descartado_fingerprint=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [flagged, normal]
    monkeypatch.setattr(
        "app.services.ml_hay_mejores_audit_service.latest_auto_fail_message",
        lambda _db, item_id: "Autoapply falló: x" if item_id == "MLA-FAIL" else None,
    )
    notified: list[bool] = []
    monkeypatch.setattr(hay_mejores, "notify_hay_mejores_changed", lambda *_a, **_k: notified.append(True))

    descartadas, omitidas = hay_mejores.descartar_hay_mejores_sugerencias_bulk(
        db, ["MLA-FAIL", "MLA-OK"], skip_auto_fail=True
    )
    assert omitidas == ["MLA-FAIL"]
    assert descartadas == ["MLA-OK"]
    assert flagged.hay_mejores_ofertas is True
    assert normal.hay_mejores_ofertas is False
    assert normal.hay_mejores_descartado_fingerprint == "B:800"
    assert notified == [True]
