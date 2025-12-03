"""
Cliente para consumir los endpoints del Cloudflare Worker del ERP
"""
import httpx
from typing import Optional, List, Dict, Any
from datetime import date
from app.core.config import settings


class ERPWorkerClient:
    """Cliente para interactuar con el worker de Cloudflare del ERP"""

    def __init__(self):
        self.base_url = settings.ERP_BASE_URL
        self.timeout = 30.0

    async def _fetch(self, script_label: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Ejecuta una consulta al worker del ERP

        Args:
            script_label: Nombre del script a ejecutar (ej: scriptBrand)
            params: Parámetros opcionales para el query

        Returns:
            Lista de diccionarios con los resultados
        """
        query_params = {"strScriptLabel": script_label}
        if params:
            query_params.update(params)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/consulta",
                params=query_params
            )
            response.raise_for_status()
            return response.json()

    async def get_brands(self, brand_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtiene marcas del ERP

        Args:
            brand_id: ID de marca específica (opcional)

        Returns:
            Lista de marcas: [{"comp_id": 1, "brand_id": 69, "brand_desc": "..."}]
        """
        params = {}
        if brand_id:
            params["brandID"] = brand_id

        return await self._fetch("scriptBrand", params)

    async def get_categories(self, cat_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtiene categorías del ERP

        Args:
            cat_id: ID de categoría específica (opcional)

        Returns:
            Lista de categorías: [{"comp_id": 1, "cat_id": 46, "cat_desc": "..."}]
        """
        params = {}
        if cat_id:
            params["catID"] = cat_id

        return await self._fetch("scriptCategory", params)

    async def get_subcategories(
        self,
        cat_id: Optional[int] = None,
        subcat_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene subcategorías del ERP

        Args:
            cat_id: ID de categoría (opcional)
            subcat_id: ID de subcategoría (opcional)

        Returns:
            Lista de subcategorías: [{"comp_id": 1, "cat_id": 46, "subcat_id": 3818, "subcat_desc": "..."}]
        """
        params = {}
        if cat_id:
            params["catID"] = cat_id
        if subcat_id:
            params["subCatID"] = subcat_id

        return await self._fetch("scriptSubCategory", params)

    async def get_items(
        self,
        brand_id: Optional[int] = None,
        cat_id: Optional[int] = None,
        subcat_id: Optional[int] = None,
        item_id: Optional[int] = None,
        item_code: Optional[str] = None,
        last_update: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene items del ERP

        Args:
            brand_id: ID de marca (opcional)
            cat_id: ID de categoría (opcional)
            subcat_id: ID de subcategoría (opcional)
            item_id: ID de item (opcional)
            item_code: Código de item (opcional)
            last_update: Fecha de última actualización (opcional)

        Returns:
            Lista de items con toda su información
        """
        params = {}
        if brand_id:
            params["brandID"] = brand_id
        if cat_id:
            params["catID"] = cat_id
        if subcat_id:
            params["subCatID"] = subcat_id
        if item_id:
            params["itemID"] = item_id
        if item_code:
            params["itemCode"] = item_code
        if last_update:
            params["lastUpdate"] = last_update.isoformat()

        return await self._fetch("scriptItem", params)

    async def get_tax_names(self, tax_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtiene nombres de impuestos del ERP

        Args:
            tax_id: ID de impuesto (opcional)

        Returns:
            Lista de impuestos: [{"comp_id": 1, "tax_id": 1, "tax_desc": "...", "tax_percentage": 10.5}]
        """
        params = {}
        if tax_id:
            params["taxID"] = tax_id

        return await self._fetch("scriptTaxName", params)

    async def get_item_taxes(
        self,
        tax_id: Optional[int] = None,
        item_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene impuestos por item del ERP

        Args:
            tax_id: ID de impuesto (opcional)
            item_id: ID de item (opcional)

        Returns:
            Lista de impuestos por item: [{"comp_id": 1, "item_id": 11, "tax_id": 1, "tax_class": 1}]
        """
        params = {}
        if tax_id:
            params["taxID"] = tax_id
        if item_id:
            params["itemID"] = item_id

        return await self._fetch("scriptItemTaxes", params)

    async def get_suppliers(self, supp_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtiene proveedores del ERP

        Args:
            supp_id: ID de proveedor específico (opcional)

        Returns:
            Lista de proveedores: [{"comp_id": 1, "supp_id": 11, "supp_name": "...", "supp_taxNumber": "..."}]
        """
        params = {}
        if supp_id:
            params["suppID"] = supp_id

        return await self._fetch("scriptSupplier", params)

    async def get_customers(
        self,
        cust_id: Optional[int] = None,
        from_cust_id: Optional[int] = None,
        to_cust_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene clientes del ERP

        Args:
            cust_id: ID de cliente específico (opcional)
            from_cust_id: ID de cliente desde (para paginación)
            to_cust_id: ID de cliente hasta (para paginación)

        Returns:
            Lista de clientes con toda su información
        """
        params = {}
        if cust_id:
            params["custID"] = cust_id
        if from_cust_id:
            params["fromCustID"] = from_cust_id
        if to_cust_id:
            params["toCustID"] = to_cust_id

        return await self._fetch("scriptCustomer", params)

    async def get_branches(
        self,
        bra_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene sucursales del ERP

        Args:
            bra_id: ID de sucursal específica (opcional)

        Returns:
            Lista de sucursales
        """
        params = {}
        if bra_id:
            params["braID"] = bra_id

        return await self._fetch("scriptBranch", params)

    async def get_salesmen(
        self,
        sm_id: Optional[int] = None,
        from_sm_id: Optional[int] = None,
        to_sm_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene vendedores del ERP

        Args:
            sm_id: ID de vendedor específico (opcional)
            from_sm_id: ID desde (para paginación)
            to_sm_id: ID hasta (para paginación)

        Returns:
            Lista de vendedores
        """
        params = {}
        if sm_id:
            params["smID"] = sm_id
        if from_sm_id:
            params["fromSmID"] = from_sm_id
        if to_sm_id:
            params["toSmID"] = to_sm_id

        return await self._fetch("scriptSalesman", params)

    async def get_document_files(
        self,
        df_id: Optional[int] = None,
        bra_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene tipos de documento del ERP

        Args:
            df_id: ID de documento específico (opcional)
            bra_id: ID de sucursal (opcional)

        Returns:
            Lista de tipos de documento
        """
        params = {}
        if df_id:
            params["dfID"] = df_id
        if bra_id:
            params["braID"] = bra_id

        return await self._fetch("scriptDocumentFile", params)

    async def get_fiscal_classes(
        self,
        fc_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene clases fiscales del ERP

        Args:
            fc_id: ID de clase fiscal específica (opcional)

        Returns:
            Lista de clases fiscales
        """
        params = {}
        if fc_id:
            params["fcID"] = fc_id

        return await self._fetch("scriptFiscalClass", params)


# Instancia singleton del cliente
erp_worker_client = ERPWorkerClient()
