import asyncio
import hashlib
import httpx
import logging
import time
from typing import Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import get_system_user_id
from app.models.producto import ProductoERP, ProductoPricing

logger = logging.getLogger(__name__)

# Timeout legacy para el fetch HTTP del gbp-parser. Conservado por si se
# necesita el fetch remoto como fallback, pero el flujo principal ahora usa
# fetch_productos_local() que ejecuta la query directo en PostgreSQL.
ERP_FETCH_TIMEOUT = 300.0


# Query optimizada espejo de la del gbp-parser (scriptItem extendido) ejecutada
# 100% local sobre las tablas espejo del ERP. Usa LATERAL JOIN en lugar de
# OUTER APPLY (equivalente PostgreSQL) y devuelve los mismos campos que la
# query SQL Server original para mantener compatibilidad con el resto del sync.
PRODUCTOS_LOCAL_SQL = """
SELECT DISTINCT
    ti.item_id                                              AS "Item_ID",
    tc.cat_desc                                             AS "Categoría",
    tb.brand_desc                                           AS "Marca",
    ti.item_code                                            AS "Código",
    UPPER(ti.item_desc)                                     AS "Descripción",

    CASE costo.curr_id WHEN 1 THEN 'ARS' WHEN 2 THEN 'USD' END  AS "Moneda_Costo",
    historia_costo.iclh_price                               AS "iclh_price",
    costo.coslis_price                                      AS "coslis_price",

    CASE tpli.curr_id WHEN 1 THEN 'ARS' WHEN 2 THEN 'USD' END   AS "Moneda",
    upp.it_price                                            AS "UPP",
    tpli.prli_price                                         AS "Lista_Precios_ML",

    ttn.tax_percentage                                      AS "IVA",
    tbmlip.mlp_price4freeshipping                           AS "Envío",
    ml_best.mlp_lastpriceinformedbyml                       AS "Precio_Publicado",
    tsc.subcat_id                                           AS "subcat_id",

    CASE
        WHEN ml_best.item_id IS NULL THEN NULL
        WHEN ml_best.mlp_active THEN 'Publicado'
        ELSE 'Pausado'
    END                                                     AS "Estado",

    ml_best.mlp_publicationid                               AS "MLA",
    ti.item_liquidation                                     AS "item_liquidation"

FROM tb_item ti
LEFT JOIN tb_category tc
    ON tc.comp_id = ti.comp_id AND tc.cat_id = ti.cat_id
LEFT JOIN tb_subcategory tsc
    ON tsc.comp_id = ti.comp_id AND tsc.cat_id = ti.cat_id AND tsc.subcat_id = ti.subcat_id
LEFT JOIN tb_brand tb
    ON tb.comp_id = ti.comp_id AND tb.brand_id = ti.brand_id
LEFT JOIN tb_mercadolibre_items_publicados tbmlip
    ON tbmlip.comp_id = ti.comp_id AND tbmlip.item_id = ti.item_id
LEFT JOIN tb_item_storage tis
    ON tis.comp_id = ti.comp_id AND tis.item_id = ti.item_id
LEFT JOIN tb_item_taxes tit
    ON tit.comp_id = ti.comp_id AND tit.item_id = ti.item_id
LEFT JOIN tb_tax_name ttn
    ON ttn.comp_id = ti.comp_id AND ttn.tax_id = tit.tax_id
LEFT JOIN tb_storage ts
    ON ts.comp_id = ti.comp_id AND ts.stor_id = tis.stor_id
INNER JOIN tb_price_list_items tpli
    ON tpli.comp_id = ti.comp_id AND tpli.item_id = ti.item_id AND tpli.prli_id = 4

LEFT JOIN LATERAL (
    SELECT ticl2.curr_id, ticl2.coslis_price
    FROM tb_item_cost_list ticl2
    WHERE ticl2.item_id = ti.item_id AND ticl2.coslis_id = 1
    LIMIT 1
) costo ON true

LEFT JOIN LATERAL (
    SELECT ticlh2.iclh_price
    FROM tb_item_cost_list_history ticlh2
    WHERE ticlh2.item_id = ti.item_id AND ticlh2.coslis_id = 1
    ORDER BY ticlh2.iclh_id DESC
    LIMIT 1
) historia_costo ON true

LEFT JOIN LATERAL (
    SELECT tit2.it_price
    FROM tb_item_transactions tit2
    WHERE tit2.item_id = ti.item_id AND tit2.puco_id = 10 AND tit2.stor_id = 1 AND tit2.it_price > 0
    ORDER BY tit2.it_cd DESC
    LIMIT 1
) upp ON true

LEFT JOIN LATERAL (
    SELECT mlp2.item_id, mlp2.mlp_lastpriceinformedbyml, mlp2.mlp_active, mlp2.mlp_publicationid
    FROM tb_mercadolibre_items_publicados mlp2
    WHERE mlp2.item_id = ti.item_id AND mlp2.mlp_listing_type_id = 'gold_special'
    ORDER BY
        CASE WHEN mlp2.mlp_catalog_listing THEN 0 ELSE 1 END,
        mlp2.mlp_lastupdate DESC NULLS LAST
    LIMIT 1
) ml_best ON true

WHERE
    (ts.stor_id IS NULL OR ts.stor_id <> 17)
    AND tc.cat_id NOT IN (1, 67, 72)
    AND (tis.stor_id = 1 OR tis.stor_id IS NULL)
    AND (tbmlip.mlp_listing_type_id = 'gold_special' OR tbmlip.mlp_listing_type_id IS NULL)
"""

