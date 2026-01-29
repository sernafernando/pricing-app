"""
Endpoint para parsear respuestas SOAP del ERP (reemplazo del worker de Cloudflare)
"""
from fastapi import APIRouter, HTTPException, Request
from typing import Optional, Dict, Any
import httpx
import re
import json
import os
from pydantic import BaseModel

router = APIRouter()

# Configuración del ERP desde variables de entorno
P_USERNAME = os.getenv("GBP_USERNAME")
P_PASSWORD = os.getenv("GBP_PASSWORD")
P_COMPANY = os.getenv("GBP_COMPANY")
P_WEBWS = os.getenv("GBP_WEBWS", "wsBasicQuery")
SOAP_URL = "http://ws.globalbluepoint.com/pastoriza/app_webservices/wsBasicQuery.asmx"

# Cache en memoria para el token (simple, sin Redis)
_token_cache = {"token": None}

# Configuración de scripts permitidos
SCRIPT_CONFIG = {
    "scriptDashboard": ["fromDate", "toDate"],
    "scriptVentasFuera2": ["fromDate", "toDate"],
    "OtroScript": ["item_id"],
    "scriptVentasML": ["fromDate", "toDate", "itemID"],
    "serialToSheets": ["itemSerial"],
    "mlidToSheets": ["mlID"],
    "scriptAgeing": ["item_id"],
    "scriptMLTitle": ["item_id"],
    "scriptTpLink": ["fromDate", "toDate"],
    "scriptCommercial": ["fromDate", "toDate", "ctTransaction", "fromCtTransaction", "toCtTransaction"],
    "scriptItemTransaction": ["fromDate", "toDate", "itTransaction"],
    "scriptItemTransactionDetails": ["fromItTransaction", "fromItTransaction"],
    "scriptMLOrdersHeader": ["fromDate", "toDate", "mloId"],
    "scriptMLOrdersDetail": ["fromDate", "toDate", "mlodId"],
    "scriptMLOrdersShipping": ["fromDate", "toDate", "mlmId", "mloId", "MLshippingID"],
    "scriptMLItemsPublicados": ["fromDate", "toDate", "mlpId", "itemID", "mlaID"],
    "scriptItemCostListHistory": ["fromDate", "toDate", "iclhID"],
    "scriptItemCostList": ["fromDate", "toDate", "coslisID"],
    "scriptCurExchHistory": ["fromDate", "toDate","cehID"],
    "scriptSaleOrderHeader": ["fromDate", "toDate", "sohID", "braID", "updateFromDate", "updateToDate"],
    "scriptSaleOrderDetail": ["fromDate", "toDate", "sohID", "sohID2", "sodID", "braID", "updateFromDate", "updateToDate"],
    "scriptSaleOrderHeaderHistory": ["fromDate", "toDate", "sohID", "sohhID", "braID", "updateFromDate", "updateToDate"],
    "scriptSaleOrderDetailHistory": ["fromDate", "toDate", "sohID", "sohhID", "sodID", "braID"],
    "scriptVentasFueraOM": ["fromDate", "toDate", "braID"],
    "scriptBrand": ["brandID"],
    "scriptCategory": ["catID"],
    "scriptSubCategory": ["catID", "subCatID"],
    "scriptItem": ["brandID", "catID", "subCatID", "itemID", "itemCode", "lastUpdate", "lastUpdateByProcess"],
    "scriptTaxName": ["taxID"],
    "scriptItemTaxes": ["taxID", "itemID"],
    "scriptSupplier": ["suppID", "cuit"],
    "scriptItemSerials": ["fromDate", "toDate", "isID", "isIDfrom", "isIDto", "itemID", "isSerial", "ctTransaction", "itTransaction"],
    "scriptCustomer": ["custID", "fromCustID", "toCustID", "lastUpdate"],
    "scriptBranch": ["braID", "frombraID", "tobraID"],
    "scriptSalesman": ["smID", "fromSmID", "toSmID"],
    "scriptDocumentFile": ["dfID", "braID"],
    "scriptFiscalClass": ["fcID"],
    "scriptTaxNumberType": ["tntID"],
    "scriptState": ["countryID", "stateID"],
    "scriptItemAssociation": ["itemAID", "itemAID4update", "itemID", "item1ID"],
    "scriptTiendaNubeOrders": ["fromDate", "toDate", "tnoID", "tnoIDfrom", "tnoIDto"],
    "scriptEnvios": ["fromDate", "toDate"],
    "scriptSaleOrderTimes": ["fromDate", "toDate", "sohID", "braID", "sotID"]
}

