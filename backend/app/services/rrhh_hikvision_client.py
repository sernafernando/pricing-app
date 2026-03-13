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

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

# Hikvision DS-K1T804AMF opera en hora local Argentina (UTC-3).
# Los timestamps en ISAPI deben enviarse SIN timezone info, en hora local.
ART_TZ = timezone(timedelta(hours=-3))

import requests
from requests.auth import HTTPDigestAuth
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

        Usa `requests` (no httpx) porque httpx 0.25.x tiene un bug con
        Digest Auth donde el body no se reenvía correctamente en el segundo
        request del handshake, causando "Server disconnected" o 400 en
        algunos entornos.

        Siempre usa ?format=json (requerido por firmware V1.3.43).
        """
        url = f"{self._get_base_url()}{path}"
        if "?" not in path:
            url += "?format=json"
        elif "format=" not in path:
            url += "&format=json"

        auth = HTTPDigestAuth(self.username or "", self.password or "")

        try:
            response = requests.request(
                method,
                url,
                json=json_body,
                auth=auth,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.ConnectionError:
            logger.error("Hikvision: dispositivo no alcanzable en %s", url)
            raise ConnectionError(f"No se puede conectar al dispositivo Hikvision en {self.host}:{self.port}")
        except requests.Timeout:
            logger.error("Hikvision: timeout en %s", url)
            raise ConnectionError(f"Timeout conectando al dispositivo Hikvision en {self.host}:{self.port}")
        except requests.HTTPError as e:
            # Log response body para diagnosticar 400/401
            body_text = ""
            try:
                body_text = (e.response.text or "")[:500]
            except Exception:
                body_text = "<no se pudo leer body>"
            logger.error(
                "Hikvision: HTTP error %s en %s — body: %s",
                e.response.status_code if e.response is not None else "?",
                url,
                body_text,
            )
            status = e.response.status_code if e.response is not None else "?"
            raise ConnectionError(f"Hikvision respondió con error HTTP {status}: {body_text}")

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
        # DS-K1T804AMF: maxResults estable en 10 por request para UserInfo/Search.
        # Valores mayores pueden generar errores/intermitencia en algunos firmwares.
        page_size = 10
        search_id = f"pricing-app-users-{uuid4().hex[:8]}"

        while True:
            body = {
                "UserInfoSearchCond": {
                    "searchID": search_id,
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

    def fetch_events(self, desde: Optional[datetime] = None, hasta: Optional[datetime] = None) -> list[dict]:
        """
        Obtiene eventos de acceso del dispositivo Hikvision.

        Pagina automáticamente (max 100 resultados por request).

        IMPORTANTE: El DS-K1T804AMF requiere timestamps en hora local Argentina
        (UTC-3), SIN info de timezone. Si se envían timestamps UTC, el dispositivo
        responde 400 Bad Request.

        Args:
            desde: Fecha/hora desde la cual buscar eventos (cualquier tz, se convierte a ART).
                   Si None, busca desde las 00:00 del día en hora Argentina.
            hasta: Fecha/hora hasta la cual buscar eventos (cualquier tz, se convierte a ART).
                   Si None, usa el momento actual en hora Argentina.

        Returns:
            Lista de eventos raw del dispositivo.
        """
        self._check_configured()

        # Defaults en hora local Argentina (el dispositivo opera en ART)
        if desde is None:
            desde = datetime.now(ART_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        if hasta is None:
            hasta = datetime.now(ART_TZ)

        # Convertir a hora local Argentina si vienen en otro timezone
        if desde.tzinfo is not None:
            desde = desde.astimezone(ART_TZ)
        if hasta.tzinfo is not None:
            hasta = hasta.astimezone(ART_TZ)

        # Formatear como naive local (el dispositivo no acepta offset)
        start_time_str = desde.strftime("%Y-%m-%dT%H:%M:%S")
        end_time_str = hasta.strftime("%Y-%m-%dT%H:%M:%S")

        logger.info("Hikvision fetch_events: %s → %s (ART local)", start_time_str, end_time_str)

        all_events: list[dict] = []
        position = 0
        # DS-K1T804AMF: page size conservador para evitar 401/intermitencia.
        page_size = 100
        search_id = f"pricing-app-events-{uuid4().hex[:8]}"

        while True:
            search_body = {
                "AcsEventCond": {
                    "searchID": search_id,
                    "searchResultPosition": position,
                    "maxResults": page_size,
                    "major": 0,
                    "minor": 0,
                    "startTime": start_time_str,
                    "endTime": end_time_str,
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

    def sync_fichadas(self, desde: Optional[datetime] = None, hasta: Optional[datetime] = None) -> dict:
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
        events = self.fetch_events(desde, hasta)

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

                fichada = RRHHFichada(
                    empleado_id=empleado_id,  # None si no mapeado
                    hikvision_employee_no=employee_no or None,
                    timestamp=ts,
                    tipo="entrada",  # Placeholder — se reclasifica abajo
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
            # Reclasificar entrada/salida para los días afectados
            self._classify_entry_exit(desde, hasta)

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

    def _classify_entry_exit(self, desde: Optional[datetime] = None, hasta: Optional[datetime] = None) -> None:
        """
        Reclasifica fichadas Hikvision como entrada/salida por empleado por día.

        Lógica: el dispositivo no distingue entrada de salida (un solo lector).
        Cada fichada alterna entre entrada y salida cronológicamente:
        - 1ª fichada del día → entrada (llegó)
        - 2ª fichada del día → salida  (salió a almorzar / ART / etc.)
        - 3ª fichada del día → entrada (volvió)
        - 4ª fichada del día → salida  (se fue)
        - etc.

        Esto preserva los fichajes intermedios (ej: salir al mediodía por ART)
        y permite calcular horas trabajadas por tramos.

        Solo toca fichadas de origen "hikvision" en el rango de fechas dado.
        """
        query = self.db.query(RRHHFichada).filter(
            RRHHFichada.origen == "hikvision",
        )
        if desde:
            query = query.filter(RRHHFichada.timestamp >= desde)
        if hasta:
            query = query.filter(RRHHFichada.timestamp <= hasta)

        fichadas = query.order_by(RRHHFichada.timestamp.asc()).all()

        if not fichadas:
            return

        # Agrupar por (empleado_key, fecha) — usamos hikvision_employee_no como key
        # porque empleado_id puede ser NULL (no mapeado aún).
        from collections import defaultdict

        groups: dict[tuple[str, str], list[RRHHFichada]] = defaultdict(list)
        for f in fichadas:
            key = f.hikvision_employee_no or f"emp-{f.empleado_id}"
            day = f.timestamp.strftime("%Y-%m-%d") if f.timestamp else "unknown"
            groups[(key, day)].append(f)

        updated = 0
        for (_key, _day), day_fichadas in groups.items():
            # Alternar: entrada (0), salida (1), entrada (2), salida (3)...
            for i, f in enumerate(day_fichadas):
                new_tipo = "entrada" if i % 2 == 0 else "salida"
                if f.tipo != new_tipo:
                    f.tipo = new_tipo
                    updated += 1

        if updated > 0:
            self.db.flush()
            logger.info("Hikvision: reclasificadas %d fichadas (entrada/salida)", updated)

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
