"""L5/L8/L9: "haceme una tabla con los productos de eli, promoción actual y mejor promoción con precio de venta y
markup efectivo para nosotros con sell in aplicado", end to end through /api/mcp on invented data.

The tool reads the app's own endpoints as the user (items view, PMs, promos per item, markup for a price); here
they answer invented data so the whole chain (OAuth token -> tools/call -> PM resolution -> pick -> answer) runs.
"""

from __future__ import annotations

import json

import pytest

from tests.mcp.conftest import call_tool, connect, tool_text

PMS = [
    {"id": 3, "nombre": "Elías Romero", "email": "eromero@example.com", "rol": "PRICING"},
    {"id": 4, "nombre": "Elisa Duarte", "email": "eduarte@example.com", "rol": "PRICING"},
    {"id": 5, "nombre": "Bruno Paz", "email": "bpaz@example.com", "rol": "PRICING"},
]


def _row(item_id: str, title: str, price: float) -> dict:
    return {
        "item_id": item_id,
        "title": title,
        "seller_sku": f"SKU-{item_id}",
        "price": {"amount": price},
        "link": {"state": "linked", "codigo": f"P-{item_id}", "marca": "Acme"},
    }


ITEMS = {
    "total": 3,
    "limit": 20,
    "offset": 0,
    "items": [_row("MLA1", "Auriculares", 1000), _row("MLA2", "Mouse", 1000), _row("MLA3", "Teclado", 500)],
}

PROMOS = {
    "MLA1": [
        {
            "status": "started",
            "application_status": "active",
            "promotion_type": "DEAL",
            "promotion_id": "S1",
            "name": "Oferta del día",
            "price": 1000,
            "nuestro_markup": 10.0,
            "markup_sell_in_out": 12.0,
        },
        {
            "status": "candidate",
            "promotion_type": "SMART",
            "promotion_id": "A",
            "name": "Smart",
            "price": 950,
            "nuestro_markup": 15.0,
            "markup_sell_in_out": 18.0,
        },
        {
            "status": "candidate",
            "promotion_type": "PRE_NEGOTIATED",
            "promotion_id": "P",
            "name": "Pre negociada",
            "price": 1000,
            "nuestro_markup": 14.0,
            "markup_sell_in_out": 20.0,
        },
    ],
    "MLA2": [
        {
            "status": "candidate",
            "promotion_type": "SMART",
            "promotion_id": "B",
            "name": "Smart",
            "price": 900,
            "nuestro_markup": 25.0,
            "markup_sell_in_out": None,
        },
    ],
    "MLA3": [],
}
PLAIN_MARKUP = {
    "MLA2": {"price": 1000, "nuestro_markup": 20.0, "markup_sell_in_out": 22.0},
    "MLA3": {"price": 500, "nuestro_markup": None, "markup_sell_in_out": None},
}


@pytest.fixture
def app_data(monkeypatch):
    """Answer the app endpoints the tool reads with the invented data; record every call."""
    from app.mcp import loopback

    calls: list[tuple[str, dict]] = []
    denied: set[str] = set()

    async def fake_send(path: str, params: dict, headers: dict) -> tuple[int, bytes]:
        calls.append((path, params))
        if any(path.startswith(prefix) for prefix in denied):
            return 403, json.dumps({"detail": "Requiere permiso promos.ver"}).encode()
        if path == "/api/usuarios/pms":
            body = PMS
        elif path == "/api/ml-publications/view/items":
            body = ITEMS
        elif path.endswith("/markup"):
            body = PLAIN_MARKUP[path.split("/")[-2]]
        elif path.startswith("/api/promociones/item/"):
            mla = path.rsplit("/", 1)[1]
            body = {"mla": mla, "count": len(PROMOS[mla]), "promotions": PROMOS[mla]}
        else:
            return 404, b"{}"
        return 200, json.dumps(body).encode()

    monkeypatch.setattr(loopback, "send_request", fake_send)
    return calls, denied


def _call(mcp_client, mcp_user, arguments: dict) -> dict:
    conn = connect(mcp_client, mcp_user)
    return call_tool(mcp_client, conn.headers, "promos_publicaciones", arguments)


def test_an_ambiguous_pm_name_gets_a_clear_question_and_reads_nothing_else(mcp_client, mcp_user, app_data):
    calls, _ = app_data
    result = _call(mcp_client, mcp_user, {"pm": "eli"})
    assert result["isError"] is False
    data = json.loads(tool_text(result))
    assert data["needs_choice"] == "pm"
    assert [c["id"] for c in data["candidates"]] == [3, 4]
    assert "Elías Romero" in data["message"] and "Elisa Duarte" in data["message"]
    assert [path for path, _ in calls] == ["/api/usuarios/pms"]


