"""
AfipService — integración con AFIP via afipsdk.com (REST API).

Flujo:
  1. POST /auth → obtener TA (token + sign) para el web service deseado
  2. POST /requests → llamar al método del WS con el TA

TAs se cachean en memoria hasta su expiración.
En producción se requiere certificado digital (cert + key).
En desarrollo se usa el CUIT de prueba 20409378472 sin certificado.

Web services utilizados:
  - ws_sr_padron_a4 → getPersona (datos completos: impuestos, regímenes, domicilios)
"""

import base64
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# IDs de impuestos clave en AFIP
IMPUESTO_IVA = 30
IMPUESTO_GANANCIAS_PERSONAS_FISICAS = 11
IMPUESTO_GANANCIAS_SOCIEDADES = 10
IMPUESTO_MONOTRIBUTO = 20

# Cache de Ticket de Acceso (TA) por wsid
# Estructura: {wsid: {"token": str, "sign": str, "expires_at": float}}
_ta_cache: dict[str, dict[str, Any]] = {}


def _restore_pem(value: str) -> str:
    """
    Restaura un PEM (cert/key) guardado en .env como una sola línea.

    El .env almacena los saltos de línea como backslash+n literal.
    Pydantic puede agregar niveles extra de escape dependiendo de la versión.
    Reemplazamos iterativamente hasta que el PEM tenga saltos reales.
    """
    if not value:
        return value
    result = value.replace("\\r", "").replace("\r", "")
    # Reemplazar iterativamente: \\n → \n hasta que no queden
    while "\\n" in result:
        result = result.replace("\\n", "\n")
    return result


# --------------------------------------------------------------------------
# WSAA direct transport (afip-direct-arca PR2)
#
# In-process WSAA client: builds the TRA, CMS-signs it locally with
# AFIP_CERT/AFIP_KEY and calls loginCms over SOAP. The private key never
# leaves the process — that is the reason this replaces afipsdk.com, which
# required uploading it on every TA request.
#
# Shipped in this slice as tested-but-not-yet-cabled machinery: `_get_ta`
# and `_query_ws` still run over afipsdk until the PR3 padrón swap.
#
# Endpoints reverified against the live WSDLs on 2026-07-27 (design open
# question: the AFIP->ARCA domain migration is still in flight; both WSAA
# hosts and both padrón hosts answer 200 on afip.gov.ar today).
# --------------------------------------------------------------------------

WSAA_URL_PROD = "https://wsaa.afip.gov.ar/ws/services/LoginCms"
WSAA_URL_HOMO = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms"

_WSAA_NS = "http://wsaa.view.sua.dvadac.desein.afip.gov"
_SOAPENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"

# TRA validity window around `now` (AFIP tolerates a few minutes of skew).
_TRA_WINDOW_SECONDS = 600

# Margin before the TA's real expiration at which we refetch (matches the
# pre-existing afipsdk cache semantics).
_TA_EXPIRY_MARGIN_SECONDS = 300

_DEFAULT_TIMEOUT = 30.0

# Shared client (design: one connection pool for all WSAA/padrón calls,
# replacing the per-call `httpx.AsyncClient` the afipsdk transport used).
_http_client_instance: Optional[httpx.AsyncClient] = None


def _http_client() -> httpx.AsyncClient:
    """Lazily-built module-level `httpx.AsyncClient`, shared across calls."""
    global _http_client_instance
    if _http_client_instance is None or _http_client_instance.is_closed:
        _http_client_instance = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
    return _http_client_instance


def _reset_http_client() -> None:
    """Drop the shared client so the next call builds a fresh one (test hook;
    also safe to call from an app shutdown handler)."""
    global _http_client_instance
    _http_client_instance = None


def _wsaa_url() -> str:
    """Homologación only for AFIP_ENVIRONMENT='dev'; producción otherwise."""
    return WSAA_URL_HOMO if settings.AFIP_ENVIRONMENT == "dev" else WSAA_URL_PROD


