"""ERP adapter of the combo bill of materials (combos-propios C1).

Records have the shape `scriptItemAssociation` returns through the gbp-parser,
as `app.scripts.sync_item_associations` reads it: `comp_id`, `itema_id`,
`item_id` (combo), `item_id_1` (component), `iasso_qty`,
`itema_canDeleteInSO`, `itema_discountPercentage4PriceListSUM`.
"""

from __future__ import annotations

import socket
import threading
import time
from decimal import Decimal

import pytest
import requests

from app.services.combos import fuente_erp

D = Decimal


def _record(itema_id: int, item_id, item_id_1, iasso_qty, comp_id: int = 1) -> dict:
    return {
        "comp_id": comp_id,
        "itema_id": itema_id,
        "item_id": item_id,
        "item_id_1": item_id_1,
        "iasso_qty": iasso_qty,
        "itema_canDeleteInSO": True,
        "itema_discountPercentage4PriceListSUM": 0,
    }


class TestSnapshotDesdeRegistros:
    def test_maps_combo_component_and_quantity(self) -> None:
        registros = [_record(1, 100, 500, 2), _record(2, 100, 600, "1.5"), _record(3, 200, 500, 1)]
        assert fuente_erp.snapshot_desde_registros(registros) == {
            100: {500: D("2"), 600: D("1.5")},
            200: {500: D("1")},
        }

    def test_ignores_rows_without_a_positive_quantity(self) -> None:
        registros = [
            _record(1, 100, 500, 1),
            _record(2, 100, 501, 0),
            _record(3, 100, 502, None),
            _record(4, 300, 7, -1),
        ]
        assert fuente_erp.snapshot_desde_registros(registros) == {100: {500: D("1")}}

    def test_sums_a_pair_that_appears_twice(self) -> None:
        registros = [_record(1, 100, 500, 1), _record(2, 100, 500, "0.5"), _record(3, 100, 500, 0)]
        assert fuente_erp.snapshot_desde_registros(registros) == {100: {500: D("1.5")}}

    def test_empty_response_is_an_empty_snapshot(self) -> None:
        assert fuente_erp.snapshot_desde_registros([]) == {}

    @pytest.mark.parametrize("campo", ["item_id", "item_id_1"])
    def test_a_row_without_its_items_makes_the_snapshot_incomplete(self, campo: str) -> None:
        # Skipping it would delete a valid pair by absence: refuse the whole snapshot.
        registro = _record(2, 100, 600, 1)
        registro[campo] = None
        with pytest.raises(fuente_erp.SnapshotIncompleto):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1), registro])

    @pytest.mark.parametrize("qty", ["abc", "NaN", "Infinity"])
    def test_an_unreadable_quantity_makes_the_snapshot_incomplete(self, qty: str) -> None:
        with pytest.raises(fuente_erp.SnapshotIncompleto):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, qty)])

    def test_more_than_one_company_is_refused(self) -> None:
        # The app-owned table has no company: two ERP companies cannot be merged into it.
        with pytest.raises(fuente_erp.SnapshotIncompleto):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1), _record(2, 200, 500, 1, comp_id=2)])

    def test_mixed_missing_and_numeric_company_is_refused(self) -> None:
        # `None` and `1` cannot be ordered; the refusal must still be a clear SnapshotIncompleto.
        with pytest.raises(fuente_erp.SnapshotIncompleto, match="company"):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1, comp_id=None), _record(2, 200, 500, 1)])

    @pytest.mark.parametrize("campo", ["item_id", "item_id_1"])
    @pytest.mark.parametrize("valor", ["abc", "12x", "1.5", 1.5, True, [1]])
    def test_a_non_numeric_item_id_makes_the_snapshot_incomplete(self, campo: str, valor) -> None:
        registro = _record(2, 100, 600, 1)
        registro[campo] = valor
        with pytest.raises(fuente_erp.SnapshotIncompleto, match=campo):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1), registro])

    def test_an_absent_company_key_is_its_own_unknown_company(self) -> None:
        # A record without `comp_id` cannot be assumed to be company 1: mixing it with any company is refused.
        sin_compania = _record(2, 200, 500, 1)
        del sin_compania["comp_id"]
        with pytest.raises(fuente_erp.SnapshotIncompleto, match="company"):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1, comp_id=1), sin_compania])

    def test_an_absent_company_key_differs_from_a_null_one(self) -> None:
        sin_compania = _record(2, 200, 500, 1)
        del sin_compania["comp_id"]
        with pytest.raises(fuente_erp.SnapshotIncompleto, match="company"):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1, comp_id=None), sin_compania])

    def test_records_that_all_lack_the_company_key_are_one_company(self) -> None:
        registros = [_record(1, 100, 500, 1), _record(2, 200, 600, 2)]
        for registro in registros:
            del registro["comp_id"]
        assert fuente_erp.snapshot_desde_registros(registros) == {100: {500: D("1")}, 200: {600: D("2")}}

    @pytest.mark.parametrize("campo", ["item_id", "item_id_1"])
    @pytest.mark.parametrize(
        "valor", ["--5", "-5", "-0", "0", 0, -5, "\u00b9\u00b2", "\u0661\u0662", " 100", "100\n", "", "+5"]
    )
    def test_a_non_positive_or_non_ascii_item_id_makes_the_snapshot_incomplete(self, campo: str, valor) -> None:
        registro = _record(2, 100, 600, 1)
        registro[campo] = valor
        with pytest.raises(fuente_erp.SnapshotIncompleto, match=campo):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1), registro])

    def test_numeric_string_ids_are_accepted(self) -> None:
        assert fuente_erp.snapshot_desde_registros([_record(1, "100", "500", 1)]) == {100: {500: D("1")}}

    @pytest.mark.parametrize("registro", [None, "row", 7, ["item_id", 100]])
    def test_a_record_that_is_not_an_object_makes_the_snapshot_incomplete(self, registro) -> None:
        with pytest.raises(fuente_erp.SnapshotIncompleto):
            fuente_erp.snapshot_desde_registros([_record(1, 100, 500, 1), registro])


