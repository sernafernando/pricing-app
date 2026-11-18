"""S2, S3, S5: kill switch (DB default OFF, env wins), motivo + per-order limits (faltan_limites), the hard ±10% per
price change, the order's own limits, the minimum markup and the C1 band, and the write rate limit. Rows over a
guard are `bloqueada` with the reason and never applied; refused orders store no plan and write nothing."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.mcp import loopback
from app.mcp.write import criteria
from app.models.mcp_write import McpWriteAction, McpWritePlan
from app.services.ml_publications import settings_store
from tests.mcp.conftest import WRITE_SCOPE, connect, write_call

LIMITES = {"max_items": 10, "max_cambio_pct": 10, "min_markup_pct": 10}


@pytest.fixture()
def conn(mcp_client, writer):
    return connect(mcp_client, writer, scope=WRITE_SCOPE)


def _plan_price(client, conn, items, limites=LIMITES, **extra):
    args = {"modo": "plan", "items": items, "motivo": "ajuste de precios", "limites": limites, **extra}
    return write_call(client, conn.headers, "precio_lista_cambiar", args)


# ---------------------------------------------------------------- kill switch


def test_writes_are_off_by_default(mcp_client, conn, db, fake_app, band_ok):
    fake_app.product(101, 1000.0)
    result, text = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}])
    assert result["isError"] is True
    assert text.startswith("deshabilitada")
    assert db.query(McpWritePlan).count() == 0


def test_db_switch_turns_writes_on(mcp_client, conn, db, fake_app, band_ok, write_enabled):
    fake_app.product(101, 1000.0)
    _, plan = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}])
    assert plan["plan_id"]
    assert db.query(McpWritePlan).count() == 1


@pytest.mark.parametrize("env", ["MCP_WRITE_KILL_SWITCH", "ML_PUB_KILL_SWITCH"])
def test_env_kill_switch_wins_over_the_db(mcp_client, conn, db, fake_app, band_ok, write_enabled, monkeypatch, env):
    fake_app.product(101, 1000.0)
    monkeypatch.setattr(settings, env, True)
    result, text = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}])
    assert result["isError"] is True
    assert "kill switch" in text
    assert db.query(McpWritePlan).count() == 0


def test_switch_off_between_plan_and_apply_writes_nothing(mcp_client, conn, db, fake_app, band_ok, write_enabled):
    fake_app.product(101, 1000.0)
    _, plan = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}])
    settings_store.set_setting("mcp_write.enabled", False, "test", session=db)
    db.commit()
    result, text = write_call(
        mcp_client,
        conn.headers,
        "precio_lista_cambiar",
        {"modo": "aplicar", "plan_id": plan["plan_id"], "confirm_token": plan["confirm_token"]},
    )
    assert result["isError"] is True and text.startswith("deshabilitada")
    assert fake_app.writes == []
    assert db.query(McpWriteAction).count() == 0


# ---------------------------------------------------------------- motivo and limits


def test_price_order_without_limits_is_refused_naming_them(mcp_client, conn, db, fake_app, write_enabled):
    fake_app.product(101, 1000.0)
    result, text = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}], limites=None)
    assert result["isError"] is True
    assert text.startswith("faltan_limites")
    assert "max_items" in text and "max_cambio_pct" in text and "min_markup_pct" in text
    result, text = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}], limites={"max_items": 3})
    assert text.startswith("faltan_limites") and "max_items" not in text.split(":", 2)[2]
    assert db.query(McpWritePlan).count() == 0
    assert fake_app.writes == []


def test_promo_order_needs_max_items_and_min_markup(mcp_client, conn, fake_app, write_enabled):
    result, text = write_call(
        mcp_client,
        conn.headers,
        "promo_aplicar",
        {
            "modo": "plan",
            "items": [{"mla": "MLA1", "promotion_id": "P1", "promotion_type": "SMART"}],
            "motivo": "x",
            "limites": {},
        },
    )
    assert text.startswith("faltan_limites") and "min_markup_pct" in text and "max_cambio_pct" not in text


def test_motivo_is_required(mcp_client, conn, fake_app, write_enabled):
    fake_app.product(101, 1000.0)
    result, text = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}], motivo="  ")
    assert result["isError"] is True and text.startswith("falta_motivo")


def test_max_cambio_pct_over_ten_is_refused(mcp_client, conn, fake_app, write_enabled):
    fake_app.product(101, 1000.0)
    result, text = _plan_price(
        mcp_client, conn, [{"item_id": 101, "precio": 1050}], limites={**LIMITES, "max_cambio_pct": 12}
    )
    assert result["isError"] is True and text.startswith("limites_invalidos")


def test_zero_price_is_refused_by_the_schema(mcp_client, conn, fake_app, write_enabled):
    fake_app.product(101, 1000.0)
    result, text = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 0}])
    assert result["isError"] is True and "argumentos_invalidos" in text


# ---------------------------------------------------------------- per row


def test_hard_ten_percent_cap_even_with_max_cambio_ten(mcp_client, conn, db, fake_app, band_ok, write_enabled):
    fake_app.product(101, 1000.0)
    fake_app.product(102, 1000.0)
    _, plan = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1120}, {"item_id": 102, "precio": 880}])
    assert plan["plan_id"] is None and plan["confirm_token"] is None
    assert [f["estado"] for f in plan["filas"]] == ["bloqueada", "bloqueada"]
    assert plan["filas"][0]["detalle"].startswith("tope_10")
    assert plan["filas"][1]["detalle"].startswith("tope_10")
    assert plan["filas"][0]["cambios_pct"] == [12.0]
    assert db.query(McpWritePlan).count() == 0


def test_order_limits_block_rows(mcp_client, conn, fake_app, band_ok, write_enabled):
    for item in (101, 102, 103, 104):
        fake_app.product(item, 1000.0)
    limites = {"max_items": 1, "max_cambio_pct": 5, "min_markup_pct": 10, "max_baja_pct": 2}
    items = [
        {"item_id": 101, "precio": 1080},  # over max_cambio_pct 5
        {"item_id": 102, "precio": 970},  # baja 3% over max_baja_pct 2
        {"item_id": 103, "precio": 1010},  # ok
        {"item_id": 104, "precio": 1020},  # ok but over max_items 1
    ]
    _, plan = _plan_price(mcp_client, conn, items, limites=limites)
    detalles = [f["detalle"] for f in plan["filas"]]
    assert detalles[0].startswith("max_cambio_pct")
    assert detalles[1].startswith("max_baja_pct")
    assert detalles[2] is None and plan["filas"][2]["estado"] == "lista"
    assert detalles[3].startswith("max_items")
    assert plan["resumen"] == {"listas": 1, "bloqueadas": 3}


def test_min_markup_blocks_a_row(mcp_client, conn, fake_app, band_ok, write_enabled):
    fake_app.product(101, 1000.0)
    fake_app.markup_by_price[1050.0] = 8.0
    _, plan = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}])
    assert plan["filas"][0]["markup_previsto"] == 8.0
    assert plan["filas"][0]["detalle"].startswith("min_markup_pct")


def test_band_unavailable_blocks_until_criteria_exist(mcp_client, conn, fake_app, write_enabled):
    fake_app.product(101, 1000.0)
    _, plan = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}])
    assert plan["filas"][0]["estado"] == "bloqueada"
    assert plan["filas"][0]["detalle"].startswith("banda_no_disponible")


def test_band_double_allows_inside_and_blocks_outside(mcp_client, conn, fake_app, write_enabled, monkeypatch):
    fake_app.product(101, 1000.0)
    fake_app.product(102, 1000.0)
    fake_app.markup_by_price[1040.0] = 50.0
    seen = []

    def band(db, target):
        seen.append(target)
        return (20.0, 40.0)

    monkeypatch.setattr(criteria, "band_for", band)
    _, plan = _plan_price(mcp_client, conn, [{"item_id": 101, "precio": 1050}, {"item_id": 102, "precio": 1040}])
    assert plan["filas"][0]["estado"] == "lista"  # markup 30 inside 20..40
    assert plan["filas"][1]["detalle"].startswith("fuera_de_banda")
    assert seen[0] == {"accion": "precio_lista", "objetivo": "101"}


def test_pause_needs_no_markup_nor_band(mcp_client, conn, fake_app, write_enabled):
    fake_app.estados["MLA1"] = "active"
    _, plan = write_call(
        mcp_client,
        conn.headers,
        "publicaciones_estado",
        {"modo": "plan", "status": "paused", "item_ids": ["MLA1"], "motivo": "sin stock", "limites": {"max_items": 1}},
    )
    assert plan["filas"][0]["estado"] == "lista"


def test_write_rate_limit(mcp_client, conn, db, fake_app, band_ok, write_enabled, monkeypatch):
    monkeypatch.setattr(settings, "MCP_WRITE_RATE_LIMIT", "1/minute")
    fake_app.product(101, 1000.0)
    fake_app.product(102, 1000.0)
    plans = [_plan_price(mcp_client, conn, [{"item_id": i, "precio": 1010}])[1] for i in (101, 102)]
    apply = {"modo": "aplicar"}
    _, first = write_call(
        mcp_client,
        conn.headers,
        "precio_lista_cambiar",
        apply | {"plan_id": plans[0]["plan_id"], "confirm_token": plans[0]["confirm_token"]},
    )
    assert first["resultados"][0]["resultado"] == "ok"
    result, text = write_call(
        mcp_client,
        conn.headers,
        "precio_lista_cambiar",
        apply | {"plan_id": plans[1]["plan_id"], "confirm_token": plans[1]["confirm_token"]},
    )
    assert result["isError"] is True and text.startswith("limitada")
    assert len(fake_app.writes_to("set-rapido")) == 1


# ---------------------------------------------------------------- loopback allowlist


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("POST", "/api/promociones/item/MLA1", True),
        ("DELETE", "/api/promociones/item/MLA1", True),
        ("POST", "/api/ml-publications/items/MLA1/status", True),
        ("POST", "/api/precios/set-rapido", True),
        ("POST", "/api/precios/set", False),
        ("PATCH", "/api/pxq/MLA1/tiers/3", True),
        ("DELETE", "/api/pxq/MLA1/tiers/3", False),
        ("POST", "/api/pxq/MLA1/sync", True),
        ("POST", "/api/usuarios", False),
        ("GET", "/api/promociones/item/MLA1", False),
    ],
)
def test_loopback_write_allowlist(method, path, allowed):
    assert loopback.write_allowed(method, path) is allowed


def test_loopback_refuses_a_route_off_the_allowlist():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(loopback.send_write("POST", "/api/usuarios", {}, {}, {}))
