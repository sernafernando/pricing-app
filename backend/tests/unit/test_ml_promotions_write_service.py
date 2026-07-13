"""
Unit tests for the write-orchestration service
`ml_promotions_write_service.py` (PR2/T4).

Order of operations under test (enroll_one_item):
  1. kill-switch (settings.PROMOS_WRITE_ENABLED) checked FIRST, before any
     read/proxy call.
  2. promotion_type restricted to SELLER_CAMPAIGN / DEAL.
  3. fresh live read of the item (ml_webhook_client.get_item_promotions)
     for [min,max] and suggested_discounted_price.
  4. defensive range validation before the POST.
  5. single POST, no retry.
  6. on ambiguous (timeout/5xx) -> reconcile via ml_item_promotions
     (mirrors reconciliar_ml_cancelaciones.py precedent), NOT a blind retry.

remove_one_item mirrors steps 1-2 and 5-6 (DELETE instead of POST).

All cross-DB engine + httpx calls are mocked. NO live-prod calls ever.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import ml_promotions_write_service as write_service


def _fake_live_item_promotions(
    promotion_id: str = "DEAL-1",
    promotion_type: str = "DEAL",
    min_price: float = 850.0,
    max_price: float = 950.0,
    suggested: float = 900.0,
) -> dict:
    return {
        "promotions": [
            {
                "promotion_id": promotion_id,
                "promotion_type": promotion_type,
                "min_discounted_price": min_price,
                "max_discounted_price": max_price,
                "suggested_discounted_price": suggested,
            }
        ]
    }


class TestKillSwitch:
    def test_disabled_short_circuits_before_any_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", False)

        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions") as mock_read,
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        mock_read.assert_not_called()
        mock_enroll.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "disabled"

    def test_remove_disabled_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", False)

        with patch.object(write_service.ml_webhook_client, "remove_item") as mock_remove:
            result = write_service.remove_one_item("MLA123456789", "DEAL", "DEAL-1")

        mock_remove.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "disabled"


class TestPromotionTypeRestriction:
    @pytest.mark.parametrize("bad_type", ["PRICE_DISCOUNT", "SMART", "DOD", "LIGHTNING"])
    def test_unsupported_type_rejected_before_proxy(self, monkeypatch: pytest.MonkeyPatch, bad_type: str) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions") as mock_read,
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "PROMO-1", bad_type, deal_price=900.0)

        mock_read.assert_not_called()
        mock_enroll.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "rejected_unsupported_type"

    @pytest.mark.parametrize("good_type", ["SELLER_CAMPAIGN", "DEAL"])
    def test_supported_type_passes_restriction(self, monkeypatch: pytest.MonkeyPatch, good_type: str) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(promotion_type=good_type),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            ) as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", good_type, deal_price=900.0)

        mock_enroll.assert_called_once()
        assert result["status"] == "submitted"


class TestDealPriceDefaultAndRangeValidation:
    def test_deal_price_none_defaults_to_suggested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(suggested=905.0),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            ) as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=None)

        mock_enroll.assert_called_once_with("MLA123456789", "DEAL-1", "DEAL", 905.0, top_deal_price=None)
        assert result["price"] == 905.0

    def test_out_of_range_rejected_before_post(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(min_price=850.0, max_price=950.0),
            ),
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=1200.0)

        mock_enroll.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "rejected_out_of_range"

    def test_in_range_price_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(min_price=850.0, max_price=950.0),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            ) as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        mock_enroll.assert_called_once()
        assert result["status"] == "submitted"


class TestFailClosedRangeValidation:
    """BLOCKER fix: enroll_one_item must NEVER POST to the proxy unless a
    concrete deal_price has passed the [min,max] range check. Every failure
    mode of the live pre-check must reject WITHOUT calling enroll_item."""

    def test_live_read_failure_rejects_without_posting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=None),
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        mock_enroll.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "rejected_read_unavailable"

    def test_promotion_not_found_in_live_payload_rejects_without_posting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(promotion_id="OTHER-PROMO"),
            ),
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        mock_enroll.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "rejected_promotion_not_found"

    def test_promotion_not_found_and_deal_price_none_never_posts_null_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression for the fail-OPEN bug: previously a missing live promo
        + no caller deal_price defaulted to None and STILL reached the POST
        (guard skipped since min/max/price were all None)."""
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(promotion_id="OTHER-PROMO"),
            ),
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=None)

        mock_enroll.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "rejected_promotion_not_found"

    def test_price_unresolved_rejects_without_posting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """promo found but suggested/min/max are None in the live payload and
        the caller passed no deal_price -> rejected_price_unresolved, no POST."""
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        incomplete_live = {
            "promotions": [
                {
                    "promotion_id": "DEAL-1",
                    "promotion_type": "DEAL",
                    "min_discounted_price": None,
                    "max_discounted_price": None,
                    "suggested_discounted_price": None,
                }
            ]
        }

        with (
            patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=incomplete_live),
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=None)

        mock_enroll.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "rejected_price_unresolved"

    def test_out_of_range_still_rejected_without_posting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(min_price=850.0, max_price=950.0),
            ),
            patch.object(write_service.ml_webhook_client, "enroll_item") as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=1200.0)

        mock_enroll.assert_not_called()
        assert result["status"] == "rejected_out_of_range"


