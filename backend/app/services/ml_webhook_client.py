import httpx
from typing import Dict, Optional, List
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class MLWebhookClient:
    """Cliente para el servicio ml-webhook que consulta la API de MercadoLibre"""

    def __init__(self):
        self.base_url = settings.ML_WEBHOOK_BASE_URL

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
                response = await client.get(f"{self.base_url}/api/ml/preview", params={"resource": resource})

                if response.status_code == 404:
                    logger.warning(f"Item {mla_id} no encontrado en ML")
                    return None

                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error obteniendo preview de {mla_id}: {e}")
            return None

    async def get_item_full(self, mla_id: str) -> Optional[Dict]:
        """Obtiene datos completos de un item consultando directamente la API de ML

        Args:
            mla_id: El ID del item

        Returns:
            Dict con todos los datos del item incluyendo listing_type_id, available_quantity, etc.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Consultar directamente usando el endpoint render que tiene acceso a la API
                response = await client.get(
                    f"{self.base_url}/api/ml/render", params={"resource": f"/items/{mla_id}", "format": "json"}
                )

                if response.status_code == 404:
                    return None

                # El render devuelve HTML, pero podemos parsear o usar preview + consulta directa
                # Mejor usamos el preview y complementamos
                preview_response = await client.get(
                    f"{self.base_url}/api/ml/preview", params={"resource": f"/items/{mla_id}"}
                )

                if preview_response.status_code != 200:
                    return None

                return preview_response.json()

        except Exception as e:
            logger.error(f"Error obteniendo item completo {mla_id}: {e}")
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
                    task = client.get(f"{self.base_url}/api/ml/preview", params={"resource": f"/items/{mla_id}"})
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

    # ── ML Seller Promotions (READ-ONLY, PR1) ───────────────────────
    # Write methods (enroll/remove) are added in PR2. No retry on any
    # of these: timeout/error -> None, mirroring the existing read
    # convention in this client.

    async def get_promotions(self) -> Optional[List[Dict]]:
        """Lista las promociones del vendedor vía el proxy ml-webhook.

        Returns:
            Lista de promociones (payload crudo del proxy), o None si hay
            error/timeout.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/promociones")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error obteniendo promociones: {e}")
            return None

    async def get_promotion_items(
        self,
        promotion_id: str,
        promotion_type: str,
        search_after: Optional[str] = None,
    ) -> Optional[Dict]:
        """Lista los items de una promoción vía el proxy ml-webhook.

        `promotion_type` es obligatorio (ML lo requiere para resolver el
        recurso correcto). Soporta paginación vía `search_after`: el caller
        pasa el cursor recibido en `paging.searchAfter` de la página anterior
        para pedir la siguiente (los items pueden ser miles).

        Args:
            promotion_id: ID de la promoción (o promotion_type para PRICE_DISCOUNT).
            promotion_type: Tipo de promoción (requerido).
            search_after: Cursor de paginación opcional.

        Returns:
            Dict con `items` y `paging.searchAfter` (payload crudo del
            proxy), o None si hay error/timeout.

        Raises:
            ValueError: si promotion_type no se pasa.
        """
        if not promotion_type:
            raise ValueError("promotion_type es requerido para listar items de una promoción")

        params: Dict[str, str] = {"promotion_type": promotion_type}
        if search_after is not None:
            params["searchAfter"] = search_after

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{self.base_url}/api/promociones/{promotion_id}/items", params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error obteniendo items de la promoción {promotion_id}: {e}")
            return None

    async def get_item_promotions(self, mla_id: str) -> Optional[Dict]:
        """Obtiene las promociones de un item puntual vía el proxy ml-webhook.

        Args:
            mla_id: El ID del item (ej: MLA2361127120).

        Returns:
            Dict con las promociones del item (payload crudo del proxy), o
            None si hay error/timeout.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/promociones/item/{mla_id}")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error obteniendo promociones del item {mla_id}: {e}")
            return None


# Instancia global del cliente
ml_webhook_client = MLWebhookClient()
