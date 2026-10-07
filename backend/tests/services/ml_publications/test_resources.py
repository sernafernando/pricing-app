"""Resource registry skeleton and the "data only from ML" static guard."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import app.services.ml_publications as package
from app.services.ml_publications.diff import array_keys_for
from app.services.ml_publications.mappers import map_item
from app.services.ml_publications.parsers.items_bulk import parse_items_bulk
from app.services.ml_publications.resources import REFRESH_RESOURCES, RESOURCES, ResourceSpec, register
from tests.services.ml_publications.conftest import FIXTURES_DIR, SUBRESOURCE_FIXTURES, load_fixture

# Modules allowed to read our product catalog (`ProductoERP`). PR5L1 adds exactly `links.py`,
# PR5L2 adds exactly the links router. The allowance covers the catalog only: GBP clients and the
# other ERP-mirror tables stay forbidden everywhere.
ERP_ALLOW_LIST: frozenset[str] = frozenset({"links.py"})
CATALOG_NAMES = ("productos_erp", "ProductoERP")
CATALOG_IMPORT_TOKEN = "producto"

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
    assert set(RESOURCES) == {"item", *SUBRESOURCE_FIXTURES}
    for spec in RESOURCES.values():
        assert spec.fixture and (FIXTURES_DIR / spec.fixture).exists(), spec.name


SUBRESOURCE_KEYS = {
    "description": ("item_id",),
    "prices": ("item_id",),
    "sale_price": ("item_id",),
    "promotions": ("item_id",),
    "user_product": ("user_product_id",),
    "stock": ("user_product_id",),
    "family": ("family_id",),
}


@pytest.mark.parametrize("name", sorted(SUBRESOURCE_FIXTURES))
def test_subresources_are_registered_under_their_refresh_names_with_their_keys_and_fixture(name):
    spec = RESOURCES[name]
    assert name in REFRESH_RESOURCES
    assert spec.key_columns == SUBRESOURCE_KEYS[name]
    assert spec.fixture == SUBRESOURCE_FIXTURES[name]
    assert dict(spec.negative_states) == {}


def test_promotions_diff_keys_come_from_the_shared_natural_key_table():
    assert RESOURCES["promotions"].array_keys == array_keys_for("promotions") == {"": ("id", "type")}
    assert all(dict(RESOURCES[n].array_keys) == {} for n in SUBRESOURCE_KEYS if n != "promotions")


@pytest.mark.parametrize("name", sorted(SUBRESOURCE_FIXTURES))
def test_every_subresource_round_trips_raw_through_its_parser_and_maps_without_error(name):
    spec = RESOURCES[name]
    ok_calls = [c for c in load_fixture(spec.fixture)["calls"] if c["status"] == 200]
    assert ok_calls
    for call in ok_calls:
        parsed = spec.parser(call["status"], call["body"])
        assert parsed.state == "ok" and parsed.body == call["body"], call["name"]
        assert isinstance(spec.mapper(parsed.body), dict)


@pytest.mark.parametrize("name", sorted(SUBRESOURCE_FIXTURES))
def test_every_subresource_classifies_its_captured_404_when_it_has_one(name):
    spec = RESOURCES[name]
    for call in load_fixture(spec.fixture)["calls"]:
        if call["status"] == 404:
            parsed = spec.parser(404, call["body"])
            assert (parsed.state, parsed.error_body) == ("not_found", call["body"])


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
        allowed = name in ERP_ALLOW_LIST
        for node in ast.walk(ast.parse(source)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""] + [alias.name for alias in node.names]
            for module in modules:
                for token in FORBIDDEN_IMPORT_TOKENS:
                    if token in module.lower() and not (allowed and token == CATALOG_IMPORT_TOKEN):
                        offenders.append((name, module))
        offenders += [
            (name, n)
            for n in FORBIDDEN_NAMES
            if re.search(rf"\b{n}\b", source) and not (allowed and n in CATALOG_NAMES)
        ]
    assert offenders == []


def test_allow_list_is_exactly_the_linking_module_in_this_pr():
    assert ERP_ALLOW_LIST == frozenset({"links.py"})


def test_the_promotions_resource_name_is_defined_once_and_shared():
    from app.services.ml_publications import events, intake, subresource_context
    from app.services.ml_publications.resources import PROMOTIONS_RESOURCE

    assert PROMOTIONS_RESOURCE == "promotions" and PROMOTIONS_RESOURCE in RESOURCES
    assert events.PROMOTIONS_RESOURCE is PROMOTIONS_RESOURCE
    assert intake.PROMOTIONS_RESOURCE is PROMOTIONS_RESOURCE
    assert subresource_context.PROMOTIONS is PROMOTIONS_RESOURCE