# Stock por item del depósito 1 (reemplaza el fetch HTTP a ItemStorage_funGetXMLData).
STOCK_LOCAL_SQL = """
SELECT item_id, COALESCE(itst_cant, 0) AS stock
FROM tb_item_storage
WHERE stor_id = 1
"""


def convertir_a_numero(valor, default=0):
    """Convierte string a número, maneja decimales"""
    try:
        if valor is None or valor == "":
            return default
        if isinstance(valor, (int, float)):
            return valor
        return float(str(valor).replace(",", ""))
    except:
        return default


def convertir_a_entero(valor, default=0):
    """Convierte a entero, truncando decimales"""
    try:
        num = convertir_a_numero(valor, default)
        return int(float(num))
    except:
        return default


async def fetch_productos_erp() -> List[Dict]:
    """Trae productos del ERP via gbp-parser (localhost)"""
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=ERP_FETCH_TIMEOUT) as client:
        response = await client.post(settings.GBP_PARSER_URL, json={"intExpgr_id": 64})
        response.raise_for_status()
        data = response.json()
    elapsed = time.monotonic() - start
    logger.info("fetch_productos_erp: %d items en %.1fs", len(data), elapsed)
    return data


async def fetch_stock_erp() -> Dict[int, int]:
    """Trae stock de todos los productos via gbp-parser (localhost)"""
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=ERP_FETCH_TIMEOUT) as client:
        response = await client.get(
            settings.GBP_PARSER_URL, params={"opName": "ItemStorage_funGetXMLData", "intStor_id": 1, "intItem_id": -1}
        )
        response.raise_for_status()
        data = response.json()

        stock_dict = {}
        for item in data:
            item_id = convertir_a_entero(item.get("item_id"))
            stock = convertir_a_entero(item.get("Stock", 0))
            stock_dict[item_id] = stock

    elapsed = time.monotonic() - start
    logger.info("fetch_stock_erp: %d items en %.1fs", len(stock_dict), elapsed)
    return stock_dict


def calcular_hash(producto: Dict) -> str:
    """Calcula hash de los datos relevantes para detectar cambios"""
    datos = f"{producto.get('Código', '')}{producto.get('coslis_price', 0)}{producto.get('Descripción', '')}{producto.get('Stock', 0)}{producto.get('Envío', 0)}"
    return hashlib.sha256(datos.encode()).hexdigest()


def fetch_productos_local(db: Session) -> List[Dict]:
    """Ejecuta la query optimizada sobre las tablas espejo locales en PostgreSQL.

    Reemplaza el fetch HTTP al gbp-parser (que tarda 2+ min). Asume que las tablas
    espejo (`tb_item`, `tb_price_list_items`, `tb_item_storage`, etc.) están al día
    via cron de `sync_all_incremental`.
    """
    start = time.monotonic()
    result = db.execute(text(PRODUCTOS_LOCAL_SQL))
    productos = [dict(row._mapping) for row in result]
    elapsed = time.monotonic() - start
    logger.info("✅ fetch_productos_local: %d items en %.2fs", len(productos), elapsed)
    return productos