class _FakeClock:
    """Deterministic monotonic clock: only advances when a fake chunk says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Response:
    """`requests` streamed response stand-in: `chunks` are (seconds_until_it_arrives, bytes)."""

    def __init__(self, chunks=(), status: int = 200, clock: _FakeClock | None = None) -> None:
        self.chunks = list(chunks)
        self.status = status
        self.clock = clock
        self.closed = False
        self.read = 0

    def raise_for_status(self) -> None:
        if self.status >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"{self.status} Server Error")

    def iter_content(self, chunk_size=None):
        for delay, chunk in self.chunks:
            if self.clock is not None:
                self.clock.now += delay
            self.read += 1
            yield chunk

    def json(self):  # the unstreamed read: consumes every chunk, however slowly it drips
        import json

        return json.loads(b"".join(self.iter_content()))

    def close(self) -> None:
        self.closed = True


def _json_chunks(payload: bytes, size: int = 8, delay: float = 0.0) -> list:
    return [(delay, payload[i : i + size]) for i in range(0, len(payload), size)]


@pytest.fixture()
def script():
    from app.scripts import sync_item_associations as script

    script.fake_clock = _FakeClock()  # advanced only by the fake responses, never read by the helper
    yield script
    del script.fake_clock


def _serve(monkeypatch: pytest.MonkeyPatch, script, response=None, error: Exception | None = None) -> list:
    calls: list = []

    def fake_get(url, params, timeout, stream=False):
        calls.append({"params": params, "timeout": timeout, "stream": stream})
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(script.requests, "get", fake_get)
    return calls


class TestFetchSnapshot:
    def test_fetches_the_unfiltered_full_association_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = []

        def fake_fetch(**kwargs):
            calls.append(kwargs)
            return [_record(1, 100, 500, 2)]

        monkeypatch.setattr(fuente_erp, "fetch_item_associations_from_erp", fake_fetch)
        assert fuente_erp.fetch_snapshot(timeout=7.5) == {100: {500: D("2")}}
        # Unfiltered, strict, and the whole budget is the total wall-clock bound.
        assert len(calls) == 1
        call = calls[0]
        assert call["strict"] is True
        assert call["total_timeout"] == 7.5
        assert call["timeout"] <= 7.5
        assert set(call) == {"timeout", "total_timeout", "strict"}

    def test_the_shared_helper_passes_the_timeout(self, monkeypatch: pytest.MonkeyPatch, script) -> None:
        calls = _serve(monkeypatch, script, _Response(_json_chunks(b"[]")))
        script.fetch_item_associations_from_erp(timeout=7.5)
        assert calls[-1]["timeout"] == 7.5 and calls[-1]["stream"] is False  # cron path: the old plain GET
        calls = _serve(monkeypatch, script, _Response(_json_chunks(b"[]")))
        script.fetch_item_associations_from_erp(timeout=7.5, total_timeout=7.5)
        assert calls[-1]["timeout"] == 7.5 and calls[-1]["stream"] is True
        calls = _serve(monkeypatch, script, _Response(_json_chunks(b"[]")))
        script.fetch_item_associations_from_erp()
        assert calls[-1]["timeout"] == 120  # the cron script keeps its old timeout

    def test_the_cron_script_still_gets_an_empty_list_for_an_unexpected_shape(
        self, monkeypatch: pytest.MonkeyPatch, script
    ) -> None:
        _serve(monkeypatch, script, _Response(_json_chunks(b'{"error": "x"}')))
        assert script.fetch_item_associations_from_erp() == []

    def test_a_connection_error_raises(self, monkeypatch: pytest.MonkeyPatch, script) -> None:
        import requests

        _serve(monkeypatch, script, error=requests.exceptions.ConnectionError("refused"))
        with pytest.raises(requests.exceptions.ConnectionError):
            fuente_erp.fetch_snapshot(timeout=10)

    def test_a_server_error_raises(self, monkeypatch: pytest.MonkeyPatch, script) -> None:
        import requests

        response = _Response(_json_chunks(b"[]"), status=500)
        _serve(monkeypatch, script, response)
        with pytest.raises(requests.exceptions.HTTPError):
            fuente_erp.fetch_snapshot(timeout=10)
        assert response.closed

    def test_malformed_json_raises(self, monkeypatch: pytest.MonkeyPatch, script) -> None:
        _serve(monkeypatch, script, _Response(_json_chunks(b'[{"item_id": 1,')))
        with pytest.raises(ValueError):
            fuente_erp.fetch_snapshot(timeout=10)

    @pytest.mark.parametrize("payload", [b'{"error": "x"}', b"null", b'"ok"', b"7"])
    def test_an_unexpected_shape_raises_instead_of_an_empty_snapshot(
        self, monkeypatch: pytest.MonkeyPatch, script, payload: bytes
    ) -> None:
        _serve(monkeypatch, script, _Response(_json_chunks(payload)))
        with pytest.raises(ValueError, match="unexpected"):
            fuente_erp.fetch_snapshot(timeout=10)

    def test_a_valid_streamed_list_is_parsed(self, monkeypatch: pytest.MonkeyPatch, script) -> None:
        import json

        payload = json.dumps([_record(1, 100, 500, 2)]).encode()
        _serve(monkeypatch, script, _Response(_json_chunks(payload, delay=0.01), clock=script.fake_clock))
        assert fuente_erp.fetch_snapshot(timeout=10) == {100: {500: D("2")}}

    def test_the_cron_path_has_no_total_bound(self, monkeypatch: pytest.MonkeyPatch, script) -> None:
        # A slow but healthy full download (here ~500s, every gap under the 120s read timeout) must still succeed.
        payload = b"[" + b" " * 2000 + b"]"
        response = _Response(_json_chunks(payload, size=4, delay=1.0), clock=script.fake_clock)
        _serve(monkeypatch, script, response)
        start = script.fake_clock.now

        assert script.fetch_item_associations_from_erp() == []

        assert script.fake_clock.now - start > 120
        assert response.read == len(response.chunks)


class _BlockingResponse:
    """A streamed response whose body read blocks INSIDE one read (a server
    dripping bytes under the per-read timeout) until the caller closes it, the
    way closing the socket unblocks a `recv`."""

    def __init__(self) -> None:
        self.released = threading.Event()
        self.closed = False

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size=None):
        yield b"["
        self.released.wait(5)  # one read that never completes on its own within the test
        if self.closed:
            raise requests.exceptions.ConnectionError("connection closed by the caller")
        yield b"]"

    def close(self) -> None:
        self.closed = True
        self.released.set()


def _wait_for_fetch_thread(script) -> None:
    thread = script._fetch_thread
    if thread is not None:
        thread.join(5)
        assert not thread.is_alive()


class TestRealWallClockBound:
    """The total bound holds against reads that block inside a single call, with real (tiny) timings."""

    BOUND = 0.2
    SLACK = 0.5  # scheduling margin; still far below the blocked read's 5s

    def test_a_read_blocked_inside_one_recv_returns_by_the_deadline(
        self, monkeypatch: pytest.MonkeyPatch, script
    ) -> None:
        response = _BlockingResponse()
        _serve(monkeypatch, script, response)

        start = time.monotonic()
        with pytest.raises(script.ErpFetchTimeout):
            script.fetch_item_associations_from_erp(timeout=60, total_timeout=self.BOUND, strict=True)
        elapsed = time.monotonic() - start

        assert self.BOUND <= elapsed < self.BOUND + self.SLACK
        assert response.closed  # the caller closed it, which unblocks the read
        _wait_for_fetch_thread(script)

    def test_a_connect_that_never_returns_is_bounded_too(self, monkeypatch: pytest.MonkeyPatch, script) -> None:
        connecting = threading.Event()

        def stuck_get(url, params, timeout, stream=False):
            connecting.wait(5)  # DNS / connect / headers: no response object to close yet
            raise requests.exceptions.ConnectionError("gave up")

        monkeypatch.setattr(script.requests, "get", stuck_get)

        start = time.monotonic()
        with pytest.raises(script.ErpFetchTimeout):
            script.fetch_item_associations_from_erp(timeout=60, total_timeout=self.BOUND, strict=True)
        assert time.monotonic() - start < self.BOUND + self.SLACK

        # While the abandoned fetch is still stuck, a new one refuses instead of piling up threads.
        with pytest.raises(script.ErpFetchTimeout, match="past its deadline"):
            script.fetch_item_associations_from_erp(timeout=60, total_timeout=self.BOUND, strict=True)

        connecting.set()
        _wait_for_fetch_thread(script)

    def test_a_response_that_arrives_just_after_the_deadline_is_closed_unread(
        self, monkeypatch: pytest.MonkeyPatch, script
    ) -> None:
        # The deadline fires while `requests.get` is still returning: the caller has nothing to close yet,
        # so the fetch thread itself must close the late response without reading any of the body.
        release_get = threading.Event()
        response = _Response(_json_chunks(b"[" + b" " * 64 + b"]"))

        def late_get(url, params, timeout, stream=False):
            release_get.wait(5)
            return response

        monkeypatch.setattr(script.requests, "get", late_get)

        with pytest.raises(script.ErpFetchTimeout):
            script.fetch_item_associations_from_erp(timeout=60, total_timeout=self.BOUND, strict=True)

        release_get.set()
        _wait_for_fetch_thread(script)
        assert response.closed
        assert response.read == 0

    def test_a_second_fetch_while_one_is_inside_its_deadline_is_refused_as_concurrent(
        self, monkeypatch: pytest.MonkeyPatch, script
    ) -> None:
        release_get = threading.Event()

        def slow_get(url, params, timeout, stream=False):
            release_get.wait(5)
            return _Response(_json_chunks(b"[]"))

        monkeypatch.setattr(script.requests, "get", slow_get)
        first: dict = {}

        def run_first() -> None:
            first["result"] = script.fetch_item_associations_from_erp(timeout=60, total_timeout=5, strict=True)

        caller = threading.Thread(target=run_first)
        caller.start()
        try:
            for _ in range(200):  # wait until the first fetch has started its thread
                if script._fetch_done is not None and not script._fetch_done.is_set():
                    break
                time.sleep(0.005)
            with pytest.raises(script.ErpFetchTimeout, match="already running") as refused:
                script.fetch_item_associations_from_erp(timeout=60, total_timeout=self.BOUND, strict=True)
            assert "past its deadline" not in str(refused.value)
        finally:
            release_get.set()
            caller.join(5)
        assert first["result"] == []  # the first fetch was not disturbed

    def test_a_real_socket_dripping_bytes_is_cut_at_the_deadline(self, script) -> None:
        # A real local HTTP server sends the headers, then one body byte every 20ms, each well under the read
        # timeout: only a true wall-clock bound stops it, and closing the socket ends the fetch thread.
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        stop = threading.Event()

        def serve() -> None:
            conn, _ = server.accept()
            with conn:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n[")
                while not stop.is_set():
                    try:
                        conn.sendall(b" ")
                    except OSError:
                        return
                    stop.wait(0.02)

        threading.Thread(target=serve, daemon=True).start()
        url = f"http://127.0.0.1:{server.getsockname()[1]}/api/gbp-parser"
        try:
            start = time.monotonic()
            with pytest.raises(script.ErpFetchTimeout):
                script._get_json_within(url, {}, read_timeout=5, total_timeout=self.BOUND)
            assert time.monotonic() - start < self.BOUND + self.SLACK
            _wait_for_fetch_thread(script)  # the socket was shut down: the fetch thread did not keep reading
        finally:
            stop.set()
            server.close()
