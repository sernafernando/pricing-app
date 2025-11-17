import httpx
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

class MLWebhookClient:
    """Cliente para el servicio ml-webhook que consulta la API de MercadoLibre"""

    def __init__(self):
        self.base_url = "https://ml-webhook.gaussonline.com.ar"

    async def get_item_preview(self, mla_id: str, include_price_to_win: bool = False) -> Optional[Dict]:
        """Obtiene preview de un item de MercadoLibre

        Args:
            mla_id: El ID del item (ej: MLA2361127120)
            include_price_to_win: Si es True, consulta también price_to_win

        Returns:
            Dict con: title, price, currency_id, thumbnail, brand, status, etc.
            Si include_price_to_win=True, incluye también status, price_to_win, winner info
            None si hay error
        """
        try:
            resource = f"/items/{mla_id}"
            if include_price_to_win:
                resource = f"/items/{mla_id}/price_to_win?version=v2"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/ml/preview",
                    params={"resource": resource}
                )

                if response.status_code == 404:
                    logger.warning(f"Item {mla_id} no encontrado en ML")
                    return None

                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error obteniendo preview de {mla_id}: {e}")
            return None

    async def get_items_batch(self, mla_ids: List[str]) -> Dict[str, Dict]:
        """Obtiene múltiples items en batch

        Args:
            mla_ids: Lista de IDs de items

        Returns:
            Dict con {mla_id: data} para cada item encontrado
        """
        results = {}

        if not mla_ids:
            return results

        # El servicio no tiene endpoint batch, así que hacemos requests en paralelo
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                tasks = []
                for mla_id in mla_ids:
                    task = client.get(
                        f"{self.base_url}/api/ml/preview",
                        params={"resource": f"/items/{mla_id}"}
                    )
                    tasks.append((mla_id, task))

                # Ejecutar todas las requests en paralelo
                for mla_id, task in tasks:
                    try:
                        response = await task
                        if response.status_code == 200:
                            data = response.json()
                            results[mla_id] = data
                    except Exception as e:
                        logger.error(f"Error obteniendo {mla_id}: {e}")
                        continue

        except Exception as e:
            logger.error(f"Error en batch de items: {e}")

        return results


# Instancia global del cliente
ml_webhook_client = MLWebhookClient()
