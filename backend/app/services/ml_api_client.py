import httpx
import os
from typing import Dict, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MercadoLibreAPIClient:
    """Cliente para la API de MercadoLibre"""

    def __init__(self):
        self.base_url = "https://api.mercadolibre.com"
        self.client_id = os.getenv("ML_CLIENT_ID")
        self.client_secret = os.getenv("ML_CLIENT_SECRET")
        self.user_id = os.getenv("ML_USER_ID")
        self.refresh_token = os.getenv("ML_REFRESH_TOKEN")
        self.access_token = None
        self.token_expires_at = None

    async def get_access_token(self) -> str:
        """Obtiene o renueva el access token"""
        # Si tenemos un token válido, lo retornamos
        if self.access_token and self.token_expires_at:
            if datetime.now() < self.token_expires_at:
                return self.access_token

        # Renovar token usando refresh_token
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/oauth/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self.refresh_token,
                    },
                )
                response.raise_for_status()
                data = response.json()

                self.access_token = data["access_token"]
                # Guardar cuando expira (generalmente 6 horas)
                expires_in = data.get("expires_in", 21600)
                from datetime import timedelta

                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)  # 5 min de margen

                # Actualizar refresh token si viene uno nuevo
                if "refresh_token" in data:
                    self.refresh_token = data["refresh_token"]

                return self.access_token

        except Exception as e:
            logger.error(f"Error renovando token de ML: {e}")
            raise

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
