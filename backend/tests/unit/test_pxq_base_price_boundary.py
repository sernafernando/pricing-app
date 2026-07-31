"""Structural boundary test (ml-wholesale-pxq-pricing, design D3): no PxQ
module may import `ProductoPricing` or reference `productos_pricing` at the
source-text/AST level.

PxQ tiers are additional quantity prices layered on top of the base price;
`markup_rebate`/`markup_oferta` live on `ProductoPricing` and derive from
`precio_lista_ml` (the BASE price) — the "recompute markup in the same
transaction" convention does NOT apply to PxQ writes, because PxQ never
touches that table at all. This is enforced as a failing test, not a
convention.

Discovery walks the WHOLE of `app/` and matches on FILE NAME, not on a list
of directories. An earlier version enumerated globs per directory and did not
include `app/routers/` — which is where this repo actually puts new domain
routers, so PR 3's router would have slipped past the one barrier this test
exists to provide, with the test still green. A name-based walk cannot
develop that kind of blind spot when code lands somewhere new.
"""

from __future__ import annotations

import ast
import os

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FORBIDDEN_NAMES = {"ProductoPricing"}
_FORBIDDEN_MODULE_SUBSTRINGS = ("productos_pricing",)

_PXQ_FILENAME_PREFIXES = ("pxq_", "ml_pxq_")
_APP_ROOT = os.path.join(_BACKEND_ROOT, "app")


def _pxq_module_paths() -> list[str]:
    """Every .py under `app/` whose file name marks it as PxQ code.

    Deliberately a walk over all of `app/`, not a per-directory glob list: a
    new module only has to be NAMED as PxQ code to be covered, no matter which
    package it lands in.
    """
    paths: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(_APP_ROOT):
        if "__pycache__" in dirpath:
            continue
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            if filename.startswith(_PXQ_FILENAME_PREFIXES):
                paths.append(os.path.join(dirpath, filename))
    return sorted(paths)


def _scan_module_for_producto_pricing_references(path: str) -> list[str]:
    """Returns a list of violation descriptions found in `path`, empty if none."""
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=path)

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(substr in module for substr in _FORBIDDEN_MODULE_SUBSTRINGS):
                violations.append(f"{path}: `from {module} import ...`")
            for alias in node.names:
                if alias.name in _FORBIDDEN_NAMES:
                    violations.append(f"{path}: `from {module} import {alias.name}`")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(substr in alias.name for substr in _FORBIDDEN_MODULE_SUBSTRINGS):
                    violations.append(f"{path}: `import {alias.name}`")
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            violations.append(f"{path}: bare reference to `{node.id}`")

    return violations


def test_no_pxq_module_imports_producto_pricing() -> None:
    modules = _pxq_module_paths()
    assert modules, "expected at least one PxQ module to exist by PR2 (pxq_markup.py)"

    all_violations: list[str] = []
    for path in modules:
        all_violations.extend(_scan_module_for_producto_pricing_references(path))

    assert all_violations == [], (
        "PxQ modules must never import/reference ProductoPricing/productos_pricing "
        f"(base-price boundary, design D3): {all_violations}"
    )


def test_scan_is_generic_enough_to_catch_a_synthetic_violation(tmp_path) -> None:
    """Proves the scan actually detects a violation shape, so a future
    silent no-op in the glob/AST logic doesn't make this test vacuous."""
    bad_module = tmp_path / "pxq_bad_example.py"
    bad_module.write_text("from app.models.producto import ProductoPricing\n")

    violations = _scan_module_for_producto_pricing_references(str(bad_module))
    assert violations != []


def test_scan_reaches_pxq_code_in_any_package(tmp_path, monkeypatch) -> None:
    """The scan must not depend on which package PxQ code lands in.

    `app/routers/` is where this repo puts new domain routers, and the previous
    per-directory glob list omitted it — so a router importing ProductoPricing
    would have passed. This pins discovery to the file NAME instead."""
    import sys

    module = sys.modules[__name__]

    fake_app = tmp_path / "app"
    for package in ("routers", "services", "api/endpoints", "somewhere/new"):
        (fake_app / package).mkdir(parents=True)
        (fake_app / package / "pxq_thing.py").write_text("x = 1\n", encoding="utf-8")
    (fake_app / "routers" / "unrelated.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(module, "_APP_ROOT", str(fake_app))
    found = {os.path.relpath(p, str(fake_app)) for p in module._pxq_module_paths()}

    assert found == {
        os.path.join("routers", "pxq_thing.py"),
        os.path.join("services", "pxq_thing.py"),
        os.path.join("api", "endpoints", "pxq_thing.py"),
        os.path.join("somewhere", "new", "pxq_thing.py"),
    }
