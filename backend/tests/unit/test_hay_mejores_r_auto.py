"""R-AUTO: pick best classic candidata and enroll after commit (ADR-5)."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.ml_hay_mejores_criterios_service import default_criterios
from app.services.ml_promotions_hay_mejores import (
    AUTOAPPLY_FAIL_PREFIX,
    C6_FINGERPRINT_KEY,
    FlagDecision,
    MejoresEvaluacion,
    _AUTO_PENDING,
    _on_hay_mejores_commit,
    _run_auto_enroll_after_commit,
    pick_mejor_candidata_auto,
    resolve_auto_enroll_target,
)


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_pick_prefers_classic_over_c2_only() -> None:
    picked = pick_mejor_candidata_auto(
        [
            {"key": "C2", "price": 900.0, "markup": 50.0, "path_clasico": False, "path_c2": True},
            {"key": "A", "price": 950.0, "markup": 12.0, "path_clasico": True, "path_c2": False},
        ]
    )
    assert picked is not None and picked["key"] == "A"


def test_pick_best_markup_within_classic() -> None:
    picked = pick_mejor_candidata_auto(
        [
            {"key": "A", "price": 900.0, "markup": 10.0, "path_clasico": True, "path_c2": False},
            {"key": "B", "price": 880.0, "markup": 18.0, "path_clasico": True, "path_c2": False},
            {"key": C6_FINGERPRINT_KEY, "price": 15900.0, "markup": 99.0, "path_clasico": False, "path_c2": False},
        ]
    )
    assert picked is not None and picked["key"] == "B"


def test_resolve_skips_lightning_without_stock() -> None:
    candidatas = [{"key": "L1", "price": 900.0, "markup": 10.0, "path_clasico": True, "path_c2": False}]
    candidates = [{"id": "L1", "type": "LIGHTNING", "status": "candidate", "price": 900}]
    assert resolve_auto_enroll_target(candidatas, candidates) is None


def test_actualizar_auto_defers_flag_and_schedules_enroll(monkeypatch) -> None:
    row = SimpleNamespace(
        hay_mejores_ofertas=False,
        hay_mejores_fingerprint=None,
        hay_mejores_descartado_fingerprint=None,
        raw=[],
    )
    sale = SimpleNamespace(amount=1000.0)
    db = MagicMock()
    db.info = {}
    db.begin_nested.return_value = _Nested()
    locked = MagicMock()
    locked.one_or_none.side_effect = [row]
    db.query.return_value.filter.return_value.with_for_update.return_value = locked
    db.query.return_value.filter.return_value.one_or_none.side_effect = [sale]

    monkeypatch.setattr(
        hay_mejores,
        "_candidate_entries",
        lambda *_a, **_k: [{"id": "A", "type": "SMART", "status": "candidate", "price": 900}],
    )
    monkeypatch.setattr(
        hay_mejores,
        "get_criterios",
        lambda *_a, **_k: replace(default_criterios("MLA1"), auto_aplicacion=True),
    )
    monkeypatch.setattr(
        hay_mejores,
        "evaluar_mejores_candidatas",
        lambda *_a, **_k: MejoresEvaluacion(
            mejores=[("A", 900.0)],
            status_quo={},
            candidatas=[{"key": "A", "price": 900.0, "markup": 12.0, "path_clasico": True, "path_c2": False}],
            criterios={},
        ),
    )
    monkeypatch.setattr(hay_mejores, "evaluar_monopolio_c6", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "record_flag_transition", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "notify_hay_mejores_changed", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "_ensure_hay_mejores_listeners", lambda *_a, **_k: None)
    enroll_calls: list[tuple] = []
    monkeypatch.setattr(
        hay_mejores,
        "_try_auto_enroll",
        lambda *a, **k: enroll_calls.append((a, k)) or {"status": "submitted"},
    )

    decision = hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1")
    assert decision == FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)
    assert row.hay_mejores_ofertas is False
    assert enroll_calls == []  # ADR-5: no MeLi HTTP while caller Session is open
    pending = db.info.get(_AUTO_PENDING) or []
    assert len(pending) == 1
    assert pending[0]["item_id"] == "MLA1"
    assert pending[0]["target"]["key"] == "A"


def test_auto_enroll_after_commit_success_does_not_reflag(monkeypatch) -> None:
    monkeypatch.setattr(hay_mejores, "_auto_still_authorized", lambda *_a, **_k: True)
    monkeypatch.setattr(hay_mejores, "_try_auto_enroll", lambda *_a, **_k: {"status": "submitted"})
    row = SimpleNamespace(hay_mejores_ofertas=False, hay_mejores_fingerprint="auto_pending:A:1700000000")
    fresh = MagicMock()
    locked = MagicMock()
    locked.one_or_none.return_value = row
    fresh.query.return_value.filter.return_value.with_for_update.return_value = locked
    payloads: list[dict] = []

    class _Bg:
        def __enter__(self):
            return fresh

        def __exit__(self, *args):
            return False

    import app.core.database as database

    monkeypatch.setattr(database, "get_background_db", lambda: _Bg())
    monkeypatch.setattr(
        hay_mejores,
        "record_flag_transition",
        lambda *_a, **_k: payloads.append({}) or (_ for _ in ()).throw(AssertionError("success must not re-flag")),
    )

    _run_auto_enroll_after_commit(
        {
            "item_id": "MLA1",
            "target": {"key": "A", "promotion_id": "A", "promotion_type": "SMART"},
            "fingerprint": "A:900",
            "descartado_fingerprint": None,
        }
    )
    assert payloads == []
    assert row.hay_mejores_fingerprint is None


def test_auto_enroll_after_commit_fail_reflags(monkeypatch) -> None:
    monkeypatch.setattr(hay_mejores, "_auto_still_authorized", lambda *_a, **_k: True)
    row = SimpleNamespace(
        hay_mejores_ofertas=False,
        hay_mejores_fingerprint=None,
        hay_mejores_descartado_fingerprint=None,
    )
    fresh = MagicMock()
    fresh.info = {}
    locked = MagicMock()
    locked.one_or_none.return_value = row
    fresh.query.return_value.filter.return_value.with_for_update.return_value = locked

    class _Bg:
        def __enter__(self):
            return fresh

        def __exit__(self, *args):
            return False

    import app.core.database as database

    monkeypatch.setattr(database, "get_background_db", lambda: _Bg())
    monkeypatch.setattr(
        hay_mejores,
        "_try_auto_enroll",
        lambda *_a, **_k: {"status": "rejected", "error": "stock insuficiente"},
    )
    payloads: list[dict] = []
    monkeypatch.setattr(
        hay_mejores,
        "record_flag_transition",
        lambda _db, _item, *, payload, **_k: payloads.append(payload),
    )
    monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "notify_hay_mejores_changed", lambda *_a, **_k: None)

    _run_auto_enroll_after_commit(
        {
            "item_id": "MLA1",
            "target": {"key": "A", "promotion_id": "A", "promotion_type": "SMART"},
            "fingerprint": "A:900",
            "descartado_fingerprint": None,
        }
    )
    assert row.hay_mejores_ofertas is True
    assert row.hay_mejores_fingerprint == "A:900"
    assert any(p.get("auto_fail") for p in payloads)
    assert any(AUTOAPPLY_FAIL_PREFIX in str(p.get("auto_fail_message", "")) for p in payloads)


def test_auto_enroll_ambiguous_does_not_reflag(monkeypatch) -> None:
    monkeypatch.setattr(hay_mejores, "_auto_still_authorized", lambda *_a, **_k: True)
    payloads: list[dict] = []
    monkeypatch.setattr(
        hay_mejores,
        "record_flag_transition",
        lambda *_a, **_k: payloads.append({}) or (_ for _ in ()).throw(AssertionError("ambiguous must not re-flag")),
    )
    monkeypatch.setattr(
        hay_mejores,
        "_try_auto_enroll",
        lambda *_a, **_k: {"status": "ambiguous", "detail": "timeout"},
    )
    _run_auto_enroll_after_commit(
        {
            "item_id": "MLA1",
            "target": {"key": "A", "promotion_id": "A", "promotion_type": "SMART"},
            "fingerprint": "A:900",
            "descartado_fingerprint": None,
        }
    )
    assert payloads == []


def test_auto_enroll_fail_reason_prefers_detail() -> None:
    assert hay_mejores._auto_enroll_fail_reason({"status": "rejected", "detail": "stock", "error": "x"}) == "stock"


def test_auto_pending_same_key_blocks_other_key_does_not() -> None:
    now = __import__("datetime").datetime(2026, 11, 18, 15, 0, tzinfo=__import__("datetime").timezone.utc)
    fp = hay_mejores._auto_pending_fingerprint("A", now=now)
    assert hay_mejores._is_auto_pending_fingerprint(fp, "A", now=now) is True
    assert hay_mejores._is_auto_pending_fingerprint(fp, "B", now=now) is False


def test_auto_pending_expires() -> None:
    from datetime import datetime, timedelta, timezone

    started = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    fp = hay_mejores._auto_pending_fingerprint("A", now=started)
    later = started + timedelta(seconds=hay_mejores.AUTO_PENDING_TTL_SECONDS + 1)
    assert hay_mejores._is_auto_pending_fingerprint(fp, "A", now=later) is False


def test_pick_prefers_c6_assist_when_no_classic_or_c2() -> None:
    picked = pick_mejor_candidata_auto(
        [
            {
                "key": "P6",
                "price": 1500.0,
                "markup": 40.0,
                "path_clasico": False,
                "path_c2": False,
                "path_c6": True,
            },
            {"key": C6_FINGERPRINT_KEY, "price": 15900.0, "markup": 99.0, "path_clasico": False, "path_c2": False},
        ]
    )
    assert picked is not None and picked["key"] == "P6"


def test_enqueue_catalog_refresh_once_per_session(monkeypatch) -> None:
    calls: list[str] = []

    class _NestedOk:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    db = MagicMock()
    db.info = {}
    db.begin_nested.return_value = _NestedOk()
    monkeypatch.setattr(
        "app.services.catalog_competition_target.mla_for_catalog_competition_refresh",
        lambda _db, item_id: item_id,
    )
    monkeypatch.setattr(
        "app.services.catalog_competition_refresh_queue.enqueue",
        lambda _db, ids, _now: calls.extend(ids) or len(ids),
    )
    hay_mejores._enqueue_catalog_competition_refresh(db, "MLA1")
    hay_mejores._enqueue_catalog_competition_refresh(db, "MLA1")
    hay_mejores._enqueue_catalog_competition_refresh(db, "MLA2")
    assert calls == ["MLA1", "MLA2"]


def test_on_commit_drains_pending_auto_jobs(monkeypatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(
        hay_mejores,
        "_run_auto_enroll_after_commit",
        lambda job: ran.append(job["item_id"]),
    )
    db = MagicMock()
    db.info = {
        _AUTO_PENDING: [
            {"item_id": "MLA1", "target": {}, "fingerprint": None, "descartado_fingerprint": None},
        ]
    }
    _on_hay_mejores_commit(db)
    assert ran == ["MLA1"]
    assert _AUTO_PENDING not in db.info
