"""Resource registry skeleton and the "data only from ML" static guard."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import app.services.ml_publications as package
from app.services.ml_publications.mappers import map_item
from app.services.ml_publications.parsers.items_bulk import parse_items_bulk
from app.services.ml_publications.resources import RESOURCES, ResourceSpec, register
from tests.services.ml_publications.conftest import FIXTURES_DIR

# Modules allowed to read ERP data. Empty in this PR: PR5L1 adds exactly `links.py`,
# PR5L2 adds exactly the links router.
ERP_ALLOW_LIST: frozenset[str] = frozenset()

FORBIDDEN_NAMES = ("tb_mercadolibre_items_publicados", "publicaciones_ml", "productos_erp", "ProductoERP")
FORBIDDEN_IMPORT_TOKENS = ("gbp", "producto", "publicacion")


def test_registry_exposes_item_with_keys_array_keys_mapper_and_parser():
    spec = RESOURCES["item"]
    assert spec.key_columns == ("item_id",)
    assert dict(spec.array_keys) == {}
    assert spec.mapper is map_item
    assert spec.parser is parse_items_bulk
    assert spec.negative_states == {}


def test_every_registered_resource_is_backed_by_a_committed_fixture():
    assert set(RESOURCES) == {"item"}
    for spec in RESOURCES.values():
        assert spec.fixture and (FIXTURES_DIR / spec.fixture).exists(), spec.name


def test_registering_a_resource_without_a_parser_is_rejected():
    spec = ResourceSpec(name="description", key_columns=("item_id",), mapper=map_item, parser=None, fixture="x.json")
    with pytest.raises(ValueError, match="parser"):
        register(spec, registry={})


def test_registering_a_resource_without_a_fixture_is_rejected():
    spec = ResourceSpec(name="description", key_columns=("item_id",), mapper=map_item, parser=map_item, fixture="")
    with pytest.raises(ValueError, match="fixture"):
        register(spec, registry={})


def test_duplicate_registration_is_rejected():
    with pytest.raises(ValueError, match="already registered"):
        register(RESOURCES["item"], registry=dict(RESOURCES))


def _package_sources():
    root = Path(package.__file__).parent
    return [(p.relative_to(root).as_posix(), p.read_text(encoding="utf-8")) for p in sorted(root.rglob("*.py"))]


def test_package_never_imports_gbp_or_names_erp_mirror_tables():
    offenders = []
    for name, source in _package_sources():
        if name in ERP_ALLOW_LIST:
            continue
        for node in ast.walk(ast.parse(source)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""] + [alias.name for alias in node.names]
            offenders += [(name, m) for m in modules if any(token in m.lower() for token in FORBIDDEN_IMPORT_TOKENS)]
        offenders += [(name, n) for n in FORBIDDEN_NAMES if re.search(rf"\b{n}\b", source)]
    assert offenders == []


def test_allow_list_is_empty_in_this_pr():
    assert ERP_ALLOW_LIST == frozenset()
