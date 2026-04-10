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

import time
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

# Retry config para 401 intermitente durante paginación Digest Auth.
# El DS-K1T804AMF invalida la sesión Digest entre requests de paginación
# cuando hay muchos eventos, causando 401 en páginas posteriores a la primera.
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

# Employee IDs del Hikvision que se ignoran al sincronizar.
# El DS-K1T804AMF a veces genera eventos con employeeNoString="0"
# que corresponden a autenticaciones fallidas o lecturas fantasma.
EMPLOYEE_NO_BANLIST: set[str] = {"0"}


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
        Hace request HTTP al dispositivo con Digest Auth + retry en 401.

        Usa `requests` (no httpx) porque httpx 0.25.x tiene un bug con
        Digest Auth donde el body no se reenvía correctamente en el segundo
        request del handshake, causando "Server disconnected" o 400 en
        algunos entornos.

        Retry: El DS-K1T804AMF invalida sesiones Digest Auth entre requests
        de paginación cuando hay muchos eventos. Un retry con nueva sesión
        de auth resuelve el 401 intermitente.

        Siempre usa ?format=json (requerido por firmware V1.3.43).
        """
        url = f"{self._get_base_url()}{path}"
        if "?" not in path:
            url += "?format=json"
        elif "format=" not in path:
            url += "&format=json"

        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            # Nueva instancia de auth en cada intento — fuerza re-handshake Digest
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
                logger.error("Hikvision: timeout en %s (intento %d/%d)", url, attempt, MAX_RETRIES)
                last_error = ConnectionError(f"Timeout conectando al dispositivo Hikvision en {self.host}:{self.port}")
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                body_text = ""
                try:
                    body_text = (e.response.text or "")[:500]
                except Exception:
                    body_text = "<no se pudo leer body>"

                if status == 401 and attempt < MAX_RETRIES:
                    # Digest Auth expiró — retry con nueva sesión
                    logger.warning(
                        "Hikvision: 401 en %s (intento %d/%d) — reintentando con nuevo handshake Digest",
                        url,
                        attempt,
                        MAX_RETRIES,
                    )
                    last_error = ConnectionError(f"Hikvision respondió con error HTTP 401: {body_text}")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                # Error no retryable (400, 403, 500, etc.) o último intento 401
                logger.error(
                    "Hikvision: HTTP error %s en %s — body: %s",
                    status or "?",
                    url,
                    body_text,
                )
                raise ConnectionError(f"Hikvision respondió con error HTTP {status}: {body_text}")

        # Si llegamos acá, todos los reintentos fallaron
        raise last_error or ConnectionError("Hikvision: todos los reintentos fallaron")

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
        # DS-K1T804AMF: searchID max 16 chars (24+ causa 400 badParameters)
        search_id = f"usr-{uuid4().hex[:8]}"

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

        Pagina automáticamente (max 30 resultados por request).
        Si una página falla tras reintentos, devuelve los eventos que ya trajo
        en vez de perder todo (graceful degradation).

        IMPORTANTE: El DS-K1T804AMF requiere timestamps en hora local Argentina
        (UTC-3), SIN info de timezone. Si se envían timestamps UTC, el dispositivo
        responde 400 Bad Request.

        Args:
            desde: Fecha/hora desde la cual buscar eventos (cualquier tz, se convierte a ART).
                   Si None, busca desde las 00:00 del día en hora Argentina.
            hasta: Fecha/hora hasta la cual buscar eventos (cualquier tz, se convierte a ART).
                   Si None, usa el momento actual en hora Argentina.

        Returns:
            Lista de eventos raw del dispositivo (puede ser parcial si hubo error de paginación).
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
        # DS-K1T804AMF: page size reducido a 30 para minimizar 401 por sesión
        # Digest expirada. Con 100, el dispositivo invalida auth entre páginas
        # cuando hay muchos eventos. Con 30, hay más requests pero cada uno
        # es más liviano y el Digest se renegocia exitosamente.
        page_size = 30
        # DS-K1T804AMF: searchID max 16 chars (24+ causa 400 badParameters)
        search_id = f"evt-{uuid4().hex[:8]}"

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

            try:
                data = self._make_request("POST", "/ISAPI/AccessControl/AcsEvent", search_body)
            except ConnectionError as e:
                # Graceful degradation: devolver lo que ya tenemos en vez de perder todo
                logger.warning(
                    "Hikvision: error en página %d — devolviendo %d eventos parciales. Error: %s",
                    position,
                    len(all_events),
                    e,
                )
                break

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
        # Track serialNos ya vistos en este batch (el dispositivo puede devolver
        # eventos duplicados con distinto major/minor pero mismo serialNo)
        seen_serial_nos: set[str] = set()
        # Proximity dedup: track (employee_no, timestamp_truncated) en este batch
        # para descartar múltiples eventos de la misma autenticación física
        PROXIMITY_SECONDS = 120
        seen_employee_times: dict[str, list[datetime]] = {}

        for event in events:
            try:
                serial_no = str(event.get("serialNo", ""))
                if not serial_no:
                    errores += 1
                    continue

                # Check dedup: en memoria (batch actual) + en DB (batches previos)
                if serial_no in seen_serial_nos:
                    duplicadas += 1
                    continue
                existing = self.db.query(RRHHFichada).filter(RRHHFichada.event_id == serial_no).first()
                if existing:
                    duplicadas += 1
                    seen_serial_nos.add(serial_no)
                    continue
                seen_serial_nos.add(serial_no)

                # Map employee (puede ser None si no está mapeado aún)
                employee_no = str(event.get("employeeNoString", ""))
                if employee_no in EMPLOYEE_NO_BANLIST:
                    duplicadas += 1
                    continue
                empleado_id = hik_map.get(employee_no)

                # Parse timestamp early for proximity check.
                # El Hikvision devuelve hora LOCAL Argentina sin timezone info
                # (ej: "2026-04-10T11:23:00"). Hay que asignarle ART_TZ explícitamente,
                # sino PostgreSQL lo interpreta como UTC y se desfasa 3 horas.
                time_str = event.get("time", "")
                try:
                    ts = datetime.fromisoformat(time_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=ART_TZ)
                except (ValueError, AttributeError):
                    ts = datetime.now(ART_TZ)

                # Proximity dedup: mismo employee_no dentro de PROXIMITY_SECONDS
                # El DS-K1T804AMF genera múltiples eventos (distintos serialNo)
                # para una sola autenticación física (ej: face + card sub-events)
                if employee_no:
                    prev_times = seen_employee_times.get(employee_no, [])
                    is_near = any(abs((ts - pt).total_seconds()) < PROXIMITY_SECONDS for pt in prev_times)
                    if not is_near and empleado_id:
                        # Also check DB for recently saved fichadas
                        db_near = (
                            self.db.query(RRHHFichada)
                            .filter(
                                RRHHFichada.hikvision_employee_no == employee_no,
                                RRHHFichada.timestamp.between(
                                    ts - timedelta(seconds=PROXIMITY_SECONDS),
                                    ts + timedelta(seconds=PROXIMITY_SECONDS),
                                ),
                            )
                            .first()
                        )
                        if db_near:
                            is_near = True
                    if is_near:
                        duplicadas += 1
                        continue
                    if employee_no not in seen_employee_times:
                        seen_employee_times[employee_no] = []
                    seen_employee_times[employee_no].append(ts)

                if not empleado_id:
                    sin_empleado += 1

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

        # Reclasificar entrada/salida SIEMPRE (no solo con fichadas nuevas).
        # El dispositivo no distingue entrada/salida — todas llegan como "entrada".
        # Si un sync previo guardó fichadas parciales (ej: solo la entrada de la
        # mañana), la reclasificación necesita correr de nuevo cuando la salida
        # ya existe para alternar correctamente los tipos por día.
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
