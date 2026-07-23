"""Unit tests for `fetch_gbp_report_78`'s bounded SOAP timeout.

`call_soap_service` defaults to `timeout: float = 300.0` (up to ~600s across
the token-expired retry). Holding a checked-out pool connection for that long
is exactly the pattern behind this repo's documented pool-exhaustion
incident — `fetch_gbp_report_78` MUST pass an explicit, bounded timeout
rather than silently inheriting that default.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.tn_reconciliation_service import GBP_FETCH_TIMEOUT_SECONDS, fetch_gbp_report_78


class TestBoundedTimeout:
    @pytest.mark.asyncio
    async def test_call_soap_service_receives_an_explicit_bounded_timeout(self):
        with (
            patch(
                "app.services.tn_reconciliation_service.authenticate_user",
                new=AsyncMock(return_value="token"),
            ),
            patch(
                "app.services.tn_reconciliation_service.call_soap_service",
                new=AsyncMock(return_value="<Result></Result>"),
            ) as mock_call,
            patch(
                "app.services.tn_reconciliation_service.parse_soap_response",
                return_value=[],
            ),
        ):
            await fetch_gbp_report_78()

            mock_call.assert_called_once()
            _, kwargs = mock_call.call_args
            assert kwargs.get("timeout") == GBP_FETCH_TIMEOUT_SECONDS
            # The explicit bound must be materially smaller than
            # call_soap_service's own 300s default — otherwise this is
            # cosmetic, not a real bound.
            assert GBP_FETCH_TIMEOUT_SECONDS < 300.0
