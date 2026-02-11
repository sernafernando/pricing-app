"""
Cliente para consultar órdenes de TiendaNube API
Basado en el visualizador-pedidos original
"""

import httpx
import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class TiendaNubeOrderClient:
    """
    Cliente para consultar detalles de órdenes desde TiendaNube API.

    Uso:
        client = TiendaNubeOrderClient()
        order_data = await client.get_order_details(12345)
    """

    def __init__(self):
        self.store_id = os.getenv("TN_STORE_ID")
        self.access_token = os.getenv("TN_ACCESS_TOKEN")

        if not self.store_id or not self.access_token:
            logger.warning("TN_STORE_ID o TN_ACCESS_TOKEN no configurados en .env")
            self.base_url = None
        else:
            self.base_url = f"https://api.tiendanube.com/v1/{self.store_id}"
            logger.info(f"TiendaNube Order Client inicializado para store_id: {self.store_id}")

        self.headers = {
            "Authentication": f"bearer {self.access_token}",
            "User-Agent": "GAUSS Pricing App (pricing@gaussonline.com.ar)",
            "Content-Type": "application/json",
        }

    async def get_order_details(self, order_id: int) -> Optional[Dict]:
        """
        Obtiene detalles de una orden desde TiendaNube API.

        Args:
            order_id: ID de la orden en TiendaNube

        Returns:
            Dict con datos de la orden:
            {
                'id': 12345,
                'number': 'NRO-0001234',
                'shipping_address': {
                    'phone': '+5491123456789',
                    'address': 'Av. Corrientes',
                    'number': '1234',
                    'floor': '5A',
                    'zipcode': '1043',
                    'city': 'Balvanera',
                    'locality': 'CABA',
                    'province': 'Ciudad Autónoma de Buenos Aires',
                    'name': 'Juan Pérez'
                }
            }

            None si hay error o no está configurado
        """
        if not self.base_url:
            logger.warning("TiendaNube API no configurada. Saltando consulta.")
            return None

        url = f"{self.base_url}/orders/{order_id}"
        logger.info(f"Consultando TiendaNube API: {url}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()

                order_data = response.json()
                logger.info(f"✅ Datos de TN orden {order_id} obtenidos: number={order_data.get('number')}")
                return order_data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Orden {order_id} no encontrada en TiendaNube (404)")
            else:
                logger.error(f"Error HTTP {e.response.status_code} al consultar TN orden {order_id}: {e.response.text}")
            return None

        except httpx.TimeoutException:
            logger.error(f"Timeout al consultar TN orden {order_id}")
            return None

        except httpx.RequestError as e:
            logger.error(f"Error de conexión al consultar TN orden {order_id}: {e}")
            return None

        except Exception as e:
            logger.error(f"Error inesperado al consultar TN orden {order_id}: {e}", exc_info=True)
            return None

    def build_shipping_address(self, shipping_address: Dict) -> str:
        """
        Construye dirección completa formateada desde datos de TN.

        Args:
            shipping_address: Dict con datos de shipping_address de TN API

        Returns:
            String con dirección formateada: "Av. Corrientes 1234 5A"
        """
        if not shipping_address:
            return ""

        address_parts = [shipping_address.get("address"), shipping_address.get("number"), shipping_address.get("floor")]

        return " ".join(filter(None, address_parts)).strip()
