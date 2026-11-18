"""S1, S4, S7: plan -> confirm token -> apply for every tool family, through the real loopback contract (stubbed
app endpoints, invented data), the single-use token (reuse returns the stored result with zero writes; expired,
foreign and wrong tokens refused), a value that moved between plan and apply, and the audit rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.mcp_oauth import McpToolCall
from app.models.mcp_write import McpWriteAction, McpWritePlan
from tests.mcp.conftest import WRITE_SCOPE, connect, write_call
from tests.mcp.write_fakes import promo

PRECIO = {"max_items": 10, "max_cambio_pct": 10, "min_markup_pct": 10}
PROMO = {"max_items": 10, "min_markup_pct": 10}


@pytest.fixture()
def conn(mcp_client, writer, write_enabled, band_ok):
    return connect(mcp_client, writer, scope=WRITE_SCOPE)


def plan(client, conn, tool: str, **args) -> dict:
    result, body = write_call(client, conn.headers, tool, {"modo": "plan", "motivo": "pedido de Alejandro", **args})
    assert result["isError"] is False, body
    return body


def apply(client, conn, tool: str, planned: dict) -> tuple[dict, dict | str]:
    return write_call(
        client,
        conn.headers,
        tool,
        {"modo": "aplicar", "plan_id": planned["plan_id"], "confirm_token": planned["confirm_token"]},
    )


# ---------------------------------------------------------------- list price + token lifecycle


def test_precio_lista_plan_then_apply(mcp_client, conn, writer, db, fake_app):
    fake_app.product(101, 1000.0, c3=1100.0)
    planned = plan(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)
    [fila] = planned["filas"]
    assert fila["estado"] == "lista"
    assert fila["objetivo"] == "101" and fila["objetivo_label"] == "COD101 - Producto 101"
    assert fila["antes"]["precio"] == 1000.0 and fila["antes"]["cuota_3"] == 1100.0
    assert fila["despues"] == {"lista": "web", "precio": 950.0}
    assert fila["cambios_pct"] == [-5.0] and fila["markup_previsto"] == 30.0
    assert "datos" not in fila
    assert planned["siguiente_paso"]
    stored = db.query(McpWritePlan).one()
    assert stored.confirm_token_hash != planned["confirm_token"] and len(stored.confirm_token_hash) == 64
    assert stored.used_at is None and stored.usuario_id == writer.id and stored.origen == "mcp"
    assert stored.tool == "precio_lista_cambiar" and stored.limites["max_items"] == 10
    assert fake_app.writes == []  # planning writes nothing

    _, result = apply(mcp_client, conn, "precio_lista_cambiar", planned)
    assert result["resultados"][0]["resultado"] == "ok"
    [write] = fake_app.writes
    assert write["path"] == "/api/precios/set-rapido"
    assert write["params"] == {"item_id": 101, "precio": 950.0, "recalcular_cuotas": "true", "lista_tipo": "web"}
    assert float(fake_app.pricing(101).precio_lista_ml) == 950.0
    action = db.query(McpWriteAction).one()
    assert (action.accion, action.objetivo, action.resultado, action.tool) == (
        "precio_lista",
        "101",
        "ok",
        "precio_lista_cambiar",
    )
    assert action.antes["precio"] == 1000.0 and action.despues["precio"] == 950.0
    assert action.motivo == "pedido de Alejandro" and action.cliente == "ChatGPT" and action.usuario_id == writer.id
    db.expire_all()
    assert db.query(McpWritePlan).one().used_at is not None
    assert db.query(McpWritePlan).one().resultado["resultados"][0]["resultado"] == "ok"
    logged = db.query(McpToolCall).order_by(McpToolCall.id.desc()).first()
    assert logged.args_summary["confirm_token"] == "***"


def test_a_used_token_returns_the_stored_result_and_writes_nothing(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0)
    planned = plan(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)
    _, first = apply(mcp_client, conn, "precio_lista_cambiar", planned)
    result, again = apply(mcp_client, conn, "precio_lista_cambiar", planned)
    assert result["isError"] is False
    assert again["resultados"] == first["resultados"]
    assert "ya se había aplicado" in again["aviso"]
    assert len(fake_app.writes) == 1
    assert db.query(McpWriteAction).count() == 1


def test_expired_wrong_and_foreign_tokens_are_refused(mcp_client, conn, writer, db, fake_app):
    fake_app.product(101, 1000.0)
    planned = plan(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)

    result, text = apply(mcp_client, conn, "precio_lista_cambiar", {**planned, "confirm_token": "x" * 43})
    assert result["isError"] and "confirm_token inválido" in text

    other = connect(mcp_client, writer, scope=WRITE_SCOPE)  # same person, another connection
    result, text = apply(mcp_client, other, "precio_lista_cambiar", planned)
    assert result["isError"] and "otra persona, conexión" in text

    result, text = apply(mcp_client, conn, "precio_cuotas_cambiar", planned)  # another tool
    assert result["isError"] and "otra persona, conexión o herramienta" in text

    stored = db.query(McpWritePlan).one()
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    result, text = apply(mcp_client, conn, "precio_lista_cambiar", planned)
    assert result["isError"] and "venció" in text

    assert fake_app.writes == []
    assert db.query(McpWriteAction).count() == 0
    db.expire_all()
    assert db.query(McpWritePlan).one().used_at is None


def test_a_price_moved_between_plan_and_apply_rejects_only_that_row(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0)
    fake_app.product(102, 2000.0)
    planned = plan(
        mcp_client,
        conn,
        "precio_lista_cambiar",
        items=[{"item_id": 101, "precio": 950}, {"item_id": 102, "precio": 2100}],
        limites=PRECIO,
    )
    pricing = fake_app.pricing(101)
    pricing.precio_lista_ml = 990.0  # someone changed it in the app
    db.commit()
    _, result = apply(mcp_client, conn, "precio_lista_cambiar", planned)
    first, second = result["resultados"]
    assert (first["resultado"], first["detalle"]) == ("rechazada", "el precio cambió desde el plan")
    assert second["resultado"] == "ok"
    assert [w["params"]["item_id"] for w in fake_app.writes] == [102]
    assert {a.objetivo: a.resultado for a in db.query(McpWriteAction).all()} == {"101": "rechazada", "102": "ok"}


def test_duplicate_targets_are_refused(mcp_client, conn, fake_app):
    fake_app.product(101, 1000.0)
    result, text = write_call(
        mcp_client,
        conn.headers,
        "precio_lista_cambiar",
        {
            "modo": "plan",
            "motivo": "x",
            "limites": PRECIO,
            "items": [{"item_id": 101, "precio": 950}, {"item_id": 101, "precio": 960}],
        },
    )
    assert result["isError"] and "repetido" in text


# ---------------------------------------------------------------- other families


def test_cuotas_plan_then_apply(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0, c6=1200.0)
    planned = plan(
        mcp_client,
        conn,
        "precio_cuotas_cambiar",
        items=[{"item_id": 101, "tipo_cuota": "6", "precio": 1150}],
        limites=PRECIO,
    )
    [fila] = planned["filas"]
    assert fila["objetivo"] == "101:web:6" and fila["antes"]["precio"] == 1200.0
    _, result = apply(mcp_client, conn, "precio_cuotas_cambiar", planned)
    assert result["resultados"][0]["resultado"] == "ok"
    [write] = fake_app.writes
    assert write["params"] == {"item_id": 101, "tipo_cuota": "6", "precio": 1150.0, "lista_tipo": "web"}
    assert float(fake_app.pricing(101).precio_6_cuotas) == 1150.0
    assert db.query(McpWriteAction).one().accion == "precio_cuota"


def test_markup_masivo_blocks_over_ten_percent_and_applies_the_rest(mcp_client, conn, db, fake_app):
    fake_app.product(101, 1000.0)
    fake_app.product(102, 1000.0)
    fake_app.precio_markup.update({101: 1120.0, 102: 1050.0})
    planned = plan(mcp_client, conn, "precios_markup_masivo", item_ids=[101, 102], markup_objetivo=25, limites=PRECIO)
    first, second = planned["filas"]
    assert first["estado"] == "bloqueada" and first["detalle"].startswith("tope_10")
    assert second["estado"] == "lista" and second["despues"]["precio"] == 1050.0 and second["markup_previsto"] == 25
    _, result = apply(mcp_client, conn, "precios_markup_masivo", planned)
    assert [r["resultado"] for r in result["resultados"]] == ["bloqueada", "ok"]
    [write] = fake_app.writes
    assert write["body"] == {"markup_objetivo": 25.0, "pricelist_id": 4, "recalcular_cuotas": True, "item_ids": [102]}
    assert db.query(McpWriteAction).one().objetivo == "102"  # plan-time blocked rows stay in the plan only


def test_promo_aplicar_and_quitar(mcp_client, conn, db, fake_app):
    fake_app.promos["MLA1"] = [promo("P1", "SMART", "candidate", 900.0, markup_sell_in_out=22.0)]
    planned = plan(
        mcp_client,
        conn,
        "promo_aplicar",
        items=[{"mla": "MLA1", "promotion_id": "P1", "promotion_type": "SMART"}],
        limites=PROMO,
    )
    [fila] = planned["filas"]
    assert fila["despues"] == {"promotion_id": "P1", "promotion_type": "SMART", "precio": 900.0}
    assert fila["markup_previsto"] == 22.0
    _, result = apply(mcp_client, conn, "promo_aplicar", planned)
    assert result["resultados"][0]["resultado"] == "ok"
    [write] = fake_app.writes
    assert (write["method"], write["path"]) == ("POST", "/api/promociones/item/MLA1")
    assert write["body"]["precio_visto"] == 900.0 and "deal_price" not in write["body"]

    planned = plan(
        mcp_client,
        conn,
        "promo_quitar",
        items=[{"mla": "MLA1", "promotion_id": "P1", "promotion_type": "SMART"}],
        limites=PROMO,
    )
    assert planned["filas"][0]["antes"]["promotion_id"] == "P1"
    _, result = apply(mcp_client, conn, "promo_quitar", planned)
    assert result["resultados"][0]["resultado"] == "ok"
    assert (fake_app.writes[-1]["method"], fake_app.writes[-1]["params"]) == (
        "DELETE",
        {"promotion_type": "SMART", "promotion_id": "P1"},
    )
    assert [a.accion for a in db.query(McpWriteAction).order_by(McpWriteAction.id)] == ["promo_aplicar", "promo_quitar"]


def test_promo_whose_ml_price_moved_is_rejected(mcp_client, conn, db, fake_app):
    fake_app.promos["MLA1"] = [promo("P1", "SMART", "candidate", 900.0)]
    planned = plan(
        mcp_client,
        conn,
        "promo_aplicar",
        items=[{"mla": "MLA1", "promotion_id": "P1", "promotion_type": "SMART"}],
        limites=PROMO,
    )
    fake_app.promos["MLA1"][0]["price"] = 850.0
    _, result = apply(mcp_client, conn, "promo_aplicar", planned)
    assert (result["resultados"][0]["resultado"], result["resultados"][0]["detalle"]) == (
        "rechazada",
        "el precio cambió desde el plan",
    )
    assert fake_app.writes == []


def test_pause_plan_then_apply(mcp_client, conn, db, fake_app):
    fake_app.estados.update({"MLA1": "active", "MLA2": "paused"})
    planned = plan(
        mcp_client, conn, "publicaciones_estado", status="paused", item_ids=["MLA1", "MLA2"], limites={"max_items": 5}
    )
    assert [f["estado"] for f in planned["filas"]] == ["lista", "bloqueada"]
    _, result = apply(mcp_client, conn, "publicaciones_estado", planned)
    assert [r["resultado"] for r in result["resultados"]] == ["ok", "bloqueada"]
    [write] = fake_app.writes
    assert (write["path"], write["body"]) == ("/api/ml-publications/items/MLA1/status", {"status": "paused"})
    action = db.query(McpWriteAction).one()
    assert (action.accion, action.antes, action.despues) == (
        "estado_pausar",
        {"estado": "active"},
        {"estado": "paused"},
    )


def test_mayorista_patches_existing_tiers_then_syncs(mcp_client, conn, db, fake_app):
    fake_app.tramos["MLA1"] = [
        {"id": 7, "cantidad_minima": 10, "precio_unitario": 100.0},
        {"id": 8, "cantidad_minima": 50, "precio_unitario": 90.0},
    ]
    planned = plan(
        mcp_client,
        conn,
        "precio_mayorista_cambiar",
        mla="MLA1",
        tramos=[{"cantidad_minima": 10, "precio_unitario": 95}, {"cantidad_minima": 50, "precio_unitario": 88}],
        limites=PRECIO,
    )
    [fila] = planned["filas"]
    assert fila["antes"] == {"tramo_10": 100.0, "tramo_50": 90.0}
    assert fila["despues"] == {"tramo_10": 95.0, "tramo_50": 88.0}
    _, result = apply(mcp_client, conn, "precio_mayorista_cambiar", planned)
    assert result["resultados"][0]["resultado"] == "ok"
    assert [(w["method"], w["path"]) for w in fake_app.writes] == [
        ("PATCH", "/api/pxq/MLA1/tiers/7"),
        ("PATCH", "/api/pxq/MLA1/tiers/8"),
        ("POST", "/api/pxq/MLA1/sync"),
    ]
    assert fake_app.writes[2]["body"] == {"allow_clear": False, "publicar_sin_markup": False}
    assert db.query(McpWriteAction).one().accion == "precio_mayorista"


def test_mayorista_unknown_tier_is_blocked(mcp_client, conn, fake_app):
    fake_app.tramos["MLA1"] = [{"id": 7, "cantidad_minima": 10, "precio_unitario": 100.0}]
    planned = plan(
        mcp_client,
        conn,
        "precio_mayorista_cambiar",
        mla="MLA1",
        tramos=[{"cantidad_minima": 20, "precio_unitario": 95}],
        limites=PRECIO,
    )
    assert planned["plan_id"] is None
    assert planned["filas"][0]["detalle"].startswith("tramo_inexistente")


def test_mayorista_sync_refused_restores_the_mirror(mcp_client, conn, fake_app):
    fake_app.tramos["MLA1"] = [{"id": 7, "cantidad_minima": 10, "precio_unitario": 100.0}]
    fake_app.fail[("POST", "/sync")] = (409, {"detail": "divergencia con ML"})
    planned = plan(
        mcp_client,
        conn,
        "precio_mayorista_cambiar",
        mla="MLA1",
        tramos=[{"cantidad_minima": 10, "precio_unitario": 95}],
        limites=PRECIO,
    )
    _, result = apply(mcp_client, conn, "precio_mayorista_cambiar", planned)
    assert result["resultados"][0]["resultado"] == "rechazada"
    assert fake_app.tramos["MLA1"][0]["precio_unitario"] == 100.0
    assert [w["body"] for w in fake_app.writes_to("/tiers/7")] == [
        {"precio_unitario": 95.0},
        {"precio_unitario": 100.0},
    ]


# ---------------------------------------------------------------- real endpoint permission (loopback as the user)


def test_endpoint_permission_still_applies_through_the_loopback(
    mcp_client, conn, db, rol_admin, grant_permiso, monkeypatch
):
    """The real POST /api/promociones/item/{mla} answers: without promos.escribir it is `denegada` and the write
    service is never reached; with it, the service is called once with the price the person saw."""
    from tests.mcp.write_fakes import FakeApp

    fake = FakeApp(db=db).install(monkeypatch, writes=False)  # reads faked, writes hit the real endpoints
    calls = []

    def fake_enroll(mla, promotion_id, promotion_type, **kwargs):
        calls.append((mla, promotion_id, promotion_type, kwargs))
        return {"submitted": True, "status": "submitted", "price": kwargs.get("precio_visto")}

    monkeypatch.setattr("app.routers.ml_promotions.enroll_one_item", fake_enroll)
    fake.promos["MLA1"] = [promo("P1", "SMART", "candidate", 900.0)]
    args = {"items": [{"mla": "MLA1", "promotion_id": "P1", "promotion_type": "SMART"}], "limites": PROMO}

    planned = plan(mcp_client, conn, "promo_aplicar", **args)
    _, result = apply(mcp_client, conn, "promo_aplicar", planned)
    assert result["resultados"][0]["resultado"] == "denegada"
    assert "promos.escribir" in result["resultados"][0]["detalle"]
    assert calls == []
    assert db.query(McpWriteAction).one().resultado == "denegada"

    grant_permiso(rol_admin, "promos.escribir")
    planned = plan(mcp_client, conn, "promo_aplicar", **args)
    _, result = apply(mcp_client, conn, "promo_aplicar", planned)
    assert result["resultados"][0]["resultado"] == "ok"
    assert len(calls) == 1
    assert calls[0][:3] == ("MLA1", "P1", "SMART") and calls[0][3]["precio_visto"] == 900.0


def test_list_price_endpoint_permission_denies_through_the_loopback(mcp_client, conn, db, monkeypatch):
    """The real POST /api/precios/set-rapido refuses a user without the product price permissions."""
    from tests.mcp.write_fakes import FakeApp

    fake = FakeApp(db=db).install(monkeypatch, writes=False)
    fake.product(101, 1000.0)
    planned = plan(mcp_client, conn, "precio_lista_cambiar", items=[{"item_id": 101, "precio": 950}], limites=PRECIO)
    _, result = apply(mcp_client, conn, "precio_lista_cambiar", planned)
    assert result["resultados"][0]["resultado"] == "denegada"
    assert float(fake.pricing(101).precio_lista_ml) == 1000.0
    assert db.query(McpWriteAction).one().resultado == "denegada"


# ---------------------------------------------------------------- "aplicá todas las que mejoran 5%"


def _item(item_id: str, price: float) -> dict:
    return {"item_id": item_id, "title": f"Item {item_id}", "price": {"amount": price}, "link": {"codigo": item_id}}


def test_apply_every_promo_that_improves_x_percent_end_to_end(mcp_client, conn, db, fake_app):
    fake_app.items_page = [_item("MLA1", 1000), _item("MLA2", 1000)]
    fake_app.promos["MLA1"] = [
        promo(
            "S1", "DEAL", "started", 1000.0, application_status="active", nuestro_markup=10.0, markup_sell_in_out=12.0
        ),
        promo("P", "PRE_NEGOTIATED", "candidate", 1000.0, nuestro_markup=14.0, markup_sell_in_out=20.0),
    ]
    fake_app.promos["MLA2"] = [promo("B", "SMART", "candidate", 900.0, nuestro_markup=21.0, markup_sell_in_out=None)]
    fake_app.markup_by_price[1000.0] = 20.0  # MLA2 sells plain at 1000 with markup 20 -> B improves 5%

    planned = plan(mcp_client, conn, "promos_aplicar_mejoras", min_mejora_pct=30, limites=PROMO)
    [fila] = planned["filas"]  # MLA1 improves 66.67%, MLA2 only 5%
    assert fila["objetivo"] == "MLA1" and fila["despues"]["promotion_id"] == "P"
    assert fila["mejora"]["percent"] == pytest.approx(66.67)

    planned = plan(mcp_client, conn, "promos_aplicar_mejoras", min_mejora_pct=5, limites=PROMO)
    assert [f["objetivo"] for f in planned["filas"]] == ["MLA1", "MLA2"]
    _, result = apply(mcp_client, conn, "promos_aplicar_mejoras", planned)
    assert [r["resultado"] for r in result["resultados"]] == ["ok", "ok"]
    assert [(w["path"], w["body"]["promotion_id"]) for w in fake_app.writes] == [
        ("/api/promociones/item/MLA1", "P"),
        ("/api/promociones/item/MLA2", "B"),
    ]
    actions = db.query(McpWriteAction).order_by(McpWriteAction.id).all()
    assert [(a.objetivo, a.accion, a.tool, a.resultado) for a in actions] == [
        ("MLA1", "promo_aplicar", "promos_aplicar_mejoras", "ok"),
        ("MLA2", "promo_aplicar", "promos_aplicar_mejoras", "ok"),
    ]
