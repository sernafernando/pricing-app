import httpx
import os
import time
from typing import Dict, Optional, List
import logging

from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_mlwebhook_engine

logger = logging.getLogger(__name__)


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
            "item_id", "from") o None si no se pudo obtener.
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
                    return None

                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error obteniendo pregunta {question_id} de ML: {e}")
            return None

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
