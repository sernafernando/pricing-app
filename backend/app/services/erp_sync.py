import httpx
import hashlib
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.producto import ProductoERP, ProductoPricing
from datetime import datetime
from typing import Dict, List

def convertir_a_numero(valor, default=0):
    """Convierte string a número, maneja decimales"""
    try:
        if valor is None or valor == '':
            return default
        if isinstance(valor, (int, float)):
            return valor
        return float(str(valor).replace(',', ''))
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
    """Trae productos del ERP"""
    url = f"{settings.ERP_BASE_URL}{settings.ERP_PRODUCTOS_ENDPOINT}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

async def fetch_stock_erp() -> Dict[int, int]:
    """Trae stock de todos los productos"""
    url = f"{settings.ERP_BASE_URL}{settings.ERP_STOCK_ENDPOINT}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

        stock_dict = {}
        for item in data:
            item_id = convertir_a_entero(item.get('item_id'))
            stock = convertir_a_entero(item.get('Stock', 0))
            stock_dict[item_id] = stock

        return stock_dict

def calcular_hash(producto: Dict) -> str:
    """Calcula hash de los datos relevantes para detectar cambios"""
    datos = f"{producto.get('coslis_price', 0)}{producto.get('Descripción', '')}{producto.get('Stock', 0)}"
    return hashlib.sha256(datos.encode()).hexdigest()

async def sincronizar_erp(db: Session) -> Dict:
    """Sincroniza productos del ERP con la base de datos"""

    stats = {
        "productos_nuevos": 0,
        "productos_actualizados": 0,
        "productos_sin_cambios": 0,
        "productos_duplicados": 0,
        "precios_sincronizados": 0,
        "errores": []
    }

    try:
        print("Trayendo productos del ERP...")
        productos = await fetch_productos_erp()

        print("Trayendo stock...")
        stock_dict = await fetch_stock_erp()

        print(f"Procesando {len(productos)} productos...")

        # Detectar duplicados en el ERP
        items_vistos = set()
        productos_unicos = []

        for producto_data in productos:
            item_id = convertir_a_entero(producto_data.get('Item_ID'))
            if item_id in items_vistos:
                stats["productos_duplicados"] += 1
                continue
            items_vistos.add(item_id)
            productos_unicos.append(producto_data)

        print(f"Productos únicos: {len(productos_unicos)}, duplicados ignorados: {stats['productos_duplicados']}")

        # Procesar en lotes de 100
        batch_size = 100
        for i in range(0, len(productos_unicos), batch_size):
            batch = productos_unicos[i:i+batch_size]

            for producto_data in batch:
                try:
                    item_id = convertir_a_entero(producto_data.get('Item_ID'))
                    if not item_id:
                        continue

                    stock = stock_dict.get(item_id, 0)
                    producto_data['Stock'] = stock
                    hash_nuevo = calcular_hash(producto_data)

                    producto_existente = db.query(ProductoERP).filter(
                        ProductoERP.item_id == item_id
                    ).first()

                    codigo = str(producto_data.get('Código', '')).replace('"', '')
                    costo = convertir_a_numero(producto_data.get('coslis_price', 0))
                    iva = convertir_a_numero(producto_data.get('IVA', 0))
                    precio_publicado = convertir_a_numero(producto_data.get('Precio_Publicado'), None)
                    envio = convertir_a_numero(producto_data.get('Envío'), None)
                    subcategoria_id = convertir_a_entero(producto_data.get('subcat_id'), None)

                    if not producto_existente:
                        nuevo_producto = ProductoERP(
                            item_id=item_id,
                            codigo=codigo,
                            descripcion=producto_data.get('Descripción'),
                            marca=producto_data.get('Marca'),
                            categoria=producto_data.get('Categoría'),
                            subcategoria_id=subcategoria_id,
                            moneda_costo=producto_data.get('Moneda_Costo'),
                            costo=costo,
                            iva=iva,
                            stock=stock,
                            envio=envio,
                            hash_datos=hash_nuevo
                        )
                        db.add(nuevo_producto)
                        stats["productos_nuevos"] += 1

                    elif producto_existente.hash_datos != hash_nuevo:
                        producto_existente.codigo = codigo
                        producto_existente.descripcion = producto_data.get('Descripción')
                        producto_existente.marca = producto_data.get('Marca')
                        producto_existente.categoria = producto_data.get('Categoría')
                        producto_existente.subcategoria_id = subcategoria_id
                        producto_existente.moneda_costo = producto_data.get('Moneda_Costo')
                        producto_existente.costo = costo
                        producto_existente.iva = iva
                        producto_existente.stock = stock
                        producto_existente.envio = envio
                        producto_existente.hash_datos = hash_nuevo
                        stats["productos_actualizados"] += 1
                    else:
                        stats["productos_sin_cambios"] += 1

                    # SINCRONIZAR PRECIO si viene del ERP
                    if precio_publicado and precio_publicado > 0:
                        from app.services.pricing_calculator import (
                            obtener_tipo_cambio_actual, convertir_a_pesos,
                            obtener_grupo_subcategoria, obtener_comision_base,
                            calcular_comision_ml_total, calcular_limpio,
                            calcular_markup, VARIOS_DEFAULT
                        )
                        
                        moneda_costo = producto_data.get('Moneda_Costo')
                        tipo_cambio = None
                        if moneda_costo == "USD":
                            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
                        
                        costo_ars = convertir_a_pesos(costo, moneda_costo, tipo_cambio)
                        grupo_id = obtener_grupo_subcategoria(db, subcategoria_id)
                        comision_base = obtener_comision_base(db, 4, grupo_id)
                        
                        markup_calculado = None
                        if comision_base:
                            comisiones = calcular_comision_ml_total(precio_publicado, comision_base, iva, VARIOS_DEFAULT)
                            limpio = calcular_limpio(precio_publicado, iva, envio or 0, comisiones["comision_total"])
                            markup = calcular_markup(limpio, costo_ars)
                            markup_calculado = round(markup * 100, 2)
                        
                        pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
                        
                        if pricing:
                            pricing.precio_lista_ml = precio_publicado
                            pricing.markup_calculado = markup_calculado
                            pricing.fecha_modificacion = datetime.now()
                        else:
                            pricing = ProductoPricing(
                                item_id=item_id,
                                precio_lista_ml=precio_publicado,
                                markup_calculado=markup_calculado,
                                usuario_id=1,
                                motivo_cambio="Sincronización ERP"
                            )
                            db.add(pricing)
                        
                        stats["precios_sincronizados"] += 1

                except Exception as e:
                    stats["errores"].append(f"Error en item {item_id}: {str(e)}")

            # Commit por lote
            try:
                db.commit()
                print(f"Lote {i//batch_size + 1} procesado ({i+len(batch)}/{len(productos_unicos)})")
            except Exception as e:
                db.rollback()
                stats["errores"].append(f"Error en lote {i//batch_size + 1}: {str(e)}")

        print(f"Sincronización completada: {stats}")

    except Exception as e:
        db.rollback()
        stats["errores"].append(f"Error general: {str(e)}")
        print(f"Error en sincronización: {e}")

    return stats
