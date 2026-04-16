"""
Productos - Force sync endpoint.

Handles forced product synchronization from gbp-parser.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_async_db
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


@router.post("/productos/{item_id}/force-sync")
async def force_sync_producto(
    item_id: int, db: Session = Depends(get_async_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Endpoint temporal para forzar la sincronización de un producto específico desde gbp-parser.
    Útil para debugging cuando el sync masivo no actualiza un producto.
    """
    import httpx
    import hashlib
    from app.core.config import settings
    from app.models.tb_item import TBItem

    try:
        # 1. Obtener datos desde gbp-parser (localhost)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(settings.GBP_PARSER_URL, json={"intExpgr_id": 64})
            response.raise_for_status()
            data = response.json()

        # 2. Buscar el item_id específico
        producto_data = None
        for item in data:
            if str(item.get("Item_ID")) == str(item_id):
                producto_data = item
                break

        if not producto_data:
            raise HTTPException(status_code=404, detail=f"Item {item_id} no encontrado en gbp-parser")

        # 3. Obtener o crear producto en productos_erp
        producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

        # 4. Extraer datos
        codigo = str(producto_data.get("Código", "")).replace('"', "")
        descripcion = producto_data.get("Descripción")
        marca = producto_data.get("Marca")
        categoria = producto_data.get("Categoría")
        subcategoria_id = int(producto_data.get("subcat_id")) if producto_data.get("subcat_id") else None
        moneda_costo = producto_data.get("Moneda_Costo")
        costo = float(producto_data.get("coslis_price", 0))
        iva = float(producto_data.get("IVA", 0))

        # Calcular hash
        datos_hash = f"{codigo}{costo}{descripcion}0{producto_data.get('Envío', 0)}"
        hash_nuevo = hashlib.sha256(datos_hash.encode()).hexdigest()

        # 5. Obtener stock desde tb_item
        tb_item = db.query(TBItem).filter(TBItem.item_id == item_id).first()
        stock = 0
        if tb_item:
            # Aquí podrías obtener el stock real, por ahora usamos 0
            stock = 0

        cambios = {}

        if not producto:
            # Crear nuevo
            nuevo_producto = ProductoERP(
                item_id=item_id,
                codigo=codigo,
                descripcion=descripcion,
                marca=marca,
                categoria=categoria,
                subcategoria_id=subcategoria_id,
                moneda_costo=moneda_costo,
                costo=costo,
                iva=iva,
                stock=stock,
                envio=float(producto_data.get("Envío", 0)) if producto_data.get("Envío") else None,
                hash_datos=hash_nuevo,
            )
            db.add(nuevo_producto)
            db.commit()

            return {"success": True, "action": "created", "item_id": item_id, "codigo": codigo, "hash": hash_nuevo}
        else:
            # Actualizar existente
            if producto.codigo != codigo:
                cambios["codigo"] = {"antes": producto.codigo, "despues": codigo}
                producto.codigo = codigo

            if producto.descripcion != descripcion:
                cambios["descripcion"] = {"antes": producto.descripcion, "despues": descripcion}
                producto.descripcion = descripcion

            if producto.marca != marca:
                cambios["marca"] = {"antes": producto.marca, "despues": marca}
                producto.marca = marca

            if producto.hash_datos != hash_nuevo:
                cambios["hash"] = {"antes": producto.hash_datos, "despues": hash_nuevo}
                producto.hash_datos = hash_nuevo

            db.commit()

            return {
                "success": True,
                "action": "updated",
                "item_id": item_id,
                "cambios": cambios,
                "codigo_actual": codigo,
                "hash_actual": hash_nuevo,
            }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al sincronizar: {str(e)}")
