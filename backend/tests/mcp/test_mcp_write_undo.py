"""S7: undo of every family through `accion_deshacer` (same guards, plan -> confirm), blocked when the target changed
since the action or it was already undone, undo of an undo, and the exemption from ±10% / limits / band."""

from __future__ import annotations

import pytest

from app.mcp.write import criteria
from app.models.mcp_write import McpWriteAction
from tests.mcp.conftest import WRITE_SCOPE, connect, write_call
from tests.mcp.write_fakes import promo

PRECIO = {"max_items": 10, "max_cambio_pct": 10, "min_markup_pct": 10}
PROMO = {"max_items": 10, "min_markup_pct": 10}


@pytest.fixture()
def conn(mcp_client, writer, write_enabled, band_ok):
    return connect(mcp_client, writer, scope=WRITE_SCOPE)


def run(client, conn, tool: str, **args) -> dict:
    """Plan then apply; returns the apply result."""
    result, planned = write_call(client, conn.headers, tool, {"modo": "plan", "motivo": "orden", **args})
    assert result["isError"] is False, planned
    assert planned["plan_id"], planned
    result, applied = write_call(
        client,
        conn.headers,
        tool,
        {"modo": "aplicar", "plan_id": planned["plan_id"], "confirm_token": planned["confirm_token"]},
    )
    assert result["isError"] is False, applied
    return applied


def undo_plan(client, conn, **args) -> dict:
    result, planned = write_call(
        client, conn.headers, "accion_deshacer", {"modo": "plan", "motivo": "deshacer", **args}
    )
    assert result["isError"] is False, planned
    return planned


def undo_apply(client, conn, planned: dict) -> dict:
    result, applied = write_call(
        client,
        conn.headers,
        "accion_deshacer",
        {"modo": "aplicar", "plan_id": planned["plan_id"], "confirm_token": planned["confirm_token"]},
    )
    assert result["isError"] is False, applied
    return applied


def test_undo_a_list_price_restores_price_and_cuotas(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0, c3=1100.0)
    applied = run(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)
    action_id = applied["resultados"][0]["nueva_accion_id"]
    pricing = fake_app.pricing(101)
    pricing.precio_3_cuotas = 1045.0  # what the recalculation left
    db.commit()

    planned = undo_plan(mcp_client, conn, accion_ids=[action_id])
    [fila] = planned["filas"]
    assert (fila["accion_id"], fila["accion"], fila["estado"]) == (action_id, "precio_lista", "lista")
    assert fila["antes"]["precio"] == 950.0 and fila["despues"]["precio"] == 1000.0
    fake_app.writes.clear()
    applied = undo_apply(mcp_client, conn, planned)
    [row] = applied["resultados"]
    assert row["resultado"] == "ok" and row["accion_id"] == action_id
    assert [(w["path"], w["params"]) for w in fake_app.writes] == [
        (
            "/api/precios/set-rapido",
            {"item_id": 101, "precio": 1000.0, "recalcular_cuotas": "false", "lista_tipo": "web"},
        ),
        ("/api/precios/set-cuota", {"item_id": 101, "tipo_cuota": "3", "precio": 1100.0, "lista_tipo": "web"}),
    ]
    pricing = fake_app.pricing(101)
    assert float(pricing.precio_lista_ml) == 1000.0 and float(pricing.precio_3_cuotas) == 1100.0
    db.expire_all()
    new = db.query(McpWriteAction).get(row["nueva_accion_id"])
    assert (new.undo_of_id, new.tool, new.accion, new.resultado, new.motivo) == (
        action_id,
        "accion_deshacer",
        "precio_lista",
        "ok",
        "deshacer",
    )
    assert db.query(McpWriteAction).get(action_id).deshecha_por_id == new.id