class TestInclusiveRangeBoundary:
    def test_deal_price_equal_to_min_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(min_price=850.0, max_price=950.0),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            ) as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=850.0)

        mock_enroll.assert_called_once()
        assert result["status"] == "submitted"

    def test_deal_price_equal_to_max_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(min_price=850.0, max_price=950.0),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            ) as mock_enroll,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=950.0)

        mock_enroll.assert_called_once()
        assert result["status"] == "submitted"


class TestReconciledRowTrimmed:
    def test_reconciled_row_drops_raw_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": False, "status_code": None, "ambiguous": True, "body": None},
            ),
            patch.object(
                write_service,
                "fetch_item_promotions",
                return_value=[
                    {
                        "mla": "MLA123456789",
                        "promotion_id": "DEAL-1",
                        "status": "started",
                        "payload": {"raw": "should not leak"},
                    },
                ],
            ),
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        assert result["status"] == "reconciled_applied"
        assert "payload" not in result["reconciled_row"]
        assert result["reconciled_row"]["promotion_id"] == "DEAL-1"


class TestAuditLogging:
    def test_ambiguous_and_rejections_log_a_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with caplog.at_level("WARNING"):
            with patch.object(write_service.ml_webhook_client, "get_item_promotions", return_value=None):
                write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

            with (
                patch.object(
                    write_service.ml_webhook_client,
                    "get_item_promotions",
                    return_value=_fake_live_item_promotions(),
                ),
                patch.object(
                    write_service.ml_webhook_client,
                    "enroll_item",
                    return_value={"ok": False, "status_code": 500, "ambiguous": True, "body": None},
                ),
                patch.object(write_service, "fetch_item_promotions", side_effect=RuntimeError("db down")),
            ):
                write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        assert any("rejected_read_unavailable" in record.message for record in caplog.records)
        assert any("ambiguous" in record.message for record in caplog.records)


class TestHappyPathSubmitted:
    def test_201_returns_submitted_not_confirmed_enrolled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": True, "status_code": 201, "ambiguous": False, "body": {"status": "candidate"}},
            ),
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        assert result["submitted"] is True
        assert result["status"] == "submitted"
        # Explicitly NOT asserting a confirmed-enrolled state — eventual
        # consistency means the table is the source of truth, not this
        # immediate 201 response.
        assert "enrolled" not in result or result.get("enrolled") is None