def _localname(tag: str) -> str:
    """`{ns}foo` -> `foo`. Namespaces vary between AFIP services and are not
    load-bearing for our parsing, so everything is matched by localname."""
    return tag.rsplit("}", 1)[-1]


def _find_localname(root: ET.Element, name: str) -> Optional[ET.Element]:
    if _localname(root.tag) == name:
        return root
    for element in root.iter():
        if _localname(element.tag) == name:
            return element
    return None


def _build_tra(wsid: str, now: Optional[datetime] = None) -> str:
    """Build the Ticket de Requerimiento de Acceso (TRA) XML for `wsid`.

    `uniqueId` is the epoch second; the validity window is `now` ± 10 min so a
    modest clock skew against AFIP still authenticates. Timestamps are
    tz-aware (naive ones are rejected by WSAA).
    """
    moment = now or datetime.now(timezone.utc)
    window = timedelta(seconds=_TRA_WINDOW_SECONDS)

    root = ET.Element("loginTicketRequest", {"version": "1.0"})
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "uniqueId").text = str(int(moment.timestamp()))
    ET.SubElement(header, "generationTime").text = (moment - window).isoformat()
    ET.SubElement(header, "expirationTime").text = (moment + window).isoformat()
    ET.SubElement(root, "service").text = wsid

    return ET.tostring(root, encoding="unicode")


def _sign_cms(tra: str, cert_pem: str, key_pem: str) -> str:
    """CMS/PKCS7-sign the TRA with the ARCA-registered cert, base64(DER).

    `PKCS7Options.Binary` keeps the payload byte-exact (no S/MIME canonical
    line-ending rewriting), which WSAA requires to validate the signature.
    """
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
        cms = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(tra.encode())
            .add_signer(cert, key, hashes.SHA256())
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
        )
    except Exception as exc:
        # Never surface the raw cryptography error: it can echo key material.
        raise AfipServiceError(
            "No se pudo firmar el TRA para WSAA",
            detail=f"Certificado o clave privada inválidos ({type(exc).__name__})",
        ) from exc

    return base64.b64encode(cms).decode()


def _raise_if_soap_fault(root: ET.Element) -> None:
    fault = _find_localname(root, "Fault")
    if fault is None:
        return
    faultstring = fault.findtext("faultstring") or ""
    if not faultstring:
        element = _find_localname(fault, "faultstring")
        faultstring = (element.text or "") if element is not None else ""
    raise AfipServiceError("AFIP rechazó la consulta (SOAP Fault)", detail=faultstring or None)


