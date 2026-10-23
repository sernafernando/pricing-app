"""
Unit tests for `ml_publication_status_service`.

Owner decision: the ML publications store (`ml_items`) is the source of
truth for a publication's status everywhere. The per-MLA status chip used
to come from the ERP mirror (`tb_mercadolibre_items_publicados`), while the
promotions panel's "Publicación pausada" banner came from `ml_items` — so
the same MLA could show "Activa" and the paused banner at once. These tests
pin the `ml_items`-backed contract:
  - `status`/`sub_status` are ML's own values, verbatim;
  - a gone or never-existing publication wins over its last status;
  - an MLA without an `ml_items` row (or without a fetched status) is keyed
    to the explicit `no_ml_data` status, never to "active";
  - every requested MLA is keyed when the read succeeds, ONE query;
  - a failing read is fail-open: an empty dict, never an exception.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.ml_publications import MlItem
from app.services.ml_publications import queue
from app.services.ml_publications.resources import CORE_RESOURCE
from app.services.ml_publication_status_service import (
    GONE,
    ML_PUBLICATION_STATUS_MAP,
    NEVER_EXISTED,
    NO_ML_DATA,
    MlPublicationStatus,
    fetch_publication_status_by_mla,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _seed_ml_item(db, mla: str, **fields) -> None:
    db.add(MlItem(item_id=mla, **fields))


class TestErpStatusMapStaysExported:
    def test_map_exposes_exactly_the_four_erp_states(self) -> None:
        """`ml_daily_metrics/board.py` still filters the ERP mirror by these ids."""
        assert ML_PUBLICATION_STATUS_MAP == {
            153: "active",
            154: "paused",
            155: "closed",
            156: "under_review",
        }


class TestFetchPublicationStatusByMla:
    def test_empty_input_returns_empty_dict_without_querying(self, db, query_counter) -> None:
        with query_counter() as counter:
            assert fetch_publication_status_by_mla(db, []) == {}
        assert counter.matching("ml_items") == 0

    def test_reads_status_and_sub_status_from_ml_items_in_one_query(self, db, query_counter) -> None:
        _seed_ml_item(db, "MLA_ST_A", status="active", sub_status=[])
        _seed_ml_item(db, "MLA_ST_B", status="paused", sub_status=["paused_by_seller"])
        _seed_ml_item(db, "MLA_ST_C", status="under_review", sub_status=None)
        _seed_ml_item(db, "MLA_ST_D", status="inactive")
        _seed_ml_item(db, "MLA_ST_E", status="closed")
        db.commit()

        with query_counter() as counter:
            result = fetch_publication_status_by_mla(db, ["MLA_ST_A", "MLA_ST_B", "MLA_ST_C", "MLA_ST_D", "MLA_ST_E"])

        assert result == {
            "MLA_ST_A": MlPublicationStatus("active", []),
            "MLA_ST_B": MlPublicationStatus("paused", ["paused_by_seller"]),
            "MLA_ST_C": MlPublicationStatus("under_review", None),
            "MLA_ST_D": MlPublicationStatus("inactive", None),
            "MLA_ST_E": MlPublicationStatus("closed", None),
        }
        assert counter.matching("ml_items") == 1

    def test_mla_without_an_ml_items_row_is_no_ml_data_never_active(self, db) -> None:
        _seed_ml_item(db, "MLA_ST_KNOWN", status="active")
        db.commit()

        result = fetch_publication_status_by_mla(db, ["MLA_ST_KNOWN", "MLA_ST_GHOST"])

        assert result["MLA_ST_KNOWN"].status == "active"
        assert result["MLA_ST_GHOST"] == MlPublicationStatus(NO_ML_DATA, None)

    def test_row_not_fetched_yet_is_no_ml_data(self, db) -> None:
        _seed_ml_item(db, "MLA_ST_BLANK")
        db.commit()

        assert fetch_publication_status_by_mla(db, ["MLA_ST_BLANK"])["MLA_ST_BLANK"].status == NO_ML_DATA

    def test_gone_wins_over_the_last_status(self, db) -> None:
        _seed_ml_item(db, "MLA_ST_GONE", status="active", gone_at=NOW)
        db.commit()

        assert fetch_publication_status_by_mla(db, ["MLA_ST_GONE"])["MLA_ST_GONE"].status == GONE

    def test_never_existed_wins_over_everything(self, db) -> None:
        _seed_ml_item(db, "MLA_ST_NEVER", status=None, never_existed=True, gone_at=NOW)
        db.commit()

        assert fetch_publication_status_by_mla(db, ["MLA_ST_NEVER"])["MLA_ST_NEVER"].status == NEVER_EXISTED

    def test_store_read_failure_is_fail_open(self, db) -> None:
        with patch.object(db, "query", side_effect=RuntimeError("store down")):
            assert fetch_publication_status_by_mla(db, ["MLA_ST_A"]) == {}


class TestFailedReadLeavesTheCallerSessionAlone:
    """The read runs on the CALLER's session (the flat productos endpoint, the
    tree assembly, the promotions banner). A failing `ml_items` read must roll
    back only its own SAVEPOINT — never the caller's transaction, which would
    drop its pending objects and expire everything it already loaded."""

    def test_pending_and_loaded_objects_survive_a_failed_read(self, db) -> None:
        _seed_ml_item(db, "MLA_ST_LOADED", status="active")
        db.commit()
        loaded = db.query(MlItem).filter(MlItem.item_id == "MLA_ST_LOADED").one()
        loaded.title = "edited, not flushed"
        pending = MlItem(item_id="MLA_ST_PENDING", status="paused")
        db.add(pending)

        real_query = db.query

        def failing_ml_items_read(*entities, **kwargs):
            if entities and getattr(entities[0], "class_", None) is MlItem:
                raise RuntimeError("ml_items unavailable")
            return real_query(*entities, **kwargs)

        with patch.object(db, "query", side_effect=failing_ml_items_read):
            assert fetch_publication_status_by_mla(db, ["MLA_ST_LOADED"]) == {}

        assert pending in db
        assert loaded in db
        assert "title" in loaded.__dict__, "the caller's loaded object was expired"
        assert loaded.title == "edited, not flushed"
        db.flush()
        assert db.query(MlItem).filter(MlItem.item_id == "MLA_ST_PENDING").one().status == "paused"


@pytest.mark.postgres
def test_postgres_aborted_read_keeps_the_caller_transaction_usable(pg_db) -> None:
    """On Postgres a failed statement aborts the whole transaction unless it ran
    inside a SAVEPOINT: the caller's already-flushed work must survive and its
    session must stay usable after a failed `ml_items` read."""
    from sqlalchemy import text

    from app.models.item_transaction import ItemTransaction

    pg_db.add(ItemTransaction(it_transaction=987654321, item_id=42))
    pg_db.flush()

    real_query = pg_db.query

    def aborting_read(*entities, **kwargs):
        pg_db.execute(text("SELECT 1/0"))  # a real server-side error
        return real_query(*entities, **kwargs)

    with patch.object(pg_db, "query", side_effect=aborting_read):
        assert fetch_publication_status_by_mla(pg_db, ["MLA_ST_PG"]) == {}

    survivor = pg_db.execute(text("SELECT item_id FROM tb_item_transactions WHERE it_transaction = 987654321"))
    assert survivor.scalar_one() == 42


class TestAnMlaTheStoreNeverSawIsFetched:
    """Owner (2026-10-23): "MLA1816578183 → status: inactive, sub_status: [forbidden, deleted] en las promos lo
    sigue mostrando con 'sin datos de ml' no que está deleted". The store discovers items by scanning the seller's
    listing, which never returns a deleted item: an MLA deleted before the store existed never gets a row. Each
    MLA a reader asks for without a row is queued for a direct fetch (ML answers its real status, or 404)."""

    def test_an_mla_without_a_row_is_queued_for_a_direct_fetch(self, db) -> None:
        _seed_ml_item(db, "MLA_Q_KNOWN", status="active")
        _seed_ml_item(db, "MLA_Q_BLANK")
        db.commit()

        with patch("app.services.ml_publication_status_service._enqueue") as enqueue:
            result = fetch_publication_status_by_mla(db, ["MLA_Q_KNOWN", "MLA_Q_BLANK", "MLA_Q_GHOST", "MLA_Q_GHOST"])

        assert result["MLA_Q_GHOST"] == MlPublicationStatus(NO_ML_DATA, None)
        (entries,), _ = enqueue.call_args
        # Only the one the store has no row for (a row not fetched yet is already the store's business); once.
        assert [(e.kind, e.entity_id, e.lane, e.resources) for e in entries] == [
            ("item", "MLA_Q_GHOST", queue.LANE_RECONCILE, (CORE_RESOURCE,))
        ]

    def test_nothing_is_queued_when_every_mla_has_a_row(self, db) -> None:
        _seed_ml_item(db, "MLA_Q_ROW", status="paused")
        db.commit()

        with patch("app.services.ml_publication_status_service._enqueue") as enqueue:
            fetch_publication_status_by_mla(db, ["MLA_Q_ROW"])

        enqueue.assert_not_called()

    def test_a_failing_enqueue_still_answers_the_statuses(self, db) -> None:
        with patch("app.services.ml_publication_status_service._enqueue", side_effect=RuntimeError("down")):
            result = fetch_publication_status_by_mla(db, ["MLA_Q_DOWN"])

        assert result == {"MLA_Q_DOWN": MlPublicationStatus(NO_ML_DATA, None)}
