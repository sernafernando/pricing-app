"""
Endpoints para sincronizar tablas maestras del ERP desde Cloudflare Worker
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date, datetime

from app.core.database import get_db
from app.services.erp_worker_client import erp_worker_client
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_item import TBItem
from app.models.tb_tax_name import TBTaxName
from app.models.tb_item_taxes import TBItemTaxes


router = APIRouter(prefix="/erp-sync", tags=["ERP Sync"])


@router.post("/brands")
async def sync_brands(
    brand_id: Optional[int] = Query(None, description="ID de marca específica a sincronizar"),
    db: Session = Depends(get_db)
):
    """
    Sincroniza marcas desde el ERP a PostgreSQL

    - Si se proporciona brand_id, sincroniza solo esa marca
    - Si no, sincroniza todas las marcas
    """
    try:
        # Obtener datos del worker
        brands = await erp_worker_client.get_brands(brand_id=brand_id)

        insertados = 0
        actualizados = 0

        for brand_data in brands:
            comp_id = brand_data["comp_id"]
            brand_id_val = brand_data["brand_id"]

            # Verificar si existe
            existente = db.query(TBBrand).filter(
                TBBrand.comp_id == comp_id,
                TBBrand.brand_id == brand_id_val
            ).first()

            if existente:
                existente.brand_desc = brand_data["brand_desc"]
                existente.bra_id = brand_data.get("bra_id")
                actualizados += 1
            else:
                nueva = TBBrand(
                    comp_id=comp_id,
                    brand_id=brand_id_val,
                    bra_id=brand_data.get("bra_id"),
                    brand_desc=brand_data["brand_desc"]
                )
                db.add(nueva)
                insertados += 1

        db.commit()

        return {
            "success": True,
            "message": "Marcas sincronizadas correctamente",
            "insertados": insertados,
            "actualizados": actualizados,
            "total": insertados + actualizados
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar marcas: {str(e)}")


@router.post("/categories")
async def sync_categories(
    cat_id: Optional[int] = Query(None, description="ID de categoría específica a sincronizar"),
    db: Session = Depends(get_db)
):
    """
    Sincroniza categorías desde el ERP a PostgreSQL

    - Si se proporciona cat_id, sincroniza solo esa categoría
    - Si no, sincroniza todas las categorías
    """
    try:
        # Obtener datos del worker
        categories = await erp_worker_client.get_categories(cat_id=cat_id)

        insertados = 0
        actualizados = 0

        for cat_data in categories:
            comp_id = cat_data["comp_id"]
            cat_id_val = cat_data["cat_id"]

            # Verificar si existe
            existente = db.query(TBCategory).filter(
                TBCategory.comp_id == comp_id,
                TBCategory.cat_id == cat_id_val
            ).first()

            if existente:
                existente.cat_desc = cat_data["cat_desc"]
                actualizados += 1
            else:
                nueva = TBCategory(
                    comp_id=comp_id,
                    cat_id=cat_id_val,
                    cat_desc=cat_data["cat_desc"]
                )
                db.add(nueva)
                insertados += 1

        db.commit()

        return {
            "success": True,
            "message": "Categorías sincronizadas correctamente",
            "insertados": insertados,
            "actualizados": actualizados,
            "total": insertados + actualizados
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar categorías: {str(e)}")


@router.post("/subcategories")
async def sync_subcategories(
    cat_id: Optional[int] = Query(None, description="ID de categoría"),
    subcat_id: Optional[int] = Query(None, description="ID de subcategoría específica"),
    db: Session = Depends(get_db)
):
    """
    Sincroniza subcategorías desde el ERP a PostgreSQL

    - Puede filtrar por cat_id y/o subcat_id
    - Si no se proporcionan filtros, sincroniza todas las subcategorías
    """
    try:
        # Obtener datos del worker
        subcategories = await erp_worker_client.get_subcategories(
            cat_id=cat_id,
            subcat_id=subcat_id
        )

        insertados = 0
        actualizados = 0

        for subcat_data in subcategories:
            comp_id = subcat_data["comp_id"]
            cat_id_val = subcat_data["cat_id"]
            subcat_id_val = subcat_data["subcat_id"]

            # Verificar si existe
            existente = db.query(TBSubCategory).filter(
                TBSubCategory.comp_id == comp_id,
                TBSubCategory.cat_id == cat_id_val,
                TBSubCategory.subcat_id == subcat_id_val
            ).first()

            if existente:
                existente.subcat_desc = subcat_data["subcat_desc"]
                actualizados += 1
            else:
                nueva = TBSubCategory(
                    comp_id=comp_id,
                    cat_id=cat_id_val,
                    subcat_id=subcat_id_val,
                    subcat_desc=subcat_data["subcat_desc"]
                )
                db.add(nueva)
                insertados += 1

        db.commit()

        return {
            "success": True,
            "message": "Subcategorías sincronizadas correctamente",
            "insertados": insertados,
            "actualizados": actualizados,
            "total": insertados + actualizados
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar subcategorías: {str(e)}")


@router.post("/items")
async def sync_items(
    brand_id: Optional[int] = Query(None, description="ID de marca"),
    cat_id: Optional[int] = Query(None, description="ID de categoría"),
    subcat_id: Optional[int] = Query(None, description="ID de subcategoría"),
    item_id: Optional[int] = Query(None, description="ID de item específico"),
    item_code: Optional[str] = Query(None, description="Código de item"),
    last_update: Optional[date] = Query(None, description="Solo items actualizados después de esta fecha"),
    db: Session = Depends(get_db)
):
    """
    Sincroniza items desde el ERP a PostgreSQL

    - Puede filtrar por brand_id, cat_id, subcat_id, item_id, item_code, last_update
    - Si no se proporcionan filtros, sincroniza todos los items
    """
    try:
        # Obtener datos del worker
        items = await erp_worker_client.get_items(
            brand_id=brand_id,
            cat_id=cat_id,
            subcat_id=subcat_id,
            item_id=item_id,
            item_code=item_code,
            last_update=last_update
        )

        insertados = 0
        actualizados = 0

        for item_data in items:
            comp_id = item_data["comp_id"]
            item_id_val = item_data["item_id"]

            # Verificar si existe
            existente = db.query(TBItem).filter(
                TBItem.comp_id == comp_id,
                TBItem.item_id == item_id_val
            ).first()

            # Convertir fechas de string a datetime
            item_cd = None
            if item_data.get("item_cd"):
                item_cd = datetime.fromisoformat(item_data["item_cd"].replace("Z", "+00:00"))

            item_lastupdate = None
            if item_data.get("item_LastUpdate"):
                item_lastupdate = datetime.fromisoformat(item_data["item_LastUpdate"].replace("Z", "+00:00"))

            if existente:
                existente.item_code = item_data["item_code"]
                existente.item_desc = item_data.get("item_desc")
                existente.cat_id = item_data.get("cat_id")
                existente.subcat_id = item_data.get("subcat_id")
                existente.brand_id = item_data.get("brand_id")
                existente.item_liquidation = item_data.get("item_liquidation")
                existente.item_LastUpdate = item_lastupdate
                actualizados += 1
            else:
                nuevo = TBItem(
                    comp_id=comp_id,
                    item_id=item_id_val,
                    item_code=item_data["item_code"],
                    item_desc=item_data.get("item_desc"),
                    cat_id=item_data.get("cat_id"),
                    subcat_id=item_data.get("subcat_id"),
                    brand_id=item_data.get("brand_id"),
                    item_liquidation=item_data.get("item_liquidation"),
                    item_cd=item_cd,
                    item_LastUpdate=item_lastupdate
                )
                db.add(nuevo)
                insertados += 1

            # Commit cada 500 items para evitar bloqueos largos
            if (insertados + actualizados) % 500 == 0:
                db.commit()

        db.commit()

        return {
            "success": True,
            "message": "Items sincronizados correctamente",
            "insertados": insertados,
            "actualizados": actualizados,
            "total": insertados + actualizados
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar items: {str(e)}")


@router.post("/tax-names")
async def sync_tax_names(
    tax_id: Optional[int] = Query(None, description="ID de impuesto específico"),
    db: Session = Depends(get_db)
):
    """
    Sincroniza nombres de impuestos desde el ERP a PostgreSQL

    - Si se proporciona tax_id, sincroniza solo ese impuesto
    - Si no, sincroniza todos los impuestos
    """
    try:
        # Obtener datos del worker
        tax_names = await erp_worker_client.get_tax_names(tax_id=tax_id)

        insertados = 0
        actualizados = 0

        for tax_data in tax_names:
            comp_id = tax_data["comp_id"]
            tax_id_val = tax_data["tax_id"]

            # Verificar si existe
            existente = db.query(TBTaxName).filter(
                TBTaxName.comp_id == comp_id,
                TBTaxName.tax_id == tax_id_val
            ).first()

            if existente:
                existente.tax_desc = tax_data["tax_desc"]
                existente.tax_percentage = tax_data.get("tax_percentage")
                actualizados += 1
            else:
                nuevo = TBTaxName(
                    comp_id=comp_id,
                    tax_id=tax_id_val,
                    tax_desc=tax_data["tax_desc"],
                    tax_percentage=tax_data.get("tax_percentage")
                )
                db.add(nuevo)
                insertados += 1

        db.commit()

        return {
            "success": True,
            "message": "Impuestos sincronizados correctamente",
            "insertados": insertados,
            "actualizados": actualizados,
            "total": insertados + actualizados
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar impuestos: {str(e)}")


@router.post("/item-taxes")
async def sync_item_taxes(
    tax_id: Optional[int] = Query(None, description="ID de impuesto"),
    item_id: Optional[int] = Query(None, description="ID de item"),
    db: Session = Depends(get_db)
):
    """
    Sincroniza impuestos por item desde el ERP a PostgreSQL

    - Puede filtrar por tax_id y/o item_id
    - Si no se proporcionan filtros, sincroniza todos los impuestos de items
    """
    try:
        # Obtener datos del worker
        item_taxes = await erp_worker_client.get_item_taxes(
            tax_id=tax_id,
            item_id=item_id
        )

        insertados = 0
        actualizados = 0

        for item_tax_data in item_taxes:
            comp_id = item_tax_data["comp_id"]
            item_id_val = item_tax_data["item_id"]
            tax_id_val = item_tax_data["tax_id"]

            # Verificar si existe
            existente = db.query(TBItemTaxes).filter(
                TBItemTaxes.comp_id == comp_id,
                TBItemTaxes.item_id == item_id_val,
                TBItemTaxes.tax_id == tax_id_val
            ).first()

            if existente:
                existente.tax_class = item_tax_data.get("tax_class")
                actualizados += 1
            else:
                nuevo = TBItemTaxes(
                    comp_id=comp_id,
                    item_id=item_id_val,
                    tax_id=tax_id_val,
                    tax_class=item_tax_data.get("tax_class")
                )
                db.add(nuevo)
                insertados += 1

            # Commit cada 500 registros
            if (insertados + actualizados) % 500 == 0:
                db.commit()

        db.commit()

        return {
            "success": True,
            "message": "Impuestos de items sincronizados correctamente",
            "insertados": insertados,
            "actualizados": actualizados,
            "total": insertados + actualizados
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar impuestos de items: {str(e)}")


@router.post("/all")
async def sync_all(
    db: Session = Depends(get_db)
):
    """
    Sincroniza todas las tablas maestras del ERP en orden

    Orden:
    1. Marcas
    2. Categorías
    3. Subcategorías
    4. Nombres de impuestos
    5. Items
    6. Impuestos por item
    """
    results = {}

    try:
        # 1. Brands
        brands_result = await sync_brands(brand_id=None, db=db)
        results["brands"] = brands_result

        # 2. Categories
        categories_result = await sync_categories(cat_id=None, db=db)
        results["categories"] = categories_result

        # 3. Subcategories
        subcategories_result = await sync_subcategories(cat_id=None, subcat_id=None, db=db)
        results["subcategories"] = subcategories_result

        # 4. Tax Names
        tax_names_result = await sync_tax_names(tax_id=None, db=db)
        results["tax_names"] = tax_names_result

        # 5. Items
        items_result = await sync_items(
            brand_id=None, cat_id=None, subcat_id=None,
            item_id=None, item_code=None, last_update=None,
            db=db
        )
        results["items"] = items_result

        # 6. Item Taxes
        item_taxes_result = await sync_item_taxes(tax_id=None, item_id=None, db=db)
        results["item_taxes"] = item_taxes_result

        return {
            "success": True,
            "message": "Sincronización completa exitosa",
            "results": results
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error durante la sincronización completa: {str(e)}"
        )
