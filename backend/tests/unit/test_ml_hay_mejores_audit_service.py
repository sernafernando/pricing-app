"""Unit tests for lean hay_mejores audit writers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.ml_hay_mejores_audit import KIND_AUTO_TOGGLE, KIND_FLAG_TRANSITION
from app.services.ml_hay_mejores_audit_service import (
    latest_auto_fail_message,
    latest_flag_transition_payload,
    record_auto_toggle,
    record_flag_transition,
)
from app.services.ml_hay_mejores_criterios_service import upsert_criterios
from decimal import Decimal


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_record_flag_transition_adds_row() -> None:
    db = MagicMock()
    db.begin_nested.return_value = _Nested()
    record_flag_transition(db, "MLA1", payload={"fingerprint": "C-1:900"})
    assert db.add.called
    row = db.add.call_args[0][0]
    assert row.item_id == "MLA1"
    assert row.kind == KIND_FLAG_TRANSITION
    assert row.payload["fingerprint"] == "C-1:900"
    db.begin_nested.assert_called_once()
    db.flush.assert_called_once()


def test_record_auto_toggle_skips_when_unchanged() -> None:
    db = MagicMock()
    record_auto_toggle(db, "MLA1", old=False, new=False, usuario_id=7)
    db.add.assert_not_called()
    db.begin_nested.assert_not_called()


def test_record_auto_toggle_logs_flip() -> None:
    db = MagicMock()
    db.begin_nested.return_value = _Nested()
    record_auto_toggle(db, "MLA1", old=False, new=True, usuario_id=7, alcance="item")
    row = db.add.call_args[0][0]
    assert row.kind == KIND_AUTO_TOGGLE
    assert row.usuario_id == 7
    assert row.payload == {"old": False, "new": True, "alcance": "item"}
    db.begin_nested.assert_called_once()


def test_upsert_criterios_logs_auto_flip(monkeypatch) -> None:
    logged: list[dict] = []

    def _log(db, item_id, *, old, new, usuario_id, alcance="item"):
        logged.append({"item_id": item_id, "old": old, "new": new, "usuario_id": usuario_id, "alcance": alcance})

    monkeypatch.setattr(
        "app.services.ml_hay_mejores_criterios_service.record_auto_toggle",
        _log,
    )
    monkeypatch.setattr(
        "app.services.ml_hay_mejores_criterios_service.get_criterios",
        lambda db, item_id: SimpleNamespace(auto_aplicacion=False),
    )
    row = SimpleNamespace(
        item_id="MLA1",
        c1_activo=False,
        c1_markup_min=None,
        c1_markup_max=None,
        c2_activo=False,
        c2_solo_markup_positivo=True,
        auto_aplicacion=False,
        sellers_excluidos=[],
        updated_by=None,
        updated_at=None,
    )
    db = MagicMock()
    db.get.return_value = row

    upsert_criterios(
        db,
        "MLA1",
        updated_by=3,
        c1_activo=False,
        c1_markup_min=None,
        c1_markup_max=None,
        c2_activo=False,
        c2_solo_markup_positivo=True,
        auto_aplicacion=True,
        puede_cambiar_auto=True,
    )
    assert logged == [{"item_id": "MLA1", "old": False, "new": True, "usuario_id": 3, "alcance": "item"}]
    assert row.auto_aplicacion is True


def test_upsert_without_auto_permission_keeps_previous_auto(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ml_hay_mejores_criterios_service.record_auto_toggle",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.ml_hay_mejores_criterios_service.get_criterios",
        lambda db, item_id: SimpleNamespace(auto_aplicacion=True),
    )
    row = SimpleNamespace(
        item_id="MLA1",
        c1_activo=False,
        c1_markup_min=None,
        c1_markup_max=None,
        c2_activo=False,
        c2_solo_markup_positivo=True,
        auto_aplicacion=True,
        sellers_excluidos=[],
        updated_by=None,
        updated_at=None,
    )
    db = MagicMock()
    db.get.return_value = row

    upsert_criterios(
        db,
        "MLA1",
        updated_by=3,
        c1_activo=False,
        c1_markup_min=None,
        c1_markup_max=None,
        c2_activo=False,
        c2_solo_markup_positivo=True,
        auto_aplicacion=False,
        puede_cambiar_auto=False,
    )
    assert row.auto_aplicacion is True


def test_latest_flag_transition_payload_returns_dict() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        payload={"status_quo": {"price": 1000.0}}
    )
    assert latest_flag_transition_payload(db, "MLA1") == {"status_quo": {"price": 1000.0}}


def test_latest_auto_fail_message_reads_fail_payload() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        payload={"auto_fail": True, "auto_fail_message": "Autoapply falló: stock insuficiente"}
    )
    assert latest_auto_fail_message(db, "MLA1") == "Autoapply falló: stock insuficiente"


def test_latest_auto_fail_message_none_without_fail_flag() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        payload={"fingerprint": "A:900"}
    )
    assert latest_auto_fail_message(db, "MLA1") is None
