"""
afip-direct-arca PR3 — unit tests for the padrón SOAP swap.

`_query_ws` now talks SOAP directly to `personaServiceA4`/`personaServiceA13`
over the shared client, authenticated by the PR2 WSAA layer. afipsdk.com is
gone from the transport entirely.

The load-bearing test here is the SHAPE contract: `_parse_persona` must
reproduce the dict the afipsdk JSON transport used to hand the extractors,
because SOAP returns everything as text where the JSON came typed. Two things
the extractors are sensitive to, both locked below:

  * numeric fields must be `int` (`idImpuesto == 30`, `orden == 1`,
    `max(..., key=periodo)` against a `0` default);
  * repeated elements must be lists — but an ABSENT list key must stay
    ABSENT, never an empty list, because `build_datos_fiscales_from_persona`
    branches on `"impuesto" in persona` to decide whether condición IVA is
    knowable at all. Injecting `impuesto: []` for A13 would silently turn a
    `None` (unknown) into `"No Responsable"` (asserted fact) on real
    taxpayers.

Payload field names/types are taken from the live WSDLs (A4/A13 read on
2026-07-27), not from documentation.

`httpx.MockTransport` + monkeypatch convention. No real network I/O.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services.afip_service import (
    AfipService,
    AfipServiceError,
    _padron_url,
    _parse_persona,
    _reset_http_client,
)

A4_NS = "http://a4.soap.ws.server.puc.sr/"
A13_NS = "http://a13.soap.ws.server.puc.sr/"

_A4_PERSONA_BODY = f"""
<ns:getPersonaResponse xmlns:ns="{A4_NS}">
  <personaReturn>
    <metadata><fechaHora>2026-07-27T10:00:00-03:00</fechaHora><servidor>wsaa</servidor></metadata>
    <persona>
      <estadoClave>ACTIVO</estadoClave>
      <idPersona>30712345671</idPersona>
      <razonSocial>ACME SOCIEDAD ANONIMA</razonSocial>
      <tipoPersona>JURIDICA</tipoPersona>
      <formaJuridica>SOCIEDAD ANONIMA</formaJuridica>
      <mesCierre>12</mesCierre>
      <impuesto>
        <descripcionImpuesto>IVA</descripcionImpuesto>
        <estado>ACTIVO</estado>
        <idImpuesto>30</idImpuesto>
        <periodo>201501</periodo>
      </impuesto>
      <impuesto>
        <descripcionImpuesto>GANANCIAS SOCIEDADES</descripcionImpuesto>
        <estado>ACTIVO</estado>
        <idImpuesto>10</idImpuesto>
        <periodo>201501</periodo>
      </impuesto>
      <actividad>
        <descripcionActividad>VENTA AL POR MAYOR DE EQUIPOS INFORMATICOS</descripcionActividad>
        <idActividad>465400</idActividad>
        <nomenclador>883</nomenclador>
        <orden>1</orden>
        <periodo>201811</periodo>
      </actividad>
      <actividad>
        <descripcionActividad>SERVICIOS DE ASESORAMIENTO</descripcionActividad>
        <idActividad>702091</idActividad>
        <nomenclador>883</nomenclador>
        <orden>2</orden>
        <periodo>201811</periodo>
      </actividad>
      <domicilio>
        <codPostal>1425</codPostal>
        <descripcionProvincia>CIUDAD AUTONOMA BUENOS AIRES</descripcionProvincia>
        <direccion>AV SIEMPRE VIVA 742</direccion>
        <idProvincia>0</idProvincia>
        <localidad>CABA</localidad>
        <orden>1</orden>
        <tipoDomicilio>FISCAL</tipoDomicilio>
      </domicilio>
    </persona>
  </personaReturn>
