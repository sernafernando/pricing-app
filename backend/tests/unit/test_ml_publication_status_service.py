"""
Unit tests for `ml_publication_status_service`.

The per-MLA publication status badge (active/paused/closed/under_review)
was historically resolved INLINE inside the flat
`GET /productos/{item_id}/mercadolibre` endpoint. It now lives here so the
flat panel and the recursive publication tree share ONE implementation.
These tests pin the exact precedence the endpoint had, so the extraction
stays behavior-preserving:
  - a truthy `mlp_laststatusid` wins over `mlp_active`;
  - an unmapped id degrades to `status_{id}`, never to None;
  - `mlp_active` is only consulted when there is no status id;
  - both absent -> None.
"""

from __future__ import annotations

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.services.ml_publication_status_service import (
    ML_PUBLICATION_STATUS_MAP,
    fetch_publication_status_by_mla,
    resolve_publication_status,
)


def _seed_publicado(db, mla: str, status_id: int | None = None, is_active: bool | None = None) -> None:
    db.add(
        MercadoLibreItemPublicado(
            mlp_publicationID=mla,
            mlp_lastStatusID=status_id,
            mlp_Active=is_active,
        )
    )


class TestResolvePublicationStatus:
    def test_known_status_ids_map_to_their_labels(self) -> None:
        assert resolve_publication_status(153, None) == "active"
        assert resolve_publication_status(154, None) == "paused"
        assert resolve_publication_status(155, None) == "closed"
        assert resolve_publication_status(156, None) == "under_review"

    def test_map_exposes_exactly_the_four_erp_states(self) -> None:
        assert ML_PUBLICATION_STATUS_MAP == {
            153: "active",
            154: "paused",
            155: "closed",
            156: "under_review",
        }

    def test_unknown_status_id_falls_back_to_status_prefix(self) -> None:
        """An unmapped ERP id must surface as `status_999`, not vanish —
        a new state is a visible anomaly, not a silent 'no status'."""
        assert resolve_publication_status(999, None) == "status_999"

    def test_status_id_wins_over_is_active(self) -> None:
        assert resolve_publication_status(154, True) == "paused"

    def test_falls_back_to_is_active_when_no_status_id(self) -> None:
        assert resolve_publication_status(None, True) == "active"
        assert resolve_publication_status(None, False) == "paused"

    def test_falsy_status_id_zero_is_treated_as_absent(self) -> None:
        assert resolve_publication_status(0, False) == "paused"

    def test_both_absent_returns_none(self) -> None:
        assert resolve_publication_status(None, None) is None


class TestFetchPublicationStatusByMla:
    def test_empty_input_returns_empty_dict(self, db) -> None:
        assert fetch_publication_status_by_mla(db, []) == {}

    def test_batches_every_requested_mla_in_one_query(self, db, query_counter) -> None:
        _seed_publicado(db, "MLA_ST_A", status_id=153)
        _seed_publicado(db, "MLA_ST_B", status_id=154)
        _seed_publicado(db, "MLA_ST_C", is_active=False)
        db.commit()

        with query_counter() as counter:
            result = fetch_publication_status_by_mla(db, ["MLA_ST_A", "MLA_ST_B", "MLA_ST_C"])

        assert result == {"MLA_ST_A": "active", "MLA_ST_B": "paused", "MLA_ST_C": "paused"}
        assert counter.matching("tb_mercadolibre_items_publicados") == 1

    def test_mla_absent_from_the_table_is_not_keyed(self, db) -> None:
        """Absence must stay distinguishable from a null status: the flat
        endpoint only emits the `publication_status` field for MLAs the
        ERP mirror knows about."""
        _seed_publicado(db, "MLA_ST_KNOWN", status_id=153)
        db.commit()

        result = fetch_publication_status_by_mla(db, ["MLA_ST_KNOWN", "MLA_ST_GHOST"])

        assert "MLA_ST_GHOST" not in result
        assert result["MLA_ST_KNOWN"] == "active"

    def test_row_with_no_status_signal_at_all_is_keyed_to_none(self, db) -> None:
        _seed_publicado(db, "MLA_ST_BLANK")
        db.flush()
        # `mlp_Active` declares a column default of True, which SQLAlchemy
        # applies to any INSERT that leaves it None — the "both signals
        # NULL" ERP row can only be reproduced with an explicit UPDATE.
        db.query(MercadoLibreItemPublicado).filter(
            MercadoLibreItemPublicado.mlp_publicationID == "MLA_ST_BLANK"
        ).update({MercadoLibreItemPublicado.mlp_Active: None}, synchronize_session=False)
        db.commit()

        assert fetch_publication_status_by_mla(db, ["MLA_ST_BLANK"]) == {"MLA_ST_BLANK": None}
