"""The ML topic subscription checklist (spec "Topic subscription checklist") stays accurate."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.ml_publications.intake import TOPIC_PATTERNS, topic_mappings
from tests.services.ml_publications.conftest import WEBHOOK_SAMPLES, load_fixture

DOC = Path(__file__).resolve().parents[3] / "docs" / "ml-publications-topics-checklist.md"
OPTIONAL_TOPICS = (
    "items_prices",
    "stock-locations",
    "user-products-families",
    "catalog_item_competition_status",
    "public_offers",
    "public_candidates",
)
NEVER_READ = ("price_suggestion", "catalog_suggestions", "fbm_stock_operations", "flex-handshakes")


@pytest.fixture(scope="module")
def doc() -> str:
    assert DOC.exists(), f"missing {DOC}"
    return DOC.read_text(encoding="utf-8")


def test_items_is_the_required_topic(doc) -> None:
    assert "`items`" in doc
    assert "required" in doc.lower()


@pytest.mark.parametrize("topic", OPTIONAL_TOPICS)
def test_every_optional_topic_is_listed_with_its_exact_production_name(doc, topic) -> None:
    assert f"`{topic}`" in doc


def test_there_is_no_user_products_topic(doc) -> None:
    assert "no `user_products` topic" in doc


def test_all_topics_were_subscribed_and_arriving_on_2026_10_06_with_the_captured_volumes(doc) -> None:
    assert "2026-10-06" in doc
    volumes = {row["topic"]: row["resources_last_hour"] for row in load_fixture(WEBHOOK_SAMPLES)["volume_last_hour"]}
    for topic in ("items", *OPTIONAL_TOPICS):
        rows = [line for line in doc.splitlines() if line.startswith("|") and f"`{topic}`" in line]
        assert rows and re.search(rf"\b{volumes[topic]}\b", rows[0]), f"volume of {topic} missing from its table row"


@pytest.mark.parametrize("topic", NEVER_READ)
def test_unmapped_topics_are_named_as_never_read(doc, topic) -> None:
    assert f"`{topic}`" in doc
    assert "never read" in doc.lower()


def test_the_readonly_count_to_confirm_a_topic_is_documented(doc) -> None:
    assert "SELECT count(*) FROM webhook_latest WHERE topic =" in doc
    assert "intake.topics" in doc


def test_the_fallback_coverage_is_stated(doc) -> None:
    lowered = doc.lower()
    assert "full-bundle refresh" in lowered
    assert "rescans" in lowered


def test_topics_without_a_fixed_pattern_are_documented_as_such(doc) -> None:
    unmapped = [t for t in OPTIONAL_TOPICS if t not in TOPIC_PATTERNS]
    assert unmapped == ["stock-locations", "user-products-families"]
    assert "real `webhook_latest` row" in doc


def test_enabling_the_price_fetchers_is_documented_with_its_gate_ages_and_rollback(doc) -> None:
    assert "## Enabling the description, prices and sale_price fetchers" in doc
    for needle in ("bundle_resources", "min_age_seconds", "description", "6 h", "reference_date", "Rollback"):
        assert needle in doc, needle


def promotions_section(doc: str) -> str:
    start = doc.index("## Enabling the promotions fetcher")
    nxt = doc.find("\n## ", start + 1)
    return doc[start : nxt if nxt != -1 else len(doc)]


def test_enabling_promotions_is_documented_with_both_gates_the_debounce_and_the_rollback(doc) -> None:
    section = promotions_section(doc)
    for needle in (
        "promotions.enabled",
        "bundle_resources",
        "intake.topics",
        "`public_offers`",
        "`public_candidates`",
        "60 s",
        "300 s",
        "Rollback",
        "ml_item_promotions",
    ):
        assert needle in section, needle


def test_the_promotions_cost_note_carries_the_measured_volumes_and_the_budget_share(doc) -> None:
    section = promotions_section(doc)
    volumes = {row["topic"]: row["resources_last_hour"] for row in load_fixture(WEBHOOK_SAMPLES)["volume_last_hour"]}
    assert (volumes["public_candidates"], volumes["public_offers"]) == (144, 24)
    for needle in ("144", "24", "about 170 items per hour", "about 4k per day", "about 0.05 req/s", "2 req/s"):
        assert needle in section, needle


def test_the_documented_promotions_topic_map_is_accepted_by_intake(doc) -> None:
    section = promotions_section(doc)
    blocks = re.findall(r"```json\n(.*?)\n```", section, flags=re.DOTALL)
    assert len(blocks) == 1
    topics = json.loads(blocks[0])

    mappings = topic_mappings(topics)
    assert sorted((m.topic, m.resources, m.debounce is not None) for m in mappings) == [
        ("items", ("bundle",), False),
        ("public_candidates", ("promotions",), True),
        ("public_offers", ("promotions",), True),
    ]
