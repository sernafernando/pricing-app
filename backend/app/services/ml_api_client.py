import httpx
import os
import time
from typing import Dict, Optional, List
import logging

from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_mlwebhook_engine

logger = logging.getLogger(__name__)


class QuestionNotFoundError(Exception):
    """Raised by `get_question` when ML confirms the question no longer
    exists (HTTP 404) — a terminal, non-retryable outcome. Distinguishes this
    case from a transient failure (network/timeout/5xx/auth), which still
    returns None so callers can retry."""

    def __init__(self, question_id: int) -> None:
        self.question_id = question_id
        super().__init__(f"Question {question_id} not found in ML (404)")


class QuestionAlreadyAnsweredError(Exception):
    """Raised by `post_answer` when ML confirms the question was already
    answered (a 4xx explicitly indicating that) — a success-equivalent
    outcome for idempotency (ml-bot Slice E, ADR-5 double-publish defense):
    a retried publish attempt (e.g. after a crash between the ML POST and
    the terminal DB write) must not be treated as a failure."""

    def __init__(self, question_id: int) -> None:
        self.question_id = question_id
        super().__init__(f"Question {question_id} was already answered in ML")


class AnswerPostPermanentError(Exception):
    """Raised by `post_answer` when ML rejects the answer with a non-
    already-answered 4xx (e.g. 401/403/404/422, or a 400 that is not a
    known already-answered signal) — a PERMANENT failure (ml-bot Slice E
    Judgment Day fix). The caller must not burn bounded retries on these:
    the request is malformed/unauthorized/rejected, not transiently
    unavailable, so retrying will not help."""

    def __init__(self, question_id: int, status_code: int, message: str) -> None:
        self.question_id = question_id
        self.status_code = status_code
        self.message = message
        super().__init__(f"Question {question_id}: ML rejected answer permanently (HTTP {status_code}): {message}")


# Narrow phrase fallback checked ONLY against the structured `message` field
# (never the whole raw body) — kept intentionally small to avoid false
# positives on unrelated validation errors.
_ALREADY_ANSWERED_PHRASES = ("already answered", "already has an answer", "already been answered")


def _load_token_from_mlwebhook() -> Optional[Dict]:
    """Lee access_token y expires_at de la tabla ml_tokens en la DB del ml-webhook."""
    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT access_token, EXTRACT(EPOCH FROM expires_at) AS expires_epoch FROM ml_tokens WHERE id = 1")
            ).fetchone()
            if not row:
                return None
            return {
                "access_token": row[0],
                "expires_epoch": float(row[1]) if row[1] is not None else 0.0,
            }
    except Exception as e:
        logger.error("No se pudo leer token de mlwebhook DB: %s", e)
        return None


