"""P3: after the settle refresh, record whether ML actually applied our recent promo writes.

The pure rule (`confirmation_for`, `warnings_from_latest_writes`) runs without a database. The queries (latest row
per promotion, the jsonb update) are Postgres only: `DISTINCT ON` and `jsonb_set` have no SQLite equivalent.
The mirror read (`fetch_item_promotions`) is the only thing mocked.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.ml_write_log import MlWriteLog
from app.services import promo_write_confirmation as confirmation
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

MLA = "MLA1610390994"
PROMO = "C-MLA1669550"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


class TestConfirmationFor:
    def test_an_enroll_still_candidate_is_not_applied(self) -> None:
        assert confirmation.confirmation_for("enroll", "candidate", NOW) == {
            "status": "not_applied",
            "mirror_status": "candidate",
            "checked_at": NOW.isoformat(),
        }

    def test_an_enroll_pending_is_applied(self) -> None:
        assert confirmation.confirmation_for("enroll", "pending", NOW)["status"] == "applied"

    def test_an_enroll_missing_from_the_mirror_is_not_applied(self) -> None:
        result = confirmation.confirmation_for("enroll", None, NOW)
        assert result["status"] == "not_applied"
        assert result["mirror_status"] is None

    def test_a_remove_still_started_is_not_applied(self) -> None:
        assert confirmation.confirmation_for("remove", "started", NOW)["status"] == "not_applied"

    def test_a_remove_missing_from_the_mirror_is_applied(self) -> None:
        assert confirmation.confirmation_for("remove", None, NOW)["status"] == "applied"


def _latest(action: str, promotion_id: str = PROMO, status: str | None = "not_applied", **kw) -> dict:
    conf = None if status is None else {"status": status, "mirror_status": kw.pop("mirror_status", "candidate")}
    return {
        "promotion_id": promotion_id,
        "action": action,
        "created_at": kw.pop("created_at", NOW),
        "usuario_id": kw.pop("usuario_id", 7),
        "nombre": kw.pop("nombre", "Ana PM"),
        "confirmation": conf,
    }


class TestWarningsFromLatestWrites:
    def test_a_not_applied_enroll_on_a_shown_candidate_row_warns_on_that_row(self) -> None:
        por_promo, sin_promo = confirmation.warnings_from_latest_writes([_latest("enroll")], {PROMO: "candidate"})

        assert por_promo == {PROMO: {"accion": "enroll", "fecha": NOW, "usuario": "Ana PM"}}
        assert sin_promo == []

    def test_a_row_that_took_effect_since_the_check_does_not_warn(self) -> None:
        # Confirmed not applied at the settle refresh, but ML enrolled it later: the current mirror wins.
        por_promo, sin_promo = confirmation.warnings_from_latest_writes([_latest("enroll")], {PROMO: "started"})

        assert por_promo == {}
        assert sin_promo == []

    def test_an_applied_or_unconfirmed_write_does_not_warn(self) -> None:
        latest = [_latest("enroll", "A", status="applied"), _latest("enroll", "B", status=None)]

        assert confirmation.warnings_from_latest_writes(latest, {"A": "candidate", "B": "candidate"}) == ({}, [])

    def test_a_not_applied_enroll_missing_from_the_shown_rows_warns_at_panel_level(self) -> None:
        por_promo, sin_promo = confirmation.warnings_from_latest_writes(
            [_latest("enroll", mirror_status="finished")], {}
        )

        assert por_promo == {}
        assert sin_promo == [
            {
                "promotion_id": PROMO,
                "accion": "enroll",
                "fecha": NOW,
                "usuario": "Ana PM",
                "estado_ml": "finished",
            }
        ]

    def test_a_remove_missing_from_the_shown_rows_is_removed_now(self) -> None:
        latest = [_latest("remove", mirror_status="started")]

        assert confirmation.warnings_from_latest_writes(latest, {}) == ({}, [])

    def test_a_not_applied_remove_still_started_warns_on_the_row(self) -> None:
        por_promo, _ = confirmation.warnings_from_latest_writes(
            [_latest("remove", mirror_status="started")], {PROMO: "started"}
        )

        assert por_promo[PROMO]["accion"] == "remove"

    def test_the_user_falls_back_to_the_id_and_then_to_none(self) -> None:
        latest = [
            _latest("enroll", "A", nombre=None, usuario_id=42),
            _latest("enroll", "B", nombre=None, usuario_id=None),
        ]

        por_promo, _ = confirmation.warnings_from_latest_writes(latest, {"A": "candidate", "B": "candidate"})

        assert por_promo["A"]["usuario"] == "#42"
        assert por_promo["B"]["usuario"] is None


class TestConfirmRecentWritesBestEffort:
    def test_a_failing_session_is_logged_and_returns_zero(self, caplog) -> None:
        @contextmanager
        def broken():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        with mock.patch.object(confirmation, "fetch_item_promotions") as mirror:
            assert confirmation.confirm_recent_writes(MLA, session_factory=broken) == 0

        mirror.assert_not_called()
        assert "confirming recent writes failed" in caplog.text


# ── Postgres ──────────────────────────────────────────────────────────────


@pytest.fixture()
def pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types([MlWriteLog.__table__])
    schema = f"promo_confirm_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            # Only what the FK and the name join need; the real table has more columns.
            conn.execute(text("CREATE TABLE usuarios (id integer PRIMARY KEY, nombre varchar(255) NOT NULL)"))
            conn.execute(text("INSERT INTO usuarios (id, nombre) VALUES (7, 'Ana PM')"))
            MlWriteLog.__table__.create(bind=conn)
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _log(engine: Engine, action: str, *, target: str = PROMO, ago: timedelta, payload=None, mla: str = MLA) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO ml_write_log (mla, resource, action, target_id, promotion_type, payload, usuario_id,"
                " created_at) VALUES (:m, 'promotion', :a, :t, 'SELLER_CAMPAIGN', CAST(:p AS jsonb), 7, :c)"
                " RETURNING id"
            ),
            {
                "m": mla,
                "a": action,
                "t": target,
                "p": json.dumps(payload or {"outcome": "submitted"}),
                "c": datetime.now(UTC) - ago,
            },
        ).scalar_one()


def _payload(engine: Engine, row_id: int) -> dict:
    with engine.connect() as conn:
        return conn.execute(text("SELECT payload FROM ml_write_log WHERE id = :i"), {"i": row_id}).scalar_one()


def _mirror(**statuses: str) -> list[dict]:
    return [{"mla": MLA, "promotion_id": pid.replace("_", "-"), "status": st} for pid, st in statuses.items()]


@pytest.mark.postgres
class TestConfirmRecentWrites:
    def test_the_real_case_an_enroll_left_candidate_is_marked_not_applied(self, pg) -> None:
        row = _log(pg, "enroll", ago=timedelta(minutes=1))

        with mock.patch.object(confirmation, "fetch_item_promotions", return_value=_mirror(C_MLA1669550="candidate")):
            assert confirmation.confirm_recent_writes(MLA) == 1

        payload = _payload(pg, row)
        assert payload["outcome"] == "submitted"  # the rest of the payload is kept
        assert payload["confirmation"]["status"] == "not_applied"
        assert payload["confirmation"]["mirror_status"] == "candidate"
        assert datetime.fromisoformat(payload["confirmation"]["checked_at"]).tzinfo is not None

    def test_only_the_latest_write_per_promotion_is_confirmed(self, pg) -> None:
        older = _log(pg, "enroll", ago=timedelta(minutes=5))
        newer = _log(pg, "remove", ago=timedelta(minutes=1))

        with mock.patch.object(confirmation, "fetch_item_promotions", return_value=_mirror(C_MLA1669550="candidate")):
            confirmation.confirm_recent_writes(MLA)

        assert "confirmation" not in _payload(pg, older)
        assert _payload(pg, newer)["confirmation"]["status"] == "applied"

    def test_old_already_confirmed_and_other_mla_rows_are_left_alone_and_the_mirror_is_read_once(self, pg) -> None:
        old = _log(pg, "enroll", target="OLD", ago=confirmation.CONFIRM_WINDOW + timedelta(minutes=1))
        done = _log(
            pg, "enroll", target="DONE", ago=timedelta(minutes=1), payload={"confirmation": {"status": "applied"}}
        )
        other = _log(pg, "enroll", ago=timedelta(minutes=1), mla="MLA999")
        a = _log(pg, "enroll", target="A", ago=timedelta(minutes=1))
        b = _log(pg, "enroll", target="B", ago=timedelta(minutes=2))

        with mock.patch.object(
            confirmation, "fetch_item_promotions", return_value=_mirror(A="started", B="pending", DONE="candidate")
        ) as mirror:
            assert confirmation.confirm_recent_writes(MLA) == 2

        mirror.assert_called_once_with(MLA)
        assert "confirmation" not in _payload(pg, old)
        assert _payload(pg, done)["confirmation"] == {"status": "applied"}
        assert "confirmation" not in _payload(pg, other)
        assert _payload(pg, a)["confirmation"]["status"] == "applied"
        assert _payload(pg, b)["confirmation"]["status"] == "applied"

    def test_nothing_recent_skips_the_mirror_read(self, pg) -> None:
        with mock.patch.object(confirmation, "fetch_item_promotions") as mirror:
            assert confirmation.confirm_recent_writes(MLA) == 0

        mirror.assert_not_called()

    def test_no_session_is_held_while_the_mirror_is_read(self, pg) -> None:
        _log(pg, "enroll", ago=timedelta(minutes=1))
        seen: list[int] = []

        def read(mla: str) -> list[dict]:
            seen.append(pg.pool.checkedout())
            return []

        with mock.patch.object(confirmation, "fetch_item_promotions", side_effect=read):
            confirmation.confirm_recent_writes(MLA)

        assert seen == [0]

    def test_a_write_made_after_the_mirror_read_waits_for_the_next_pass(self, pg) -> None:
        # The mirror snapshot predates this write, so it cannot say whether ML applied it: stamping it now would
        # record "not applied" for good (first wins). It stays unstamped until a pass reads a later mirror.
        read_at = datetime.now(UTC)
        later = _log(pg, "enroll", ago=-timedelta(seconds=30))

        with (
            mock.patch.object(confirmation, "_utcnow", return_value=read_at),
            mock.patch.object(confirmation, "fetch_item_promotions", return_value=[]),
        ):
            assert confirmation.confirm_recent_writes(MLA) == 0

        assert "confirmation" not in _payload(pg, later)

        with (
            mock.patch.object(confirmation, "_utcnow", return_value=read_at + timedelta(minutes=1)),
            mock.patch.object(confirmation, "_db_now", return_value=read_at + timedelta(minutes=1)),
            mock.patch.object(confirmation, "fetch_item_promotions", return_value=_mirror(C_MLA1669550="pending")),
        ):
            assert confirmation.confirm_recent_writes(MLA) == 1

        assert _payload(pg, later)["confirmation"]["status"] == "applied"

    def test_the_read_bound_uses_the_database_clock_not_the_app_clock(self, pg) -> None:
        # `created_at` is stamped by Postgres, so the read bound must come from the same clock. With the app clock
        # two minutes ahead, a write made after the real read would fall under an app-clock bound and be stamped
        # "not applied" for good.
        later = _log(pg, "enroll", ago=-timedelta(seconds=30))

        with (
            mock.patch.object(confirmation, "_utcnow", return_value=datetime.now(UTC) + timedelta(minutes=2)),
            mock.patch.object(confirmation, "fetch_item_promotions", return_value=[]),
        ):
            assert confirmation.confirm_recent_writes(MLA) == 0

        assert "confirmation" not in _payload(pg, later)

    def test_a_failing_mirror_read_writes_nothing_and_does_not_raise(self, pg) -> None:
        row = _log(pg, "enroll", ago=timedelta(minutes=1))

        with mock.patch.object(confirmation, "fetch_item_promotions", side_effect=RuntimeError("mlwebhook down")):
            assert confirmation.confirm_recent_writes(MLA) == 0

        assert "confirmation" not in _payload(pg, row)


@pytest.mark.postgres
class TestLatestWritesForPanel:
    def test_one_batched_read_returns_the_latest_write_per_promotion_with_the_user_name(self, pg) -> None:
        _log(pg, "enroll", ago=timedelta(minutes=5))
        _log(
            pg,
            "enroll",
            ago=timedelta(minutes=1),
            payload={"confirmation": {"status": "not_applied", "mirror_status": "candidate"}},
        )
        _log(pg, "enroll", target="OTHER", ago=timedelta(minutes=3))

        with sessionmaker(bind=pg)() as db:
            latest = {row["promotion_id"]: row for row in confirmation.latest_writes_by_promotion(db, MLA)}

        assert set(latest) == {PROMO, "OTHER"}
        assert latest[PROMO]["confirmation"] == {"status": "not_applied", "mirror_status": "candidate"}
        assert latest[PROMO]["nombre"] == "Ana PM"
        assert latest["OTHER"]["confirmation"] is None

    def test_writes_older_than_the_lookback_are_ignored(self, pg) -> None:
        _log(pg, "enroll", ago=confirmation.WARNING_LOOKBACK + timedelta(days=1))

        with sessionmaker(bind=pg)() as db:
            assert confirmation.latest_writes_by_promotion(db, MLA) == []
