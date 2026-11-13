"""hay_mejores_ofertas changes publish one SSE refresh signal for the PMs' top-bar badge, after the commit only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.ml_promotions_hay_mejores import FlagDecision


@pytest.fixture()
def published(monkeypatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        hay_mejores, "sse_publish_any_process", lambda channel, data=None: calls.append((channel, data))
    )
    return calls


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    with Session(engine) as s:
        s.execute(text("SELECT 1"))  # a transaction is open, as in the sync and the endpoints
        yield s


class _Query:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def filter(self, *args):
        return self

    def one_or_none(self):
        return self.rows.pop(0)

    def all(self):
        return self.rows


def _fake_query(session: Session, monkeypatch, rows: list) -> None:
    query = _Query(rows)
    monkeypatch.setattr(session, "query", lambda *args: query)


def _row(flag: bool, fingerprint=None) -> SimpleNamespace:
    return SimpleNamespace(
        hay_mejores_ofertas=flag, hay_mejores_fingerprint=fingerprint, hay_mejores_descartado_fingerprint=None, raw=[]
    )


class TestPublishAfterCommit:
    def test_the_channel_is_the_badge_one(self) -> None:
        assert hay_mejores.SSE_CHANNEL_MEJORES_OFERTAS == "ml-publications:mejores-ofertas"

    def test_the_stream_accepts_the_channel(self) -> None:
        from app.routers.sse import VALID_CHANNELS

        assert hay_mejores.SSE_CHANNEL_MEJORES_OFERTAS in VALID_CHANNELS

    def test_a_change_publishes_once_after_the_commit(self, session, published) -> None:
        hay_mejores.notify_hay_mejores_changed(session)
        hay_mejores.notify_hay_mejores_changed(session)
        assert published == []  # never before the data is visible
        session.commit()
        assert published == [("ml-publications:mejores-ofertas", {"hint": "reload"})]

    def test_a_rollback_publishes_nothing_and_forgets_the_change(self, session, published) -> None:
        hay_mejores.notify_hay_mejores_changed(session)
        session.rollback()
        session.execute(text("SELECT 1"))
        session.commit()
        assert published == []

    def test_each_transaction_publishes_its_own_change(self, session, published) -> None:
        hay_mejores.notify_hay_mejores_changed(session)
        session.commit()
        session.execute(text("SELECT 1"))
        session.commit()  # nothing changed in this one
        hay_mejores.notify_hay_mejores_changed(session)
        session.commit()
        assert len(published) == 2


class TestWhoNotifies:
    def _actualizar(self, session, monkeypatch, prev_flag: bool, decision: FlagDecision) -> None:
        _fake_query(
            session, monkeypatch, [_row(prev_flag, "C-1:900" if prev_flag else None), SimpleNamespace(amount=1000.0)]
        )
        monkeypatch.setattr(hay_mejores, "decidir_flag_hay_mejores", lambda **kwargs: decision)
        monkeypatch.setattr(hay_mejores, "listar_mejores_candidatas", lambda *a, **k: [("C-1", 900.0)])
        monkeypatch.setattr(hay_mejores, "_candidate_entries", lambda raw, now: [{"id": "C-1"}])
        monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda _db, _item_id: None)
        hay_mejores.actualizar_hay_mejores_ofertas(session, "MLA1", raw_promotions=[{"id": "C-1"}])
        session.commit()

    def test_a_newly_raised_flag_notifies(self, session, monkeypatch, published) -> None:
        decision = FlagDecision(hay_mejores=True, fingerprint="C-1:900", descartado_fingerprint=None)
        self._actualizar(session, monkeypatch, False, decision)
        assert len(published) == 1

    def test_a_cleared_flag_notifies(self, session, monkeypatch, published) -> None:
        decision = FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)
        self._actualizar(session, monkeypatch, True, decision)
        assert len(published) == 1

    def test_an_unchanged_flag_does_not_notify(self, session, monkeypatch, published) -> None:
        decision = FlagDecision(hay_mejores=True, fingerprint="C-1:900", descartado_fingerprint=None)
        self._actualizar(session, monkeypatch, True, decision)
        assert published == []

    def test_discarding_a_flagged_publication_notifies(self, session, monkeypatch, published) -> None:
        _fake_query(session, monkeypatch, [_row(True, "C-1:900")])
        assert hay_mejores.descartar_hay_mejores_ofertas(session, "MLA1") is True
        session.commit()
        assert len(published) == 1

    def test_discarding_an_unflagged_publication_does_not_notify(self, session, monkeypatch, published) -> None:
        _fake_query(session, monkeypatch, [_row(False)])
        hay_mejores.descartar_hay_mejores_ofertas(session, "MLA1")
        session.commit()
        assert published == []

    def test_clearing_flagged_rows_notifies_and_unflagged_ones_do_not(self, session, monkeypatch, published) -> None:
        _fake_query(session, monkeypatch, [_row(False), _row(False)])
        hay_mejores.limpiar_hay_mejores_ofertas(session, ["MLA1", "MLA2"])
        session.commit()
        assert published == []
        _fake_query(session, monkeypatch, [_row(False), _row(True, "C-1:900")])
        session.execute(text("SELECT 1"))
        hay_mejores.limpiar_hay_mejores_ofertas(session, ["MLA1", "MLA2"])
        session.commit()
        assert len(published) == 1