</ns:getPersonaResponse>
"""

_A13_PERSONA_BODY = f"""
<ns:getPersonaResponse xmlns:ns="{A13_NS}">
  <personaReturn>
    <metadata><fechaHora>2026-07-27T10:00:00-03:00</fechaHora><servidor>wsaa</servidor></metadata>
    <persona>
      <estadoClave>ACTIVO</estadoClave>
      <idPersona>30712345671</idPersona>
      <razonSocial>ACME SOCIEDAD ANONIMA</razonSocial>
      <tipoPersona>JURIDICA</tipoPersona>
      <formaJuridica>SOCIEDAD ANONIMA</formaJuridica>
      <descripcionActividadPrincipal>VENTA AL POR MAYOR DE EQUIPOS INFORMATICOS</descripcionActividadPrincipal>
      <idActividadPrincipal>465400</idActividadPrincipal>
      <periodoActividadPrincipal>201811</periodoActividadPrincipal>
      <domicilio>
        <codigoPostal>1425</codigoPostal>
        <descripcionProvincia>CIUDAD AUTONOMA BUENOS AIRES</descripcionProvincia>
        <direccion>AV SIEMPRE VIVA 742</direccion>
        <localidad>CABA</localidad>
        <tipoDomicilio>FISCAL</tipoDomicilio>
      </domicilio>
    </persona>
  </personaReturn>
