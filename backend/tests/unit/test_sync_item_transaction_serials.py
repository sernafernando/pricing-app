"""
Unit tests for app.scripts.sync_item_transaction_serials.

Regression suite for the production runaway: `--full` reached its_id
3_705_620_001 (batch #370563) sustaining ~25 req/s against the ERP webservice
for hours, because `/api/gbp-parser` answers HTTP 200 with `[{"error": ...}]`
or `[{"raw": ...}]` on upstream failure and the script read those sentinels as
data.

Tests cover:
  - _fetch_from_erp: error sentinels raise instead of masquerading as rows
  - sync_full: termination driven by rows PERSISTED, not payload truthiness
  - sync_full: consecutive failures abort with a non-zero exit
  - sync_full: a failed batch retries the SAME its_id range, never skips it
  - sync_full: a DB-side failure rolls the session back so the retry can work
  - sync_full: --max-id and the MAX_BATCHES safety valve
  - sync_incremental: ERP failure no longer exits 0

IMPORTANT: async functions are tested via asyncio.run() inside plain def tests.
The project has NO pytest-asyncio configured — do NOT use @pytest.mark.asyncio.

Nothing here touches the network or a real database: httpx.AsyncClient is
stubbed and the Session is either the permissive `db` MagicMock or, for
resilience claims, `StrictSessionDouble` (see its docstring).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.exc import OperationalError, PendingRollbackError

import app.scripts.sync_item_transaction_serials as module
from app.scripts.sync_item_transaction_serials import (
    ErpPayloadError,
    SyncAbortedError,
    _fetch_from_erp,
    _is_erp_error_sentinel,
    sync_full,
    sync_incremental,
)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

# Hard ceiling on ERP calls any test may make. Deliberately a BaseException so
# it escapes the `except Exception` batch handler in sync_full: a regression
# must surface as a LOUD test failure, never as a hanging test suite.
FETCH_TRIPWIRE = 25


class FetchLimitExceeded(BaseException):
    """Tripwire tripped: the loop under test is not terminating."""


class HttpStub:
    """Stands in for httpx.AsyncClient, recording every gbp-parser request.

    Args:
        responses: JSON payload returned for every call, or a list of payloads
            consumed in order (the last one repeats once exhausted).
        raises: exception raised instead of answering, for failure-path tests.
    """

    def __init__(
        self,
        responses: object = None,
        raises: BaseException | None = None,
    ) -> None:
        self._responses = responses
        self._raises = raises
        self.calls: list[dict] = []

    def _next_payload(self) -> object:
        if isinstance(self._responses, list) and self._responses and isinstance(self._responses[0], list):
            index = min(len(self.calls) - 1, len(self._responses) - 1)
            return self._responses[index]
        return self._responses

    async def _get(self, url: str, params: dict | None = None) -> MagicMock:
        self.calls.append(dict(params or {}))
        if len(self.calls) > FETCH_TRIPWIRE:
            raise FetchLimitExceeded(f"sync made more than {FETCH_TRIPWIRE} ERP requests — the loop is not terminating")
        if self._raises is not None:
            raise self._raises
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = self._next_payload()
        return response

    def patcher(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=self._get)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return patch.object(module.httpx, "AsyncClient", return_value=ctx)


def make_rows(count: int, start: int = 1) -> list[dict]:
    """Build `count` ERP rows that normalize successfully."""
    return [
        {
            "comp_id": "1",
            "bra_id": "1",
            "its_id": str(start + i),
            "it_transaction": "100",
            "is_id": "200",
            "ct_transaction": "300",
            "impData_id": "400",
            "import_id": "500",
        }
        for i in range(count)
    ]


class StrictSessionDouble:
    """A Session double that honours SQLAlchemy's post-failure contract.

    The permissive `db` MagicMock keeps answering happily after an exception,
    which is precisely what hid the missing `db.rollback()`. A real Session
    does not: once an operation raises, the transaction is left inactive and
    every later operation raises PendingRollbackError until rollback() runs.

    Use this double — never the MagicMock — whenever a test claims something
    about RECOVERY after a DB-side failure.

    `persisted` is keyed by the (comp_id, bra_id, its_id) triple so it models
    the real ON CONFLICT DO UPDATE: re-upserting a range replaces rows instead
    of duplicating them, which is exactly why retrying a range is safe.

    Args:
        fail_on_execute: 1-based indexes of the execute() calls that must blow
            up with a DB-side error (deadlock, DataError, pool disconnect).
    """

    def __init__(self, fail_on_execute: set[int] | None = None) -> None:
        self._fail_on_execute = set(fail_on_execute or ())
        self._inactive = False
        self._uncommitted: list[dict] = []
        self.execute_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.persisted: dict[tuple[int, int, int], dict] = {}
        self.operations: list[str] = []

    def _guard(self, operation: str) -> None:
        self.operations.append(operation)
        if self._inactive:
            raise PendingRollbackError(
                "This Session's transaction has been rolled back due to a previous exception during flush."
            )

    def execute(self, statement: object, rows: list[dict] | None = None) -> MagicMock:
        self._guard("execute")
        self.execute_count += 1
        if self.execute_count in self._fail_on_execute:
            self._inactive = True
            raise OperationalError(
                "INSERT INTO tb_item_transaction_serials ...",
                None,
                Exception("deadlock detected"),
            )
        self._uncommitted.extend(rows or [])
        return MagicMock()

    def commit(self) -> None:
        self._guard("commit")
        self.commit_count += 1
        for row in self._uncommitted:
            self.persisted[(row["comp_id"], row["bra_id"], row["its_id"])] = row
        self._uncommitted.clear()

    def rollback(self) -> None:
        self.operations.append("rollback")
        self._inactive = False
        self._uncommitted.clear()
        self.rollback_count += 1


@pytest.fixture()
def db() -> MagicMock:
    """A Session stub; _upsert_batch only needs execute() and commit().

    WARNING: this mock is PERMISSIVE. It never raises PendingRollbackError and
    never demands a rollback, so it cannot prove that sync_full survives a
    DB-side failure — it only records the calls that were made. For anything
    about recovery after a failed upsert, use StrictSessionDouble instead.
    """
    return MagicMock()


# ---------------------------------------------------------------------------
# _is_erp_error_sentinel / _fetch_from_erp
# ---------------------------------------------------------------------------


class TestErrorSentinelDetection:
    @pytest.mark.parametrize(
        "payload",
        [
            [{"error": "No se encontró el tag result"}],
            [{"raw": "<html><h1>503 Service Unavailable</h1></html>"}],
        ],
    )
    def test_sentinels_are_detected(self, payload: list[dict]) -> None:
        assert _is_erp_error_sentinel(payload) is True

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            [{"Column1": "no data"}],
            make_rows(1),
            make_rows(2),
            [{"error": "x"}, {"error": "y"}],  # two elements: not the sentinel shape
        ],
    )
    def test_real_payloads_are_not_sentinels(self, payload: list[dict]) -> None:
        assert _is_erp_error_sentinel(payload) is False

    @pytest.mark.parametrize(
        "payload",
        [
            [{"error": "No se encontró el tag result"}],
            [{"raw": "<html>503</html>"}],
        ],
    )
    def test_fetch_raises_on_sentinel(self, payload: list[dict]) -> None:
        """An upstream outage must NOT be indistinguishable from 'no more rows'."""
        stub = HttpStub(responses=payload)
        with stub.patcher():
            with pytest.raises(ErpPayloadError):
                asyncio.run(_fetch_from_erp({"strScriptLabel": "x"}))

    def test_fetch_maps_column1_sentinel_to_empty(self) -> None:
        """The legitimate GBP 'no data' sentinel still maps to []."""
        stub = HttpStub(responses=[{"Column1": "sin datos"}])
        with stub.patcher():
            assert asyncio.run(_fetch_from_erp({"strScriptLabel": "x"})) == []

    def test_fetch_returns_rows_untouched(self) -> None:
        rows = make_rows(3)
        stub = HttpStub(responses=rows)
        with stub.patcher():
            assert asyncio.run(_fetch_from_erp({"strScriptLabel": "x"})) == rows

    def test_fetch_raises_on_non_list_payload(self) -> None:
        stub = HttpStub(responses={"unexpected": "object"})
        with stub.patcher():
            with pytest.raises(ErpPayloadError):
                asyncio.run(_fetch_from_erp({"strScriptLabel": "x"}))

    def test_fetch_uses_settings_url(self) -> None:
        """The gbp-parser URL comes from settings, not a hardcoded literal."""
        stub = HttpStub(responses=[])
        with stub.patcher() as _:
            with patch.object(module.settings, "GBP_PARSER_URL", "http://configured:9999/api/gbp-parser"):
                client_ctx = module.httpx.AsyncClient()
                asyncio.run(_fetch_from_erp({"strScriptLabel": "x"}))

        called_url = client_ctx.__aenter__.return_value.get.call_args[0][0]
        assert called_url == "http://configured:9999/api/gbp-parser"

    def test_fetch_propagates_http_status_error(self) -> None:
        """raise_for_status() is preserved: a 502 from gbp-parser is a failure."""
        stub = HttpStub(responses=[])
        with stub.patcher() as _:
            client_ctx = module.httpx.AsyncClient()
            response = MagicMock()
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "502", request=MagicMock(), response=MagicMock()
            )
            client_ctx.__aenter__.return_value.get = AsyncMock(return_value=response)
            with pytest.raises(httpx.HTTPStatusError):
                asyncio.run(_fetch_from_erp({"strScriptLabel": "x"}))


# ---------------------------------------------------------------------------
# sync_full — the runaway regressions
# ---------------------------------------------------------------------------


class TestSyncFullTerminates:
    @pytest.mark.parametrize(
        "sentinel",
        [
            [{"error": "No se encontró el tag result"}],
            [{"raw": "<html><h1>503 Service Unavailable</h1></html>"}],
        ],
    )
    def test_permanent_error_sentinel_stops_promptly(self, db: MagicMock, sentinel: list[dict]) -> None:
        """THE regression: a gbp-parser error sentinel used to loop forever.

        Before the fix `_fetch_from_erp` returned the sentinel as data, so the
        payload was truthy, `consecutive_empty` reset to 0 every batch, zero
        rows normalized, and the loop printed '0 registros' until the ERP died.
        """
        stub = HttpStub(responses=sentinel)
        with stub.patcher():
            with pytest.raises(SyncAbortedError):
                sync_full(db, batch_size=10000)

        assert len(stub.calls) == module.MAX_CONSECUTIVE_FAILURES
        db.execute.assert_not_called()

    def test_permanent_transport_error_aborts(self, db: MagicMock) -> None:
        """A dead ERP (connection refused) aborts instead of retrying forever."""
        stub = HttpStub(raises=httpx.ConnectError("connection refused"))
        with stub.patcher():
            with pytest.raises(SyncAbortedError, match="errores consecutivos"):
                sync_full(db, batch_size=10000)

        assert len(stub.calls) == module.MAX_CONSECUTIVE_FAILURES

    def test_unnormalizable_rows_count_as_empty(self, db: MagicMock) -> None:
        """Payload truthiness must not reset the stop counter (defect B2).

        These rows are well formed JSON but every one fails _normalize_row
        (no comp_id/bra_id/its_id), so ZERO rows are persisted. That is an
        empty batch, whatever the payload looked like.
        """
        garbage = [{"something_else": "1"}, {"another": "2"}]
        stub = HttpStub(responses=garbage)
        with stub.patcher():
            sync_full(db, batch_size=10000)

        assert len(stub.calls) == module.MAX_CONSECUTIVE_EMPTY_BATCHES
        db.execute.assert_not_called()

    def test_column1_sentinel_counts_toward_termination(self, db: MagicMock) -> None:
        """The legitimate 'no data' sentinel still ends the run normally."""
        stub = HttpStub(responses=[{"Column1": "sin datos"}])
        with stub.patcher():
            sync_full(db, batch_size=10000)

        assert len(stub.calls) == module.MAX_CONSECUTIVE_EMPTY_BATCHES

    def test_transient_error_does_not_abort_a_healthy_run(self, db: MagicMock) -> None:
        """One hiccup must not kill a long run; the counter resets on success."""
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(params)
            if len(calls) in (2, 4):
                raise httpx.ConnectError("transient")
            if len(calls) <= 5:
                return make_rows(3, start=len(calls) * 10)
            return []

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            sync_full(db, batch_size=10000)

        # 3 successful data batches + 2 transient errors + 3 empty batches
        assert len(calls) == 8


class TestSyncFullRetriesFailedRange:
    """A failing batch must retry its range, not lose it.

    The two lines that advance the walk used to live OUTSIDE try/except/else,
    so a failure below the abort threshold moved `current_from` forward anyway:
    that its_id range was never requested again and the run still exited 0
    printing 'Sync full finalizado'. For a table whose whole purpose is serial
    traceability, one transient ERP hiccup silently lost `batch_size` ids.
    """

    def test_failed_batch_retries_the_same_range(self, db: MagicMock) -> None:
        """THE regression: the retry must re-request the exact failed range."""
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            if len(calls) == 2:
                raise httpx.ConnectError("transient")
            if len(calls) <= 4:
                return make_rows(2, start=len(calls) * 10)
            return []

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            sync_full(db, batch_size=10000)

        ranges = [(c["itsIDfrom"], c["itsIDto"]) for c in calls]

        # Attempt #2 failed on 10001-20000, so attempt #3 must re-request THAT
        # range — not the next one.
        assert ranges[1] == (10001, 20000)
        assert ranges[2] == ranges[1]

        # And no range is skipped anywhere in the run: collapsing the retries
        # leaves a strictly contiguous walk.
        walked = [r for i, r in enumerate(ranges) if i == 0 or r != ranges[i - 1]]
        assert walked == [
            (1, 10000),
            (10001, 20000),
            (20001, 30000),
            (30001, 40000),
            (40001, 50000),
            (50001, 60000),
        ]

    def test_consecutive_failures_abort_reporting_the_stuck_range(self, db: MagicMock) -> None:
        """The abort path is unchanged, and now names the range it got stuck on."""
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            if len(calls) == 1:
                return make_rows(2)
            raise httpx.ConnectError("erp caido")

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            with pytest.raises(SyncAbortedError, match=r"10001-20000"):
                sync_full(db, batch_size=10000)

        # One good batch plus MAX_CONSECUTIVE_FAILURES attempts on the same range.
        assert len(calls) == 1 + module.MAX_CONSECUTIVE_FAILURES
        assert [(c["itsIDfrom"], c["itsIDto"]) for c in calls[1:]] == [(10001, 20000)] * module.MAX_CONSECUTIVE_FAILURES

    def test_flapping_erp_is_bounded_by_max_batches(self, db: MagicMock) -> None:
        """Retries must not make the walk unbounded.

        Alternating failure/success never reaches MAX_CONSECUTIVE_FAILURES, so
        only the safety valve can stop this run. That only works because
        `batch_num` counts upstream ATTEMPTS, retries included.
        """
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            if len(calls) % 2 == 0:
                raise httpx.ConnectError("flapping")
            return make_rows(2, start=len(calls) * 10)

        original = module.MAX_BATCHES
        module.MAX_BATCHES = 6
        try:
            with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
                with pytest.raises(SyncAbortedError, match="[Vv]álvula de seguridad"):
                    sync_full(db, batch_size=10000)
        finally:
            module.MAX_BATCHES = original

        assert len(calls) == 6

    def test_partially_persisted_failure_is_not_double_counted(
        self, db: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Rows persisted by a failed attempt are counted once, by the retry.

        _upsert_batch is idempotent (ON CONFLICT DO UPDATE on the PK triple),
        so the successful retry re-upserts the very same rows: adding the
        failed attempt's partial count too would inflate the total.
        """
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            if len(calls) <= 2:
                return make_rows(1000, start=1)
            return []

        upserts: list[int] = []

        def flaky_upsert(session: object, rows: list[dict]) -> int:
            upserts.append(len(rows))
            # First attempt: sub-batch 1 persists, sub-batch 2 blows up.
            if len(upserts) == 2:
                raise RuntimeError("deadlock en el upsert")
            return len(rows)

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            with patch.object(module, "_upsert_batch", side_effect=flaky_upsert):
                sync_full(db, batch_size=10000)

        assert upserts == [500, 500, 500, 500]
        assert "Total: 1000 registros" in capsys.readouterr().out