# Configuración de operaciones
OPERATION_CONFIG = {
    "ItemStorage_funGetXMLData": {
        "soapAction": "http://microsoft.com/webservices/ItemStorage_funGetXMLData",
        "params": ["intStor_id", "intItem_id"],
        "template": """<ItemStorage_funGetXMLData xmlns="http://microsoft.com/webservices/">
            <intStor_id>{intStor_id}</intStor_id>
            <intItem_id>{intItem_id}</intItem_id>
        </ItemStorage_funGetXMLData>"""
    },
    "wsExportDataById": {
        "soapAction": "http://microsoft.com/webservices/wsExportDataById",
        "params": ["intExpgr_id"],
        "template": """<wsExportDataById xmlns="http://microsoft.com/webservices/">
            <intExpgr_id>{intExpgr_id}</intExpgr_id>
        </wsExportDataById>"""
    },
    "wsGBPScriptExecute4Dataset": {
        "soapAction": "http://microsoft.com/webservices/wsGBPScriptExecute4Dataset",
        "params": ["strScriptLabel", "strJSonParameters"],
        "template": """<wsGBPScriptExecute4Dataset xmlns="http://microsoft.com/webservices/">
            <strScriptLabel>{strScriptLabel}</strScriptLabel>
            <strJSonParameters>{strJSonParameters}</strJSonParameters>
        </wsGBPScriptExecute4Dataset>"""
    },
    "wsItem_funGetXMLDataById": {
        "soapAction": "http://microsoft.com/webservices/wsItem_funGetXMLDataById",
        "params": ["intItemID"],
        "template": """<wsItem_funGetXMLDataById xmlns="http://microsoft.com/webservices/">
            <intItemID>{intItemID}</intItemID>
        </wsItem_funGetXMLDataById>"""
    },
    "ws_GetItemAssociationOrComposition": {
        "soapAction": "http://microsoft.com/webservices/ws_GetItemAssociationOrComposition",
        "params": ["intItemID", "bolIsAssociation"],
        "template": """<ws_GetItemAssociationOrComposition xmlns="http://microsoft.com/webservices/">
            <intItemID>{intItemID}</intItemID>
            <bolIsAssociation>{bolIsAssociation}</bolIsAssociation>
        </ws_GetItemAssociationOrComposition>"""
    },
    "PriceListItems_funGetXMLData": {
        "soapAction": "http://microsoft.com/webservices/PriceListItems_funGetXMLData",
        "params": ["pPriceList", "pItem"],
        "template": """<PriceListItems_funGetXMLData xmlns="http://microsoft.com/webservices/">
            <pPriceList>{pPriceList}</pPriceList>
            <pItem>{pItem}</pItem>
        </PriceListItems_funGetXMLData>"""
    },
    "ItemBasicData_funGetXMLData": {
        "soapAction": "http://microsoft.com/webservices/ItemBasicData_funGetXMLData",
        "params": ["bitOnlyNewOrUpdated"],
        "template": """<ItemBasicData_funGetXMLData xmlns="http://microsoft.com/webservices/">
            <bitOnlyNewOrUpdated>{bitOnlyNewOrUpdated}</bitOnlyNewOrUpdated>
        </ItemBasicData_funGetXMLData>"""
    },
    "Item_funGetXMLData": {
        "soapAction": "http://microsoft.com/webservices/Item_funGetXMLData",
        "params": [],
        "template": """<Item_funGetXMLData xmlns="http://microsoft.com/webservices/" />"""
    },
    "ws_GetLatestItemsUpdated": {
        "soapAction": "http://microsoft.com/webservices/ws_GetLatestItemsUpdated",
        "params": ["intLastUpdateID"],
        "template": """<ws_GetLatestItemsUpdated xmlns="http://microsoft.com/webservices/">
            <intLastUpdateID>{intLastUpdateID}</intLastUpdateID>
        </ws_GetLatestItemsUpdated>"""
    },
    "Category_funGetXMLData": {
        "soapAction": "http://microsoft.com/webservices/Category_funGetXMLData",
        "params": [],
        "template": """<Category_funGetXMLData xmlns="http://microsoft.com/webservices/" />"""
    },
    "SubCategory_funGetXMLData": {
        "soapAction": "http://microsoft.com/webservices/SubCategory_funGetXMLData",
        "params": ["pCategory"],
        "template": """<SubCategory_funGetXMLData xmlns="http://microsoft.com/webservices/">
            <pCategory>{pCategory}</pCategory>
        </SubCategory_funGetXMLData>"""
    }
}


