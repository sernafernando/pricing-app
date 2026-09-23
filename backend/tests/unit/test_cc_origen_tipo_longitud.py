"""Guard: every `origen_tipo` literal must fit its column.

SQLite (what the suite runs on) ignores `VARCHAR(n)` lengths; Postgres does
not — it rejects the insert. That gap let
`cancelacion_pedido_por_correccion` (33 chars) ship against a
`String(32)` column in April 2026 and only surfaced in production months
later, as a 500 on "corregir pedido", when someone finally corrected a
pedido that already had CC movements.

So the check cannot be a normal insert test: it has to compare the
literals in the source against the column definition.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.imputacion import Imputacion

APP_DIR = Path(__file__).resolve().parents[2] / "app"
_ORIGEN_TIPO_LITERAL = re.compile(r'origen_tipo\s*=\s*"([a-z_]+)"')


def _column_max_len() -> int:
    """El techo real es la columna más chica: un mismo literal viaja a las dos."""
    return min(
        CCProveedorMovimiento.__table__.c.origen_tipo.type.length,
        Imputacion.__table__.c.origen_tipo.type.length,
    )


def _literales() -> dict[str, list[str]]:
    encontrados: dict[str, list[str]] = {}
    for path in APP_DIR.rglob("*.py"):
        for valor in _ORIGEN_TIPO_LITERAL.findall(path.read_text(encoding="utf-8")):
            encontrados.setdefault(valor, []).append(str(path.relative_to(APP_DIR)))
    return encontrados


def test_hay_literales_para_revisar() -> None:
    """Si el regex deja de matchear, el test de abajo pasa vacío y no prueba nada."""
    assert len(_literales()) >= 5


def test_todo_origen_tipo_entra_en_la_columna() -> None:
    maximo = _column_max_len()
    excedidos = {valor: (len(valor), archivos) for valor, archivos in _literales().items() if len(valor) > maximo}
    assert not excedidos, (
        f"origen_tipo es String({maximo}) y estos valores no entran: {excedidos}. "
        "Postgres rechaza el insert; SQLite lo deja pasar y el test de negocio queda en verde."
    )