class TestSyncFullRollsBackPoisonedSession:
    """A DB-side failure must not poison the session for the retry.

    The try block guards TWO failure sources, not one: the ERP call AND the
    `_upsert_batch` loop, which does real DB work (`db.execute` + `db.commit`).
    When sub-batch N of a range explodes (deadlock, DataError, pool
    disconnect), the Session is left inactive. Without a rollback the retry —
    the whole point of this branch — dies with PendingRollbackError on its
    first statement, burns MAX_CONSECUTIVE_FAILURES, and aborts blaming the
    ERP for a failure the script inflicted on itself.
    """

    def test_rollback_runs_before_the_retry_touches_the_session(self, db: MagicMock) -> None:
        """The rollback must land BETWEEN the failure and the retry's first statement."""
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            if len(calls) <= 2:
                return make_rows(1000, start=1)
            return []

        executes = {"count": 0}

        def flaky_execute(*args: object, **kwargs: object) -> MagicMock:
            # Sub-batch 1 commits fine; sub-batch 2 blows up mid-range.
            executes["count"] += 1
            if executes["count"] == 2:
                raise OperationalError("INSERT ...", None, Exception("deadlock detected"))
            return MagicMock()

        db.execute.side_effect = flaky_execute

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            sync_full(db, batch_size=10000)

        names = [name for name, _, _ in db.mock_calls]
        assert "rollback" in names, "the failure path never rolled the session back"

        execute_positions = [i for i, name in enumerate(names) if name == "execute"]
        rollback_position = names.index("rollback")

        # execute #1 and #2 belong to the failed attempt; execute #3 is the
        # retry's first DB operation. The rollback has to sit strictly between.
        assert execute_positions[1] < rollback_position < execute_positions[2]

        # And the retry really did persist the range: 1 commit before the
        # failure plus 2 from the successful retry.
        assert db.commit.call_count == 3

    def test_retry_persists_the_range_against_a_strict_session(self) -> None:
        """Fail-then-succeed on a Session that models transaction invalidation.

        This is the test the MagicMock could never be: StrictSessionDouble
        raises PendingRollbackError on every statement issued after a failure
        until rollback() runs, exactly like SQLAlchemy. Drop the rollback and
        this run aborts with SyncAbortedError instead of persisting anything.
        """
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            if len(calls) <= 2:
                return make_rows(1000, start=1)
            return []

        session = StrictSessionDouble(fail_on_execute={2})

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            sync_full(session, batch_size=10000)

        assert session.rollback_count == 1
        # The retry re-upserted the whole range: 1000 distinct its_id, none lost.
        assert len(session.persisted) == 1000
        assert {its_id for _, _, its_id in session.persisted} == set(range(1, 1001))
        # The run ended normally instead of aborting, and never re-poisoned itself.
        assert session.operations[-1] != "rollback"

    def test_rollback_failure_does_not_bypass_the_guard_rails(self, db: MagicMock) -> None:
        """A dead connection makes rollback() itself raise; accounting survives.

        If that exception escaped the handler it would skip consecutive_failures,
        the SyncAbortedError abort path and MAX_BATCHES entirely, surfacing as a
        raw traceback from main() instead of the controlled abort.
        """
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            return make_rows(10, start=1)

        db.execute.side_effect = OperationalError("INSERT ...", None, Exception("server closed the connection"))
        db.rollback.side_effect = OperationalError("ROLLBACK", None, Exception("connection already closed"))

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            with pytest.raises(SyncAbortedError, match="errores consecutivos"):
                sync_full(db, batch_size=10000)

        # The abort came from the guard rails, after exactly the budgeted attempts.
        assert len(calls) == module.MAX_CONSECUTIVE_FAILURES
        assert db.rollback.call_count == module.MAX_CONSECUTIVE_FAILURES

    def test_rollback_failure_is_reported_not_swallowed(
        self, db: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A failed rollback is a real problem and has to be visible in the log."""
        calls: list[dict] = []

        async def fake_fetch(params: dict) -> list[dict]:
            calls.append(dict(params))
            return make_rows(10, start=1)

        db.execute.side_effect = OperationalError("INSERT ...", None, Exception("server closed the connection"))
        db.rollback.side_effect = OperationalError("ROLLBACK", None, Exception("connection already closed"))

        with patch.object(module, "_fetch_from_erp", side_effect=fake_fetch):
            with pytest.raises(SyncAbortedError):
                sync_full(db, batch_size=10000)

        out = capsys.readouterr().out
        assert "rollback" in out.lower()
        assert "connection already closed" in out


class TestSyncFullBounds:
    def test_max_id_is_honored(self, db: MagicMock) -> None:
        """The loop must never request a range beyond --max-id."""
        stub = HttpStub(responses=make_rows(2))
        with stub.patcher():
            sync_full(db, batch_size=10000, max_id=25000)

        assert len(stub.calls) == 3
        assert [(c["itsIDfrom"], c["itsIDto"]) for c in stub.calls] == [
            (1, 10000),
            (10001, 20000),
            (20001, 25000),
        ]
        assert all(c["itsIDto"] <= 25000 for c in stub.calls)

    def test_max_id_smaller_than_batch_size(self, db: MagicMock) -> None:
        """A --max-id below one batch clamps the very first range."""
        stub = HttpStub(responses=make_rows(1))
        with stub.patcher():
            sync_full(db, batch_size=10000, max_id=50)

        assert [(c["itsIDfrom"], c["itsIDto"]) for c in stub.calls] == [(1, 50)]

    def test_safety_valve_fails_loudly(self, db: MagicMock) -> None:
        """MAX_BATCHES makes an unbounded walk structurally impossible.

        Every batch returns real rows, so neither the empty-batch counter nor
        the failure counter ever trips — only the valve can stop this.
        """
        original = module.MAX_BATCHES
        module.MAX_BATCHES = 5
        stub = HttpStub(responses=make_rows(2))
        try:
            with stub.patcher():
                with pytest.raises(SyncAbortedError, match="[Vv]álvula de seguridad"):
                    sync_full(db, batch_size=10000)
        finally:
            module.MAX_BATCHES = original

        assert len(stub.calls) == 5

    def test_safety_valve_is_below_the_tripwire_by_construction(self) -> None:
        """The shipped ceiling is finite and far below the observed runaway."""
        assert 0 < module.MAX_BATCHES < 370_563


class TestSyncFullHappyPath:
    def test_rows_are_normalized_upserted_and_run_ends(self, db: MagicMock) -> None:
        """Regression guard: normal syncing behaviour is unchanged."""
        payloads = [make_rows(1200, start=1), make_rows(3, start=20000), [], [], []]
        stub = HttpStub(responses=payloads)

        captured: list[list[dict]] = []
        real_upsert = module._upsert_batch

        def spy(session: object, rows: list[dict]) -> int:
            captured.append(list(rows))
            return real_upsert(session, rows)

        with stub.patcher():
            with patch.object(module, "_upsert_batch", side_effect=spy):
                sync_full(db, batch_size=10000)

        # 1200 rows -> 500/500/200 sub-batches, then 3 rows -> one sub-batch
        assert [len(b) for b in captured] == [500, 500, 200, 3]

        first = captured[0][0]
        assert first == {
            "comp_id": 1,
            "bra_id": 1,
            "its_id": 1,
            "it_transaction": 100,
            "is_id": 200,
            "ct_transaction": 300,
            "impdata_id": 400,
            "import_id": 500,
        }

        # 2 data batches + 3 genuinely empty batches
        assert len(stub.calls) == 5
        assert db.commit.call_count == 4

    def test_upsert_uses_on_conflict_do_update(self, db: MagicMock) -> None:
        """Upsert semantics preserved: ON CONFLICT DO UPDATE on the PK triple."""
        from sqlalchemy.dialects import postgresql

        module._upsert_batch(db, make_rows(1))

        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        assert "on conflict" in sql
        assert "do update" in sql
        for column in ("it_transaction", "is_id", "ct_transaction", "impdata_id", "import_id"):
            assert column in sql

    def test_partially_valid_batch_resets_the_empty_counter(self, db: MagicMock) -> None:
        """A batch persisting >= 1 row is not empty, even if other rows are junk."""
        mixed = make_rows(1) + [{"comp_id": None, "bra_id": None, "its_id": None}]
        stub = HttpStub(responses=[mixed, mixed, [], [], []])

        with stub.patcher():
            sync_full(db, batch_size=10000)

        assert len(stub.calls) == 5


# ---------------------------------------------------------------------------
# sync_incremental
# ---------------------------------------------------------------------------


class TestSyncIncremental:
    def _db_with_last_id(self, last_id: int | None) -> MagicMock:
        db = MagicMock()
        db.query.return_value.scalar.return_value = last_id
        return db

    def test_erp_failure_aborts_instead_of_exiting_zero(self) -> None:
        """A failed incremental run must not look like a successful one."""
        db = self._db_with_last_id(500)
        stub = HttpStub(responses=[{"error": "No se encontró el tag result"}])

        with stub.patcher():
            with pytest.raises(SyncAbortedError, match="Error consultando el ERP"):
                sync_incremental(db)

        assert len(stub.calls) == 1

    def test_no_previous_data_returns_early(self) -> None:
        db = self._db_with_last_id(None)
        stub = HttpStub(responses=make_rows(1))

        with stub.patcher():
            sync_incremental(db)

        assert stub.calls == []

    def test_new_rows_are_upserted_in_sub_batches(self) -> None:
        db = self._db_with_last_id(1000)
        stub = HttpStub(responses=make_rows(700, start=1001))

        captured: list[list[dict]] = []
        with stub.patcher():
            with patch.object(
                module,
                "_upsert_batch",
                side_effect=lambda s, rows: captured.append(list(rows)) or len(rows),
            ):
                sync_incremental(db)

        assert [len(b) for b in captured] == [500, 200]
        assert stub.calls[0]["itsID"] == 1000


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class TestCli:
    def test_max_id_flag_is_forwarded(self) -> None:
        """--max-id is real now, not just documented in the docstring."""
        with patch.object(module.sys, "argv", ["prog", "--full", "--max-id", "500000"]):
            with patch.object(module, "SessionLocal", return_value=MagicMock()):
                with patch.object(module, "sync_full") as mock_full:
                    module.main()

        assert mock_full.call_args.kwargs["max_id"] == 500000

    def test_max_id_defaults_to_none(self) -> None:
        with patch.object(module.sys, "argv", ["prog", "--full"]):
            with patch.object(module, "SessionLocal", return_value=MagicMock()):
                with patch.object(module, "sync_full") as mock_full:
                    module.main()

        assert mock_full.call_args.kwargs["max_id"] is None

    def test_aborted_sync_exits_non_zero(self) -> None:
        with patch.object(module.sys, "argv", ["prog", "--full"]):
            with patch.object(module, "SessionLocal", return_value=MagicMock()):
                with patch.object(module, "sync_full", side_effect=SyncAbortedError("boom")):
                    with pytest.raises(SystemExit) as exc:
                        module.main()

        assert exc.value.code == 1

    @pytest.mark.parametrize("argv", [["prog", "--full", "--max-id", "0"], ["prog", "--full", "--batch-size", "0"]])
    def test_invalid_bounds_exit_non_zero(self, argv: list[str]) -> None:
        with patch.object(module.sys, "argv", argv):
            with pytest.raises(SystemExit) as exc:
                module.main()

        assert exc.value.code == 1
