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

import time
from datetime import UTC, datetime
from typing import Any, Optional

import httpx

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


class AfipServiceError(Exception):
    """Error genérico de AfipService."""

    def __init__(self, message: str, detail: Optional[str] = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class AfipService:
    """Cliente para AFIP SDK API (afipsdk.com)."""

    BASE_URL = settings.AFIP_SDK_BASE_URL
    ACCESS_TOKEN = settings.AFIP_ACCESS_TOKEN
    CUIT = settings.AFIP_CUIT
    ENVIRONMENT = settings.AFIP_ENVIRONMENT
    CERT = settings.AFIP_CERT
    KEY = settings.AFIP_KEY
    # Timeout generoso — AFIP puede tardar
    TIMEOUT = 30.0

    def __init__(self) -> None:
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
            body["cert"] = _restore_pem(self.CERT)
            body["key"] = _restore_pem(self.KEY)

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