</ns:getPersonaResponse>
"""


def _envelope(inner: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{inner}</soap:Body></soap:Envelope>"
    )


_EMPTY_PERSONA = _envelope(f'<ns:getPersonaResponse xmlns:ns="{A4_NS}"><personaReturn/></ns:getPersonaResponse>')

_PADRON_FAULT = _envelope(
    "<soap:Fault><faultcode>soap:Server</faultcode><faultstring>No existe persona con ese Id</faultstring></soap:Fault>"
)

_NOT_AUTHORIZED_FAULT = _envelope(
    "<soap:Fault><faultcode>soap:Server</faultcode>"
    "<faultstring>El CUIT representado no se encuentra habilitado</faultstring></soap:Fault>"
)


class TestParsePersonaShape:
    """Golden contract: the dict handed to the extractors."""

    def test_a4_lists_and_int_casts(self) -> None:
        persona = _parse_persona(_envelope(_A4_PERSONA_BODY))

        assert isinstance(persona["impuesto"], list)
        assert isinstance(persona["actividad"], list)
        assert isinstance(persona["domicilio"], list)
        assert len(persona["impuesto"]) == 2

        assert persona["impuesto"][0]["idImpuesto"] == 30
        assert isinstance(persona["impuesto"][0]["idImpuesto"], int)
        assert persona["actividad"][0]["orden"] == 1
        assert persona["actividad"][0]["periodo"] == 201811
        assert persona["actividad"][0]["idActividad"] == 465400
        assert persona["mesCierre"] == 12

    def test_string_fields_are_not_coerced_to_int(self) -> None:
        """`numeroDocumento` is xs:string in the WSDL even though it looks
        numeric — casting it would corrupt leading zeros."""
        body = _envelope(
            f'<ns:getPersonaResponse xmlns:ns="{A4_NS}"><personaReturn><persona>'
            "<numeroDocumento>01234567</numeroDocumento>"
            "</persona></personaReturn></ns:getPersonaResponse>"
        )
        persona = _parse_persona(body)
        assert persona["numeroDocumento"] == "01234567"

    def test_single_repeated_element_is_still_a_list(self) -> None:
        """One `<impuesto>` must not collapse into a bare dict — the
        extractors iterate it unconditionally."""
        body = _envelope(
            f'<ns:getPersonaResponse xmlns:ns="{A4_NS}"><personaReturn><persona>'
            "<impuesto><idImpuesto>30</idImpuesto><estado>ACTIVO</estado></impuesto>"
            "</persona></personaReturn></ns:getPersonaResponse>"
        )
        persona = _parse_persona(body)
        assert isinstance(persona["impuesto"], list)
        assert len(persona["impuesto"]) == 1

    def test_absent_list_key_stays_absent_not_empty_list(self) -> None:
        """THE critical one. A13 carries no `impuesto`; emitting `[]` would
        flip `build_datos_fiscales_from_persona` from "unknown" (None) to an
        asserted "No Responsable" for every A13-resolved taxpayer."""
        persona = _parse_persona(_envelope(_A13_PERSONA_BODY))

        assert "impuesto" not in persona
        assert "actividad" not in persona

        datos = AfipService.build_datos_fiscales_from_persona(persona, "30712345671", "ws_sr_padron_a13")
        assert datos["condicion_iva"] is None
        assert datos["inscripto_ganancias"] is None

    def test_a13_flat_activity_fields_are_int_cast(self) -> None:
        persona = _parse_persona(_envelope(_A13_PERSONA_BODY))
        assert persona["idActividadPrincipal"] == 465400
        assert isinstance(persona["idActividadPrincipal"], int)

    def test_empty_persona_raises_not_found(self) -> None:
        with pytest.raises(AfipServiceError) as exc:
            _parse_persona(_EMPTY_PERSONA)
        assert "no se encontró" in exc.value.message.lower()

    def test_soap_fault_raises_with_faultstring(self) -> None:
        with pytest.raises(AfipServiceError) as exc:
            _parse_persona(_PADRON_FAULT)
        assert "No existe persona" in (exc.value.detail or "")

    @pytest.mark.parametrize("body", ["", "<html>502</html>", "<soap:Envelope><trunc"])
    def test_malformed_body_raises_afip_error(self, body: str) -> None:
        with pytest.raises(AfipServiceError):
            _parse_persona(body)


class TestExtractorEquivalence:
    """Same logical taxpayer via A4 and A13 must extract the same values for
    everything A13 actually carries (contract-stability requirement)."""

    def test_a4_and_a13_agree_on_shared_fields(self) -> None:
        a4 = _parse_persona(_envelope(_A4_PERSONA_BODY))
        a13 = _parse_persona(_envelope(_A13_PERSONA_BODY))

        assert AfipService.extraer_actividad_principal(a4) == AfipService.extraer_actividad_principal(a13)
        assert AfipService.extraer_domicilio_fiscal(a4) == AfipService.extraer_domicilio_fiscal(a13)

        d4 = AfipService.build_datos_fiscales_from_persona(a4, "30712345671", "ws_sr_padron_a4")
        d13 = AfipService.build_datos_fiscales_from_persona(a13, "30712345671", "ws_sr_padron_a13")
        for field in ("razon_social_afip", "estado_clave", "tipo_persona", "forma_juridica"):
            assert d4[field] == d13[field]
        for field in ("domicilio_fiscal", "domicilio_fiscal_cp", "domicilio_fiscal_provincia"):
            assert d4[field] == d13[field]

    def test_a4_extracts_iva_and_ganancias(self) -> None:
        a4 = _parse_persona(_envelope(_A4_PERSONA_BODY))
        assert AfipService.extraer_condicion_iva(a4) == "Responsable Inscripto"
        assert AfipService.extraer_inscripto_ganancias(a4) is True

    def test_actividad_principal_picks_orden_1(self) -> None:
        a4 = _parse_persona(_envelope(_A4_PERSONA_BODY))
        desc, act_id = AfipService.extraer_actividad_principal(a4)
        assert act_id == 465400
        assert "INFORMATICOS" in desc


class TestPadronUrl:
    def test_prod_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.core.config.settings.AFIP_ENVIRONMENT", "prod")
        assert _padron_url("ws_sr_padron_a4") == ("https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA4")
        assert _padron_url("ws_sr_padron_a13") == ("https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13")

    def test_dev_urls_use_homologacion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.core.config.settings.AFIP_ENVIRONMENT", "dev")
        assert "awshomo" in _padron_url("ws_sr_padron_a4")

    def test_unknown_wsid_raises(self) -> None:
        with pytest.raises(AfipServiceError):
            _padron_url("ws_sr_padron_a99")


def _wsaa_ok(expiration: datetime | None = None) -> str:
    exp = expiration or (datetime.now(timezone.utc) + timedelta(hours=12))
    inner = (
        '<loginTicketResponse version="1.0">'
        f"<header><expirationTime>{exp.isoformat()}</expirationTime></header>"
        "<credentials><token>TK</token><sign>SG</sign></credentials>"
        "</loginTicketResponse>"
    )
    import xml.etree.ElementTree as ET

    wsaa_ns = "http://wsaa.view.sua.dvadac.desein.afip.gov"
    resp = ET.Element(f"{{{wsaa_ns}}}loginCmsResponse")
    ret = ET.SubElement(resp, f"{{{wsaa_ns}}}loginCmsReturn")
    ret.text = inner
    return _envelope(ET.tostring(resp, encoding="unicode"))


@pytest.fixture
def wired_service(monkeypatch: pytest.MonkeyPatch, cert_and_key: tuple[str, str]):
    """Builds an `AfipService` whose every HTTP call is routed through a
    caller-supplied handler, with the TA cache cleared."""

    def _build(handler):
        cert_pem, key_pem = cert_and_key
        monkeypatch.setattr("app.core.config.settings.AFIP_CUIT", "30712345671")
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

    return _build


class TestQueryWsOverSoap:
    def test_a4_happy_path_sends_credentials_and_cuit(self, wired_service) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if "LoginCms" in str(request.url):
                return httpx.Response(200, text=_wsaa_ok())
            return httpx.Response(200, text=_envelope(_A4_PERSONA_BODY))

        service = wired_service(handler)
        persona, wsid = asyncio.run(service.get_persona("30-71234567-1"))

        assert wsid == "ws_sr_padron_a4"
        assert persona["razonSocial"] == "ACME SOCIEDAD ANONIMA"

        padron_call = calls[-1]
        assert str(padron_call.url).endswith("personaServiceA4")
        body = padron_call.content.decode()
        assert "TK" in body and "SG" in body
        assert "30712345671" in body

    def test_no_afipsdk_host_is_ever_contacted(self, wired_service) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if "LoginCms" in str(request.url):
                return httpx.Response(200, text=_wsaa_ok())
            return httpx.Response(200, text=_envelope(_A4_PERSONA_BODY))

        service = wired_service(handler)
        asyncio.run(service.get_persona("30712345671"))

        assert calls
        assert all("afipsdk" not in str(c.url) for c in calls)

    def test_a4_fault_falls_back_to_a13(self, wired_service) -> None:
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            urls.append(url)
            if "LoginCms" in url:
                return httpx.Response(200, text=_wsaa_ok())
            if url.endswith("personaServiceA4"):
                return httpx.Response(200, text=_NOT_AUTHORIZED_FAULT)
            return httpx.Response(200, text=_envelope(_A13_PERSONA_BODY))

        service = wired_service(handler)
        persona, wsid = asyncio.run(service.get_persona("30712345671"))

        assert wsid == "ws_sr_padron_a13"
        assert "impuesto" not in persona
        padron_urls = [u for u in urls if "personaService" in u]
        assert padron_urls[0].endswith("personaServiceA4")
        assert padron_urls[-1].endswith("personaServiceA13")

    def test_both_services_failing_raises(self, wired_service) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "LoginCms" in str(request.url):
                return httpx.Response(200, text=_wsaa_ok())
            return httpx.Response(200, text=_PADRON_FAULT)

        service = wired_service(handler)
        with pytest.raises(AfipServiceError):
            asyncio.run(service.get_persona("30712345671"))

    def test_padron_http_error_falls_back_then_raises(self, wired_service) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "LoginCms" in str(request.url):
                return httpx.Response(200, text=_wsaa_ok())
            return httpx.Response(503, text="service unavailable")

        service = wired_service(handler)
        with pytest.raises(AfipServiceError) as exc:
            asyncio.run(service.get_persona("30712345671"))
        assert "503" in exc.value.message

    def test_invalid_cuit_still_short_circuits_before_any_call(self, wired_service) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            calls.append(request)
            return httpx.Response(200, text=_wsaa_ok())

        service = wired_service(handler)
        with pytest.raises(AfipServiceError):
            asyncio.run(service.get_persona("20123456787"))
        assert calls == []

    def test_wsaa_failure_surfaces_as_afip_error(self, wired_service) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="wsaa down")

        service = wired_service(handler)
        with pytest.raises(AfipServiceError):
            asyncio.run(service.get_persona("30712345671"))


class TestTaStampede:
    """PR2 review follow-up: concurrent cache misses must collapse into a
    single loginCms. WSAA faults the extra concurrent logins with
    'El CEE ya posee un TA valido...', so without this every burst after
    expiry fails all-but-one caller."""

    def test_concurrent_misses_trigger_one_login(self, wired_service) -> None:
        logins: list[httpx.Request] = []

        async def handler_async(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "LoginCms" in url:
                logins.append(request)
                await asyncio.sleep(0.05)
                return httpx.Response(200, text=_wsaa_ok())
            return httpx.Response(200, text=_envelope(_A4_PERSONA_BODY))

        service = wired_service(handler_async)

        async def _run():
            await asyncio.gather(*(service.get_persona("30712345671") for _ in range(5)))

        asyncio.run(_run())
        assert len(logins) == 1
