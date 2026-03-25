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

    async def get_persona_padron_a4(self, cuit_persona: str) -> dict[str, Any]:
        """
        Consulta el Padrón Alcance 4 (ws_sr_padron_a4) para un CUIT.

        Retorna el dict completo de `personaReturn.persona` con:
        - actividad, domicilio, email, telefono
        - estadoClave, formaJuridica, tipoPersona
        - impuesto[] (IVA, Ganancias, etc. con estado ACTIVO/BAJA)
        - regimen[] (retenciones/percepciones)
        - relacion[] (sociedades vinculadas)
        """
        wsid = "ws_sr_padron_a4"
        ta = await self._get_ta(wsid)

        cuit_clean = cuit_persona.replace("-", "").replace(" ", "")
        cuit_representada = int(self.CUIT)
        id_persona = int(cuit_clean)

        logger.info("Consultando Padrón A4 para CUIT %s", cuit_clean)

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
            logger.error("Error consultando Padrón A4: status=%d, msg=%s", resp.status_code, error_msg)
            raise AfipServiceError(
                f"Error consultando AFIP Padrón A4 (HTTP {resp.status_code})",
                detail=str(error_msg),
            )

        data = resp.json()

        # Verificar si la API devolvió error de AFIP (no HTTP)
        if "code" in data and "message" in data:
            raise AfipServiceError(
                "AFIP rechazó la consulta",
                detail=data["message"],
            )

        persona = data.get("personaReturn", {}).get("persona")
        if not persona:
            raise AfipServiceError(
                f"No se encontró persona con CUIT {cuit_clean} en AFIP",
                detail="La respuesta de AFIP no contiene datos de persona",
            )

        return persona

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
        Extrae la actividad principal (orden=1, período más reciente).
        Retorna (descripcion, id_actividad).
        """
        actividades = persona.get("actividad", [])
        if not actividades:
            return None, None

        # Filtrar las de orden 1, tomar la de período más reciente
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
            "cp": fiscal.get("codPostal"),
            "provincia": fiscal.get("descripcionProvincia"),
            "localidad": fiscal.get("localidad"),
        }

    @staticmethod
    def build_datos_fiscales_from_persona(
        persona: dict[str, Any],
        cuit: str,
    ) -> dict[str, Any]:
        """
        Construye el dict de campos para ProveedorDatosFiscales a partir
        del response crudo del Padrón A4.
        """
        condicion_iva = AfipService.extraer_condicion_iva(persona)
        inscripto_ganancias = AfipService.extraer_inscripto_ganancias(persona)
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
            "wsid_consultado": "ws_sr_padron_a4",
        }
