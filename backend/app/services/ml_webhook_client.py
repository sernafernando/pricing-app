import asyncio
import httpx
from datetime import datetime
from typing import Dict, Optional, List, Union
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
        """Obtiene el item COMPLETO de MercadoLibre vía el proxy `render`.

        A diferencia de `get_item_preview` (que usa `/api/ml/preview` y NO
        trae los campos de vinculación entre publicaciones), este método
        usa `/api/ml/render?format=json`, el único recurso que expone
        `family_id`, `user_product_id`, `inventory_id`, `catalog_listing`,
        `catalog_product_id` e `item_relations` (productos-catalog-family-tree,
        PR1b — antes este método descartaba el render y volvía a pedir el
        preview recortado, perdiendo justamente esos campos).

        Args:
            mla_id: El ID del item (ej: MLA2361127120).

        Returns:
            Dict con el payload completo del item (incluye los campos de
            vinculación arriba), o None si hay error/timeout/404. Nunca
            levanta (mismo shape de error-swallow que el resto del cliente).
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/ml/render", params={"resource": f"/items/{mla_id}", "format": "json"}
                )

                if response.status_code == 404:
                    return None

                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error obteniendo item completo {mla_id}: {e}")
            return None

    async def get_catalog_competition(self, mla_id: str) -> Dict:
        """Catalog competitor listing for `mla_id` via the ml-webhook proxy.

        UNLIKE every other read method in this client, this one does NOT
        collapse errors to None. The caller must distinguish two outcomes
        that look identical from a None:
          - the MLA is simply not a catalog publication (proxy answers
            400) — a legitimate, cacheable business fact the UI renders
            as "no aplica";
          - the proxy/network failed — a transient condition the UI must
            render as an error with a retry.
        Collapsing both to None would make it impossible to store an
        honest `fetch_status`, so this method returns a structured
        outcome instead (same reasoning as `_classify_write_response`).

        The proxy returns HTML on error even with `format=processed`, so
        the status code AND the content-type are both checked before
        `.json()`.

        Args:
            mla_id: The item ID (e.g. MLA2361127120).

        Returns:
            {"status": "ok", "payload": <dict>}          on 200 + JSON body
            {"status": "not_catalog", "detail": <str>}   on 400
            {"status": "error", "detail": <str>}         on anything else:
                404, other 4xx, 5xx, timeout, non-JSON content-type, or a
                body that fails to parse.
        NEVER raises.
        """
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(
                    f"{self.base_url}/catalogCompetition",
                    params={"input": mla_id, "format": "processed"},
                )
        except Exception as e:
            logger.error(f"Error (transporte) obteniendo competencia de catálogo para {mla_id}: {e}")
            return {"status": "error", "detail": str(e)[:200]}

        if response.status_code == 400:
            logger.info(f"{mla_id} no es publicación de catálogo (400): {response.text[:200]}")
            return {"status": "not_catalog", "detail": response.text[:200]}

        if response.status_code != 200:
            logger.warning(
                f"Error obteniendo competencia de catálogo para {mla_id}: "
                f"HTTP {response.status_code}: {response.text[:200]}"
            )
            return {"status": "error", "detail": f"HTTP {response.status_code}"}

        content_type = response.headers.get("content-type") or ""
        if "application/json" not in content_type:
            logger.warning(
                f"Respuesta no-JSON para competencia de catálogo de {mla_id} "
                f"(content-type={content_type!r}): {response.text[:200]}"
            )
            return {"status": "error", "detail": "non-json response"}

        try:
            payload = response.json()
        except Exception as e:
            logger.warning(
                f"No se pudo parsear la respuesta de competencia de catálogo para {mla_id}: "
                f"{e} — body: {response.text[:200]}"
            )
            return {"status": "error", "detail": "unparseable json"}

        return {"status": "ok", "payload": payload}

    async def get_items_full_batch(self, mla_ids: List[str]) -> Dict[str, Dict]:
        """Obtiene el item COMPLETO (`get_item_full`) para múltiples MLAs.

        Mirrors `get_items_batch`'s batch-of-50 + 0.5s-pause pattern (ver
        `scripts/refresh_and_sync_catalog.py`), pero llamando a
        `get_item_full` (render) en vez de preview, y extrayendo solo los
        campos de vinculación que persiste `ml_publication_link_service`.

        Graceful degradation: un MLA para el que el proxy no devuelve nada
        (404/timeout/error) queda simplemente AUSENTE del dict resultado —
        nunca levanta, nunca aborta el resto del batch.

        Args:
            mla_ids: Lista de IDs de items.

        Returns:
            Dict `{mla_id: {family_id, user_product_id, inventory_id,
            catalog_listing, catalog_product_id, item_relations}}` — solo
            para los MLAs encontrados.
        """
        results: Dict[str, Dict] = {}

        if not mla_ids:
            return results

        batch_size = 50
        for start in range(0, len(mla_ids), batch_size):
            batch = mla_ids[start : start + batch_size]

            for mla_id in batch:
                try:
                    item = await self.get_item_full(mla_id)
                except Exception as e:
                    logger.error(f"Error obteniendo item completo en batch {mla_id}: {e}")
                    continue

                if item is None:
                    continue

                results[mla_id] = {
                    "family_id": item.get("family_id"),
                    "user_product_id": item.get("user_product_id"),
                    "inventory_id": item.get("inventory_id"),
                    "catalog_listing": item.get("catalog_listing"),
                    "catalog_product_id": item.get("catalog_product_id"),
                    "item_relations": item.get("item_relations") or [],
                }

            # Pequeña pausa entre batches (mirrors refresh_and_sync_catalog.py)
            # para no saturar la API de ML vía el proxy.
            await asyncio.sleep(0.5)

        return results

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

    # ── ML Orders/Shipments ops (ml-ventas-fuente-de-verdad, slice 2) ─
    # Additive read-only methods for the ML-API-sourced operations layer
    # (see design obs #1823). Same error-swallow shape as every other
    # read method: never raises for HTTP/network errors, always None.
    # Ids ARE validated (coerced to int) BEFORE any HTTP call — the
    # Threat Matrix SSRF row: no caller-supplied string can ever reach
    # the proxy `resource=` path.

    async def get_order(self, order_id: Union[int, str]) -> Optional[Dict]:
        """Obtiene una orden de MercadoLibre vía el proxy `preview`.

        Args:
            order_id: El id numérico de la orden ML (natural key, NUNCA
                el `mlo_id` interno del ERP).

        Returns:
            Dict con el payload crudo de la orden, o None si hay
            error/timeout/404.

        Raises:
            ValueError: si `order_id` no es coercionable a `int` — se
                levanta ANTES de cualquier llamada HTTP (SSRF-safe).
        """
        try:
            order_id_int = int(order_id)
        except (TypeError, ValueError) as e:
            raise ValueError(f"order_id no coercionable a int: {order_id!r}") from e

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/ml/orders", params={"resource": f"/orders/{order_id_int}"}
                )

                if response.status_code == 404:
                    logger.warning(f"Orden {order_id_int} no encontrada en ML")
                    return None

                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error obteniendo orden {order_id_int}: {e}")
            return None

    async def get_shipment(self, shipment_id: Union[int, str]) -> Optional[Dict]:
        """Obtiene un envío de MercadoLibre vía el proxy `preview`.

        Args:
            shipment_id: El id numérico del shipment ML.

        Returns:
            Dict con el payload crudo del shipment, o None si hay
            error/timeout/404.

        Raises:
            ValueError: si `shipment_id` no es coercionable a `int` —
                se levanta ANTES de cualquier llamada HTTP (SSRF-safe).
        """
        try:
            shipment_id_int = int(shipment_id)
        except (TypeError, ValueError) as e:
            raise ValueError(f"shipment_id no coercionable a int: {shipment_id!r}") from e

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/ml/orders", params={"resource": f"/shipments/{shipment_id_int}"}
                )

                if response.status_code == 404:
                    logger.warning(f"Shipment {shipment_id_int} no encontrado en ML")
                    return None

                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error obteniendo shipment {shipment_id_int}: {e}")
            return None

    async def search_orders(
        self,
        seller_id: Union[int, str],
        date_from: datetime,
        date_to: datetime,
        offset: int = 0,
    ) -> Optional[Dict]:
        """Busca órdenes de MercadoLibre por ventana de `date_last_updated`
        vía el proxy `preview`, usado por el sweep de reconciliación
        (`sync_ml_orders_ops`, slice 3).

        Args:
            seller_id: Id numérico del vendedor ML.
            date_from: Límite inferior (inclusive) de `date_last_updated`.
                DEBE ser timezone-aware.
            date_to: Límite superior (exclusive) de `date_last_updated`.
                DEBE ser timezone-aware.
            offset: Offset de paginación (ML cap ~1000; el sweep bisecta
                la ventana en vez de profundizar el offset, ver design).

        Returns:
            Dict crudo `{results, paging}`, o None si hay error/timeout.

        Raises:
            ValueError: si `seller_id` no es coercionable a `int`, o si
                `date_from`/`date_to` son naive (sin tzinfo) — se levanta
                ANTES de cualquier llamada HTTP.
        """
        try:
            seller_id_int = int(seller_id)
        except (TypeError, ValueError) as e:
            raise ValueError(f"seller_id no coercionable a int: {seller_id!r}") from e

        if not isinstance(date_from, datetime) or not isinstance(date_to, datetime):
            raise ValueError(f"date_from/date_to must be datetimes: {date_from!r}, {date_to!r}")
        if date_from.tzinfo is None or date_to.tzinfo is None:
            raise ValueError("date_from/date_to must be timezone-aware")

        resource = (
            f"/orders/search?seller={seller_id_int}"
            f"&order.date_last_updated.from={date_from.isoformat()}"
            f"&order.date_last_updated.to={date_to.isoformat()}"
            f"&offset={offset}"
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{self.base_url}/api/ml/orders", params={"resource": resource})
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Error buscando órdenes (seller={seller_id_int}, offset={offset}): {e}")
            return None

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

    async def get_item_promotions(self, mla_id: str) -> Optional[List[Dict]]:
        """Obtiene las promociones de un item puntual vía el proxy ml-webhook.

        Args:
            mla_id: El ID del item (ej: MLA2361127120).

        Returns:
            LISTA de promos del item (payload crudo del proxy: el endpoint
            `/api/promociones/item/<MLA>` devuelve un array de entradas, cada
            una con `id` (=promotion_id), `type`, `status`, precios, etc.), o
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

    async def refresh_item_promotions(self, mla_id: str) -> bool:
        """Triggers a server-side point-refresh of the ml-webhook mirror
        for a single item, right after our own enroll/remove write, so
        dependent consumers (panel/L1 badges, list filters, price sync)
        stop showing stale state until the next webhook/backfill cycle.

        Args:
            mla_id: The item ID (e.g. MLA2361127120).

        Returns:
            True on 2xx, False on any error (404 route-absent, other
            4xx/5xx, timeout, or any other exception) — mirrors the read
            methods' error-swallowing shape, NEVER raises. A route-absent
            404 degrades gracefully back to the existing backfill cadence.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{self.base_url}/api/promociones/item/{mla_id}/refresh")
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Error refrescando promociones del item {mla_id}: {e}")
            return False

    # ── PxQ (wholesale price-by-quantity, PR3) ───────────────────────
    # Mirrors the promotions read/write shapes above: reads collapse errors
    # to None, writes always return the structured {ok, status_code,
    # ambiguous, body} outcome so the orchestrator (ml_pxq_write_service)
    # can distinguish a definitive rejection from a genuinely ambiguous
    # timeout/5xx. `POST /items/{item_id}/prices/standard/quantity`
    # REPLACES the whole array -- see pxq_diff.py.

    async def get_pxq_prices(self, item_id: str) -> Optional[List[Dict]]:
        """Fresh, never-cached read of an item's live PxQ tiers.

        Returns:
            The raw `prices` array from ML (each entry carries `id`,
            `quantity`, `amount`), or None on error/timeout -- the write
            path treats None as `rejected_read_unavailable`.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/pxq/item/{item_id}")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error obteniendo precios PxQ del item {item_id}: {e}")
            return None

    async def post_pxq_prices(self, item_id: str, prices: List[Dict]) -> Dict:
        """Replaces the FULL PxQ prices array for an item (single-shot, no
        retry -- a blind retry on an ambiguous write could double-apply
        it, same contract as `enroll_item`/`remove_item`).

        Returns:
            `{ok, status_code, ambiguous, body}` -- see
            `_classify_pxq_write_response`.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(f"{self.base_url}/api/pxq/item/{item_id}", json={"prices": prices})
        except Exception as e:
            logger.error(f"Error (ambiguo) escribiendo precios PxQ del item {item_id}: {e}")
            return {"ok": False, "status_code": None, "ambiguous": True, "body": None}

        return self._classify_pxq_write_response(response)

    @classmethod
    def _classify_pxq_write_response(cls, response: httpx.Response) -> Dict:
        """Classifies a PxQ write, refining the shared status-only verdict
        with the `pxq_write` field the proxy stamps on the responses IT
        generates.

        Status code alone cannot separate "the write never left" from "the
        write may have landed": a 502 the proxy raises because its own
        pre-write read failed is byte-identical to a 502 relayed from ML,
        and the two mean opposite things. Hence the field, and hence its
        ABSENCE being meaningful -- no field means the response is an ML
        passthrough, untouched by the proxy.

            2xx     / absent          -> written (ML passthrough)
            400     / not_attempted   -> not written (payload refused by proxy)
            502     / not_attempted   -> not written (pre-write read failed)
            504     / ambiguous       -> maybe written (POST to ML timed out)
            500     / ambiguous       -> maybe written (handler exception)
            non-2xx / absent          -> ML error relayed as-is

        DELIBERATE DEVIATION from the provider's stated rule. Theirs reads:
        `not_attempted` means not written, ANY other non-2xx (`ambiguous`,
        or field absent) is ambiguous. We follow it except for a 4xx with
        no field, which we keep as a definitive rejection.

        Why: on our side `ambiguous=True` is not merely a retry gate. In
        `ml_pxq_write_service.sync_pxq_tiers` it writes `estado =
        desconocido` across the mirror rows and commits, forcing a manual
        reconciliation. A 4xx relayed from ML (e.g. "You can just send a
        maximum of 5 prices per quantity") is ML refusing the payload after
        looking at it -- we KNOW nothing was applied. Marking those tiers
        `desconocido` would not be conservative, it would persist a
        falsehood and send someone to reconcile a write that never
        happened. The provider wrote their rule without knowing our flag
        mutates state. The deviation was declared to them so they can veto
        it; do not "fix" it back without that conversation.

        Kept SEPARATE from `_classify_write_response` on purpose: that one
        is shared with `enroll_item` / `remove_item` (promotions), whose
        responses have no `pxq_write` field. Folding this rule in there
        would turn every promotions non-2xx into an ambiguous write.
        """
        result = cls._classify_write_response(response)
        if result["ok"]:
            return result

        body = result["body"]
        # Guarded: an error body is whatever the proxy or ML happened to
        # emit -- a list, a string, or nothing parseable at all.
        pxq_write = body.get("pxq_write") if isinstance(body, dict) else None

        if pxq_write == "not_attempted":
            result["ambiguous"] = False
        elif pxq_write == "ambiguous":
            result["ambiguous"] = True
        # Field absent: the shared status-only verdict already says the
        # right thing (5xx unknown, 4xx definitive), including the
        # deviation documented above.
        return result

    async def get_pxq_seller_shipping_cost(self, item_id: str, quantity: int, tier_price: float) -> Optional[float]:
        """Fetches the whole-shipment shipping cost for an N-unit PxQ tier
        order, via the proxy route `GET /api/shipping/seller-cost`.

        NOTE: this route does not exist on the ml-webhook proxy yet. A 404
        is the CURRENT real-world response and is treated identically to
        every other failure mode -- there is no special-casing "route
        absent" as distinct from "server error." Callers (`refresh_tier_shipping`
        in `pxq_markup_service.py`) treat None as `shipping_unavailable` and
        MUST NOT fabricate a 0 or a markup from it.

        Same None-on-anything collapse shape as `get_item_full`
        (:479-494) / `post_pxq_prices` classification (:574-599): 404,
        any other non-2xx, a timeout, or a body that does not carry a
        numeric `amount` field all collapse to None. Only a 2xx body with
        a numeric `amount` returns a value.

        Args:
            item_id: The item ID (e.g. MLA2361127120).
            quantity: The tier's `cantidad_minima`.
            tier_price: The tier's `precio_unitario`.

        Returns:
            The whole-shipment cost as a float, or None on any error.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/shipping/seller-cost",
                    params={"item_id": item_id, "quantity": quantity, "tier_price": tier_price},
                )
                response.raise_for_status()
                body = response.json()
        except Exception as e:
            logger.error(f"Error obteniendo costo de envío PxQ del item {item_id}: {e}")
            return None

        if not isinstance(body, dict):
            return None
        amount = body.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return None
        return float(amount)

    async def get_pxq_eligibility(self, item_id: str) -> Optional[Dict]:
        """Fetches the eligibility facts for a PxQ sync: the item's own
        `tags` (must include `standard_price_by_quantity`) and the
        seller's `tags` (must include `business`).

        Returns:
            `{"item_tags": [...], "seller_tags": [...]}`, or None if
            either the item or the seller could not be read -- the
            write path treats None as ineligible (fail-closed).
        """
        item = await self.get_item_full(item_id)
        if item is None:
            return None
        seller_id = item.get("seller_id")
        if seller_id is None:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/ml/render", params={"resource": f"/users/{seller_id}", "format": "json"}
                )
                response.raise_for_status()
                seller = response.json()
        except Exception as e:
            logger.error(f"Error obteniendo vendedor {seller_id} para elegibilidad PxQ de {item_id}: {e}")
            return None
        return {"item_tags": item.get("tags") or [], "seller_tags": seller.get("tags") or []}


# Instancia global del cliente
ml_webhook_client = MLWebhookClient()
