"""S5, S7: the "Acciones IA" API exactly as the contract (handoffs/mcp-write-contract.md §2, §3): the audit list,
undo from the app (plan -> confirm -> apply through the same guards, origin `app`, client "App") and the kill switch.
Every route answers 403 without mcp.escribir."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.models.mcp_write import McpWriteAction, McpWritePlan
from tests.mcp.conftest import app_login
from tests.mcp.write_fakes import FakeApp

ITEM_KEYS = {
    "id",
    "plan_id",
    "created_at",
    "usuario_id",
    "usuario_nombre",
    "cliente",
    "tool",
    "accion",
    "objetivo",
    "objetivo_label",
    "antes",
    "despues",
    "motivo",
    "resultado",
    "detalle",
    "deshacible",
    "deshecha",
    "undo_of_id",
}


def _action(db, user, **overrides) -> McpWriteAction:
    values = {
        "plan_id": "p_1",
        "usuario_id": user.id,
        "cliente": "Claude",
        "tool": "publicaciones_estado",
        "accion": "estado_pausar",
        "objetivo": "MLA1",
        "objetivo_label": "MLA1 - Auriculares",
        "antes": {"estado": "active"},
        "despues": {"estado": "paused"},
        "motivo": "sin stock",
        "resultado": "ok",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    action = McpWriteAction(**values)
    db.add(action)
    db.commit()
    return action


@pytest.fixture()
def headers(mcp_client, writer):
    return app_login(mcp_client, writer)


@pytest.fixture()
def fake(db, monkeypatch):
    return FakeApp(db=db).install(monkeypatch)


# ---------------------------------------------------------------- permission


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/admin/mcp/acciones", None),
        ("post", "/api/admin/mcp/acciones/deshacer/plan", {"accion_ids": [1], "motivo": "x"}),
        ("post", "/api/admin/mcp/acciones/deshacer/aplicar", {"plan_id": "p", "confirm_token": "t"}),
        ("get", "/api/admin/mcp/escritura", None),
        ("put", "/api/admin/mcp/escritura", {"habilitado": True}),
    ],
)
def test_every_route_needs_mcp_escribir(mcp_client, mcp_user, method, path, body):
    headers = app_login(mcp_client, mcp_user)  # mcp.conectar only
    kwargs = {"headers": headers} | ({"json": body} if body is not None else {})
    assert getattr(mcp_client, method)(path, **kwargs).status_code == 403
    assert getattr(mcp_client, method)(path, **({"json": body} if body else {})).status_code == 401


# ---------------------------------------------------------------- list


def test_list_shape_newest_first_and_filters(mcp_client, headers, writer, db):
    old = _action(db, writer, created_at=datetime.now(UTC) - timedelta(days=3), objetivo="MLA0")
    new = _action(
        db,
        writer,
        plan_id="p_2",
        tool="precio_lista_cambiar",
        accion="precio_lista",
        objetivo="101",
        antes={"precio": 100000.0},
        despues={"precio": 95000.0},
        resultado="rechazada",
        detalle="movió",
    )
    r = mcp_client.get("/api/admin/mcp/acciones", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [i["id"] for i in body["items"]] == [new.id, old.id]
    item = body["items"][0]
    assert set(item) == ITEM_KEYS
    assert item["usuario_nombre"] == writer.nombre
    assert item["created_at"].endswith("Z")
    assert (item["antes"], item["despues"]) == ({"precio": 100000.0}, {"precio": 95000.0})
    assert (item["resultado"], item["deshacible"], item["deshecha"], item["undo_of_id"]) == (
        "rechazada",
        False,
        False,
        None,
    )
    assert body["items"][1]["deshacible"] is True

    def ids(**params):
        return [
            i["id"] for i in mcp_client.get("/api/admin/mcp/acciones", params=params, headers=headers).json()["items"]
        ]

    assert ids(resultado="ok") == [old.id]
    assert ids(tool="precio_lista_cambiar") == [new.id]
    assert ids(plan_id="p_1") == [old.id]
    assert ids(cliente="Claude") == [new.id, old.id]
    assert ids(usuario_id=writer.id + 1000) == []
    today = datetime.now(UTC).date()
    assert ids(desde=today.isoformat()) == [new.id]
    assert ids(hasta=(today - timedelta(days=2)).isoformat()) == [old.id]
    assert ids(limit=1, offset=1) == [old.id]
    assert mcp_client.get("/api/admin/mcp/acciones", params={"limit": 101}, headers=headers).status_code == 422


# ---------------------------------------------------------------- kill switch


def test_kill_switch_get_put_and_env_override(mcp_client, headers, db, monkeypatch):
    monkeypatch.setattr(settings, "MCP_WRITE_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    assert mcp_client.get("/api/admin/mcp/escritura", headers=headers).json() == {
        "habilitado": False,
        "fuente": "default",
    }
    r = mcp_client.put("/api/admin/mcp/escritura", json={"habilitado": True}, headers=headers)
    assert r.status_code == 200 and r.json() == {"habilitado": True, "fuente": "db"}
    assert mcp_client.get("/api/admin/mcp/escritura", headers=headers).json() == {"habilitado": True, "fuente": "db"}
    monkeypatch.setattr(settings, "MCP_WRITE_KILL_SWITCH", True)
    assert mcp_client.get("/api/admin/mcp/escritura", headers=headers).json() == {
        "habilitado": False,
        "fuente": "kill_switch",
    }
    r = mcp_client.put("/api/admin/mcp/escritura", json={"habilitado": True}, headers=headers)
    assert r.json() == {"habilitado": False, "fuente": "kill_switch"}


# ---------------------------------------------------------------- undo from the app


def test_undo_from_the_app_plan_then_apply(mcp_client, headers, writer, db, fake, write_enabled):
    fake.estados["MLA1"] = "paused"
    action = _action(db, writer)
    r = mcp_client.post(
        "/api/admin/mcp/acciones/deshacer/plan",
        json={"accion_ids": [action.id], "motivo": "me equivoqué"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    planned = r.json()
    assert set(planned) == {"plan_id", "confirm_token", "expires_at", "filas"}
    assert planned["plan_id"].startswith("p_") and planned["expires_at"].endswith("Z")
    assert planned["filas"] == [
        {
            "accion_id": action.id,
            "objetivo": "MLA1",
            "objetivo_label": "MLA1 - Auriculares",
            "accion": "estado_activar",
            "antes": {"estado": "paused"},
            "despues": {"estado": "active"},
            "estado": "lista",
            "detalle": None,
        }
    ]
    stored = db.query(McpWritePlan).one()
    assert (stored.origen, stored.cliente, stored.connection_id, stored.tool) == ("app", "App", None, "accion_deshacer")

    body = {"plan_id": planned["plan_id"], "confirm_token": planned["confirm_token"]}
    r = mcp_client.post("/api/admin/mcp/acciones/deshacer/aplicar", json=body, headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()
    [row] = result["resultados"]
    assert set(result) == {"plan_id", "resultados"}
    assert set(row) == {"accion_id", "nueva_accion_id", "resultado", "detalle"}
    assert (row["accion_id"], row["resultado"], row["detalle"]) == (action.id, "ok", None)
    assert fake.writes[-1]["body"] == {"status": "active"}
    db.expire_all()
    new = db.get(McpWriteAction, row["nueva_accion_id"])
    assert (new.cliente, new.undo_of_id, new.motivo, new.connection_id) == ("App", action.id, "me equivoqué", None)
    assert db.get(McpWriteAction, action.id).deshecha_por_id == new.id

    r = mcp_client.post("/api/admin/mcp/acciones/deshacer/aplicar", json=body, headers=headers)
    assert r.status_code == 409 and "ya se aplicó" in r.json()["error"]["message"]
    assert len(fake.writes) == 1

    listed = mcp_client.get("/api/admin/mcp/acciones", headers=headers).json()["items"]
    by_id = {i["id"]: i for i in listed}
    assert by_id[action.id]["deshecha"] is True and by_id[new.id]["undo_of_id"] == action.id


def test_undo_plan_by_plan_id_lists_blocked_rows(mcp_client, headers, writer, db, fake, write_enabled):
    fake.estados.update({"MLA1": "paused", "MLA2": "active"})
    first = _action(db, writer)
    second = _action(db, writer, objetivo="MLA2")  # someone activated it again since
    third = _action(db, writer, objetivo="MLA3", resultado="rechazada")
    r = mcp_client.post(
        "/api/admin/mcp/acciones/deshacer/plan", json={"plan_id": "p_1", "motivo": "x"}, headers=headers
    )
    filas = {f["accion_id"]: f for f in r.json()["filas"]}
    assert filas[first.id]["estado"] == "lista"
    assert filas[second.id]["estado"] == "bloqueada" and "cambió desde la acción" in filas[second.id]["detalle"]
    assert filas[third.id]["estado"] == "bloqueada"


def test_undo_tokens_used_expired_or_foreign_answer_409(
    mcp_client, headers, writer, db, fake, write_enabled, rol_admin
):
    fake.estados["MLA1"] = "paused"
    action = _action(db, writer)
    planned = mcp_client.post(
        "/api/admin/mcp/acciones/deshacer/plan", json={"accion_ids": [action.id], "motivo": "x"}, headers=headers
    ).json()
    body = {"plan_id": planned["plan_id"], "confirm_token": planned["confirm_token"]}
    assert (
        mcp_client.post(
            "/api/admin/mcp/acciones/deshacer/aplicar", json={**body, "confirm_token": "nope"}, headers=headers
        ).status_code
        == 409
    )
    stored = db.query(McpWritePlan).one()
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert mcp_client.post("/api/admin/mcp/acciones/deshacer/aplicar", json=body, headers=headers).status_code == 409
    assert fake.writes == []


def test_undo_from_the_app_answers_503_when_writes_are_off(mcp_client, headers, writer, db, fake, monkeypatch):
    monkeypatch.setattr(settings, "MCP_WRITE_KILL_SWITCH", True)
    action = _action(db, writer)
    r = mcp_client.post(
        "/api/admin/mcp/acciones/deshacer/plan", json={"accion_ids": [action.id], "motivo": "x"}, headers=headers
    )
    assert r.status_code == 503
    r = mcp_client.post(
        "/api/admin/mcp/acciones/deshacer/aplicar", json={"plan_id": "p", "confirm_token": "t"}, headers=headers
    )
    assert r.status_code == 503


def test_undo_plan_needs_a_motivo_and_a_target(mcp_client, headers, write_enabled):
    assert (
        mcp_client.post("/api/admin/mcp/acciones/deshacer/plan", json={"accion_ids": [1]}, headers=headers).status_code
        == 422
    )
    assert (
        mcp_client.post("/api/admin/mcp/acciones/deshacer/plan", json={"motivo": "x"}, headers=headers).status_code
        == 422
    )
