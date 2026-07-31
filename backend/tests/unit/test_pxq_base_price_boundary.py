"""Structural boundary test (ml-wholesale-pxq-pricing, design D3): no PxQ
module may import `ProductoPricing` or reference `productos_pricing` at the
source-text/AST level.

PxQ tiers are additional quantity prices layered on top of the base price;
`markup_rebate`/`markup_oferta` live on `ProductoPricing` and derive from
`precio_lista_ml` (the BASE price) — the "recompute markup in the same
transaction" convention does NOT apply to PxQ writes, because PxQ never
touches that table at all. This is enforced as a failing test, not a
convention, and is written generically by PATH PATTERN
(`app/services/ml_pxq_*`, `app/services/pxq_*`, `app/api/endpoints/pxq*`) so
future PR 3 modules are covered without editing this test again.
"""

from __future__ import annotations

import ast
import glob
import os

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FORBIDDEN_NAMES = {"ProductoPricing"}
_FORBIDDEN_MODULE_SUBSTRINGS = ("productos_pricing",)

_PXQ_PATH_GLOBS = (
    "app/services/pxq_*.py",
    "app/services/ml_pxq_*.py",
    "app/api/endpoints/pxq*.py",
    "app/models/ml_pxq_*.py",
)


def _pxq_module_paths() -> list[str]:
    paths: list[str] = []
    for pattern in _PXQ_PATH_GLOBS:
        paths.extend(sorted(glob.glob(os.path.join(_BACKEND_ROOT, pattern))))
    return paths


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
