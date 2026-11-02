"""The SQL listing kind and its rank (Métricas ML and Publicaciones ML order publications Clásica, 3, 6, 9, 12
cuotas) agree with `pricelist_resolver` on every input combination, on real Postgres."""

from __future__ import annotations

import itertools
import re
from pathlib import Path
from typing import Optional

import pytest
from sqlalchemy import Text, column, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY

from app.services.ml_publications.listing_kind import KIND_LABELS, KIND_RANKS, kind_label, listing_kind, listing_rank
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
CAMPAIGNS = [None, "", "3x_campaign", "6x_campaign", "9x_campaign", "12x_campaign", "24x_campaign"]


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


def test_the_rank_reads_each_campaign_tag_position_a_bounded_number_of_times() -> None:
    # Publicaciones ML orders its whole filtered set by the rank of an expression (no temp table to read a column
    # from): each CASE branch that repeats the kind repeats every campaign-tag lookup under it.
    kind = listing_kind(column("listing_type_id"), column("tags"), column("installments_campaign"))
    sql = str(select(listing_rank(kind)).compile(dialect=postgresql.dialect()))
    assert sql.count("array_position") <= 48


# The list's Tipo badge, whose words the CSV repeats (`KIND_LABELS`).
BADGE = Path(__file__).resolve().parents[4] / "frontend/src/components/publicacionesMl/ListingKindBadge.jsx"


def _badge_labels() -> dict[str, str]:
    """The badge's `KINDS` labels and its `OTHER_TYPES` names, read from its source."""
    source = BADGE.read_text(encoding="utf-8")
    kinds = re.search(r"const KINDS = \{(.*?)\n\};", source, re.S).group(1)
    others = re.search(r"const OTHER_TYPES = \{(.*?)\n\};", source, re.S).group(1)
    labels = dict(re.findall(r"(\w+): \{ label: '([^']+)'", kinds))
    labels.update(re.findall(r"(\w+): '([^']+)'", others))
    return labels


def test_the_csv_words_are_the_badge_words() -> None:
    assert KIND_LABELS == _badge_labels()


def test_every_ranked_kind_reads_as_a_word_and_an_unnamed_type_keeps_its_id() -> None:
    assert {kind: kind_label(kind) for kind in KIND_RANKS} == {
        "clasica": "Clásica",
        "clasica_cofinanciada": "Clásica",
        "cuotas_3": "3 cuotas",
        "cuotas_6": "6 cuotas",
        "cuotas_9": "9 cuotas",
        "cuotas_12": "12 cuotas",
    }
    # ML's other types by ML's names; `gold_pro` stays a kind only with a campaign the resolver does not know.
    assert [kind_label(kind) for kind in ("free", "bronze", "silver", "gold", "gold_premium", "gold_pro")] == [
        "Gratuita",
        "Bronce",
        "Plata",
        "Oro",
        "Oro Premium",
        "Premium",
    ]
    assert kind_label("some_new_type") == "some_new_type"
    assert kind_label(None) is None
