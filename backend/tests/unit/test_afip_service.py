"""
afip-direct-arca PR1 — unit tests for `validar_cuit` (mod-11 check-digit
gate) and its wiring into `AfipService.get_persona` (design §CUIT
check-digit validation).

Same `httpx.MockTransport` + monkeypatch convention as
`test_ml_api_client_get_message.py`. `validar_cuit` is a pure module-level
function (no I/O); `get_persona` on invalid CUIT must raise
`AfipServiceError` without ever touching `_get_ta`/`_query_ws`.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.afip_service import AfipService, AfipServiceError, validar_cuit


class TestValidarCuit:
    @pytest.mark.parametrize(
        "cuit",
        [
            "20123456786",
            "23123456785",
            "27123456780",
            "30123456781",
            "33123456780",
            "34123456787",
        ],
    )
    def test_valid_cuits_across_prefixes(self, cuit: str) -> None:
        assert validar_cuit(cuit) is True

    def test_bad_check_digit_returns_false(self) -> None:
        # Last digit of a known-valid CUIT flipped.
        assert validar_cuit("20123456787") is False

    def test_wrong_length_10_digits_returns_false(self) -> None:
        assert validar_cuit("2012345678") is False

    def test_wrong_length_12_digits_returns_false(self) -> None:
        assert validar_cuit("201234567860") is False

    def test_non_numeric_returns_false(self) -> None:
        assert validar_cuit("2012345678X") is False

    def test_empty_returns_false(self) -> None:
        assert validar_cuit("") is False

    def test_verificador_11_maps_to_check_digit_0(self) -> None:
        assert validar_cuit("20000000060") is True

    def test_verificador_10_maps_to_check_digit_9(self) -> None:
        assert validar_cuit("20000000019") is True

    def test_normalizes_dashes_and_spaces(self) -> None:
        assert validar_cuit("20-12345678-6") is True
        assert validar_cuit("20 12345678 6") is True


class TestGetPersonaValidatesBeforeNetworkCall:
    def _service(self, monkeypatch: pytest.MonkeyPatch) -> AfipService:
        monkeypatch.setattr("app.core.config.settings.AFIP_ACCESS_TOKEN", "fake-token")
        monkeypatch.setattr("app.core.config.settings.AFIP_CUIT", "20000000006")
        return AfipService()

    def test_invalid_cuit_raises_without_network_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = self._service(monkeypatch)

        async def _fail_get_ta(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("_get_ta must not be called for an invalid CUIT")

        async def _fail_query_ws(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("_query_ws must not be called for an invalid CUIT")

        monkeypatch.setattr(service, "_get_ta", _fail_get_ta)
        monkeypatch.setattr(service, "_query_ws", _fail_query_ws)

        with pytest.raises(AfipServiceError):
            asyncio.run(service.get_persona("20123456787"))

    def test_normalization_runs_before_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A validly-formatted-but-dashed CUIT must be normalized then pass validation
        (i.e. reach the network layer) rather than being rejected due to the dashes."""
        service = self._service(monkeypatch)

        called = {"query_ws": False}

        async def _fake_query_ws(wsid: str, cuit_persona: str):
            called["query_ws"] = True
            return {"estadoClave": "ACTIVO"}

        monkeypatch.setattr(service, "_query_ws", _fake_query_ws)

        result, wsid = asyncio.run(service.get_persona("20-12345678-6"))
        assert called["query_ws"] is True
        assert wsid == "ws_sr_padron_a4"
        assert result == {"estadoClave": "ACTIVO"}
