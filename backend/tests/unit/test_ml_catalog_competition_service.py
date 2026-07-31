"""
RED/GREEN — `app.services.ml_catalog_competition_service`
(promos-catalog-prices-and-official-store, slice C1b).

Spec coverage (design #1210 section 3.3-3.6, spec #1209 C1.4-C1.7):
  - bucket key derivation: same listing_type_id + differing labels -> same
    bucket; same listing_type_id + differing installment interest -> DIFFERENT
    buckets; unresolvable input -> "unknown"/"0", never raises.
  - our row identified strictly by item_id == queried MLA; not found ->
    our_bucket_key is None, every same_bucket False, is_cheaper_than_us None
    everywhere, still fetch_status='ok'.
  - `_to_ars`: ARS passthrough; USD + tipo_cambio -> converted; USD without
    tipo_cambio -> None (NEVER the raw passthrough number — this is the money
    guard the whole slice exists to protect).
  - `_resolve_pricing_context` resolved EXACTLY ONCE per MLA regardless of
    competitor count (decision #8 regression guard).
  - not_catalog / error fetch outcomes persist a row with competitors=[].
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ml_catalog_competition_service import (
    _bucket_key,
    _normalize_installments,
    _to_ars,
    obtener_ultimo_snapshot,
    refrescar_competencia_catalogo,
    undercutting_competitors,
)


# ── _to_ars — the money-path guard ───────────────────────────────────


class TestToArs:
    def test_none_price_returns_none(self) -> None:
        assert _to_ars(None, "ARS", 1000.0) is None

    def test_ars_price_passes_through_unchanged(self) -> None:
        assert _to_ars(1000.0, "ARS", None) == 1000.0

    def test_usd_with_tipo_cambio_converts(self) -> None:
        assert _to_ars(10.0, "USD", 1000.0) == 10000.0

    def test_usd_without_tipo_cambio_returns_none_never_passthrough(self) -> None:
        """THE test that pins the guard. `convertir_a_pesos` itself would
        fall through and return 10.0 unchanged (fail-open) when
        `tipo_cambio` is falsy — that is correct for our own cost but
        catastrophic for a competitor price, making them look ~1000x
        cheaper. `_to_ars` must return None instead, never the raw
        number."""
        assert _to_ars(10.0, "USD", None) is None
        assert _to_ars(10.0, "USD", 0) is None
        assert _to_ars(10.0, "USD", 0.0) is None

    def test_unknown_currency_returns_none(self) -> None:
        assert _to_ars(10.0, "BRL", 1000.0) is None


# ── _normalize_installments / _bucket_key ────────────────────────────


class TestNormalizeInstallments:
    def test_none_installments_returns_zero(self) -> None:
        assert _normalize_installments({"installments": None}) == "0"

    def test_absent_installments_returns_zero(self) -> None:
        assert _normalize_installments({}) == "0"

    def test_interest_free_installments(self) -> None:
        entry = {"installments": {"quantity": 6, "rate": 0}}
        assert _normalize_installments(entry) == "6"

    def test_interest_bearing_installments_marked_distinctly(self) -> None:
        entry = {"installments": {"quantity": 6, "rate": 15.5}}
        assert _normalize_installments(entry) == "6c"

    def test_interest_free_and_bearing_same_count_differ(self) -> None:
        free = _normalize_installments({"installments": {"quantity": 3, "rate": 0}})
        bearing = _normalize_installments({"installments": {"quantity": 3, "rate": 10}})
        assert free != bearing


class TestBucketKey:
    def test_same_listing_type_different_labels_same_bucket(self) -> None:
        a = _bucket_key({"listing_type_id": "gold_special", "listing_label": "Clásica"})
        b = _bucket_key({"listing_type_id": "gold_special", "listing_label": "Clasica (premium)"})
        assert a == b

    def test_same_listing_type_different_installments_different_bucket(self) -> None:
        a = _bucket_key({"listing_type_id": "gold_special", "installments": {"quantity": 3, "rate": 0}})
        b = _bucket_key({"listing_type_id": "gold_special", "installments": {"quantity": 6, "rate": 0}})
        assert a != b

    def test_missing_listing_type_id_degrades_to_unknown(self) -> None:
        assert _bucket_key({}).startswith("unknown|")

    def test_never_raises_on_garbage_input(self) -> None:
        assert _bucket_key({"listing_type_id": None, "installments": "garbage"}) is not None


# ── refrescar_competencia_catalogo ───────────────────────────────────


def _run(coro):
    return asyncio.run(coro)


PAYLOAD_OK = {
    "catalog_product_id": "MLA_CAT_1",
    "competitors": [
        {
            "item_id": "MLA_US",
            "seller_id": 111,
            "nickname": "US",
            "price": 1000.0,
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
            "listing_label": "Clásica",
            "installments": None,
        },
        {
            "item_id": "MLA_CHEAPER",
            "seller_id": 222,
            "nickname": "RIVAL",
            "price": 900.0,
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
            "listing_label": "Clásica",
            "installments": None,
        },
        {
            "item_id": "MLA_USD_NO_TC",
            "seller_id": 333,
            "nickname": "RIVAL_USD",
            "price": 5.0,
            "currency_id": "USD",
            "listing_type_id": "gold_special",
            "listing_label": "Clásica",
            "installments": None,
        },
    ],
}


class TestRefrescarCompetenciaCatalogo:
    def _patch_context(self, context_return, tc_return=None):
        return (
            patch(
                "app.services.ml_catalog_competition_service._resolve_pricing_context",
                return_value=context_return,
            ),
            patch(
                "app.services.ml_catalog_competition_service.obtener_tipo_cambio_actual",
                return_value=tc_return,
            ),
            patch(
                "app.services.ml_catalog_competition_service._markup_con_contexto",
                return_value=12.5,
            ),
        )

    def test_ok_payload_persists_row_with_our_row_and_cheaper_competitor(self) -> None:
        db = MagicMock()
        context = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "ok", "payload": PAYLOAD_OK})

        p1, p2, p3 = self._patch_context(context, tc_return=None)
        with p1, p2, p3:
            with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
                rows = _run(refrescar_competencia_catalogo(db, ["MLA_US"]))

        assert len(rows) == 1
        row = rows[0]
        assert row.fetch_status == "ok"
        assert row.our_item_id == "MLA_US"
        assert row.our_price == 1000.0
        assert row.competitor_count == 3

        competitors_by_id = {c["item_id"]: c for c in row.competitors}
        assert competitors_by_id["MLA_CHEAPER"]["is_cheaper_than_us"] is True
        assert competitors_by_id["MLA_CHEAPER"]["same_bucket"] is True
        # Unconvertible USD competitor: excluded from comparison, never hidden.
        usd_entry = competitors_by_id["MLA_USD_NO_TC"]
        assert usd_entry["price_ars"] is None
        assert usd_entry["currency_unconvertible"] is True
        assert usd_entry["is_cheaper_than_us"] is None
        assert usd_entry["markup"] is None

        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_pricing_context_resolved_exactly_once_per_mla(self) -> None:
        """Decision #8 regression guard: N competitors must not trigger N
        calls to `_resolve_pricing_context`."""
        db = MagicMock()
        context = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "ok", "payload": PAYLOAD_OK})

        with (
            patch(
                "app.services.ml_catalog_competition_service._resolve_pricing_context",
                return_value=context,
            ) as mock_resolve,
            patch("app.services.ml_catalog_competition_service.obtener_tipo_cambio_actual", return_value=None),
            patch("app.services.ml_catalog_competition_service._markup_con_contexto", return_value=12.5),
            patch("app.services.ml_catalog_competition_service.ml_webhook_client", client),
        ):
            _run(refrescar_competencia_catalogo(db, ["MLA_US"]))

        assert mock_resolve.call_count == 1

    def test_our_row_absent_from_payload_never_falsely_claims_cheaper(self) -> None:
        db = MagicMock()
        context = MagicMock()
        client = MagicMock()
        payload = {
            "catalog_product_id": "MLA_CAT_1",
            "competitors": [
                {
                    "item_id": "MLA_OTHER",
                    "price": 900.0,
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                    "listing_label": "Clásica",
                    "installments": None,
                }
            ],
        }
        client.get_catalog_competition = AsyncMock(return_value={"status": "ok", "payload": payload})

        with (
            patch(
                "app.services.ml_catalog_competition_service._resolve_pricing_context",
                return_value=context,
            ),
            patch("app.services.ml_catalog_competition_service.obtener_tipo_cambio_actual", return_value=None),
            patch("app.services.ml_catalog_competition_service._markup_con_contexto", return_value=None),
            patch("app.services.ml_catalog_competition_service.ml_webhook_client", client),
        ):
            rows = _run(refrescar_competencia_catalogo(db, ["MLA_NOT_IN_PAYLOAD"]))

        row = rows[0]
        assert row.our_item_id is None
        assert row.our_bucket_key is None
        for competitor in row.competitors:
            assert competitor["same_bucket"] is False
            assert competitor["is_cheaper_than_us"] is None

    def test_not_catalog_status_persists_row_with_no_competitors(self) -> None:
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "not_catalog", "detail": "HTTP 400 body"})

        with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
            rows = _run(refrescar_competencia_catalogo(db, ["MLA_NOT_CATALOG"]))

        row = rows[0]
        assert row.fetch_status == "not_catalog"
        assert row.competitors == []
        assert row.competitor_count == 0
        assert row.error_detail == "HTTP 400 body"

    def test_error_status_persists_row_with_no_competitors(self) -> None:
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "error", "detail": "HTTP 500"})

        with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
            rows = _run(refrescar_competencia_catalogo(db, ["MLA_ERR"]))

        row = rows[0]
        assert row.fetch_status == "error"
        assert row.competitors == []
        assert row.competitor_count == 0
        assert row.error_detail == "HTTP 500"

    def test_multiple_mlas_produce_one_row_each(self) -> None:
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "not_catalog", "detail": "nope"})

        with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
            rows = _run(refrescar_competencia_catalogo(db, ["MLA_A", "MLA_B"]))

        assert len(rows) == 2
        assert client.get_catalog_competition.await_count == 2

    def test_no_pricing_context_yields_none_markup_but_still_persists(self) -> None:
        """Our own publication cannot be resolved (context None) -> every
        competitor markup is None, but the row (including the competitor
        listing) is still persisted; the pricing failure does not turn
        into a fetch_status='error'."""
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "ok", "payload": PAYLOAD_OK})

        with (
            patch(
                "app.services.ml_catalog_competition_service._resolve_pricing_context",
                return_value=None,
            ),
            patch("app.services.ml_catalog_competition_service.obtener_tipo_cambio_actual", return_value=None),
            patch("app.services.ml_catalog_competition_service.ml_webhook_client", client),
        ):
            rows = _run(refrescar_competencia_catalogo(db, ["MLA_US"]))

        row = rows[0]
        assert row.fetch_status == "ok"
        for competitor in row.competitors:
            assert competitor["markup"] is None


# ── Review findings: degraded buckets and batch durability ───────────


PAYLOAD_BOTH_UNKNOWN_BUCKET = {
    "catalog_product_id": "MLA_CAT_2",
    "competitors": [
        # Our own row: no listing_type_id, so its bucket degrades to unknown.
        {"item_id": "MLA_US", "price": 1000.0, "currency_id": "ARS", "seller_id": "1"},
        # A competitor whose bucket ALSO degrades to unknown. Two unresolvable
        # buckets are not evidence of comparability.
        {"item_id": "MLA_OTHER", "price": 400.0, "currency_id": "ARS", "seller_id": "2"},
    ],
}


class TestDegradedBucketIsNeverComparable:
    """`_bucket_key` collapses unresolvable input to "unknown|0". When OUR row
    also degrades, every degraded competitor produces the same string, so a
    naive equality check reports same_bucket=True and computes
    is_cheaper_than_us across publications that are not comparable at all.

    That is the "falsely claim cheaper than us" direction this module exists
    to forbid: it would tell the user a Clasica listing undercuts their
    12-cuotas Premium and invite a real price cut.
    """

    def _patch_context(self, context_return):
        return (
            patch(
                "app.services.ml_catalog_competition_service._resolve_pricing_context",
                return_value=context_return,
            ),
            patch(
                "app.services.ml_catalog_competition_service.obtener_tipo_cambio_actual",
                return_value=None,
            ),
            patch(
                "app.services.ml_catalog_competition_service._markup_con_contexto",
                return_value=12.5,
            ),
        )

    def test_unknown_bucket_on_both_sides_is_not_same_bucket(self) -> None:
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(
            return_value={"status": "ok", "payload": PAYLOAD_BOTH_UNKNOWN_BUCKET}
        )

        p1, p2, p3 = self._patch_context(MagicMock())
        with p1, p2, p3:
            with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
                rows = _run(refrescar_competencia_catalogo(db, ["MLA_US"]))

        other = {c["item_id"]: c for c in rows[0].competitors}["MLA_OTHER"]
        assert other["same_bucket"] is False, "two unresolvable buckets must not be treated as equal"
        assert other["is_cheaper_than_us"] is None, "must not claim a non-comparable listing undercuts us"


class TestBatchDurability:
    """A batch is expensive: every MLA costs 3+N calls through ml-webhook's
    globally throttled ML proxy. One bad MLA must not discard the rows already
    paid for — the loop commits once at the end, so an exception before the
    commit loses the ENTIRE batch.
    """

    def _patch_context(self):
        return (
            patch(
                "app.services.ml_catalog_competition_service._resolve_pricing_context",
                return_value=MagicMock(),
            ),
            patch(
                "app.services.ml_catalog_competition_service.obtener_tipo_cambio_actual",
                return_value=None,
            ),
            patch(
                "app.services.ml_catalog_competition_service._markup_con_contexto",
                return_value=12.5,
            ),
        )

    def test_client_exception_degrades_to_an_error_row_and_keeps_the_batch(self) -> None:
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(
            side_effect=[RuntimeError("boom"), {"status": "ok", "payload": PAYLOAD_OK}]
        )

        p1, p2, p3 = self._patch_context()
        with p1, p2, p3:
            with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
                rows = _run(refrescar_competencia_catalogo(db, ["MLA_BOOM", "MLA_US"]))

        assert len(rows) == 2, "a single MLA's failure must not discard the whole batch"
        assert rows[0].fetch_status == "error"
        assert rows[1].fetch_status == "ok"
        db.commit.assert_called_once()

    def test_missing_status_normalizes_to_error_never_null(self) -> None:
        """fetch_status is NOT NULL; persisting None would blow up the commit
        for the whole batch, not just this row."""
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"detail": "malformed, no status key"})

        p1, p2, p3 = self._patch_context()
        with p1, p2, p3:
            with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
                rows = _run(refrescar_competencia_catalogo(db, ["MLA_WEIRD"]))

        assert rows[0].fetch_status == "error"


class TestPersistedColumnTypes:
    """The tests above use a MagicMock session, so SQLAlchemy never validates
    types. Postgres does: `our_seller_id` is String(32) and ML returns
    `seller_id` as an INTEGER, which fails on insert — and since the writer
    commits once after the loop, that failure discards the whole batch.
    """

    def _patch_context(self):
        return (
            patch(
                "app.services.ml_catalog_competition_service._resolve_pricing_context",
                return_value=MagicMock(),
            ),
            patch(
                "app.services.ml_catalog_competition_service.obtener_tipo_cambio_actual",
                return_value=None,
            ),
            patch(
                "app.services.ml_catalog_competition_service._markup_con_contexto",
                return_value=12.5,
            ),
        )

    def test_our_seller_id_is_coerced_to_str(self) -> None:
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "ok", "payload": PAYLOAD_OK})

        p1, p2, p3 = self._patch_context()
        with p1, p2, p3:
            with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
                rows = _run(refrescar_competencia_catalogo(db, ["MLA_US"]))

        assert rows[0].our_seller_id == "111"
        assert isinstance(rows[0].our_seller_id, str), "String(32) column cannot take ML's integer seller_id"

    def test_error_detail_is_truncated_to_the_column_width(self) -> None:
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "error", "detail": "x" * 900})

        p1, p2, p3 = self._patch_context()
        with p1, p2, p3:
            with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
                rows = _run(refrescar_competencia_catalogo(db, ["MLA_LONG"]))

        assert len(rows[0].error_detail) <= 500

    def test_all_ml_sourced_string_columns_are_type_and_width_safe(self) -> None:
        """seller_id was the instance the review named, but every String column
        fed from the ML payload has the same blast radius: one bad value fails
        the single end-of-loop commit and discards the whole batch.
        """
        hostile = {
            "catalog_product_id": "C" * 120,
            "competitors": [
                {
                    "item_id": "MLA_US",
                    "seller_id": 999,
                    "price": 1000.0,
                    "currency_id": "X" * 40,
                    "listing_type_id": "L" * 200,
                    "installments": 6,
                },
            ],
        }
        db = MagicMock()
        client = MagicMock()
        client.get_catalog_competition = AsyncMock(return_value={"status": "ok", "payload": hostile})

        p1, p2, p3 = self._patch_context()
        with p1, p2, p3:
            with patch("app.services.ml_catalog_competition_service.ml_webhook_client", client):
                rows = _run(refrescar_competencia_catalogo(db, ["MLA_US"]))

        row = rows[0]
        limits = {
            "mla": 20,
            "catalog_product_id": 50,
            "fetch_status": 20,
            "our_item_id": 20,
            "our_seller_id": 32,
            "our_currency_id": 8,
            "our_bucket_key": 64,
            "source_payload_hash": 64,
            "error_detail": 500,
        }
        for field, max_len in limits.items():
            value = getattr(row, field)
            if value is None:
                continue
            assert isinstance(value, str), f"{field} must be a str for its String column, got {type(value)}"
            assert len(value) <= max_len, f"{field} is {len(value)} chars, exceeds String({max_len})"


# ── obtener_ultimo_snapshot / undercutting_competitors (slice C2) ────


class TestObtenerUltimoSnapshot:
    def test_returns_none_when_never_fetched(self) -> None:
        db = MagicMock()
        query = db.query.return_value
        query.filter.return_value.order_by.return_value.first.return_value = None
        assert obtener_ultimo_snapshot(db, "MLA123") is None

    def test_returns_latest_row_ordered_desc(self) -> None:
        db = MagicMock()
        row = MagicMock()
        query = db.query.return_value
        query.filter.return_value.order_by.return_value.first.return_value = row
        result = obtener_ultimo_snapshot(db, "MLA123")
        assert result is row
        # ordered DESC on fecha_consulta so LIMIT-1-equivalent .first() picks
        # the newest row, matching the latest view's semantics.
        order_by_call = query.filter.return_value.order_by.call_args
        assert order_by_call is not None


class TestUndercuttingCompetitors:
    def test_none_row_returns_empty_list(self) -> None:
        assert undercutting_competitors(None) == []

    def test_failed_row_with_empty_competitors_returns_empty_list(self) -> None:
        row = MagicMock()
        row.competitors = []
        assert undercutting_competitors(row) == []

    def test_only_same_bucket_and_strictly_cheaper_survive(self) -> None:
        row = MagicMock()
        row.competitors = [
            {"item_id": "A", "same_bucket": True, "is_cheaper_than_us": True, "price_ars": 900},
            {"item_id": "B", "same_bucket": True, "is_cheaper_than_us": False, "price_ars": 1100},
            {"item_id": "C", "same_bucket": False, "is_cheaper_than_us": True, "price_ars": 500},
            {"item_id": "D", "same_bucket": True, "is_cheaper_than_us": None, "price_ars": None},
        ]
        result = undercutting_competitors(row)
        assert [c["item_id"] for c in result] == ["A"]

    def test_competitors_none_degrades_to_empty_list(self) -> None:
        row = MagicMock()
        row.competitors = None
        assert undercutting_competitors(row) == []
