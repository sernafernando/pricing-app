"""abm-productos T6 (L18 c): the TN catalog fetch of the worker handler is paged (~2.2k variants in prod, ~11 pages of
200) and bounded by the run's deadline; a fetch cut by the deadline is partial and says so in a warning with the pages
and products it got."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services import tienda_nube_catalogo


def _page(n: int) -> list[dict]:
    return [{"id": i, "name": {"es": f"P{i}"}, "variants": []} for i in range(n)]


@pytest.fixture()
def tn(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    monkeypatch.setattr(tienda_nube_catalogo.settings, "TN_STORE_ID", "1")
    monkeypatch.setattr(tienda_nube_catalogo.settings, "TN_ACCESS_TOKEN", "t")
    pages: list[int] = []

    def get(self, url, *, params, **_):
        pages.append(params["page"])
        return httpx.Response(200, json=_page(tienda_nube_catalogo.PER_PAGE), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", get)
    return pages


def test_a_fetch_cut_by_the_deadline_is_partial_and_warns_with_pages_and_products(
    tn: list[int], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    left = iter([60.0, 60.0, 1.0])
    monkeypatch.setattr(tienda_nube_catalogo, "_segundos_restantes", lambda _deadline: next(left))

    with caplog.at_level(logging.WARNING, logger=tienda_nube_catalogo.__name__):
        products, completo = tienda_nube_catalogo.fetch_productos(deadline=datetime.now(UTC) + timedelta(seconds=60))

    assert completo is False
    assert tn == [1, 2]
    assert len(products) == 2 * tienda_nube_catalogo.PER_PAGE
    assert "2 pages" in caplog.text and "400 products" in caplog.text


def test_the_handler_deadline_leaves_room_for_the_prod_catalog() -> None:
    from app.workers.handlers.tienda_nube_sync import sync

    # ~11 pages in prod (2026-11-16); each request may take up to its own timeout under a slow TN.
    assert sync.deadline_seconds >= 11 * 15
