"""ml-ads-display-contributions S2 -- `channel` on `ml_ads_campaign_contributions`.

A contribution is for Product Ads or for Display. Rows loaded before the column existed are Product Ads. A Display
contribution may leave `campaign_id` NULL: the whole Display account of its advertiser. Downgrading would lose what
tells a Display contribution from a Product Ads one, so it refuses while any Display row exists. Runs in a throwaway
Postgres schema built by the earlier contribution migrations.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.services.ml_ads.test_account_level_migration import _script_directory
from tests.services.ml_ads.test_contributions_migration import (
    _INSERT,
    _SETTLEMENT_PATH,
    run_migration,
    throwaway_schema,
)

REVISION = "20261229_ml_ads_contribution_channel"
_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{REVISION}.py"
_INSERT_CHANNEL = (
    "INSERT INTO ml_ads_campaign_contributions (advertiser_id, campaign_id, channel, kind, value, date_from, "
    "date_to, created_by_id, updated_by_id) VALUES (25713, :campaign, :channel, 'percentage', 10, '2026-10-01', "
    "'2026-10-31', 7, 7)"
)
_ROWS = "SELECT campaign_id, channel FROM ml_ads_campaign_contributions ORDER BY id"


def _rows_before_the_column(eng) -> None:
    run_migration(eng, "upgrade")
    run_migration(eng, "upgrade", _SETTLEMENT_PATH)
    with eng.begin() as conn:
        conn.execute(text(_INSERT), {"kind": "percentage", "value": "30", "desde": "2026-10-01", "hasta": "2026-10-31"})
    run_migration(eng, "upgrade", _PATH)


def _columns(eng) -> dict[str, str]:
    with eng.connect() as conn:
        return dict(
            conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'ml_ads_campaign_contributions'"
                )
            ).all()
        )


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    assert script.get_revision(REVISION).down_revision == "20261224_gestion_full_envio_last_polled"
    [head] = script.get_heads()
    assert REVISION in {r.revision for r in script.walk_revisions(base="base", head=head)}


@pytest.mark.postgres
def test_existing_rows_become_product_ads_and_campaign_id_turns_nullable() -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with eng.connect() as conn:
            assert [tuple(r) for r in conn.execute(text(_ROWS))] == [(351001, "product_ads")]
        columns = _columns(eng)
        assert (columns["channel"], columns["campaign_id"]) == ("NO", "YES")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "campaign, channel",
    [(None, "product_ads"), (335306, "brand_ads"), (None, "brand_ads")],
    ids=["product-ads-without-campaign", "unknown-channel", "unknown-channel-whole-account"],
)
def test_the_database_rejects_rows_that_break_the_channel_rules(campaign, channel) -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with pytest.raises(IntegrityError), eng.begin() as conn:
            conn.execute(text(_INSERT_CHANNEL), {"campaign": campaign, "channel": channel})


@pytest.mark.postgres
@pytest.mark.parametrize("campaign", [None, 335306], ids=["whole-account", "one-campaign"])
def test_a_display_row_is_accepted_with_or_without_a_campaign(campaign) -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with eng.begin() as conn:
            conn.execute(text(_INSERT_CHANNEL), {"campaign": campaign, "channel": "display"})
        with eng.connect() as conn:
            assert [tuple(r) for r in conn.execute(text(_ROWS))] == [
                (351001, "product_ads"),
                (campaign, "display"),
            ]


@pytest.mark.postgres
def test_the_existing_rules_still_hold() -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with pytest.raises(IntegrityError), eng.begin() as conn:
            conn.execute(
                text(_INSERT), {"kind": "percentage", "value": "101", "desde": "2026-11-01", "hasta": "2026-11-30"}
            )


@pytest.mark.postgres
def test_downgrade_without_display_rows_drops_the_column_and_keeps_the_rows() -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        run_migration(eng, "downgrade", _PATH)
        columns = _columns(eng)
        assert "channel" not in columns and columns["campaign_id"] == "NO"
        with eng.connect() as conn:
            assert conn.execute(text("SELECT campaign_id FROM ml_ads_campaign_contributions")).scalars().all() == [
                351001
            ]


@pytest.mark.postgres
def test_downgrade_refuses_while_a_display_row_exists_and_changes_nothing() -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with eng.begin() as conn:
            conn.execute(text(_INSERT_CHANNEL), {"campaign": None, "channel": "display"})
        with pytest.raises(RuntimeError, match="1 Display contribution"):
            run_migration(eng, "downgrade", _PATH)
        assert _columns(eng)["channel"] == "NO"
        with eng.connect() as conn:
            assert [tuple(r) for r in conn.execute(text(_ROWS))] == [(351001, "product_ads"), (None, "display")]
