"""
Cliente Hikvision ISAPI para sincronización de fichadas — Phase 7.

Dispositivo: DS-K1T804AMF (face + fingerprint terminal).
Protocolo: ISAPI sobre HTTP + Digest Auth.
Puerto: 80 (NO 8000 — ese es SDK/binario).
Formato: ?format=json (firmware V1.3.43 requiere query param, no Accept header).

Endpoints usados:
- POST /ISAPI/AccessControl/AcsEvent?format=json        → eventos de fichaje
- POST /ISAPI/AccessControl/UserInfo/Search?format=json  → usuarios registrados

Dedup fichadas: serialNo → event_id (unique index en rrhh_fichadas).
Mapeo empleado: employeeNoString → rrhh_empleados.hikvision_employee_no.
"""

from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_fichada import RRHHFichada

logger = get_logger(__name__)


class HikvisionClient:
    """Cliente para sincronizar fichadas desde terminal Hikvision DS-K1T804AMF."""

    def __init__(self, db: Session):
        self.db = db
        self.host = settings.HIKVISION_HOST
        self.port = settings.HIKVISION_PORT
        self.username = settings.HIKVISION_USERNAME
        self.password = settings.HIKVISION_PASSWORD

    def _get_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _is_configured(self) -> bool:
        """Verifica si el dispositivo Hikvision está configurado."""
        return bool(self.host and self.username and self.password)

    def _check_configured(self) -> None:
        """Lanza ValueError si no está configurado."""
        if not self._is_configured():
            raise ValueError(
                "Hikvision no configurado. Verificar HIKVISION_HOST, HIKVISION_USERNAME, HIKVISION_PASSWORD en .env"
            )

    def _make_request(self, method: str, path: str, json_body: Optional[dict] = None) -> dict:
        """
        Hace request HTTP al dispositivo con Digest Auth.

        Siempre usa ?format=json (requerido por firmware V1.3.43).
        """
        url = f"{self._get_base_url()}{path}"
        if "?" not in path:
            url += "?format=json"
        elif "format=" not in path:
            url += "&format=json"

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method,
                    url,
                    json=json_body,
                    auth=httpx.DigestAuth(self.username or "", self.password or ""),
                )
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            logger.error("Hikvision: dispositivo no alcanzable en %s", url)
            raise ConnectionError(f"No se puede conectar al dispositivo Hikvision en {self.host}:{self.port}")
        except httpx.HTTPStatusError as e:
            logger.error(
                "Hikvision: HTTP error %s en %s",
                e.response.status_code,
                url,
            )
            raise ConnectionError(f"Hikvision respondió con error HTTP {e.response.status_code}")

    # ──────────────────────────────────────────────
    # Usuarios registrados en el dispositivo
    # ──────────────────────────────────────────────

    def fetch_users(self) -> list[dict]:
        """
        Obtiene TODOS los usuarios registrados en el Hikvision.

        Pagina automáticamente (el dispositivo devuelve max 10 por request).

        Returns:
            Lista de dicts con: employeeNo, name, userType, Valid, etc.
        """
        self._check_configured()

        all_users: list[dict] = []
        position = 0
        page_size = 30

        while True:
            body = {
                "UserInfoSearchCond": {
                    "searchID": "pricing-app-sync",
                    "searchResultPosition": position,
                    "maxResults": page_size,
                }
            }

            data = self._make_request("POST", "/ISAPI/AccessControl/UserInfo/Search", body)

            search_result = data.get("UserInfoSearch", {})
            users = search_result.get("UserInfo", [])
            total = search_result.get("totalMatches", 0)
            status_str = search_result.get("responseStatusStrg", "OK")

            all_users.extend(users)

            logger.info(
                "Hikvision users: fetched %d (total=%d, status=%s)",
                len(all_users),
                total,
                status_str,
            )

            if status_str != "MORE" or len(all_users) >= total:
                break

            position = len(all_users)

        return all_users

    # ──────────────────────────────────────────────
    # Eventos de fichaje (AcsEvent)
    # ──────────────────────────────────────────────

    def fetch_events(self, desde: Optional[datetime] = None) -> list[dict]:
        """
        Obtiene eventos de acceso del dispositivo Hikvision.

        Pagina automáticamente (max 1000 resultados por request).

        Args:
            desde: Fecha/hora desde la cual buscar eventos.
                   Si None, busca desde las 00:00 del día.

        Returns:
            Lista de eventos raw del dispositivo.
        """
        self._check_configured()

        if desde is None:
            desde = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        all_events: list[dict] = []
        position = 0
        page_size = 1000

        while True:
            search_body = {
                "AcsEventCond": {
                    "searchID": "pricing-app-sync",
                    "searchResultPosition": position,
                    "maxResults": page_size,
                    "major": 0,
                    "minor": 0,
                    "startTime": desde.strftime("%Y-%m-%dT%H:%M:%S"),
                    "endTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                }
            }

            data = self._make_request("POST", "/ISAPI/AccessControl/AcsEvent", search_body)

            acs_event = data.get("AcsEvent", {})
            info_list = acs_event.get("InfoList", [])
            total = acs_event.get("totalMatches", 0)
            status_str = acs_event.get("responseStatusStrg", "OK")

            all_events.extend(info_list)

            logger.info(
                "Hikvision events: fetched %d (total=%d, status=%s)",
                len(all_events),
                total,
                status_str,
            )

            if status_str != "MORE" or len(all_events) >= total:
                break

            position = len(all_events)

        return all_events

    # ──────────────────────────────────────────────
    # Sync fichadas a DB
    # ──────────────────────────────────────────────

    def sync_fichadas(self, desde: Optional[datetime] = None) -> dict:
        """
        Sincroniza eventos del dispositivo Hikvision a rrhh_fichadas.

        Guarda TODOS los eventos, incluso sin empleado mapeado.
        - Dedup por event_id (serialNo del dispositivo).
        - Siempre guarda hikvision_employee_no (employeeNoString).
        - Si el empleado está mapeado → asigna empleado_id.
        - Si no está mapeado → empleado_id=NULL (se linkea al mapear).

        Returns:
            { "nuevas": int, "duplicadas": int, "sin_empleado": int, "errores": int }
        """
        events = self.fetch_events(desde)

        # Pre-cargar mapeo hikvision_employee_no → empleado_id
        empleados = (
            self.db.query(RRHHEmpleado)
            .filter(
                RRHHEmpleado.activo.is_(True),
                RRHHEmpleado.hikvision_employee_no.isnot(None),
            )
            .all()
        )
        hik_map = {emp.hikvision_employee_no: emp.id for emp in empleados}

        nuevas = 0
        duplicadas = 0
        sin_empleado = 0
        errores = 0

        for event in events:
            try:
                serial_no = str(event.get("serialNo", ""))
                if not serial_no:
                    errores += 1
                    continue

                # Check dedup
                existing = self.db.query(RRHHFichada).filter(RRHHFichada.event_id == serial_no).first()
                if existing:
                    duplicadas += 1
                    continue

                # Map employee (puede ser None si no está mapeado aún)
                employee_no = str(event.get("employeeNoString", ""))
                empleado_id = hik_map.get(employee_no)

                if not empleado_id:
                    sin_empleado += 1

                # Parse timestamp — ej: "2026-03-12T08:01:32-03:00"
                time_str = event.get("time", "")
                try:
                    ts = datetime.fromisoformat(time_str)
                except (ValueError, AttributeError):
                    ts = datetime.now(timezone.utc)

                # Tipo: siempre "entrada" — el dispositivo no distingue.
                tipo = "entrada"

                fichada = RRHHFichada(
                    empleado_id=empleado_id,  # None si no mapeado
                    hikvision_employee_no=employee_no or None,
                    timestamp=ts,
                    tipo=tipo,
                    origen="hikvision",
                    device_serial=event.get("deviceName", "") or None,
                    event_id=serial_no,
                )
                self.db.add(fichada)
                nuevas += 1

            except Exception as e:
                errores += 1
                logger.error("Hikvision: error procesando evento: %s", e)

        if nuevas > 0:
            self.db.flush()

        logger.info(
            "Hikvision sync: nuevas=%d, duplicadas=%d, sin_empleado=%d, errores=%d",
            nuevas,
            duplicadas,
            sin_empleado,
            errores,
        )

        return {
            "nuevas": nuevas,
            "duplicadas": duplicadas,
            "sin_empleado": sin_empleado,
            "errores": errores,
        }

    @staticmethod
    def vincular_fichadas_retroactivas(db: Session, hikvision_employee_no: str, empleado_id: int) -> int:
        """
        Actualiza fichadas huérfanas: asigna empleado_id a todas las fichadas
        que tienen este hikvision_employee_no pero empleado_id IS NULL.

        Returns:
            Número de fichadas actualizadas.
        """
        count = (
            db.query(RRHHFichada)
            .filter(
                RRHHFichada.hikvision_employee_no == hikvision_employee_no,
                RRHHFichada.empleado_id.is_(None),
            )
            .update({"empleado_id": empleado_id})
        )
        logger.info(
            "Hikvision: vinculadas %d fichadas retroactivas (hik_no=%s -> empleado_id=%d)",
            count,
            hikvision_employee_no,
            empleado_id,
        )
        return count
