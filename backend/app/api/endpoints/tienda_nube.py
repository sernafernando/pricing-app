"""
Endpoints para sincronización de productos de Tienda Nube
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
import httpx
import os
import logging

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.usuario import Usuario

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuración de Tienda Nube desde variables de entorno
TN_STORE_ID = os.getenv("TN_STORE_ID")
TN_ACCESS_TOKEN = os.getenv("TN_ACCESS_TOKEN")


class SyncTiendaNubeResponse(BaseModel):
    total_productos: int
    total_variantes: int
    nuevos: int
    actualizados: int
    errores: int


@router.post("/sync", response_model=SyncTiendaNubeResponse)
async def sincronizar_tienda_nube(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Sincroniza productos y variantes desde Tienda Nube
    Equivalente al script de Google Sheets pero guardando en BD
    """
    if not TN_STORE_ID or not TN_ACCESS_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="Configuración de Tienda Nube no encontrada. Verificar TN_STORE_ID y TN_ACCESS_TOKEN en .env"
        )

    logger.info(f"Iniciando sincronización de Tienda Nube - Store ID: {TN_STORE_ID}")

    base_url = f"https://api.tiendanube.com/v1/{TN_STORE_ID}/products"
    per_page = 200
    page = 1
    all_products = []

    # Headers para la API
    headers = {
        "Authentication": f"bearer {TN_ACCESS_TOKEN}",
        "User-Agent": "GAUSS Pricing App (pricing@gaussonline.com.ar)"
    }

    # Obtener todos los productos con paginación
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            url = f"{base_url}?per_page={per_page}&page={page}"

            try:
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    products_page = response.json()

                    if not isinstance(products_page, list):
                        logger.error(f"Respuesta inesperada en página {page}")
                        break

                    all_products.extend(products_page)
                    logger.info(f"Página {page}: {len(products_page)} productos")

                    # Si obtenemos menos productos que el límite, es la última página
                    if len(products_page) < per_page:
                        break

                    page += 1

                elif response.status_code == 401:
                    raise HTTPException(
                        status_code=401,
                        detail="Token de acceso inválido o expirado"
                    )
                else:
                    logger.error(f"Error en API TN - Código: {response.status_code}")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error al consultar Tienda Nube: {response.text}"
                    )

            except httpx.HTTPError as e:
                logger.error(f"Error de conexión: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error de conexión con Tienda Nube: {str(e)}"
                )

    if not all_products:
        return SyncTiendaNubeResponse(
            total_productos=0,
            total_variantes=0,
            nuevos=0,
            actualizados=0,
            errores=0
        )

    logger.info(f"Total productos obtenidos: {len(all_products)}")

    # Procesar productos y variantes
    nuevos = 0
    actualizados = 0
    errores = 0
    total_variantes = 0

    # Primero, marcar todos como inactivos para luego actualizar solo los existentes
    db.execute(text("UPDATE tienda_nube_productos SET activo = false"))

    for product in all_products:
        product_id = product.get("id")
        product_name = product.get("name", {}).get("es", "Sin nombre")

        variants = product.get("variants", [])
        if not variants:
            # Si no hay variantes explícitas, usar datos del producto base
            variants = [{
                "id": product_id,
                "sku": "",
                "price": product.get("price"),
                "compare_at_price": None,
                "promotional_price": None
            }]

        for variant in variants:
            total_variantes += 1

            try:
                variant_id = variant.get("id")
                variant_sku = variant.get("sku", "")
                price = float(variant.get("price", 0)) if variant.get("price") else None
                compare_at_price = float(variant.get("compare_at_price", 0)) if variant.get("compare_at_price") else None
                promotional_price = float(variant.get("promotional_price", 0)) if variant.get("promotional_price") else None

                # Buscar si existe la variante
                existing = db.query(TiendaNubeProducto).filter(
                    TiendaNubeProducto.product_id == product_id,
                    TiendaNubeProducto.variant_id == variant_id
                ).first()

                if existing:
                    # Actualizar
                    existing.product_name = product_name
                    existing.variant_sku = variant_sku
                    existing.price = price
                    existing.compare_at_price = compare_at_price
                    existing.promotional_price = promotional_price
                    existing.activo = True
                    actualizados += 1
                else:
                    # Crear nuevo
                    nuevo_producto = TiendaNubeProducto(
                        product_id=product_id,
                        product_name=product_name,
                        variant_id=variant_id,
                        variant_sku=variant_sku,
                        price=price,
                        compare_at_price=compare_at_price,
                        promotional_price=promotional_price,
                        activo=True
                    )
                    db.add(nuevo_producto)
                    nuevos += 1

            except Exception as e:
                logger.error(f"Error procesando variante {variant.get('id')}: {e}")
                errores += 1

    # Intentar relacionar con productos del ERP por SKU
    try:
        # Primero intentar match exacto
        db.execute(text("""
            UPDATE tienda_nube_productos tn
            SET item_id = pe.item_id
            FROM productos_erp pe
            WHERE tn.variant_sku = pe.codigo
            AND tn.item_id IS NULL
            AND tn.variant_sku IS NOT NULL
            AND tn.variant_sku != ''
        """))

        # Intentar match sin el 0 inicial (ERP tiene 0123456, TN tiene 123456)
        # Solo para SKUs que empiezan con 0 y aún no tienen match
        db.execute(text("""
            UPDATE tienda_nube_productos tn
            SET item_id = pe.item_id
            FROM productos_erp pe
            WHERE tn.variant_sku = SUBSTRING(pe.codigo, 2)
            AND tn.item_id IS NULL
            AND tn.variant_sku IS NOT NULL
            AND tn.variant_sku != ''
            AND pe.codigo LIKE '0%'
            AND LENGTH(pe.codigo) > 1
        """))

        # Intentar match agregando 0 inicial (ERP tiene 0123456, TN tiene 123456)
        # Solo para SKUs que aún no tienen match
        db.execute(text("""
            UPDATE tienda_nube_productos tn
            SET item_id = pe.item_id
            FROM productos_erp pe
            WHERE '0' || tn.variant_sku = pe.codigo
            AND tn.item_id IS NULL
            AND tn.variant_sku IS NOT NULL
            AND tn.variant_sku != ''
            AND tn.variant_sku NOT LIKE '0%'
        """))

        logger.info("SKUs relacionados con productos ERP (con fallback de 0 inicial)")
    except Exception as e:
        logger.warning(f"No se pudieron relacionar SKUs: {e}")

    db.commit()

    logger.info(f"Sincronización completada - Nuevos: {nuevos}, Actualizados: {actualizados}, Errores: {errores}")

    return SyncTiendaNubeResponse(
        total_productos=len(all_products),
        total_variantes=total_variantes,
        nuevos=nuevos,
        actualizados=actualizados,
        errores=errores
    )


@router.get("/productos")
async def listar_productos_tienda_nube(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Lista productos sincronizados de Tienda Nube
    """
    productos = db.query(TiendaNubeProducto).filter(
        TiendaNubeProducto.activo == True
    ).offset(skip).limit(limit).all()

    return {
        "productos": productos,
        "total": db.query(TiendaNubeProducto).filter(TiendaNubeProducto.activo == True).count()
    }
