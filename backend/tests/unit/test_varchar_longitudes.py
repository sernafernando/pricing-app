"""Ningún literal del código puede exceder el `String(n)` de su columna.

Por qué existe este test y no uno de negocio: la suite corre sobre SQLite,
que IGNORA el largo de un VARCHAR. Postgres no: rechaza el insert. Esa
diferencia dejó pasar `origen_tipo="cancelacion_pedido_por_correccion"`
(33) contra una columna de 32 desde abril de 2026, con todos los tests en
verde, hasta que en septiembre alguien corrigió un pedido con movimientos
de cuenta corriente y se comió un 500.

Un test que inserte no sirve para esto. Hay que mirar el código.

Cómo resuelve a qué columna va cada literal:

1. `Modelo(campo="x")` — directo.
2. `helper(campo="x")` donde `helper` recibe `campo` y se lo pasa tal cual
   a `Modelo(campo=campo)`. Este segundo caso es el que importa: el bug de
   2026 entró por `cc_proveedor_service.insertar_mov(...)`, no por el
   constructor, así que mirar solo constructores no lo habría encontrado.

Lo que NO cubre: valores armados en runtime (f-strings, concatenaciones,
datos externos). Para eso el límite real sigue siendo la base.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
MODELS = APP / "models"


def _largo_de_string(node: ast.Call) -> int | None:
    """`String(32)` o `String(length=32)` → 32. Cualquier otra cosa → None."""
    if getattr(node.func, "id", None) != "String":
        return None
    if node.args and isinstance(node.args[0], ast.Constant):
        return node.args[0].value
    for kw in node.keywords:
        if kw.arg == "length" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def _columnas() -> dict[tuple[str, str], int]:
    """(Modelo, columna) → largo máximo declarado."""
    encontradas: dict[tuple[str, str], int] = {}
    for path in MODELS.rglob("*.py"):
        for clase in [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ClassDef)]:
            for st in clase.body:
                if not (isinstance(st, ast.Assign) and isinstance(st.value, ast.Call)):
                    continue
                if getattr(st.value.func, "id", None) != "Column" or not st.value.args:
                    continue
                arg = st.value.args[0]
                largo = _largo_de_string(arg) if isinstance(arg, ast.Call) else None
                if largo and isinstance(st.targets[0], ast.Name):
                    encontradas[(clase.name, st.targets[0].id)] = largo
    return encontradas


def _helpers(columnas: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    """(función, parámetro) → largo, cuando el parámetro se pasa tal cual a un modelo."""
    encontrados: dict[tuple[str, str], int] = {}
    for path in APP.rglob("*.py"):
        for fn in [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.FunctionDef)]:
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and getattr(node.func, "id", None)):
                    continue
                for kw in node.keywords:
                    if kw.arg and isinstance(kw.value, ast.Name) and kw.value.id in params:
                        largo = columnas.get((node.func.id, kw.arg))
                        if largo:
                            encontrados[(fn.name, kw.value.id)] = largo
    return encontrados


def _excedidos() -> list[tuple[str, str, str, int, int, str]]:
    columnas = _columnas()
    helpers = _helpers(columnas)
    fuera: list[tuple[str, str, str, int, int, str]] = []
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            destino = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if not destino:
                continue
            for kw in node.keywords:
                if not (kw.arg and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                    continue
                largo = columnas.get((destino, kw.arg)) or helpers.get((destino, kw.arg))
                if largo and len(kw.value.value) > largo:
                    fuera.append(
                        (
                            destino,
                            kw.arg,
                            kw.value.value,
                            len(kw.value.value),
                            largo,
                            str(path.relative_to(BACKEND)),
                        )
                    )
    return fuera


def test_el_analisis_encuentra_columnas_y_helpers() -> None:
    """Si el parseo deja de resolver, el test de abajo pasa en vacío y no prueba nada."""
    columnas = _columnas()
    assert len(columnas) > 100
    helpers = _helpers(columnas)
    assert len(helpers) > 10
    # El sink del incidente de 2026: si deja de resolverse, perdimos la cobertura
    # que motivó este archivo.
    assert ("insertar_mov", "origen_tipo") in helpers


def test_ningun_literal_excede_su_columna() -> None:
    fuera = _excedidos()
    detalle = "\n".join(
        f"  {archivo}: {destino}({campo}=...) → {largo} chars, la columna admite {maximo}: {valor!r}"
        for destino, campo, valor, largo, maximo, archivo in fuera
    )
    assert not fuera, (
        "Literales que Postgres va a rechazar (SQLite los deja pasar, "
        f"así que ningún test de negocio los ve):\n{detalle}"
    )
