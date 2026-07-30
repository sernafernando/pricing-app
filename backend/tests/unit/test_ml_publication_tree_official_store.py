"""
Unit tests for official-store surfacing on the recursive publication tree
(promos-catalog-prices-and-official-store, slice A).

Covers:
  - `official_store_id` set on both `_build_mla_node` (root-level leaves) and
    `_build_vinculadas` (recursed children).
  - MLA absent from the ERP mirror -> `None` (fail-open, matches
    `_load_status_by_mla`'s contract).
  - `SQLAlchemyError` from the batched loader -> whole tree still returns,
    every store `None`.
  - `_compose_matches` truth table, including both-None and one-None cases.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_item_relation import MlItemRelation
from app.models.ml_publication_link import MlPublicationLink
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.api.endpoints.productos_detail import _compose_matches
from app.services.ml_publication_tree_service import (
    _load_official_store_by_mla,
    assemble_publication_tree,
)


def _seed_producto(db, item_id: int) -> None:
    if db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first() is None:
        db.add(ProductoERP(item_id=item_id, codigo=f"COD{item_id}", descripcion=f"Producto {item_id}"))
        db.flush()


def _seed_pub(db, mla: str, item_id: int) -> None:
    db.add(PublicacionML(mla=mla, item_id=item_id, pricelist_id=4, activo=True))


def _seed_link(db, mla: str, item_id: int) -> None:
    db.add(MlPublicationLink(mla=mla, item_id=item_id, catalog_listing=False))


def _seed_publicado(db, mla: str, official_store_id=None) -> None:
    db.add(MercadoLibreItemPublicado(mlp_publicationID=mla, mlp_official_store_id=official_store_id))


class TestLoadOfficialStoreByMla:
    def test_empty_input_short_circuits(self, db) -> None:
        assert _load_official_store_by_mla(db, []) == {}

    def test_batch_loads_known_stores(self, db) -> None:
        _seed_publicado(db, "MLA1", official_store_id=57997)
        _seed_publicado(db, "MLA2", official_store_id=2645)
        db.commit()

        result = _load_official_store_by_mla(db, ["MLA1", "MLA2"])

        assert result == {"MLA1": 57997, "MLA2": 2645}

    def test_failure_degrades_fail_open(self, db, monkeypatch) -> None:
        def _boom(*args, **kwargs):
            raise SQLAlchemyError("tb_mercadolibre_items_publicados unavailable")

        monkeypatch.setattr(db, "query", _boom)

        result = _load_official_store_by_mla(db, ["MLA1"])

        assert result == {}


class TestTreeSurfacesOfficialStore:
    def test_official_store_id_set_on_root_mla_node(self, db) -> None:
        _seed_producto(db, 1)
        _seed_pub(db, "MLA1", 1)
        _seed_link(db, "MLA1", 1)
        _seed_publicado(db, "MLA1", official_store_id=57997)
        db.commit()

        result = assemble_publication_tree(db, item_id=1)

        assert result.tree.children[0].official_store_id == 57997

    def test_official_store_id_set_on_vinculada_node(self, db) -> None:
        _seed_producto(db, 2)
        _seed_pub(db, "MLA_ROOT", 2)
        _seed_pub(db, "MLA_CHILD", 2)
        _seed_link(db, "MLA_ROOT", 2)
        _seed_link(db, "MLA_CHILD", 2)
        db.add(MlItemRelation(mla="MLA_ROOT", related_mla="MLA_CHILD", stock_relation=1))
        _seed_publicado(db, "MLA_ROOT", official_store_id=57997)
        _seed_publicado(db, "MLA_CHILD", official_store_id=2645)
        db.commit()

        result = assemble_publication_tree(db, item_id=2)

        root = result.tree.children[0]
        assert root.official_store_id == 57997
        child = root.children[0]
        assert child.mla == "MLA_CHILD"
        assert child.official_store_id == 2645

    def test_absent_mla_is_none(self, db) -> None:
        _seed_producto(db, 3)
        _seed_pub(db, "MLA_UNKNOWN", 3)
        _seed_link(db, "MLA_UNKNOWN", 3)
        db.commit()

        result = assemble_publication_tree(db, item_id=3)

        assert result.tree.children[0].official_store_id is None

    def test_loader_failure_degrades_fail_open_whole_tree(self, db, monkeypatch) -> None:
        _seed_producto(db, 4)
        _seed_pub(db, "MLA_ROOT4", 4)
        _seed_pub(db, "MLA_CHILD4", 4)
        _seed_link(db, "MLA_ROOT4", 4)
        _seed_link(db, "MLA_CHILD4", 4)
        db.add(MlItemRelation(mla="MLA_ROOT4", related_mla="MLA_CHILD4", stock_relation=1))
        _seed_publicado(db, "MLA_ROOT4", official_store_id=57997)
        _seed_publicado(db, "MLA_CHILD4", official_store_id=2645)
        db.commit()

        real_query = db.query

        def _boom(model, *args, **kwargs):
            if model is MercadoLibreItemPublicado.mlp_publicationID:
                raise SQLAlchemyError("tb_mercadolibre_items_publicados unavailable")
            return real_query(model, *args, **kwargs)

        monkeypatch.setattr(db, "query", _boom)

        result = assemble_publication_tree(db, item_id=4)

        root = result.tree.children[0]
        assert root.mla == "MLA_ROOT4"
        assert root.official_store_id is None
        child = root.children[0]
        assert child.official_store_id is None


class TestComposeMatches:
    def test_both_none_is_none(self) -> None:
        assert _compose_matches(None, None) is None

    def test_a_none_returns_b(self) -> None:
        b = {"MLA1": True}
        assert _compose_matches(None, b) == b

    def test_b_none_returns_a(self) -> None:
        a = {"MLA1": True}
        assert _compose_matches(a, None) == a

    def test_and_composition_true_true(self) -> None:
        a = {"MLA1": True}
        b = {"MLA1": True}
        assert _compose_matches(a, b) == {"MLA1": True}

    def test_and_composition_true_false(self) -> None:
        a = {"MLA1": True}
        b = {"MLA1": False}
        assert _compose_matches(a, b) == {"MLA1": False}

    def test_and_composition_missing_key_defaults_true(self) -> None:
        """A key present in only one map defaults to True on the missing
        side (fail-open: absence of an opinion never turns a match into a
        non-match)."""
        a = {"MLA1": True}
        b = {"MLA2": False}
        result = _compose_matches(a, b)

        assert result["MLA1"] is True
        assert result["MLA2"] is False
