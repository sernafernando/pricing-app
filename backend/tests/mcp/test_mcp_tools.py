"""MCP read tools (S5, S8, S9): same gates as the app, cost masking, caps, logging, rate limit.

Denied paths hit the REAL endpoints in process, so the permission check that answers is the
app's own. Parameter mapping and response shaping are checked with a recording stand-in for
the in-process call (the real endpoints need Postgres fixtures that live in their own suites).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.models.mcp_oauth import McpConnection, McpToolCall
from tests.mcp.conftest import call_tool, connect, tool_text


@pytest.fixture()
def recorder(monkeypatch):
    """Replace the in-process HTTP call with a recorder that answers `payload`."""
    from app.mcp import loopback

    calls: list[dict] = []
    state = {"status": 200, "payload": {"total": 0, "items": []}}

    async def fake_send(path: str, params: dict, headers: dict) -> tuple[int, bytes]:
        calls.append({"path": path, "params": params, "headers": headers})
        return state["status"], json.dumps(state["payload"]).encode()

    monkeypatch.setattr(loopback, "send_request", fake_send)
    return calls, state


# ---------------------------------------------------------------- same gates as the app (real endpoints)


@pytest.mark.parametrize(
    ("tool", "arguments", "codigo"),
    [
        ("pubml_items", {}, "productos.ver"),
        ("pubml_item", {"item_id": "MLA1"}, "productos.ver"),
        ("pubml_kpis", {}, "productos.ver"),
        ("metricas_board", {"canal": "ml"}, "ml_metricas.ver"),
        ("ventas_por_fuera", {}, "ventas_fuera.ver_metricas_pdf"),
        ("pubml_stock_audit", {}, "ml_publicaciones.ver_auditoria_stock"),
    ],
)
def test_a_user_without_the_app_permission_is_denied_by_the_app_endpoint(
    mcp_client, mcp_user, db, tool, arguments, codigo
):
    conn = connect(mcp_client, mcp_user)
    result = call_tool(mcp_client, conn.headers, tool, arguments)
    assert result["isError"] is True
    assert "Sin permiso" in tool_text(result)
    log = db.query(McpToolCall).one()
    assert log.tool == tool
    assert log.status == "denied"
    assert log.usuario_id == mcp_user.id


def test_granting_the_app_permission_lets_the_same_call_through(mcp_client, mcp_user, rol_admin, grant_permiso):
    conn = connect(mcp_client, mcp_user)
    denied = call_tool(mcp_client, conn.headers, "ventas_por_fuera", {})
    assert "Sin permiso" in tool_text(denied)
    grant_permiso(rol_admin, "ventas_fuera.ver_metricas_pdf")
    allowed = call_tool(mcp_client, conn.headers, "ventas_por_fuera", {})
    assert "Sin permiso" not in tool_text(allowed)


def test_the_in_process_call_runs_as_the_connected_user(mcp_client, mcp_user, recorder):
    calls, _ = recorder
    conn = connect(mcp_client, mcp_user)
    call_tool(mcp_client, conn.headers, "pubml_items", {"q": "notebook"})
    [call] = calls
    token = call["headers"]["Authorization"].removeprefix("Bearer ")
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], audience="pricing-app-api")
    assert payload["sub"] == mcp_user.username
    assert payload["via"] == "mcp"
    assert payload["exp"] - datetime.now(UTC).timestamp() <= 60


# ---------------------------------------------------------------- parameter mapping


@pytest.mark.parametrize(
    ("tool", "arguments", "path", "params"),
    [
        (
            "pubml_items",
            {"q": "notebook", "marcas": "3,4", "estado": "active", "pms": "7", "limit": 10, "offset": 20},
            "/api/ml-publications/view/items",
            {"q": "notebook", "marcas": "3,4", "estado": "active", "pms": "7", "limit": 10, "offset": 20},
        ),
        ("pubml_item", {"item_id": "MLA123"}, "/api/ml-publications/view/items/MLA123", {}),
        ("pubml_kpis", {"q": "x"}, "/api/ml-publications/view/kpis", {"q": "x"}),
        (
            "metricas_board",
            {"canal": "todo", "costo": "costo", "date_from": "2026-11-01", "date_to": "2026-11-17"},
            "/api/ml-metricas/board",
            {
                "canal": "todo",
                "costo": "costo",
                "date_from": "2026-11-01",
                "date_to": "2026-11-17",
                "limit": 20,
                "offset": 0,
            },
        ),
        ("venta_ml", {"order_id": 2000001}, "/api/ml-ventas-ops/orders/2000001", {}),
        (
            "ventas_por_fuera",
            {"desde": "2026-11-01", "hasta": "2026-11-17", "page": 2},
            "/api/ventas-fuera-pdf/operaciones",
            {"desde": "2026-11-01", "hasta": "2026-11-17", "page": 2, "page_size": 20},
        ),
        (
            "pubml_stock_audit",
            {"orden": "valor_total", "dir": "asc"},
            "/api/ml-publications/view/stock-audit",
            {"orden": "valor_total", "dir": "asc", "limit": 20, "offset": 0},
        ),
        (
            "productos_precios_listas",
            {"search": "mouse"},
            "/api/productos/precios-listas",
            {"search": "mouse", "page": 1, "page_size": 20},
        ),
        ("producto_detalle", {"item_id": 55}, "/api/productos/55/detalle", {}),
        ("promos_item", {"mla_id": "MLA77"}, "/api/promociones/item/MLA77", {}),
    ],
)
def test_each_tool_calls_its_app_endpoint(mcp_client, mcp_user, recorder, tool, arguments, path, params):
    calls, _ = recorder
    conn = connect(mcp_client, mcp_user)
    result = call_tool(mcp_client, conn.headers, tool, arguments)
    assert result["isError"] is False, tool_text(result)
    [call] = calls
    assert call["path"] == path
    assert call["params"] == params


def test_ventas_ml_returns_the_sales_and_their_kpis(mcp_client, mcp_user, recorder):
    calls, state = recorder
    state["payload"] = {"total": 0, "items": []}
    conn = connect(mcp_client, mcp_user)
    arguments = {"date_from": "2026-11-01", "date_to": "2026-11-17"}
    data = json.loads(tool_text(call_tool(mcp_client, conn.headers, "ventas_ml", arguments)))
    assert [c["path"] for c in calls] == ["/api/ml-ventas-ops/sales", "/api/ml-ventas-ops/sales/kpis"]
    assert calls[0]["params"] == {**arguments, "limit": 20, "offset": 0}
    assert calls[1]["params"] == arguments
    assert set(data) == {"ventas", "kpis"}


def test_ventas_por_fuera_defaults_to_the_last_30_days(mcp_client, mcp_user, recorder):
    from datetime import date

    calls, _ = recorder
    conn = connect(mcp_client, mcp_user)
    call_tool(mcp_client, conn.headers, "ventas_por_fuera", {})
    hoy = date.today()
    assert calls[0]["params"]["hasta"] == hoy.isoformat()
    assert calls[0]["params"]["desde"] == (hoy - timedelta(days=29)).isoformat()


def test_arguments_outside_the_endpoint_are_refused(mcp_client, mcp_user, recorder):
    calls, _ = recorder
    conn = connect(mcp_client, mcp_user)
    result = call_tool(mcp_client, conn.headers, "pubml_items", {"usuario_id": 1})
    assert result["isError"] is True
    assert "usuario_id" in tool_text(result)
    assert calls == []


def test_paging_is_capped(mcp_client, mcp_user, recorder):
    calls, _ = recorder
    conn = connect(mcp_client, mcp_user)
    assert call_tool(mcp_client, conn.headers, "pubml_items", {"limit": 500})["isError"] is True
    assert call_tool(mcp_client, conn.headers, "productos_precios_listas", {"page_size": 51})["isError"] is True
    assert calls == []


def test_path_arguments_cannot_escape_their_endpoint(mcp_client, mcp_user, recorder):
    calls, _ = recorder
    conn = connect(mcp_client, mcp_user)
    result = call_tool(mcp_client, conn.headers, "pubml_item", {"item_id": "../../usuarios"})
    assert result["isError"] is True
    assert calls == []


@pytest.mark.parametrize("value", ["..", ".", "a/..", "%2e%2e"])
def test_dot_segments_are_refused_in_unpatterned_path_arguments(mcp_client, mcp_user, recorder, value):
    calls, _ = recorder
    conn = connect(mcp_client, mcp_user)
    result = call_tool(mcp_client, conn.headers, "promos_item", {"mla_id": value})
    assert result["isError"] is True
    assert calls == []


def test_metricas_board_returns_the_board_as_is(mcp_client, mcp_user, recorder):
    _, state = recorder
    state["payload"] = {"rows": [{"producto": "A"}], "kpis": {"ventas": 10}, "total": 1}
    conn = connect(mcp_client, mcp_user)
    data = json.loads(tool_text(call_tool(mcp_client, conn.headers, "metricas_board", {"canal": "ml"})))
    assert data == state["payload"]


def test_product_costs_are_dropped_without_productos_ver_costos(mcp_client, mcp_user, recorder):
    _, state = recorder
    state["payload"] = {
        "total": 1,
        "productos": [
            {
                "item_id": 1,
                "costo": 10.5,
                "moneda_costo": "USD",
                "precio_lista": 99,
                "detalle": {"costo_ars": 1, "costos": {"envio": 2}},
            }
        ],
    }
    conn = connect(mcp_client, mcp_user)
    data = json.loads(tool_text(call_tool(mcp_client, conn.headers, "productos_precios_listas", {})))
    assert data["productos"] == [{"item_id": 1, "precio_lista": 99, "detalle": {}}]


def test_product_costs_stay_with_productos_ver_costos(mcp_client, mcp_user, rol_admin, grant_permiso, recorder):
    _, state = recorder
    state["payload"] = {"total": 1, "productos": [{"item_id": 1, "costo": 10.5, "moneda_costo": "USD"}]}
    grant_permiso(rol_admin, "productos.ver_costos")
    conn = connect(mcp_client, mcp_user)
    data = json.loads(tool_text(call_tool(mcp_client, conn.headers, "productos_precios_listas", {})))
    assert data["productos"] == [{"item_id": 1, "costo": 10.5, "moneda_costo": "USD"}]


def test_oversized_results_are_truncated(mcp_client, mcp_user, recorder, monkeypatch):
    from app.mcp import tools

    _, state = recorder
    monkeypatch.setattr(tools, "MAX_RESULT_BYTES", 2_000)
    state["payload"] = {"total": 500, "items": [{"id": i, "titulo": "x" * 50} for i in range(500)]}
    conn = connect(mcp_client, mcp_user)
    text = tool_text(call_tool(mcp_client, conn.headers, "pubml_items", {}))
    data = json.loads(text)
    assert data["truncated"] is True
    assert 0 < len(data["items"]) < 500
    assert len(text.encode()) <= 2_000 + 200


def test_endpoint_404_is_a_tool_error(mcp_client, mcp_user, recorder):
    _, state = recorder
    state["status"], state["payload"] = 404, {"detail": "No encontrado"}
    conn = connect(mcp_client, mcp_user)
    result = call_tool(mcp_client, conn.headers, "pubml_item", {"item_id": "MLA9"})
    assert result["isError"] is True
    assert "No encontrado" in tool_text(result)


# ---------------------------------------------------------------- logging, rate limit, pruning


def test_every_call_is_logged_without_secrets(mcp_client, mcp_user, recorder, db):
    conn = connect(mcp_client, mcp_user)
    call_tool(mcp_client, conn.headers, "pubml_items", {"q": "y" * 500})
    log = db.query(McpToolCall).one()
    assert log.tool == "pubml_items"
    assert log.status == "ok"
    assert log.usuario_id == mcp_user.id
    assert log.connection_id == db.query(McpConnection).one().id
    assert log.result_bytes > 0
    assert log.duration_ms >= 0
    assert len(log.args_summary["q"]) <= 200
    assert conn.access not in json.dumps(log.args_summary)
    assert db.query(McpConnection).one().last_used_at is not None


def test_per_user_rate_limit(mcp_client, mcp_user, recorder, monkeypatch, db):
    monkeypatch.setattr(settings, "MCP_RATE_LIMIT", "2/minute")
    conn = connect(mcp_client, mcp_user)
    for _ in range(2):
        assert call_tool(mcp_client, conn.headers, "pubml_kpis", {})["isError"] is False
    third = call_tool(mcp_client, conn.headers, "pubml_kpis", {})
    assert third["isError"] is True
    assert "Demasiadas consultas" in tool_text(third)
    assert db.query(McpToolCall).filter(McpToolCall.status == "limited").count() == 1


def test_old_tool_call_logs_are_pruned_on_token_exchange(mcp_client, mcp_user, db):
    old = McpToolCall(
        usuario_id=mcp_user.id,
        connection_id=None,
        tool="viejo",
        args_summary={},
        status="ok",
        result_bytes=1,
        duration_ms=1,
        created_at=datetime.now(UTC) - timedelta(days=181),
    )
    recent = McpToolCall(
        usuario_id=mcp_user.id,
        connection_id=None,
        tool="reciente",
        args_summary={},
        status="ok",
        result_bytes=1,
        duration_ms=1,
        created_at=datetime.now(UTC) - timedelta(days=179),
    )
    db.add_all([old, recent])
    db.commit()
    connect(mcp_client, mcp_user)
    assert [r.tool for r in db.query(McpToolCall).all()] == ["reciente"]


def test_promos_item_applies_the_promociones_tab_filter(mcp_client, mcp_user, recorder):
    """The panel's type / per-type name filter runs in the browser; the tool applies the same rule."""
    calls, state = recorder
    promos = [
        {"promotion_id": "A", "promotion_type": "SMART", "name": "Smart 1"},
        {"promotion_id": "B", "promotion_type": "DEAL", "name": "Día"},
        {"promotion_id": "C", "promotion_type": "DEAL", "payload": {"name": "Semana"}},
        {"promotion_id": "D", "promotion_type": "LIGHTNING", "name": "Relámpago"},
    ]
    state["payload"] = {"mla": "MLA9", "count": 4, "promotions": promos}
    conn = connect(mcp_client, mcp_user)
    arguments = {"mla_id": "MLA9", "promotion_types": ["DEAL", "SMART"], "promotion_names": {"DEAL": ["Semana"]}}
    data = json.loads(tool_text(call_tool(mcp_client, conn.headers, "promos_item", arguments)))
    assert [p["promotion_id"] for p in data["promotions"]] == ["A", "C"]
    assert data["count"] == 2
    assert calls[0]["params"] == {}
    unfiltered = json.loads(tool_text(call_tool(mcp_client, conn.headers, "promos_item", {"mla_id": "MLA9"})))
    assert unfiltered["count"] == 4


def test_ventas_fuera_cargas_reads_the_upload_history(mcp_client, mcp_user, recorder):
    calls, state = recorder
    state["payload"] = []
    conn = connect(mcp_client, mcp_user)
    result = call_tool(mcp_client, conn.headers, "ventas_fuera_cargas", {"dias": 7, "empresa": "1"})
    assert result["isError"] is False, tool_text(result)
    assert calls[0]["path"] == "/api/ventas-fuera-pdf/cargas"
    assert calls[0]["params"]["dias"] == 7
