"""
afip-direct-arca PR2 — unit tests for the direct WSAA transport layer
(design §Interfaces/Contracts, §Testing Strategy).

Covers the pure helpers (`_build_tra`, `_sign_cms`, `_parse_ta`, `_wsaa_url`),
the shared `httpx.AsyncClient` singleton, and `_wsaa_get_ta` (loginCms call +
per-wsid TA cache with the 5-minute expiry margin).

This slice ships the WSAA machinery as tested-but-not-yet-cabled internals:
`get_persona`/`_query_ws` still run over the afipsdk transport until PR3.

`httpx.MockTransport` + monkeypatch convention, same as
`test_ml_api_client_get_message.py`. No test performs real network I/O.
"""

from __future__ import annotations

import asyncio
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from app.services.afip_service import (
    AfipService,
    AfipServiceError,
    _build_tra,
    _parse_ta,
    _reset_http_client,
    _sign_cms,
    _wsaa_url,
)

WSAA_NS = "http://wsaa.view.sua.dvadac.desein.afip.gov"


@pytest.fixture
def cert_and_key() -> tuple[str, str]:
    """Self-signed cert + key PEM pair, generated in-test.

    Never registered with ARCA — signing correctness is verified locally by
    decoding the produced CMS, per the design's certless verification (option B).
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pricing-app-test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem


def _login_ticket_response(expiration: datetime, token: str = "TOKEN-ABC", sign: str = "SIGN-XYZ") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<loginTicketResponse version="1.0">'
        "<header><source>CN=wsaa</source><destination>CN=test</destination>"
        "<uniqueId>1234567890</uniqueId>"
        f"<generationTime>{(expiration - timedelta(hours=12)).isoformat()}</generationTime>"
        f"<expirationTime>{expiration.isoformat()}</expirationTime>"
        "</header>"
        f"<credentials><token>{token}</token><sign>{sign}</sign></credentials>"
        "</loginTicketResponse>"
    )


def _wsaa_envelope(inner: str) -> str:
    """WSAA wraps the loginTicketResponse XML as escaped text inside
    `loginCmsReturn` — reproduced faithfully via ElementTree escaping."""
    body = ET.Element(f"{{{WSAA_NS}}}loginCmsResponse")
    ret = ET.SubElement(body, f"{{{WSAA_NS}}}loginCmsReturn")
    ret.text = inner
    payload = ET.tostring(body, encoding="unicode")
    return (
        '<?xml version="1.0"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soapenv:Body>{payload}</soapenv:Body>"
        "</soapenv:Envelope>"
    )


_SOAP_FAULT = (
    '<?xml version="1.0"?>'
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
    "<soapenv:Body><soapenv:Fault>"
    "<faultcode>soapenv:Server</faultcode>"
    "<faultstring>El CEE ya posee un TA valido para el acceso al WSN solicitado</faultstring>"
    "</soapenv:Fault></soapenv:Body></soapenv:Envelope>"
)


class TestBuildTra:
    def test_structure_and_service(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        tra = _build_tra("ws_sr_padron_a4", now=now)
        root = ET.fromstring(tra)

        assert root.tag == "loginTicketRequest"
        assert root.get("version") == "1.0"
        assert root.findtext("service") == "ws_sr_padron_a4"
        assert root.findtext("header/uniqueId") == str(int(now.timestamp()))

    def test_generation_and_expiration_window_is_tz_aware(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        root = ET.fromstring(_build_tra("ws_sr_padron_a13", now=now))

        generation = datetime.fromisoformat(root.findtext("header/generationTime"))
        expiration = datetime.fromisoformat(root.findtext("header/expirationTime"))

        assert generation.tzinfo is not None
        assert expiration.tzinfo is not None
        assert generation == now - timedelta(seconds=600)
        assert expiration == now + timedelta(seconds=600)


class TestSignCms:
    def test_produces_base64_der_pkcs7_containing_the_cert(self, cert_and_key: tuple[str, str]) -> None:
        cert_pem, key_pem = cert_and_key
        tra = _build_tra("ws_sr_padron_a4", now=datetime.now(timezone.utc))

        cms_b64 = _sign_cms(tra, cert_pem, key_pem)

        raw = base64.b64decode(cms_b64, validate=True)
        embedded = pkcs7.load_der_pkcs7_certificates(raw)
        expected = x509.load_pem_x509_certificate(cert_pem.encode())
        assert [c.subject for c in embedded] == [expected.subject]

    def test_invalid_cert_material_raises_afip_error(self) -> None:
        tra = _build_tra("ws_sr_padron_a4", now=datetime.now(timezone.utc))
        with pytest.raises(AfipServiceError):
            _sign_cms(tra, "not-a-pem", "not-a-key")


class TestParseTa:
    def test_extracts_token_sign_and_expiration(self) -> None:
        expiration = datetime(2026, 7, 27, 23, 0, 0, tzinfo=timezone.utc)
        token, sign, parsed_expiration = _parse_ta(_wsaa_envelope(_login_ticket_response(expiration)))

        assert token == "TOKEN-ABC"
        assert sign == "SIGN-XYZ"
        assert parsed_expiration == expiration

    def test_soap_fault_raises_with_faultstring_as_detail(self) -> None:
        with pytest.raises(AfipServiceError) as exc:
            _parse_ta(_SOAP_FAULT)
        assert "TA valido" in (exc.value.detail or "")

    @pytest.mark.parametrize(
        "body",
        ["", "<html><body>502 Bad Gateway</body></html>", "<soapenv:Envelope><truncated"],
    )
    def test_malformed_body_raises_afip_error_not_parse_error(self, body: str) -> None:
        with pytest.raises(AfipServiceError):
            _parse_ta(body)

    def test_envelope_without_credentials_raises_afip_error(self) -> None:
        with pytest.raises(AfipServiceError):
            _parse_ta(_wsaa_envelope('<loginTicketResponse version="1.0"><header/></loginTicketResponse>'))


class TestWsaaUrl:
    def test_dev_environment_uses_homologacion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.core.config.settings.AFIP_ENVIRONMENT", "dev")
        assert _wsaa_url() == "https://wsaahomo.afip.gov.ar/ws/services/LoginCms"

    def test_prod_environment_uses_produccion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.core.config.settings.AFIP_ENVIRONMENT", "prod")
        assert _wsaa_url() == "https://wsaa.afip.gov.ar/ws/services/LoginCms"


class TestSharedHttpClient:
    def test_returns_the_same_instance_until_reset(self) -> None:
        from app.services.afip_service import _http_client

        _reset_http_client()
        first = _http_client()
        assert _http_client() is first

        _reset_http_client()
        assert _http_client() is not first


class TestWsaaGetTa:
    """`_wsaa_get_ta` — loginCms over the shared client + per-wsid TA cache
    honoring the existing 5-minute expiry margin."""

    def _service(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cert_and_key: tuple[str, str],
        handler,
    ) -> AfipService:
        cert_pem, key_pem = cert_and_key
        monkeypatch.setattr("app.core.config.settings.AFIP_ACCESS_TOKEN", "fake-token")
        monkeypatch.setattr("app.core.config.settings.AFIP_CUIT", "20000000006")
        monkeypatch.setattr("app.core.config.settings.AFIP_ENVIRONMENT", "prod")
        monkeypatch.setattr("app.core.config.settings.AFIP_CERT", cert_pem)
        monkeypatch.setattr("app.core.config.settings.AFIP_KEY", key_pem)

        _reset_http_client()
        monkeypatch.setattr(
            "app.services.afip_service._http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        from app.services.afip_service import _ta_cache

        _ta_cache.clear()
        return AfipService()

    def test_cache_miss_calls_login_cms_once_and_returns_credentials(
        self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]
    ) -> None:
        calls: list[httpx.Request] = []
        expiration = datetime.now(timezone.utc) + timedelta(hours=12)

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text=_wsaa_envelope(_login_ticket_response(expiration)))

        service = self._service(monkeypatch, cert_and_key, handler)
        ta = asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))

        assert ta == {"token": "TOKEN-ABC", "sign": "SIGN-XYZ"}
        assert len(calls) == 1
        assert str(calls[0].url) == "https://wsaa.afip.gov.ar/ws/services/LoginCms"
        assert b"loginCms" in calls[0].content

    def test_cache_hit_does_not_call_login_cms_again(
        self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]
    ) -> None:
        calls: list[httpx.Request] = []
        expiration = datetime.now(timezone.utc) + timedelta(hours=12)

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text=_wsaa_envelope(_login_ticket_response(expiration)))

        service = self._service(monkeypatch, cert_and_key, handler)
        asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))
        asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))

        assert len(calls) == 1

    def test_expiry_margin_forces_refetch(self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]) -> None:
        """A TA expiring inside the 5-minute margin must be refetched, not reused."""
        calls: list[httpx.Request] = []
        expirations = [
            datetime.now(timezone.utc) + timedelta(minutes=4),
            datetime.now(timezone.utc) + timedelta(hours=12),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text=_wsaa_envelope(_login_ticket_response(expirations[len(calls) - 1])))

        service = self._service(monkeypatch, cert_and_key, handler)
        asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))
        asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))

        assert len(calls) == 2

    def test_cache_is_keyed_per_wsid(self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]) -> None:
        calls: list[httpx.Request] = []
        expiration = datetime.now(timezone.utc) + timedelta(hours=12)

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text=_wsaa_envelope(_login_ticket_response(expiration)))

        service = self._service(monkeypatch, cert_and_key, handler)
        asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))
        asyncio.run(service._wsaa_get_ta("ws_sr_padron_a13"))

        assert len(calls) == 2
        assert b"ws_sr_padron_a13" not in calls[0].content

    def test_http_error_raises_afip_error_with_status(
        self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="upstream exploded")

        service = self._service(monkeypatch, cert_and_key, handler)
        with pytest.raises(AfipServiceError) as exc:
            asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))
        assert "500" in exc.value.message

    def test_soap_fault_raises_afip_error(self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_SOAP_FAULT)

        service = self._service(monkeypatch, cert_and_key, handler)
        with pytest.raises(AfipServiceError):
            asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))

    def test_failed_login_is_not_cached(self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]) -> None:
        """A fault must not poison the cache — the next call retries the network."""
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text=_SOAP_FAULT)

        service = self._service(monkeypatch, cert_and_key, handler)
        for _ in range(2):
            with pytest.raises(AfipServiceError):
                asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))

        assert len(calls) == 2

    def test_private_key_never_leaves_the_process(
        self, monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]
    ) -> None:
        """The CMS is sent; the PEM private key never is (ADR: no third party
        sees the key — that was the whole point of dropping afipsdk.com)."""
        _cert_pem, key_pem = cert_and_key
        calls: list[httpx.Request] = []
        expiration = datetime.now(timezone.utc) + timedelta(hours=12)

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text=_wsaa_envelope(_login_ticket_response(expiration)))

        service = self._service(monkeypatch, cert_and_key, handler)
        asyncio.run(service._wsaa_get_ta("ws_sr_padron_a4"))

        key_body = "".join(key_pem.strip().splitlines()[1:-1])
        assert key_body.encode() not in calls[0].content
        assert b"PRIVATE KEY" not in calls[0].content
