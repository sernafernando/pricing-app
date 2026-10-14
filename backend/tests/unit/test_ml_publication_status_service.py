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

from app.models.ml_publications import MlItem
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