class MercadoLibreAPIClient:
    """Cliente para la API de MercadoLibre.

    Lee el access_token directamente de la DB del ml-webhook,
    que se encarga del flujo OAuth (refresh, rotación, persistencia).
    """

    def __init__(self) -> None:
        self.base_url = "https://api.mercadolibre.com"
        self.user_id = os.getenv("ML_USER_ID")
        self._cached_token: Optional[str] = None
        self._cached_expires_epoch: float = 0.0

    async def get_access_token(self) -> str:
        """Obtiene el access token desde la DB del ml-webhook."""
        # Si tenemos un token cacheado y no expiró (con 60s de margen), usarlo
        if self._cached_token and time.time() < (self._cached_expires_epoch - 60):
            return self._cached_token

        token_data = _load_token_from_mlwebhook()
        if not token_data or not token_data.get("access_token"):
            raise RuntimeError(
                f"No se pudo obtener access_token de mlwebhook DB. Re-autenticar en {settings.ML_WEBHOOK_BASE_URL}/auth"
            )

        self._cached_token = token_data["access_token"]
        self._cached_expires_epoch = token_data.get("expires_epoch", 0.0)

        logger.debug("Access token leído de mlwebhook DB (expira epoch=%.0f)", self._cached_expires_epoch)
        return self._cached_token

    async def get_item(self, item_id: str) -> Optional[Dict]:
        """Obtiene información de un item de ML

        Args:
            item_id: El ID del item (MLA, MLB, etc.)

        Returns:
            Dict con la información del item o None si hay error
        """
        try:
            token = await self.get_access_token()

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/items/{item_id}", headers={"Authorization": f"Bearer {token}"}
                )

                if response.status_code == 404:
                    logger.warning(f"Item {item_id} no encontrado en ML")
                    return None

                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error obteniendo item {item_id} de ML: {e}")
            return None

    async def get_question(self, question_id: int) -> Optional[Dict]:
        """Obtiene el detalle completo de una pregunta de ML (ml-bot Slice C, R-101).

        El webhook de mlwebhook solo trae el resource id; el texto de la
        pregunta, comprador, item y estado se obtienen con un GET puntual acá.

        Args:
            question_id: El id numérico de la pregunta ML.

        Returns:
            Dict con la pregunta (incluye "status", "text", "date_created",
            "item_id", "from") si tuvo éxito.

        Raises:
            QuestionNotFoundError: si ML devuelve 404 (la pregunta ya no
                existe — resultado terminal, no reintentable).

        Returns None for transient failures (network/timeout/5xx/auth) —
        callers should retry these.
        """
        try:
            token = await self.get_access_token()

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/questions/{question_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )

                if response.status_code == 404:
                    logger.warning(f"Pregunta {question_id} no encontrada en ML")
                    raise QuestionNotFoundError(question_id)

                response.raise_for_status()
                return response.json()

        except QuestionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error obteniendo pregunta {question_id} de ML: {e}")
            return None

    async def post_answer(self, question_id: int, text: str) -> Optional[Dict]:
        """Publica la respuesta de una pregunta en ML (ml-bot Slice E, ADR-5).

        Args:
            question_id: El id numérico de la pregunta ML.
            text: El texto de la respuesta a publicar.

        Returns:
            Dict con la respuesta de ML si tuvo éxito.

        Raises:
            QuestionAlreadyAnsweredError: si ML indica explícitamente (4xx)
                que la pregunta ya fue respondida — tratado como
                éxito-equivalente por el caller (idempotencia).
            AnswerPostPermanentError: si ML rechaza la respuesta con un 4xx
                que NO es "ya respondida" (401/403/404/422/etc, o un 400 sin
                señal de idempotencia) — falla PERMANENTE, no reintentable.

        Returns None for transient failures (network/timeout/5xx) — callers
        should retry these (bounded).
        """
        try:
            token = await self.get_access_token()

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/answers",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"question_id": question_id, "text": text},
                )

                if 200 <= response.status_code < 300:
                    return response.json()

                if 400 <= response.status_code < 500:
                    self._classify_post_answer_client_error(question_id, response)
                    # _classify_post_answer_client_error always raises.

                response.raise_for_status()
                return response.json()

        except (QuestionAlreadyAnsweredError, AnswerPostPermanentError):
            raise
        except Exception as e:
            logger.error(f"Error publicando respuesta a pregunta {question_id} en ML: {e}")
            return None

    def _classify_post_answer_client_error(self, question_id: int, response: httpx.Response) -> None:
        """Classify a 4xx `post_answer` response and raise the matching
        exception. Never returns normally.

        Prefers structured matching over the previous brittle
        whole-body substring check: parses ML's JSON error shape
        (`{"message": ..., "error": ..., "status": ..., "cause": [...]}`)
        and inspects only the `message`/`error`/`cause[].message` fields for
        known already-answered signals. Falls back to a narrow phrase check
        on `message` alone. Logs a WARNING with a truncated body when a 400
        matches neither — a signal of ML contract drift.
        """
        try:
            body = response.json()
        except ValueError:
            logger.warning(
                "ml-bot post_answer: 400 body from ML is not JSON (possible contract drift) for question %s: %s",
                question_id,
                response.text[:500],
            )
            raise AnswerPostPermanentError(question_id, response.status_code, response.text[:500])

        if not isinstance(body, dict):
            logger.warning(
                "ml-bot post_answer: 400 body from ML is not a JSON object (possible contract drift) "
                "for question %s: %s",
                question_id,
                str(body)[:500],
            )
            raise AnswerPostPermanentError(question_id, response.status_code, str(body)[:500])

        message = str(body.get("message") or "")
        error_field = str(body.get("error") or "")
        cause = body.get("cause") or []
        cause_messages = " ".join(str(c.get("message", "")) for c in cause if isinstance(c, dict))
        combined = " ".join([message, error_field, cause_messages]).lower()

        if any(phrase in combined for phrase in _ALREADY_ANSWERED_PHRASES):
            logger.warning(f"Pregunta {question_id} ya estaba respondida en ML ({response.status_code}): {message}")
            raise QuestionAlreadyAnsweredError(question_id)

        # Narrow fallback, message field only.
        message_lower = message.lower()
        if "already" in message_lower or "answered" in message_lower:
            logger.warning(f"Pregunta {question_id} ya estaba respondida en ML ({response.status_code}): {message}")
            raise QuestionAlreadyAnsweredError(question_id)

        raise AnswerPostPermanentError(question_id, response.status_code, message or str(body)[:500])

    async def get_items_batch(self, item_ids: List[str]) -> Dict[str, Dict]:
        """Obtiene múltiples items en batch

        Args:
            item_ids: Lista de IDs de items

        Returns:
            Dict con {item_id: data} para cada item encontrado
        """
        results = {}

        if not item_ids:
            return results

        try:
            token = await self.get_access_token()

            # ML permite hasta 20 items por request
            batch_size = 20
            for i in range(0, len(item_ids), batch_size):
                batch = item_ids[i : i + batch_size]
                ids_param = ",".join(batch)

                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.get(
                        f"{self.base_url}/items",
                        params={"ids": ids_param},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    response.raise_for_status()

                    # La respuesta es un array de objetos con code, body
                    data = response.json()
                    for item_response in data:
                        if item_response.get("code") == 200:
                            body = item_response.get("body")
                            if body:
                                results[body["id"]] = body

        except Exception as e:
            logger.error(f"Error obteniendo items en batch: {e}")

        return results

    async def update_item_shipping(self, item_id: str, *, free_shipping: bool = False) -> Optional[Dict]:
        """Actualiza el shipping de un item en ML.

        Args:
            item_id: El ID del item (e.g. MLA1234567890)
            free_shipping: True para activar envío gratis, False para desactivar

        Returns:
            Dict con la respuesta de ML o None si hubo error
        """
        try:
            token = await self.get_access_token()

            payload = {
                "shipping": {
                    "free_shipping": free_shipping,
                    "free_methods": [] if not free_shipping else None,
                }
            }
            # Limpiar None del payload
            payload["shipping"] = {k: v for k, v in payload["shipping"].items() if v is not None}

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.put(
                    f"{self.base_url}/items/{item_id}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )

                if response.status_code == 200:
                    logger.info("Item %s shipping updated: free_shipping=%s", item_id, free_shipping)
                    return response.json()

                logger.warning(
                    "ML rejected shipping update for %s: %s %s",
                    item_id,
                    response.status_code,
                    response.text,
                )
                return None

        except Exception as e:
            logger.error("Error updating shipping for %s: %s", item_id, e)
            return None

    async def get_user_items(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Obtiene los items de un usuario

        Args:
            user_id: ID del usuario (usa el del .env si no se especifica)
            limit: Cantidad máxima de items a retornar

        Returns:
            Lista de items del usuario
        """
        if not user_id:
            user_id = self.user_id

        try:
            token = await self.get_access_token()

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/users/{user_id}/items/search",
                    params={"limit": limit, "offset": 0},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                data = response.json()

                item_ids = data.get("results", [])

                # Obtener detalles de cada item
                if item_ids:
                    return await self.get_items_batch(item_ids)

                return {}

        except Exception as e:
            logger.error(f"Error obteniendo items del usuario {user_id}: {e}")
            return {}


# Instancia global del cliente
ml_client = MercadoLibreAPIClient()
