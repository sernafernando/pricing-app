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
    ) -> Optional[Dict]:
        """Lista TODOS los items de una promoción vía el proxy ml-webhook.

        `promotion_type` es obligatorio (ML lo requiere para resolver el
        recurso correcto). Pagina internamente vía `paging.searchAfter`
        hasta agotar el cursor (los items pueden ser miles), agregando
        todas las páginas en un único resultado. Se corta el loop si el
        cursor viene vacío/None o si no cambia entre llamadas (guarda
        contra un loop infinito si el proxy se comporta mal).

        Args:
            promotion_id: ID de la promoción (o promotion_type para PRICE_DISCOUNT).
            promotion_type: Tipo de promoción (requerido).

        Returns:
            Dict con `items` (todas las páginas agregadas) y `count`, o
            None si hay error/timeout en cualquier página.

        Raises:
            ValueError: si promotion_type no se pasa.
        """
        if not promotion_type:
            raise ValueError("promotion_type es requerido para listar items de una promoción")

        all_items: List[Dict] = []
        search_after: Optional[str] = None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                while True:
                    params: Dict[str, str] = {"promotion_type": promotion_type}
                    if search_after is not None:
                        params["searchAfter"] = search_after

                    response = await client.get(f"{self.base_url}/api/promociones/{promotion_id}/items", params=params)
                    response.raise_for_status()
                    page = response.json()

                    all_items.extend(page.get("items") or [])

                    next_cursor = (page.get("paging") or {}).get("searchAfter")
                    if not next_cursor or next_cursor == search_after:
                        break
                    search_after = next_cursor

            return {"items": all_items, "count": len(all_items)}
        except Exception as e:
            logger.error(f"Error obteniendo items de la promoción {promotion_id}: {e}")
            return None

    # ── ML Seller Promotions (WRITE, PR2) ────────────────────────────
    # Unlike the read methods above, write methods NEVER collapse errors
    # to None: they always return a structured outcome
    # {ok, status_code, ambiguous, body} so the write-orchestration
    # service can classify timeout/5xx as ambiguous (needs reconciliation)
    # vs. a definitive rejection (400). Single-shot: NO retry here — a
    # blind retry on an ambiguous write could double-apply it.

    async def enroll_item(
        self,
        mla_id: str,
        promotion_id: str,
        promotion_type: str,
        deal_price: float,
        top_deal_price: Optional[float] = None,
        offer_id: Optional[str] = None,
    ) -> Dict:
        """Inscribe un item en una promoción vía el proxy ml-webhook (POST).

        Args:
            mla_id: El ID del item (ej: MLA2361127120).
            promotion_id: ID de la promoción.
            promotion_type: Tipo de promoción (SELLER_CAMPAIGN, DEAL o SMART).
            deal_price: Precio con descuento a aplicar.
            top_deal_price: Precio tope opcional (solo algunos tipos lo usan).
            offer_id: Requerido por SMART (el `ref_id` de la entrada SMART
                candidata en la lectura live); ignorado/omitido para
                SELLER_CAMPAIGN/DEAL, que no lo usan.

        Returns:
            Dict `{ok, status_code, ambiguous, body}`. `ambiguous=True`
            solo en timeout/5xx (no se puede saber si la escritura se
            aplicó del lado de ML); 400 es un rechazo definitivo
            (`ok=False, ambiguous=False`); 201 es éxito (`ok=True`). Para
            SMART, el body del 201 trae el `offer_id` autoritativo nuevo
            (forma "OFFER-...") — se propaga sin modificar en `body`.
        """
        payload: Dict = {"promotion_id": promotion_id, "promotion_type": promotion_type, "deal_price": deal_price}
        if top_deal_price is not None:
            payload["top_deal_price"] = top_deal_price
        if offer_id is not None:
            payload["offer_id"] = offer_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(f"{self.base_url}/api/promociones/item/{mla_id}", json=payload)
        except Exception as e:
            logger.error(f"Error (ambiguo) inscribiendo item {mla_id} en promoción {promotion_id}: {e}")
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        return self._classify_write_response(response)

    async def remove_item(
        self,
        mla_id: str,
        promotion_type: str,
        promotion_id: str,
        offer_id: Optional[str] = None,
    ) -> Dict:
        """Remueve un item de una promoción vía el proxy ml-webhook (DELETE).

        Args:
            mla_id: El ID del item.
            promotion_type: Tipo de promoción (SELLER_CAMPAIGN, DEAL o SMART).
            promotion_id: ID de la promoción.
            offer_id: Requerido por SMART (el `ref_id` CURRENT/OFFER- leído
                fresco antes del delete — el ref_id muta de CANDIDATE- a
                OFFER- al iniciar); ignorado/omitido para SELLER_CAMPAIGN/DEAL.

        Returns:
            Dict `{ok, status_code, ambiguous, body}` (mismo contrato que
            `enroll_item`).
        """
        params: Dict[str, str] = {"promotion_type": promotion_type, "promotion_id": promotion_id}
        if offer_id is not None:
            params["offer_id"] = offer_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.delete(f"{self.base_url}/api/promociones/item/{mla_id}", params=params)
        except Exception as e:
            logger.error(f"Error (ambiguo) removiendo item {mla_id} de promoción {promotion_id}: {e}")
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        return self._classify_write_response(response)

    @staticmethod
    def _classify_write_response(response: httpx.Response) -> Dict:
        """Clasifica la respuesta de un POST/DELETE de escritura.

        2xx -> ok=True. 5xx -> ambiguous=True (no se sabe si aplicó del
        lado de ML). 4xx -> rechazo definitivo, no ambiguo.
        """
        try:
            body = response.json()
        except Exception:
            body = None

        if 200 <= response.status_code < 300:
            return {"ok": True, "status_code": response.status_code, "ambiguous": False, "body": body}

        if response.status_code >= 500:
            return {"ok": False, "status_code": response.status_code, "ambiguous": True, "body": body}

        return {"ok": False, "status_code": response.status_code, "ambiguous": False, "body": body}

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
