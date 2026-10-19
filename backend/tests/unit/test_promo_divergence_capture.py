"""When ML's enroll 201 price differs from the price the operator confirmed,
the enroll also captures, best effort, what ML's two READ sources say about
that item and promotion at that moment, and stores it in that write's
`ml_write_log` payload under `divergence_capture` (promo-mirror-freshness F2).

Fixture shapes are live captures (2026-10-19), not invented:
  - `/seller-promotions/items/{mla}` entry (the item's promo list);
  - `/seller-promotions/promotions/{id}/items?item_id=` page (the promotion's
    item list, filtered by item). The ml-webhook proxy forwards every query
    param except `app_version`, so `item_id` reaches ML.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import httpx
import pytest

from app.models.ml_write_log import MlWriteLog
from app.services import ml_promotions_write_service as write_service
from app.services.ml_webhook_client import MLWebhookClient

MLA = "MLA1807356285"
PROMO_ID = "P-MLA18161080"
CONFIRMED_PRICE = 976653
APPLIED_PRICE = 950000


def _item_list_entry(price: float = CONFIRMED_PRICE) -> Dict[str, Any]:
    """`/seller-promotions/items/{mla}` entry, captured live."""
    return {
        "id": PROMO_ID,
        "type": "SMART",
        "ref_id": "CANDIDATE-MLA1807356285-71690560920",
        "status": "candidate",
        "price": price,
        "meli_percentage": 2.8,
        "seller_percentage": 42.1,
        "original_price": 1770186,
        "name": "Ofertas compartidas CM",
    }


def _other_item_list_entry() -> Dict[str, Any]:
    entry = _item_list_entry()
    entry.update(id="P-MLA99999999", ref_id="CANDIDATE-MLA1807356285-1")
    return entry


def _promotion_items_page(price: float = APPLIED_PRICE) -> Dict[str, Any]:
    """`/seller-promotions/promotions/{id}/items?item_id=` page, captured live."""
    return {
        "paging": {"total": 1, "limit": 50},
        "results": [
            {
                "id": MLA,
                "status": "candidate",
                "price": price,
                "original_price": 1770186,
                "offer_id": "CANDIDATE-MLA1807356285-71690560920",
                "meli_percentage": 2.8,
                "seller_percentage": 42.1,
                "start_date": "2026-10-19T00:00:00",
                "end_date": "2026-11-19T00:00:00",
            }
        ],
    }


def _enroll_201(price: float) -> Dict[str, Any]:
    return {
        "ok": True,
        "status_code": 201,
        "ambiguous": False,
        "body": {"offer_id": "OFFER-MLA1807356285-71690560920", "price": price, "original_price": 1770186},
    }


class FakeSession:
    def __init__(self) -> None:
        self.added: List[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


@pytest.fixture()
def log_rows(monkeypatch: pytest.MonkeyPatch) -> List[MlWriteLog]:
    """Routes `_record_write_log`'s session to a recorder: the rows it adds."""
    session = FakeSession()

    @contextmanager
    def _fake():
        yield session

    monkeypatch.setattr(write_service, "get_background_db", _fake)
    return session.added