def test_undo_is_blocked_when_the_value_changed_since_the_action(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0)
    applied = run(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)
    pricing = fake_app.pricing(101)
    pricing.precio_lista_ml = 970.0
    db.commit()
    planned = undo_plan(mcp_client, conn, accion_ids=[applied["resultados"][0]["nueva_accion_id"]])
    assert planned["plan_id"] is None
    assert planned["filas"][0]["estado"] == "bloqueada"
    assert planned["filas"][0]["detalle"] == "el precio cambió desde la acción"


def test_already_undone_is_blocked_and_undo_of_an_undo_is_allowed(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0)
    applied = run(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)
    original = applied["resultados"][0]["nueva_accion_id"]
    undone = undo_apply(mcp_client, conn, undo_plan(mcp_client, conn, accion_ids=[original]))
    undo_id = undone["resultados"][0]["nueva_accion_id"]

    again = undo_plan(mcp_client, conn, accion_ids=[original])
    assert (again["filas"][0]["estado"], again["filas"][0]["detalle"]) == ("bloqueada", "ya deshecha")

    redo = undo_apply(mcp_client, conn, undo_plan(mcp_client, conn, accion_ids=[undo_id]))
    assert redo["resultados"][0]["resultado"] == "ok"
    assert float(fake_app.pricing(101).precio_lista_ml) == 950.0


def test_undo_is_exempt_from_limits_and_band_but_not_from_the_kill_switch(mcp_client, conn, db, fake_app, monkeypatch):
    from app.services.ml_publications import settings_store

    fake_app.product(101, 1000.0)
    applied = run(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)
    monkeypatch.setattr(criteria, "band_for", lambda db, target: criteria.UNAVAILABLE)
    planned = undo_plan(mcp_client, conn, accion_ids=[applied["resultados"][0]["nueva_accion_id"]])  # no limites
    assert planned["filas"][0]["estado"] == "lista"
    settings_store.set_setting("mcp_write.enabled", False, "test", session=db)
    db.commit()
    result, text = write_call(
        mcp_client,
        conn.headers,
        "accion_deshacer",
        {"modo": "aplicar", "plan_id": planned["plan_id"], "confirm_token": planned["confirm_token"]},
    )
    assert result["isError"] is True and text.startswith("deshabilitada")


def test_undo_pause_activates_again(mcp_client, conn, db, fake_app):
    fake_app.estados["MLA1"] = "active"
    applied = run(
        mcp_client, conn, "publicaciones_estado", status="paused", item_ids=["MLA1"], limites={"max_items": 1}
    )
    planned = undo_plan(mcp_client, conn, accion_ids=[applied["resultados"][0]["nueva_accion_id"]])
    assert planned["filas"][0]["accion"] == "estado_activar"
    undo_apply(mcp_client, conn, planned)
    assert fake_app.writes[-1]["body"] == {"status": "active"}
    assert fake_app.estados["MLA1"] == "active"


def test_undo_promo_aplicar_removes_it(mcp_client, conn, db, fake_app):
    fake_app.promos["MLA1"] = [promo("P1", "SMART", "candidate", 900.0)]
    items = [{"mla": "MLA1", "promotion_id": "P1", "promotion_type": "SMART"}]
    applied = run(mcp_client, conn, "promo_aplicar", items=items, limites=PROMO)
    planned = undo_plan(mcp_client, conn, accion_ids=[applied["resultados"][0]["nueva_accion_id"]])
    assert planned["filas"][0]["accion"] == "promo_quitar"
    undo_apply(mcp_client, conn, planned)
    assert (fake_app.writes[-1]["method"], fake_app.writes[-1]["params"]) == (
        "DELETE",
        {"promotion_type": "SMART", "promotion_id": "P1"},
    )