async def authenticate_user() -> str:
    """Autentica con el ERP y retorna el token"""
    soap_action = "http://microsoft.com/webservices/AuthenticateUser"
    xml_payload = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                   xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Header>
        <wsBasicQueryHeader xmlns="http://microsoft.com/webservices/">
          <pUsername>{P_USERNAME}</pUsername>
          <pPassword>{P_PASSWORD}</pPassword>
          <pCompany>{P_COMPANY}</pCompany>
          <pBranch>1</pBranch>
          <pLanguage>2</pLanguage>
          <pWebWervice>{P_WEBWS}</pWebWervice>
        </wsBasicQueryHeader>
      </soap:Header>
      <soap:Body>
        <AuthenticateUser xmlns="http://microsoft.com/webservices/" />
      </soap:Body>
    </soap:Envelope>"""

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            SOAP_URL,
            content=xml_payload,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": soap_action
            }
        )

    match = re.search(r'<AuthenticateUserResult>(.*?)</AuthenticateUserResult>', response.text)
    if not match:
        raise HTTPException(status_code=500, detail="No se pudo obtener token del ERP")

    token = match.group(1)
    _token_cache["token"] = token
    return token


async def call_soap_service(soap_body: str, soap_action: str, token: str) -> str:
    """Llama al servicio SOAP del ERP"""
    xml_payload = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                   xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Header>
        <wsBasicQueryHeader xmlns="http://microsoft.com/webservices/">
          <pUsername>{P_USERNAME}</pUsername>
          <pPassword>{P_PASSWORD}</pPassword>
          <pCompany>{P_COMPANY}</pCompany>
          <pWebWervice>{P_WEBWS}</pWebWervice>
          <pAuthenticatedToken>{token}</pAuthenticatedToken>
        </wsBasicQueryHeader>
      </soap:Header>
      <soap:Body>
        {soap_body}
      </soap:Body>
    </soap:Envelope>"""

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            SOAP_URL,
            content=xml_payload,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": soap_action
            }
        )

    return response.text