@pytest.fixture(autouse=True)
def _writes_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)
    monkeypatch.setattr(write_service, "_maybe_refresh_after_write", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "_maybe_recompute_after_write", lambda *a, **k: None)
    monkeypatch.setattr(write_service, "DIVERGENCE_CAPTURE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(write_service, "DIVERGENCE_CAPTURE_GRACE_S", 0.1)


class FakeProxy:
    """The first `get_item_promotions` call is the pre-apply live read; any
    later one is the divergence capture (`capture_item_list`)."""

    def __init__(
        self,
        applied_price: float,
        capture_item_list: Any = None,
        capture_promotion_items: Any = None,
    ) -> None:
        self.applied_price = applied_price
        self.capture_item_list = capture_item_list
        self.capture_promotion_items = capture_promotion_items
        self.item_reads: List[Dict[str, Any]] = []
        self.promotion_item_reads: List[Dict[str, Any]] = []

    def get_item_promotions(self, mla_id: str, timeout: Optional[float] = None) -> Any:
        self.item_reads.append({"mla_id": mla_id, "timeout": timeout})
        if len(self.item_reads) == 1:
            return [_item_list_entry()]
        return _outcome(self.capture_item_list)

    async def get_promotion_item(self, promotion_id: str, promotion_type: str, item_id: str, timeout=None) -> Any:
        self.promotion_item_reads.append(
            {"promotion_id": promotion_id, "promotion_type": promotion_type, "item_id": item_id, "timeout": timeout}
        )
        value = _outcome(self.capture_promotion_items)
        if asyncio.iscoroutine(value):
            value = await value
        return value

    def enroll_item(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return _enroll_201(self.applied_price)


def _outcome(value: Any) -> Any:
    if isinstance(value, BaseException):
        raise value
    if callable(value):
        return value()
    return value


def _enroll(proxy: FakeProxy) -> Dict[str, Any]:
    client = write_service.ml_webhook_client
    with (
        patch.object(client, "get_item_promotions", side_effect=proxy.get_item_promotions),
        patch.object(client, "get_promotion_item", side_effect=proxy.get_promotion_item, create=True),
        patch.object(client, "enroll_item", side_effect=proxy.enroll_item),
    ):
        return write_service.enroll_one_item(MLA, PROMO_ID, "SMART", precio_visto=CONFIRMED_PRICE, usuario_id=7)


def _capture(log_rows: List[MlWriteLog]) -> Dict[str, Any]:
    assert len(log_rows) == 1
    return log_rows[0].payload["divergence_capture"]


class TestDivergenceCapture:
    def test_divergence_stores_both_sources_matched_entries_in_the_write_log(self, log_rows) -> None:
        proxy = FakeProxy(
            APPLIED_PRICE,
            capture_item_list=[_other_item_list_entry(), _item_list_entry(price=APPLIED_PRICE)],
            capture_promotion_items=_promotion_items_page(),
        )

        outcome = _enroll(proxy)

        assert outcome["status"] == "submitted"
        assert outcome["precio_difiere"] is True
        capture = _capture(log_rows)
        item_list = capture["item_promotions"]
        promotion_items = capture["promotion_items"]
        assert item_list["status"] == "ok"
        assert item_list["entry"] == _item_list_entry(price=APPLIED_PRICE)
        assert promotion_items["status"] == "ok"
        assert promotion_items["entry"] == _promotion_items_page()["results"][0]
        assert item_list["captured_at"].endswith("+00:00")
        assert promotion_items["captured_at"].endswith("+00:00")
        # The log row still records both prices of the divergence.
        assert log_rows[0].payload["precio_aplicado"] == APPLIED_PRICE
        assert log_rows[0].payload["precio_visto"] == CONFIRMED_PRICE

    def test_promotion_items_read_is_filtered_by_item_with_a_short_timeout(self, log_rows) -> None:
        proxy = FakeProxy(APPLIED_PRICE, [_item_list_entry()], _promotion_items_page())

        _enroll(proxy)

        assert proxy.promotion_item_reads == [
            {
                "promotion_id": PROMO_ID,
                "promotion_type": "SMART",
                "item_id": MLA,
                "timeout": write_service.DIVERGENCE_CAPTURE_TIMEOUT_S,
            }
        ]
        assert proxy.item_reads[1] == {"mla_id": MLA, "timeout": write_service.DIVERGENCE_CAPTURE_TIMEOUT_S}

    def test_matching_price_calls_neither_source(self, log_rows) -> None:
        proxy = FakeProxy(CONFIRMED_PRICE, [_item_list_entry()], _promotion_items_page())

        outcome = _enroll(proxy)

        assert outcome["precio_difiere"] is False
        assert len(proxy.item_reads) == 1  # the pre-apply read only
        assert proxy.promotion_item_reads == []
        assert "divergence_capture" not in log_rows[0].payload

    def test_a_source_that_raises_is_an_error_and_the_other_still_captures(self, log_rows) -> None:
        proxy = FakeProxy(APPLIED_PRICE, RuntimeError("proxy down"), _promotion_items_page())

        outcome = _enroll(proxy)

        assert outcome["status"] == "submitted"
        assert outcome["precio_difiere"] is True
        capture = _capture(log_rows)
        assert capture["item_promotions"]["status"] == "error"
        assert capture["item_promotions"]["entry"] is None
        assert "proxy down" in capture["item_promotions"]["error"]
        assert capture["promotion_items"]["status"] == "ok"

    def test_a_source_that_hangs_times_out_as_an_error_within_the_budget(self, log_rows) -> None:
        async def _hang() -> Any:
            await asyncio.sleep(1)

        proxy = FakeProxy(APPLIED_PRICE, [_item_list_entry()], _hang)

        outcome = _enroll(proxy)

        assert outcome["precio_difiere"] is True
        capture = _capture(log_rows)
        assert capture["promotion_items"]["status"] == "error"
        assert capture["promotion_items"]["entry"] is None
        assert capture["promotion_items"]["error"].startswith("TimeoutError")
        assert capture["item_promotions"]["status"] == "ok"

    def test_sync_reads_run_concurrently(self, log_rows, monkeypatch: pytest.MonkeyPatch) -> None:
        """A blocking client call must not hold back the other source."""
        monkeypatch.setattr(write_service, "DIVERGENCE_CAPTURE_TIMEOUT_S", 1.0)

        def _slow(value: Any) -> Any:
            def _read() -> Any:
                time.sleep(0.3)
                return value

            return _read

        proxy = FakeProxy(APPLIED_PRICE, _slow([_item_list_entry()]), _slow(_promotion_items_page()))

        started = time.monotonic()
        _enroll(proxy)
        elapsed = time.monotonic() - started

        capture = _capture(log_rows)
        assert capture["item_promotions"]["status"] == "ok"
        assert capture["promotion_items"]["status"] == "ok"
        # Serial reads take at least 0.6s; concurrent ones about 0.3s.
        assert elapsed < 0.5

    def test_a_blocking_read_that_hangs_is_bounded_by_the_budget(self, log_rows) -> None:
        def _block() -> Any:
            time.sleep(1)
            return [_item_list_entry()]

        proxy = FakeProxy(APPLIED_PRICE, _block, _promotion_items_page())

        started = time.monotonic()
        _enroll(proxy)
        elapsed = time.monotonic() - started

        capture = _capture(log_rows)
        assert capture["item_promotions"]["status"] == "error"
        assert capture["item_promotions"]["error"].startswith("TimeoutError")
        assert capture["promotion_items"]["status"] == "ok"
        assert elapsed < 0.6

    def test_the_capture_works_inside_a_running_event_loop(self) -> None:
        """The capture must not depend on the caller's loop state: its reads
        run in worker threads, never on a loop the caller may be running."""
        client = write_service.ml_webhook_client

        async def _item_list(mla_id: str, timeout: Optional[float] = None) -> Any:
            return [_item_list_entry()]

        async def _promotion_items(*args: Any, **kwargs: Any) -> Any:
            return _promotion_items_page()

        async def _from_async_context() -> Dict[str, Any]:
            return write_service._capture_divergence_sources(MLA, PROMO_ID, "SMART")

        with (
            patch.object(client, "get_item_promotions", new=_item_list),
            patch.object(client, "get_promotion_item", new=_promotion_items, create=True),
        ):
            capture = asyncio.run(_from_async_context())

        assert capture["item_promotions"]["status"] == "ok"
        assert capture["promotion_items"]["status"] == "ok"

    def test_a_failed_read_returning_none_is_an_error(self, log_rows) -> None:
        proxy = FakeProxy(APPLIED_PRICE, None, None)

        _enroll(proxy)

        capture = _capture(log_rows)
        assert capture["item_promotions"]["status"] == "error"
        assert capture["promotion_items"]["status"] == "error"

    def test_a_source_without_this_promo_is_ok_with_no_entry(self, log_rows) -> None:
        proxy = FakeProxy(APPLIED_PRICE, [_other_item_list_entry()], {"paging": {"total": 0}, "results": []})

        _enroll(proxy)

        capture = _capture(log_rows)
        assert capture["item_promotions"] == {
            "status": "ok",
            "entry": None,
            "captured_at": capture["item_promotions"]["captured_at"],
        }
        assert capture["promotion_items"]["status"] == "ok"
        assert capture["promotion_items"]["entry"] is None

    def test_the_capture_is_not_part_of_the_api_outcome(self, log_rows) -> None:
        proxy = FakeProxy(APPLIED_PRICE, [_item_list_entry()], _promotion_items_page())

        outcome = _enroll(proxy)

        assert "divergence_capture" not in outcome

    def test_a_crashing_capture_never_breaks_the_enroll(self, log_rows, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*a: Any, **k: Any) -> None:
            raise RuntimeError("capture bug")

        monkeypatch.setattr(write_service, "_read_divergence_sources", _boom)
        proxy = FakeProxy(APPLIED_PRICE, [_item_list_entry()], _promotion_items_page())

        outcome = _enroll(proxy)

        assert outcome["status"] == "submitted"
        assert outcome["precio_difiere"] is True
        assert log_rows[0].payload["divergence_capture"]["status"] == "error"


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestGetPromotionItem:
    def test_forwards_item_id_and_type_to_the_proxy_items_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: List[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=_promotion_items_page())

        _patch_transport(monkeypatch, handler)

        result = asyncio.run(MLWebhookClient().get_promotion_item(PROMO_ID, "SMART", MLA, timeout=5.0))

        assert result == _promotion_items_page()
        assert len(seen) == 1  # a single page, never a walk of the whole promotion
        assert seen[0].url.path == f"/api/promociones/{PROMO_ID}/items"
        assert dict(seen[0].url.params) == {"promotion_type": "SMART", "item_id": MLA}

    def test_an_error_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_transport(monkeypatch, lambda request: httpx.Response(502, json={"error": "bad gateway"}))

        assert asyncio.run(MLWebhookClient().get_promotion_item(PROMO_ID, "SMART", MLA, timeout=5.0)) is None