def test_undo_promo_quitar_reenrolls_only_while_ml_offers_it(mcp_client, conn, db, fake_app):
    fake_app.promos["MLA1"] = [promo("P1", "SMART", "started", 900.0)]
    items = [{"mla": "MLA1", "promotion_id": "P1", "promotion_type": "SMART"}]
    applied = run(mcp_client, conn, "promo_quitar", items=items, limites=PROMO)
    action_id = applied["resultados"][0]["nueva_accion_id"]

    fake_app.promos["MLA1"] = []  # ML stopped offering it
    planned = undo_plan(mcp_client, conn, accion_ids=[action_id])
    assert (planned["filas"][0]["estado"], planned["filas"][0]["detalle"]) == ("bloqueada", "ML ya no ofrece esa promo")

    fake_app.promos["MLA1"] = [promo("P1", "SMART", "candidate", 900.0)]
    planned = undo_plan(mcp_client, conn, accion_ids=[action_id])
    assert planned["filas"][0]["accion"] == "promo_aplicar"
    undo_apply(mcp_client, conn, planned)
    assert fake_app.writes[-1]["body"]["precio_visto"] == 900.0


def test_undo_cuota_and_mayorista_and_markup_masivo(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0, c6=1200.0)
    fake_app.product(102, 1000.0)
    fake_app.precio_markup[102] = 1050.0
    fake_app.tramos["MLA1"] = [{"id": 7, "cantidad_minima": 10, "precio_unitario": 100.0}]
    ids = [
        run(
            mcp_client,
            conn,
            "precio_cuotas_cambiar",
            items=[{"item_id": 101, "tipo_cuota": "6", "precio": 1150}],
            limites=PRECIO,
        ),
        run(
            mcp_client,
            conn,
            "precio_mayorista_cambiar",
            mla="MLA1",
            tramos=[{"cantidad_minima": 10, "precio_unitario": 95}],
            limites=PRECIO,
        ),
        run(mcp_client, conn, "precios_markup_masivo", item_ids=[102], markup_objetivo=20, limites=PRECIO),
    ]
    action_ids = [r["resultados"][0]["nueva_accion_id"] for r in ids]
    planned = undo_plan(mcp_client, conn, accion_ids=action_ids)
    assert [f["accion"] for f in planned["filas"]] == ["precio_cuota", "precio_mayorista", "precio_lista"]
    assert all(f["estado"] == "lista" for f in planned["filas"])
    applied = undo_apply(mcp_client, conn, planned)
    assert [r["resultado"] for r in applied["resultados"]] == ["ok", "ok", "ok"]
    assert float(fake_app.pricing(101).precio_6_cuotas) == 1200.0
    assert fake_app.tramos["MLA1"][0]["precio_unitario"] == 100.0
    assert fake_app.writes_to("/sync")[-1]["path"] == "/api/pxq/MLA1/sync"
    assert float(fake_app.pricing(102).precio_lista_ml) == 1000.0


def test_mcp_undo_only_reaches_your_own_actions(mcp_client, conn, db, fake_app, active_user):
    other = McpWriteAction(
        plan_id="p_other",
        usuario_id=active_user.id,
        cliente="Claude",
        tool="publicaciones_estado",
        accion="estado_pausar",
        objetivo="MLA9",
        motivo="x",
        resultado="ok",
    )
    db.add(other)
    db.commit()
    result, text = write_call(
        mcp_client, conn.headers, "accion_deshacer", {"modo": "plan", "motivo": "x", "accion_ids": [other.id]}
    )
    assert result["isError"] is True and "no hay acciones" in text


def test_acciones_recientes_lists_your_actions(mcp_client, conn, db, fake_app):
    fake_app.estados["MLA1"] = "active"
    run(mcp_client, conn, "publicaciones_estado", status="paused", item_ids=["MLA1"], limites={"max_items": 1})
    result, body = write_call(mcp_client, conn.headers, "acciones_recientes", {})
    assert result["isError"] is False
    assert body["total"] == 1
    item = body["items"][0]
    assert (item["accion"], item["objetivo"], item["resultado"], item["deshacible"], item["deshecha"]) == (
        "estado_pausar",
        "MLA1",
        "ok",
        True,
        False,
    )
