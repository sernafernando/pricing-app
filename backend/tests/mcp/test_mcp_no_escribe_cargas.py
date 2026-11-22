"""Tacticals approval S6: no MCP tool loads or edits a tactical, a brand bonus, a sell-in purchase or a sell-out
campaign, so no load can skip the approval through the MCP. The MCP writes only through the app's own API
(`app.mcp.write.live.write`) and its write families name their endpoints; none of them, nor any other MCP module,
reaches those routes, engines, models or tables. A new MCP write path to them must start the row `pendiente` and
update this test."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MCP = Path(__file__).resolve().parents[2] / "app" / "mcp"
PROHIBIDOS = [
    r"/api/tacticals",
    r"/api/sell-in",
    r"/api/sell-out",
    r"\bsell-in/",
    r"\bsell-out/",
    r"app\.services(\.| import )tacticals",
    r"app\.services\.sell_in",
    r"app\.services\.sell_out",
    r"\bSellInBonoMarca\b",
    r"\bSellInCompra\b",
    r"\bSellOutCampana\b",
    r"\bTactical\b",
    r"\b(INSERT INTO|UPDATE|DELETE FROM)\s+(tacticals|sell_in_bonos_marca|sell_in_compras|sell_out_campanas)\b",
]
FUENTES = sorted(MCP.rglob("*.py"))


def test_the_mcp_package_is_where_it_was() -> None:
    assert (MCP / "write" / "families.py") in FUENTES  # the scan below reads real files


@pytest.mark.parametrize("fuente", FUENTES, ids=lambda p: str(p.relative_to(MCP)))
def test_no_mcp_module_writes_a_load_that_waits_for_approval(fuente: Path) -> None:
    texto = fuente.read_text(encoding="utf-8")

    encontrados = [patron for patron in PROHIBIDOS if re.search(patron, texto, flags=re.IGNORECASE)]

    assert encontrados == [], f"{fuente.relative_to(MCP)} reaches {encontrados}"