class TestAmbiguousReconciliation:
    def test_timeout_triggers_reconciliation_no_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": False, "status_code": None, "ambiguous": True, "body": None},
            ) as mock_enroll,
            patch.object(
                write_service,
                "fetch_item_promotions",
                return_value=[
                    {"mla": "MLA123456789", "promotion_id": "DEAL-1", "status": "started"},
                ],
            ),
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        mock_enroll.assert_called_once()  # no retry
        assert result["status"] == "reconciled_applied"

    def test_ambiguous_not_applied_when_absent_from_table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": False, "status_code": 503, "ambiguous": True, "body": None},
            ),
            patch.object(write_service, "fetch_item_promotions", return_value=[]),
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        assert result["status"] == "reconciled_not_applied"

    def test_ambiguous_reconciliation_read_failure_is_still_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": False, "status_code": 500, "ambiguous": True, "body": None},
            ),
            patch.object(write_service, "fetch_item_promotions", side_effect=RuntimeError("db down")),
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        assert result["status"] == "ambiguous"

    def test_400_is_definitive_rejection_no_reconciliation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "get_item_promotions",
                return_value=_fake_live_item_promotions(),
            ),
            patch.object(
                write_service.ml_webhook_client,
                "enroll_item",
                return_value={"ok": False, "status_code": 400, "ambiguous": False, "body": {"message": "bad"}},
            ),
            patch.object(write_service, "fetch_item_promotions") as mock_fetch,
        ):
            result = write_service.enroll_one_item("MLA123456789", "DEAL-1", "DEAL", deal_price=900.0)

        mock_fetch.assert_not_called()
        assert result["submitted"] is False
        assert result["status"] == "rejected_by_proxy"

    def test_remove_5xx_row_absent_after_ambiguous_delete_means_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DELETE reconciliation is direction-dependent: for a `remove`, the
        row being ABSENT after an ambiguous DELETE means the removal DID
        take effect (the item is no longer discounted) -> reconciled_applied.
        This is the OPPOSITE of enroll's mapping."""
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "remove_item",
                return_value={"ok": False, "status_code": 500, "ambiguous": True, "body": None},
            ) as mock_remove,
            patch.object(write_service, "fetch_item_promotions", return_value=[]),
        ):
            result = write_service.remove_one_item("MLA123456789", "DEAL", "DEAL-1")

        mock_remove.assert_called_once()
        assert result["status"] == "reconciled_applied"

    def test_remove_5xx_row_still_present_after_ambiguous_delete_means_not_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mirror case: the row is still PRESENT after an ambiguous DELETE ->
        the removal did NOT take effect -> reconciled_not_applied."""
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with (
            patch.object(
                write_service.ml_webhook_client,
                "remove_item",
                return_value={"ok": False, "status_code": 500, "ambiguous": True, "body": None},
            ) as mock_remove,
            patch.object(
                write_service,
                "fetch_item_promotions",
                return_value=[{"mla": "MLA123456789", "promotion_id": "DEAL-1", "status": "started"}],
            ),
        ):
            result = write_service.remove_one_item("MLA123456789", "DEAL", "DEAL-1")

        mock_remove.assert_called_once()
        assert result["status"] == "reconciled_not_applied"


class TestRemoveHappyPath:
    def test_200_returns_submitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with patch.object(
            write_service.ml_webhook_client,
            "remove_item",
            return_value={"ok": True, "status_code": 200, "ambiguous": False, "body": {"ok": True}},
        ):
            result = write_service.remove_one_item("MLA123456789", "DEAL", "DEAL-1")

        assert result["submitted"] is True
        assert result["status"] == "submitted"

    def test_unsupported_type_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(write_service.settings, "PROMOS_WRITE_ENABLED", True)

        with patch.object(write_service.ml_webhook_client, "remove_item") as mock_remove:
            result = write_service.remove_one_item("MLA123456789", "SMART", "PROMO-1")

        mock_remove.assert_not_called()
        assert result["status"] == "rejected_unsupported_type"
