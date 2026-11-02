"""The SQL listing kind and its rank (Métricas ML and Publicaciones ML order publications Clásica, 3, 6, 9, 12
cuotas) agree with `pricelist_resolver` on every input combination, on real Postgres."""

from __future__ import annotations

import itertools
from typing import Optional

import pytest
from sqlalchemy import Text, literal, select
from sqlalchemy.dialects.postgresql import ARRAY

from app.services.ml_publications.listing_kind import listing_kind, listing_rank
from app.services.ml_publications.pricelist_resolver import REASON_COFINANCIADA, REASON_OK, resolve_pricelist

KIND_BY_PRICELIST = {4: "clasica", 17: "cuotas_3", 14: "cuotas_6", 13: "cuotas_9", 23: "cuotas_12"}

TYPES = ["gold_special", "gold_pro", "free", None]
TAGS = [
    [],
    ["3x_campaign"],
    ["9x_campaign", "3x_campaign"],
    ["12x_campaign"],
    ["pcj-co-funded"],
    ["pcj-co-funded", "3x_campaign"],
    ["good_quality_thumbnail"],
]
CAMPAIGNS = [None, "3x_campaign", "6x_campaign", "9x_campaign", "12x_campaign", "24x_campaign"]


def _expected(listing_type_id: Optional[str], tags: list, campaign: Optional[str]) -> Optional[str]:
    resolution = resolve_pricelist(listing_type_id, tags, campaign)
    if resolution.reason == REASON_COFINANCIADA:
        return "clasica_cofinanciada"
    if resolution.reason == REASON_OK:
        return KIND_BY_PRICELIST[resolution.pricelist_id]
    return listing_type_id


def _kind(db, listing_type_id, tags, campaign):
    kind = listing_kind(literal(listing_type_id, Text), literal(tags, ARRAY(Text)), literal(campaign, Text))
    return db.execute(select(kind, listing_rank(kind))).one()


@pytest.mark.postgres
def test_the_sql_kind_follows_the_pricelist_resolver_on_every_combination(pg_db) -> None:
    for listing_type_id, tags, campaign in itertools.product(TYPES, TAGS, CAMPAIGNS):
        kind, _ = _kind(pg_db, listing_type_id, tags, campaign)
        assert kind == _expected(listing_type_id, tags, campaign), (listing_type_id, tags, campaign)


@pytest.mark.postgres
def test_a_null_tags_array_reads_like_no_tags(pg_db) -> None:
    kind = listing_kind(literal("gold_pro", Text), literal(None, ARRAY(Text)), literal("9x_campaign", Text))
    assert pg_db.execute(select(kind)).scalar_one() == "cuotas_9"


@pytest.mark.postgres
def test_the_rank_orders_clasica_then_3_6_9_12_cuotas_then_other_types_then_none(pg_db) -> None:
    inputs = [
        ("free", [], None),
        (None, [], None),
        ("gold_pro", ["12x_campaign"], None),
        ("gold_pro", [], None),
        ("gold_special", ["pcj-co-funded"], None),
        ("gold_pro", ["9x_campaign"], None),
        ("gold_pro", ["3x_campaign"], None),
        ("gold_special", [], None),
    ]
    ranked = sorted((_kind(pg_db, *row) for row in inputs), key=lambda kr: (kr[1], kr[0] or ""))
    assert [kind for kind, _ in ranked] == [
        "clasica",
        "clasica_cofinanciada",
        "cuotas_3",
        "cuotas_6",
        "cuotas_9",
        "cuotas_12",
        "free",
        None,
    ]