def _parse_ta(body: str) -> tuple[str, str, datetime]:
    """Parse a WSAA `loginCms` response into `(token, sign, expiration)`.

    WSAA nests the `loginTicketResponse` document as *escaped text* inside
    `loginCmsReturn`, so this parses twice. Any malformed/HTML/truncated body
    becomes an `AfipServiceError` — never a raw `ElementTree` exception.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise AfipServiceError(
            "Respuesta de WSAA malformada",
            detail=f"No se pudo parsear el XML de WSAA ({exc})",
        ) from exc

    _raise_if_soap_fault(root)

    login_return = _find_localname(root, "loginCmsReturn")
    if login_return is None or not (login_return.text or "").strip():
        raise AfipServiceError(
            "Respuesta de WSAA sin loginCmsReturn",
            detail="La respuesta de WSAA no contiene el ticket de acceso",
        )

    try:
        ticket = ET.fromstring(login_return.text)
    except ET.ParseError as exc:
        raise AfipServiceError(
            "Ticket de acceso de WSAA malformado",
            detail=f"No se pudo parsear el loginTicketResponse ({exc})",
        ) from exc

    token = ticket.findtext("credentials/token")
    sign = ticket.findtext("credentials/sign")
    expiration_raw = ticket.findtext("header/expirationTime")

    if not token or not sign or not expiration_raw:
        raise AfipServiceError(
            "Ticket de acceso de WSAA incompleto",
            detail="Faltan token, sign o expirationTime en el loginTicketResponse",
        )

    try:
        expiration = datetime.fromisoformat(expiration_raw)
    except ValueError as exc:
        raise AfipServiceError(
            "Ticket de acceso de WSAA con expiración inválida",
            detail=f"expirationTime no es una fecha ISO válida: {expiration_raw!r}",
        ) from exc

    return token, sign, expiration


def _build_login_cms_envelope(cms_b64: str) -> str:
    envelope = ET.Element(f"{{{_SOAPENV_NS}}}Envelope")
    ET.SubElement(envelope, f"{{{_SOAPENV_NS}}}Header")
    soap_body = ET.SubElement(envelope, f"{{{_SOAPENV_NS}}}Body")
    login = ET.SubElement(soap_body, f"{{{_WSAA_NS}}}loginCms")
    ET.SubElement(login, f"{{{_WSAA_NS}}}in0").text = cms_b64
    return ET.tostring(envelope, encoding="unicode")


_CUIT_PESOS = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def validar_cuit(cuit: str) -> bool:
    """
    Valida el dígito verificador de un CUIT (algoritmo mod-11 de AFIP).

    Pura, sin I/O. Normaliza defensivamente (quita guiones/espacios) por si
    se invoca antes de la normalización habitual del caller.
    """
    cuit_limpio = (cuit or "").replace("-", "").replace(" ", "")

    if not cuit_limpio.isdigit() or len(cuit_limpio) != 11:
        return False

    base = cuit_limpio[:10]
    digito_verificador = int(cuit_limpio[10])

    suma = sum(int(digito) * peso for digito, peso in zip(base, _CUIT_PESOS))
    resto = suma % 11
    verificador = 11 - resto

    if verificador == 11:
        verificador = 0
    elif verificador == 10:
        verificador = 9

    return verificador == digito_verificador


class AfipServiceError(Exception):
    """Error genérico de AfipService."""

    def __init__(self, message: str, detail: Optional[str] = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class AfipService:
    """Cliente para AFIP SDK API (afipsdk.com)."""

    # Timeout generoso — AFIP puede tardar
    TIMEOUT = 30.0

    def __init__(self) -> None:
        # Leer settings en runtime (no como class attrs) para que
        # _restore_pem se aplique con el valor actual de .env
        self.BASE_URL = settings.AFIP_SDK_BASE_URL
        self.ACCESS_TOKEN = settings.AFIP_ACCESS_TOKEN
        self.CUIT = settings.AFIP_CUIT
        self.ENVIRONMENT = settings.AFIP_ENVIRONMENT
        self.CERT = _restore_pem(settings.AFIP_CERT or "")
        self.KEY = _restore_pem(settings.AFIP_KEY or "")

        if not self.ACCESS_TOKEN:
            raise AfipServiceError(
                "AFIP_ACCESS_TOKEN no configurado",
                detail="Configurar AFIP_ACCESS_TOKEN en .env",
            )
        if not self.CUIT:
            raise AfipServiceError(
                "AFIP_CUIT no configurado",
                detail="Configurar AFIP_CUIT en .env",
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.ACCESS_TOKEN}",
        }

    async def _wsaa_get_ta(self, wsid: str) -> dict[str, str]:
        """Obtain a Ticket de Acceso directly from WSAA (no third party).

        Same cache contract as the afipsdk `_get_ta` it will replace in PR3:
        one entry per `wsid`, refetched once the cached TA falls inside the
        5-minute expiry margin. A failed login is never cached.

        NOT cabled into `get_persona` yet — `_query_ws` still uses the
        afipsdk `_get_ta` until the padrón swap lands.
        """
        cached = _ta_cache.get(wsid)
        if cached and cached["expires_at"] > time.time():
            return {"token": cached["token"], "sign": cached["sign"]}

        if not self.CERT or not self.KEY:
            raise AfipServiceError(
                "AFIP_CERT/AFIP_KEY no configurados",
                detail="La autenticación directa contra WSAA requiere certificado y clave privada en .env",
            )

        logger.info("Solicitando TA a WSAA para wsid=%s, env=%s", wsid, self.ENVIRONMENT)

        cms_b64 = _sign_cms(_build_tra(wsid), self.CERT, self.KEY)
        envelope = _build_login_cms_envelope(cms_b64)

        try:
            resp = await _http_client().post(
                _wsaa_url(),
                content=envelope.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
            )
        except httpx.HTTPError as exc:
            raise AfipServiceError(
                "Error de red conectando a WSAA",
                detail=str(exc),
            ) from exc

        if resp.status_code != 200:
            logger.error("Error obteniendo TA de WSAA: status=%d", resp.status_code)
            raise AfipServiceError(
                f"Error obteniendo TA de WSAA (HTTP {resp.status_code})",
                detail=resp.text[:500],
            )

        token, sign, expiration = _parse_ta(resp.text)

        _ta_cache[wsid] = {
            "token": token,
            "sign": sign,
            "expires_at": expiration.timestamp() - _TA_EXPIRY_MARGIN_SECONDS,
        }

        logger.info("TA de WSAA obtenido para wsid=%s, expira=%s", wsid, expiration.isoformat())

        return {"token": token, "sign": sign}

    async def _get_ta(self, wsid: str) -> dict[str, str]:
        """
        Obtiene el Ticket de Acceso (TA) para un web service.
        Cachea el TA hasta su expiración.
        """
        cached = _ta_cache.get(wsid)
        if cached and cached["expires_at"] > time.time():
            return {"token": cached["token"], "sign": cached["sign"]}

        logger.info("Solicitando nuevo TA para wsid=%s, env=%s", wsid, self.ENVIRONMENT)

        body: dict[str, Any] = {
            "environment": self.ENVIRONMENT,
            "tax_id": self.CUIT,
            "wsid": wsid,
        }

        # En producción, agregar cert y key para autenticar con ARCA
        if self.CERT and self.KEY:
            body["cert"] = self.CERT
            body["key"] = self.KEY

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(
                f"{self.BASE_URL}/auth",
                json=body,
                headers=self._headers(),
            )

        if resp.status_code != 200:
            error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            detail = str(error_data.get("data_errors", error_data.get("message", resp.text)))
            logger.error("Error obteniendo TA: status=%d, detail=%s", resp.status_code, detail)
            raise AfipServiceError(
                f"Error obteniendo TA de AFIP (HTTP {resp.status_code})",
                detail=detail,
            )

        data = resp.json()
        token = data["token"]
        sign = data["sign"]

        # Cachear con margen de 5 minutos antes de expiración real
        expiration = datetime.fromisoformat(data["expiration"].replace("Z", "+00:00"))
        expires_at = expiration.timestamp() - 300

        _ta_cache[wsid] = {
            "token": token,
            "sign": sign,
            "expires_at": expires_at,
        }

        logger.info("TA obtenido para wsid=%s, expira=%s", wsid, data["expiration"])
        return {"token": token, "sign": sign}

    async def _query_ws(self, wsid: str, cuit_persona: str) -> dict[str, Any]:
        """
        Consulta genérica a un web service de padrón AFIP.
        Retorna el dict de `personaReturn.persona`.
        """
        ta = await self._get_ta(wsid)

        cuit_clean = cuit_persona.replace("-", "").replace(" ", "")
        cuit_representada = int(self.CUIT)
        id_persona = int(cuit_clean)

        body = {
            "environment": self.ENVIRONMENT,
            "method": "getPersona",
            "wsid": wsid,
            "params": {
                "token": ta["token"],
                "sign": ta["sign"],
                "cuitRepresentada": cuit_representada,
                "idPersona": id_persona,
            },
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(
                f"{self.BASE_URL}/requests",
                json=body,
                headers=self._headers(),
            )

        if resp.status_code != 200:
            error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = error_data.get("message", resp.text)
            logger.error("Error consultando %s: status=%d, msg=%s", wsid, resp.status_code, error_msg)
            raise AfipServiceError(
                f"Error consultando AFIP {wsid} (HTTP {resp.status_code})",
                detail=str(error_msg),
            )

        data = resp.json()

        if "code" in data and "message" in data:
            raise AfipServiceError("AFIP rechazó la consulta", detail=data["message"])

        persona = data.get("personaReturn", {}).get("persona")
        if not persona:
            raise AfipServiceError(
                f"No se encontró persona con CUIT {cuit_clean} en AFIP",
                detail="La respuesta de AFIP no contiene datos de persona",
            )

        return persona

    async def get_persona(self, cuit_persona: str) -> tuple[dict[str, Any], str]:
        """
        Consulta datos de una persona en AFIP.

        Intenta Padrón A4 primero (datos completos con impuestos y regímenes).
        Si A4 no está habilitado, usa A13 (datos básicos sin impuestos).

        Retorna (persona_dict, wsid_usado).
        """
        cuit_clean = cuit_persona.replace("-", "").replace(" ", "")

        if not validar_cuit(cuit_clean):
            raise AfipServiceError(
                "CUIT inválido: dígito verificador incorrecto",
                detail=f"El CUIT {cuit_clean} no supera la validación mod-11",
            )

        # Intentar A4 primero
        try:
            logger.info("Consultando Padrón A4 para CUIT %s", cuit_clean)
            persona = await self._query_ws("ws_sr_padron_a4", cuit_persona)
            return persona, "ws_sr_padron_a4"
        except AfipServiceError as e:
            # Cualquier error en A4 → intentar A13 como fallback.
            # Errores comunes: "notAuthorized", "no se encuentra habilitada",
            # "Only 8, 16, 24, or 32 bits supported" (AFIP SDK crypto error
            # cuando el WS no está autorizado para el certificado).
            logger.warning(
                "A4 falló para CUIT %s (%s), intentando A13...",
                cuit_clean,
                e.message,
            )

        # Fallback a A13
        logger.info("Consultando Padrón A13 para CUIT %s", cuit_clean)
        persona = await self._query_ws("ws_sr_padron_a13", cuit_persona)
        return persona, "ws_sr_padron_a13"

    @staticmethod
    def extraer_condicion_iva(persona: dict[str, Any]) -> str:
        """
        Determina la condición ante IVA a partir de los impuestos.

        Lógica:
        - Si tiene IVA (id=30) ACTIVO → "Responsable Inscripto"
        - Si tiene Monotributo (id=20) ACTIVO → "Monotributista"
        - Si tiene IVA con estado EXENTO → "IVA Exento"
        - Si no tiene IVA ni Monotributo → "No Responsable / Consumidor Final"
        """
        impuestos = persona.get("impuesto", [])

        iva = next((i for i in impuestos if i.get("idImpuesto") == IMPUESTO_IVA), None)
        monotributo = next((i for i in impuestos if i.get("idImpuesto") == IMPUESTO_MONOTRIBUTO), None)

        if iva:
            estado = (iva.get("estado") or "").upper()
            if estado == "ACTIVO":
                return "Responsable Inscripto"
            if "EXENTO" in estado:
                return "IVA Exento"

        if monotributo:
            estado = (monotributo.get("estado") or "").upper()
            if estado == "ACTIVO":
                return "Monotributista"

        return "No Responsable"

    @staticmethod
    def extraer_inscripto_ganancias(persona: dict[str, Any]) -> bool:
        """Verifica si está inscripto en Ganancias (id=10 sociedades o id=11 personas físicas)."""
        impuestos = persona.get("impuesto", [])
        ganancias_ids = {IMPUESTO_GANANCIAS_SOCIEDADES, IMPUESTO_GANANCIAS_PERSONAS_FISICAS}

        return any(
            i.get("idImpuesto") in ganancias_ids and (i.get("estado") or "").upper() == "ACTIVO" for i in impuestos
        )

    @staticmethod
    def extraer_actividad_principal(persona: dict[str, Any]) -> tuple[Optional[str], Optional[int]]:
        """
        Extrae la actividad principal.

        A4: array `actividad[]` con orden y periodo → tomar orden=1 más reciente.
        A13: campos planos `descripcionActividadPrincipal` e `idActividadPrincipal`.
        """
        # A13: campos planos
        if "descripcionActividadPrincipal" in persona:
            return persona.get("descripcionActividadPrincipal"), persona.get("idActividadPrincipal")

        # A4: array
        actividades = persona.get("actividad", [])
        if not actividades:
            return None, None

        principales = [a for a in actividades if a.get("orden") == 1]
        if not principales:
            principales = actividades

        principal = max(principales, key=lambda a: a.get("periodo", 0))
        return principal.get("descripcionActividad"), principal.get("idActividad")

    @staticmethod
    def extraer_domicilio_fiscal(persona: dict[str, Any]) -> dict[str, Optional[str]]:
        """Extrae el domicilio fiscal de la lista de domicilios."""
        domicilios = persona.get("domicilio", [])
        fiscal = next(
            (d for d in domicilios if (d.get("tipoDomicilio") or "").upper() == "FISCAL"),
            domicilios[0] if domicilios else None,
        )

        if not fiscal:
            return {
                "direccion": None,
                "cp": None,
                "provincia": None,
                "localidad": None,
            }

        return {
            "direccion": fiscal.get("direccion"),
            "cp": fiscal.get("codPostal") or fiscal.get("codigoPostal"),
            "provincia": fiscal.get("descripcionProvincia"),
            "localidad": fiscal.get("localidad"),
        }

    @staticmethod
    def build_datos_fiscales_from_persona(
        persona: dict[str, Any],
        cuit: str,
        wsid: str = "ws_sr_padron_a4",
    ) -> dict[str, Any]:
        """
        Construye el dict de campos para ProveedorDatosFiscales a partir
        del response crudo del Padrón A4 o A13.

        A4 tiene impuestos y regímenes → condición IVA y ganancias se extraen.
        A13 no trae impuestos → condición IVA y ganancias quedan como None.
        """
        # A4 tiene impuestos → podemos extraer condición IVA y ganancias
        # A13 no tiene → dejamos None (se completará cuando se habilite A4)
        has_impuestos = "impuesto" in persona
        condicion_iva = AfipService.extraer_condicion_iva(persona) if has_impuestos else None
        inscripto_ganancias = AfipService.extraer_inscripto_ganancias(persona) if has_impuestos else None

        act_desc, act_id = AfipService.extraer_actividad_principal(persona)
        domicilio = AfipService.extraer_domicilio_fiscal(persona)

        return {
            "condicion_iva": condicion_iva,
            "inscripto_ganancias": inscripto_ganancias,
            "estado_clave": persona.get("estadoClave"),
            "tipo_persona": persona.get("tipoPersona"),
            "forma_juridica": persona.get("formaJuridica"),
            "razon_social_afip": persona.get("razonSocial") or persona.get("apellido"),
            "actividad_principal": act_desc,
            "actividad_principal_id": act_id,
            "domicilio_fiscal": domicilio["direccion"],
            "domicilio_fiscal_cp": domicilio["cp"],
            "domicilio_fiscal_provincia": domicilio["provincia"],
            "domicilio_fiscal_localidad": domicilio["localidad"],
            "padron_a4_raw": persona,
            "cuit_consultado": cuit,
            "ultima_consulta_afip": datetime.now(UTC),
            "ultimo_error_afip": None,
            "wsid_consultado": wsid,
        }