def test_an_unknown_pm_name_says_so(mcp_client, mcp_user, app_data):
    result = _call(mcp_client, mcp_user, {"pm": "zoe"})
    assert result["isError"] is True
    assert "zoe" in tool_text(result) and "Bruno Paz" in tool_text(result)


def test_pm_and_pms_together_are_refused(mcp_client, mcp_user, app_data):
    result = _call(mcp_client, mcp_user, {"pm": "elisa", "pms": "4"})
    assert result["isError"] is True


def test_owner_example_table_of_eli_products(mcp_client, mcp_user, app_data):
    calls, _ = app_data
    data = json.loads(tool_text(_call(mcp_client, mcp_user, {"pm": "elisa", "estado": "active"})))

    assert data["pm"] == {"id": 4, "nombre": "Elisa Duarte"}
    items_call = next(params for path, params in calls if path == "/api/ml-publications/view/items")
    assert items_call == {"pms": "4", "estado": "active", "limit": 20, "offset": 0}
    assert data["total"] == 3
    rows = {row["item_id"]: row for row in data["rows"]}

    # Current promo (ML applies DEAL S1) vs the Sugeridas; best = highest markup with sell in (L9 option A).
    mla1 = rows["MLA1"]
    assert mla1["title"] == "Auriculares" and mla1["product"] == "P-MLA1" and mla1["sale_price"] == 1000
    assert mla1["current"] == {
        "promo": {"promotion_id": "S1", "name": "Oferta del día", "type": "DEAL"},
        "price": 1000,
        "markup": 10.0,
        "markup_sell_in_out": 12.0,
    }
    assert set(mla1["suggested"]) == {"SMART", "PRE_NEGOTIATED"}
    assert mla1["best"] == {
        "promotion_id": "P",
        "name": "Pre negociada",
        "type": "PRE_NEGOTIATED",
        "price": 1000,
        "markup": 14.0,
        "markup_sell_in_out": 20.0,
    }
    assert mla1["improvement"] == {"points": 8.0, "percent": 66.67, "basis": "markup_sell_in_out"}

    # No promo applied: the status quo is the sale price and its markup (same as the panel).
    mla2 = rows["MLA2"]
    assert mla2["current"] == {"promo": None, "price": 1000, "markup": 20.0, "markup_sell_in_out": 22.0}
    assert mla2["best"]["promotion_id"] == "B"
    assert mla2["improvement"] == {"points": 5.0, "percent": 25.0, "basis": "nuestro_markup"}
    assert ("/api/promociones/item/MLA2/markup", {"price": 1000}) in calls

    # Without a markup there is nothing to compare against: said, not invented.
    mla3 = rows["MLA3"]
    assert mla3["best"] is None and mla3["improvement"] is None and mla3["suggested"] == {}
    assert mla3["note"]


def test_without_promos_permission_the_tool_is_denied(mcp_client, mcp_user, app_data):
    _, denied = app_data
    denied.add("/api/promociones/")
    result = _call(mcp_client, mcp_user, {"pms": "4"})
    assert result["isError"] is True
    assert tool_text(result).startswith("Sin permiso")


def test_page_size_is_capped(mcp_client, mcp_user, app_data):
    result = _call(mcp_client, mcp_user, {"pms": "4", "limit": 500})
    assert result["isError"] is True


def test_rows_are_read_concurrently_but_bounded(mcp_client, mcp_user, monkeypatch):
    """A page of up to 50 publications must not run its per-row reads one after another, nor all at once."""
    import anyio

    from app.mcp import loopback, promos_bulk

    many = {"total": 12, "limit": 12, "offset": 0, "items": [_row(f"MLA{i}", "x", 1000) for i in range(12)]}
    state = {"inflight": 0, "peak": 0}

    async def fake_send(path: str, params: dict, headers: dict) -> tuple[int, bytes]:
        if path == "/api/ml-publications/view/items":
            return 200, json.dumps(many).encode()
        state["inflight"] += 1
        state["peak"] = max(state["peak"], state["inflight"])
        await anyio.sleep(0.02)
        state["inflight"] -= 1
        if path.endswith("/markup"):
            return 200, json.dumps({"nuestro_markup": 10.0, "markup_sell_in_out": None}).encode()
        return 200, json.dumps({"promotions": []}).encode()

    monkeypatch.setattr(loopback, "send_request", fake_send)
    data = json.loads(tool_text(_call(mcp_client, mcp_user, {"pms": "4", "limit": 12})))
    assert [row["item_id"] for row in data["rows"]] == [f"MLA{i}" for i in range(12)]
    assert 1 < state["peak"] <= promos_bulk.ROW_CONCURRENCY
