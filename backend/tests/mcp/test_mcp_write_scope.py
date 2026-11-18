"""S6: the `pricing.write` scope. Only a user holding mcp.escribir gets it (downgraded to read at consent otherwise),
read tokens never see nor call write tools, and read tools keep working with either token."""

from __future__ import annotations

from app.models.mcp_oauth import McpConnection, McpToolCall
from app.models.permiso import Permiso, RolPermisoBase
from tests.mcp.conftest import (
    WRITE_SCOPE,
    app_login,
    call_tool,
    connect,
    decide,
    exchange_code,
    pkce_pair,
    redirect_query,
    rpc,
    start_authorize,
    tool_text,
)

WRITE_TOOLS = {
    "promo_aplicar",
    "promo_quitar",
    "promos_aplicar_mejoras",
    "publicaciones_estado",
    "precio_lista_cambiar",
    "precios_markup_masivo",
    "precio_cuotas_cambiar",
    "precio_mayorista_cambiar",
    "acciones_recientes",
    "accion_deshacer",
}


def _revoke(db, rol, codigo: str) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).one()
    db.query(RolPermisoBase).filter(RolPermisoBase.rol_id == rol.id, RolPermisoBase.permiso_id == permiso.id).delete()
    db.commit()


def _consent(client, user, scope: str) -> dict:
    _, challenge = pkce_pair()
    req = start_authorize(client, challenge, scope=scope)
    r = client.get(f"/api/oauth/requests/{req}", headers=app_login(client, user))
    assert r.status_code == 200, r.text
    return r.json()


def test_consent_card_says_write_when_asked_and_the_user_may_write(mcp_client, writer):
    body = _consent(mcp_client, writer, WRITE_SCOPE)
    assert body["escritura_pedida"] is True
    assert body["escritura"] is True
    assert body["scope"] == "pricing.read pricing.write"


def test_consent_card_says_read_only_when_the_user_lacks_mcp_escribir(mcp_client, mcp_user):
    body = _consent(mcp_client, mcp_user, WRITE_SCOPE)
    assert body["escritura_pedida"] is True
    assert body["escritura"] is False


def test_consent_card_for_a_read_request_is_unchanged(mcp_client, writer):
    body = _consent(mcp_client, writer, "pricing.read")
    assert body["escritura_pedida"] is False
    assert body["escritura"] is False
    assert body["scope"] == "pricing.read"


def test_a_user_without_mcp_escribir_gets_a_read_token(mcp_client, mcp_user, db):
    verifier, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge, scope=WRITE_SCOPE)
    code = redirect_query(decide(mcp_client, req, app_login(mcp_client, mcp_user)).json()["redirect_to"])["code"]
    r = exchange_code(mcp_client, code, verifier)
    assert r.json()["scope"] == "pricing.read"
    assert db.query(McpConnection).one().scope == "pricing.read"


def test_a_writer_gets_a_write_token_and_write_implies_read(mcp_client, writer, db):
    verifier, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge, scope="pricing.write")
    code = redirect_query(decide(mcp_client, req, app_login(mcp_client, writer)).json()["redirect_to"])["code"]
    r = exchange_code(mcp_client, code, verifier)
    assert r.json()["scope"] == "pricing.read pricing.write"
    assert db.query(McpConnection).one().scope == "pricing.read pricing.write"


def _tools(client, headers) -> dict[str, dict]:
    r = rpc(client, headers, "tools/list")
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()["result"]["tools"]}


def test_a_read_token_does_not_list_write_tools(mcp_client, writer):
    conn = connect(mcp_client, writer)
    listed = _tools(mcp_client, conn.headers)
    assert not WRITE_TOOLS & set(listed)
    assert "pubml_items" in listed
    assert listed["pubml_items"]["annotations"]["readOnlyHint"] is True


def test_a_write_token_lists_write_tools_with_annotations(mcp_client, writer):
    conn = connect(mcp_client, writer, scope=WRITE_SCOPE)
    listed = _tools(mcp_client, conn.headers)
    assert WRITE_TOOLS <= set(listed)
    for name in WRITE_TOOLS - {"acciones_recientes"}:
        annotations = listed[name]["annotations"]
        assert annotations["readOnlyHint"] is False, name
        assert annotations["openWorldHint"] is True, name
        assert annotations["idempotentHint"] is True, name
        assert "modo" in listed[name]["inputSchema"]["properties"], name
    destructive = {n for n in WRITE_TOOLS - {"acciones_recientes"} if listed[n]["annotations"]["destructiveHint"]}
    assert destructive == WRITE_TOOLS - {"acciones_recientes", "promo_aplicar", "promos_aplicar_mejoras"}
    assert listed["acciones_recientes"]["annotations"]["readOnlyHint"] is True
    assert "limites" in listed["precio_lista_cambiar"]["inputSchema"]["properties"]
    assert "pubml_items" in listed


def test_a_read_token_cannot_call_a_write_tool(mcp_client, writer, db, write_enabled):
    conn = connect(mcp_client, writer)
    result = call_tool(mcp_client, conn.headers, "publicaciones_estado", {"modo": "plan"})
    assert result["isError"] is True
    assert "denegada" in tool_text(result)
    assert "solo lectura" in tool_text(result)
    log = db.query(McpToolCall).one()
    assert (log.tool, log.status) == ("publicaciones_estado", "denied")


def test_a_write_token_is_denied_once_the_user_loses_mcp_escribir(mcp_client, writer, rol_admin, db, write_enabled):
    conn = connect(mcp_client, writer, scope=WRITE_SCOPE)
    _revoke(db, rol_admin, "mcp.escribir")
    result = call_tool(
        mcp_client,
        conn.headers,
        "publicaciones_estado",
        {"modo": "plan", "status": "paused", "item_ids": ["MLA1"], "motivo": "x", "limites": {"max_items": 1}},
    )
    assert result["isError"] is True
    assert "denegada" in tool_text(result) and "mcp.escribir" in tool_text(result)
    assert db.query(McpToolCall).one().status == "denied"


def test_read_tools_work_with_a_write_token(mcp_client, writer, fake_app):
    conn = connect(mcp_client, writer, scope=WRITE_SCOPE)
    result = call_tool(mcp_client, conn.headers, "pubml_items", {})
    assert result["isError"] is False
    assert fake_app.gets[0][0] == "/api/ml-publications/view/items"


def test_server_instructions_explain_plan_confirm_and_limits(mcp_client, writer):
    conn = connect(mcp_client, writer, scope=WRITE_SCOPE)
    r = rpc(
        mcp_client,
        conn.headers,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    )
    instructions = r.json()["result"]["instructions"]
    assert "Read-only" not in instructions
    assert "plan" in instructions and "aplicar" in instructions and "limites" in instructions