def parse_soap_response(xml_content: str) -> Any:
    """Parsea la respuesta SOAP y extrae los datos"""
    # Buscar el tag Result
    match = re.search(r'<\w*:?\s*\w+Result[^>]*>([\s\S]*?)</\w*:?\s*\w+Result>', xml_content)
    if not match:
        return [{"error": "No se encontró el tag result"}]

    # Decodificar entidades HTML
    inner_xml = match.group(1)
    inner_xml = inner_xml.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    inner_xml = inner_xml.replace('&quot;', '"').replace('&apos;', "'")

    # Remover CDATA
    inner_xml = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', inner_xml, flags=re.DOTALL)

    # Buscar tablas
    tables = re.findall(r'<Table[\s\S]*?</Table>', inner_xml)

    if tables:
        rows = []
        for table_xml in tables:
            row = {}
            # Extraer tags
            tag_matches = re.findall(r'<([^>/\s]+)>([^<]*)</\1>', table_xml)
            for tag_name, tag_value in tag_matches:
                value = tag_value.strip()

                # Intentar parsear JSON
                if value and len(value) > 1:
                    first, last = value[0], value[-1]
                    if (first == '{' and last == '}') or (first == '[' and last == ']'):
                        try:
                            value = json.loads(value)
                        except (json.JSONDecodeError, ValueError):
                            pass

                row[tag_name] = value

            rows.append(row)

        # Si es una sola fila con un solo campo que es un array, retornar el array
        if len(rows) == 1 and len(rows[0]) == 1:
            value = list(rows[0].values())[0]
            if isinstance(value, list):
                return value

        return rows
    else:
        # Buscar JSON directo
        json_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', inner_xml)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except (json.JSONDecodeError, ValueError):
                return [{"raw": inner_xml}]
        else:
            return [{"raw": inner_xml}]


@router.api_route("/gbp-parser", methods=["GET", "POST"])
async def gbp_parser(request: Request):
    """
    Endpoint para parsear respuestas SOAP del ERP.
    Reemplaza el worker de Cloudflare.

    Soporta tanto GET (query params) como POST (body JSON)
    """
    try:
        # Obtener parámetros (GET o POST)
        if request.method == "GET":
            body = dict(request.query_params)
            # Convertir números
            for k, v in body.items():
                if v.strip():
                    try:
                        num_val = float(v)
                        if num_val.is_integer():
                            body[k] = int(num_val)
                        else:
                            body[k] = num_val
                    except (ValueError, AttributeError):
                        pass
        else:
            body = await request.json()

        if not body:
            raise HTTPException(status_code=400, detail="No se enviaron parámetros")

        intExpgr_id = body.get("intExpgr_id")
        strScriptLabel = body.get("strScriptLabel")
        opName = body.get("opName")

        soap_body = ""
        soap_action = None

        # Construir SOAP body según tipo de operación
        if intExpgr_id:
            conf = OPERATION_CONFIG["wsExportDataById"]
            soap_action = conf["soapAction"]
            soap_body = conf["template"].format(intExpgr_id=intExpgr_id)

        elif strScriptLabel:
            allowed_params = SCRIPT_CONFIG.get(strScriptLabel, [])
            params = {k: body[k] for k in allowed_params if k in body}
            json_params = json.dumps(params)

            conf = OPERATION_CONFIG["wsGBPScriptExecute4Dataset"]
            soap_action = conf["soapAction"]
            soap_body = conf["template"].format(
                strScriptLabel=strScriptLabel,
                strJSonParameters=json_params
            )

        elif opName:
            conf = OPERATION_CONFIG.get(opName)
            if not conf:
                raise HTTPException(status_code=400, detail=f"Operación desconocida: {opName}")

            # Construir parámetros
            params = {}
            for param in conf["params"]:
                if param in body:
                    params[param] = body[param]
                else:
                    params[param] = -1

            soap_action = conf["soapAction"]
            soap_body = conf["template"].format(**params)

        else:
            raise HTTPException(status_code=400, detail="Faltan parámetros válidos (intExpgr_id, strScriptLabel o opName)")

        # Obtener o crear token
        token = _token_cache.get("token")
        if not token:
            token = await authenticate_user()

        # Llamar al SOAP
        xml_content = await call_soap_service(soap_body, soap_action, token)

        # Si el token expiró, renovar y reintentar
        if "TOKEN Expired" in xml_content:
            token = await authenticate_user()
            xml_content = await call_soap_service(soap_body, soap_action, token)

        # Parsear respuesta
        data = parse_soap_response(xml_content)

        return data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gbp-parser/health")
async def health_check():
    """Health check del parser"""
    return {"status": "ok", "service": "gbp-parser"}