def fetch_stock_local(db: Session) -> Dict[int, int]:
    """Trae el stock por item del depósito 1 desde tb_item_storage local."""
    start = time.monotonic()
    result = db.execute(text(STOCK_LOCAL_SQL))
    stock_dict = {row.item_id: convertir_a_entero(row.stock) for row in result}
    elapsed = time.monotonic() - start
    logger.info("✅ fetch_stock_local: %d items en %.2fs", len(stock_dict), elapsed)
    return stock_dict


async def sincronizar_erp(db: Session) -> Dict:
    """Sincroniza productos del ERP con la base de datos.

    Flujo:
    1. Sync incremental rápido de tb_price_list_items (precios cambian seguido).
    2. Ejecuta la query optimizada SOBRE las tablas espejo locales (no HTTP al ERP).
    3. **Stock se trae por HTTP via gbp-parser** (`ItemStorage_funGetXMLData`) porque
       `tb_item_storage` se actualiza por `itst_LastAvailableInRelalculation`, que solo
       se mueve al recalcular disponibilidad — NO refleja cambios de stock real-time
       (ventas, movimientos). El fetch HTTP es rápido (~1-2 seg) y trae el estado actual.
    4. Procesa los resultados igual que antes (upsert en productos_erp + pricing).

    Las demás tablas espejo (tb_item, tb_brand, tb_mercadolibre_items_publicados, etc.)
    se asume que las mantiene al día el cron de sync_all_incremental.
    """

    stats = {
        "productos_nuevos": 0,
        "productos_actualizados": 0,
        "productos_sin_cambios": 0,
        "productos_duplicados": 0,
        "precios_sincronizados": 0,
        "errores": [],
    }

    try:
        system_user_id = get_system_user_id(db)

        # Sync previo de tb_price_list_items (precios cambian con frecuencia).
        # to_thread porque la función usa requests bloqueante.
        # NOTA: tb_item_storage NO se sincroniza acá; el stock se trae directo del ERP
        # más abajo via fetch_stock_erp() para tener valores real-time.
        from app.scripts.sync_price_list_items import sync_price_list_items_incremental

        logger.info("🔄 Sincronizando tb_price_list_items (lista 4)...")
        await asyncio.to_thread(sync_price_list_items_incremental, db, price_list_id=4)

        logger.info("🔄 Ejecutando query local de productos...")
        productos = fetch_productos_local(db)

        logger.info("🔄 Trayendo stock real-time del ERP (gbp-parser)...")
        stock_dict = await fetch_stock_erp()

        logger.info("🔄 Procesando %d productos...", len(productos))

        # Detectar duplicados en el ERP
        items_dict = {}

        for producto_data in productos:
            item_id = convertir_a_entero(producto_data.get("Item_ID"))
            envio_actual = convertir_a_numero(producto_data.get("Envío"), 0)

            if item_id in items_dict:
                # Si ya existe, comparar envío
                envio_guardado = convertir_a_numero(items_dict[item_id].get("Envío"), 0)
                if envio_actual > envio_guardado:
                    items_dict[item_id] = producto_data
                stats["productos_duplicados"] += 1
            else:
                items_dict[item_id] = producto_data

        productos_unicos = list(items_dict.values())

        print(
            f"Productos únicos: {len(productos_unicos)}, duplicados resueltos por mayor envío: {stats['productos_duplicados']}"
        )

        # Procesar en lotes de 100
        batch_size = 100
        for i in range(0, len(productos_unicos), batch_size):
            batch = productos_unicos[i : i + batch_size]

            for producto_data in batch:
                try:
                    item_id = convertir_a_entero(producto_data.get("Item_ID"))
                    if not item_id:
                        continue

                    stock = stock_dict.get(item_id, 0)
                    producto_data["Stock"] = stock
                    hash_nuevo = calcular_hash(producto_data)

                    producto_existente = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

                    codigo = str(producto_data.get("Código", "")).replace('"', "")
                    costo = convertir_a_numero(producto_data.get("coslis_price", 0))
                    iva = convertir_a_numero(producto_data.get("IVA", 0))
                    precio_publicado = convertir_a_numero(producto_data.get("Precio_Publicado"), None)
                    envio = convertir_a_numero(producto_data.get("Envío"), None)
                    subcategoria_id = convertir_a_entero(producto_data.get("subcat_id"), None)

                    if not producto_existente:
                        nuevo_producto = ProductoERP(
                            item_id=item_id,
                            codigo=codigo,
                            descripcion=producto_data.get("Descripción"),
                            marca=producto_data.get("Marca"),
                            categoria=producto_data.get("Categoría"),
                            subcategoria_id=subcategoria_id,
                            moneda_costo=producto_data.get("Moneda_Costo"),
                            costo=costo,
                            iva=iva,
                            stock=stock,
                            envio=envio,
                            hash_datos=hash_nuevo,
                        )
                        db.add(nuevo_producto)
                        stats["productos_nuevos"] += 1

                    elif producto_existente.hash_datos != hash_nuevo:
                        producto_existente.codigo = codigo
                        producto_existente.descripcion = producto_data.get("Descripción")
                        producto_existente.marca = producto_data.get("Marca")
                        producto_existente.categoria = producto_data.get("Categoría")
                        producto_existente.subcategoria_id = subcategoria_id
                        producto_existente.moneda_costo = producto_data.get("Moneda_Costo")
                        producto_existente.costo = costo
                        producto_existente.iva = iva
                        producto_existente.stock = stock
                        producto_existente.envio = envio
                        producto_existente.hash_datos = hash_nuevo
                        stats["productos_actualizados"] += 1
                    else:
                        if producto_existente.stock != stock:
                            producto_existente.stock = stock
                            stats["productos_actualizados"] += 1
                        else:
                            stats["productos_sin_cambios"] += 1

                    # SINCRONIZAR PRECIO si viene del ERP
                    if precio_publicado and precio_publicado > 0:
                        pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

                        # SOLO actualizar si NO existe o NO tiene precio
                        if not pricing or pricing.precio_lista_ml is None:
                            from app.services.pricing_calculator import (
                                obtener_tipo_cambio_actual,
                                convertir_a_pesos,
                                obtener_grupo_subcategoria,
                                obtener_comision_base,
                                calcular_comision_ml_total,
                                calcular_limpio,
                                calcular_markup,
                            )

                            moneda_costo = producto_data.get("Moneda_Costo")
                            tipo_cambio = None
                            if moneda_costo == "USD":
                                tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

                            costo_ars = convertir_a_pesos(costo, moneda_costo, tipo_cambio)
                            grupo_id = obtener_grupo_subcategoria(db, subcategoria_id)
                            comision_base = obtener_comision_base(db, 4, grupo_id)

                            markup_calculado = None
                            if comision_base:
                                # Usar db=db para obtener constantes actualizadas de pricing_constants
                                comisiones = calcular_comision_ml_total(precio_publicado, comision_base, iva, db=db)
                                limpio = calcular_limpio(
                                    precio_publicado,
                                    iva,
                                    envio or 0,
                                    comisiones["comision_total"],
                                    db=db,
                                    grupo_id=grupo_id,
                                )
                                markup = calcular_markup(limpio, costo_ars)
                                markup_calculado = round(markup * 100, 2)

                            if not pricing:
                                pricing = ProductoPricing(
                                    item_id=item_id,
                                    precio_lista_ml=precio_publicado,
                                    markup_calculado=markup_calculado,
                                    usuario_id=system_user_id,
                                    motivo_cambio="Sincronización ERP - Inicial",
                                )
                                db.add(pricing)
                                stats["precios_sincronizados"] += 1

                except Exception as e:
                    stats["errores"].append(f"Error en item {item_id}: {str(e)}")

            # Commit por lote
            try:
                db.commit()
                print(f"Lote {i // batch_size + 1} procesado ({i + len(batch)}/{len(productos_unicos)})")
            except Exception as e:
                db.rollback()
                stats["errores"].append(f"Error en lote {i // batch_size + 1}: {str(e)}")

        print(f"Sincronización completada: {stats}")

    except Exception as e:
        db.rollback()
        stats["errores"].append(f"Error general: {str(e)}")
        print(f"Error en sincronización: {e}")

    return stats
