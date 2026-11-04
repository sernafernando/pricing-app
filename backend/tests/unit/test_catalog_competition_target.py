"""Resolve which MLA gets a catalog-competition refresh for a hay_mejores flag."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.catalog_competition_target import mla_for_catalog_competition_refresh


def test_returns_self_when_catalog_listing() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = SimpleNamespace(
        item_id="MLA-CAT",
        catalog_listing=True,
    )
    assert mla_for_catalog_competition_refresh(db, "MLA-CAT") == "MLA-CAT"


def test_returns_none_when_item_missing() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    assert mla_for_catalog_competition_refresh(db, "MLA-X") is None


def test_returns_catalog_sibling_when_classic_linked() -> None:
    db = MagicMock()
    item_q = MagicMock()
    item_q.filter.return_value.one_or_none.return_value = SimpleNamespace(
        item_id="MLA-CLASSIC",
        catalog_listing=False,
    )
    link_q = MagicMock()
    link_q.filter.return_value.one_or_none.return_value = SimpleNamespace(producto_item_id=4101)
    siblings_q = MagicMock()
    siblings_q.filter.return_value.all.return_value = [
        SimpleNamespace(item_id="MLA-CLASSIC"),
        SimpleNamespace(item_id="MLA-CAT"),
    ]
    catalog_q = MagicMock()
    catalog_q.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(item_id="MLA-CAT")

    # query() is called for MlItem, then product link, then sibling ids, then catalog pick
    db.query.side_effect = [item_q, link_q, siblings_q, catalog_q]

    assert mla_for_catalog_competition_refresh(db, "MLA-CLASSIC") == "MLA-CAT"
    assert link_q.filter.called


def test_returns_none_when_no_catalog_sibling() -> None:
    db = MagicMock()
    item_q = MagicMock()
    item_q.filter.return_value.one_or_none.return_value = SimpleNamespace(
        item_id="MLA-CLASSIC",
        catalog_listing=False,
    )
    link_q = MagicMock()
    link_q.filter.return_value.one_or_none.return_value = SimpleNamespace(producto_item_id=4101)
    siblings_q = MagicMock()
    siblings_q.filter.return_value.all.return_value = [SimpleNamespace(item_id="MLA-CLASSIC")]
    catalog_q = MagicMock()
    catalog_q.filter.return_value.order_by.return_value.first.return_value = None
    db.query.side_effect = [item_q, link_q, siblings_q, catalog_q]
    assert mla_for_catalog_competition_refresh(db, "MLA-CLASSIC") is None
