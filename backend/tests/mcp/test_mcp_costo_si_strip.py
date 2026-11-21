"""The `producto_detalle` MCP tool drops the costo SI without `productos.ver_costos` (sell-in-costo-si T3 PR 2, C12):
the detail's `costo_si` key is a cost key for the strip, like `costo` and `costo_ars`. Invented data."""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from app.api.endpoints.productos_detail import _DETALLE_PRICING_FIELDS, _DETALLE_PRODUCTO_FIELDS
from app.main import app
from app.mcp import tools
from app.schemas.costo_si import CostoSiPayload


def _detalle() -> dict[str, Any]:
    """A /productos/{id}/detalle answer as the endpoint shapes it, every field filled."""
    producto = {field: 1 for field in _DETALLE_PRODUCTO_FIELDS}
    producto["costo_si"] = CostoSiPayload(
        costo=25.0, moneda="USD", fuente="costo_si", tipo_cambio=1000.0, costo_ars=25000.0, markups={"clasica": 10.0}
    ).model_dump(mode="json")
    return {"producto": producto, "pricing": dict.fromkeys(_DETALLE_PRICING_FIELDS), "ultimas_compras": []}


@pytest.fixture()
def detalle_tool(monkeypatch):
    async def _get(path: str, params: dict[str, Any], username: str) -> Any:
        return _detalle()

    monkeypatch.setattr(tools, "_get", _get)
    return tools.build_catalog(app.openapi())["producto_detalle"]


def _run(tool, can_see_costs: bool) -> dict[str, Any]:
    return anyio.run(tools.run_tool, tool, {"item_id": 6301}, "costo-si", can_see_costs)


def test_the_detail_lists_costo_si_among_its_product_fields() -> None:
    assert "costo_si" in _DETALLE_PRODUCTO_FIELDS


def test_without_ver_costos_the_costo_si_is_dropped_with_the_other_costs(detalle_tool) -> None:
    producto = _run(detalle_tool, can_see_costs=False)["producto"]

    assert "costo_si" not in producto
    assert not {"costo", "costo_ars", "costo_envio"} & set(producto)
    assert producto["codigo"] == 1  # the rest stays


def test_with_ver_costos_the_costo_si_stays(detalle_tool) -> None:
    producto = _run(detalle_tool, can_see_costs=True)["producto"]

    assert producto["costo_si"]["costo"] == 25.0
    assert producto["costo_si"]["fuente"] == "costo_si"
