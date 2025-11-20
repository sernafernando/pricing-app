#!/usr/bin/env python3
"""
Script para sincronizar productos de Tienda Nube
Ejecutar: python backend/scripts/sync_tienda_nube.py
"""

import os
import sys
from pathlib import Path

# Agregar el directorio backend al path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Cargar variables de entorno
dotenv_path = backend_dir / '.env'
load_dotenv(dotenv_path)

DATABASE_URL = os.getenv('DATABASE_URL')
TN_STORE_ID = os.getenv('TN_STORE_ID')
TN_ACCESS_TOKEN = os.getenv('TN_ACCESS_TOKEN')

if not all([DATABASE_URL, TN_STORE_ID, TN_ACCESS_TOKEN]):
    print("❌ Error: Faltan variables de entorno (DATABASE_URL, TN_STORE_ID, TN_ACCESS_TOKEN)")
    sys.exit(1)

# Configurar base de datos
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def sync_tienda_nube():
    """Sincroniza productos de Tienda Nube"""

    print("🚀 Iniciando sincronización con Tienda Nube...")

    base_url = f"https://api.tiendanube.com/v1/{TN_STORE_ID}/products"
    headers = {
        "Authentication": f"bearer {TN_ACCESS_TOKEN}",
        "User-Agent": "GAUSS Pricing App (Python Script)"
    }

    all_products = []
    page = 1
    per_page = 200

    # Obtener todos los productos con paginación
    print(f"📥 Obteniendo productos de Tienda Nube...")

    with httpx.Client(timeout=30.0) as client:
        while True:
            print(f"  Página {page}...", end=" ")

            try:
                response = client.get(
                    base_url,
                    headers=headers,
                    params={"page": page, "per_page": per_page}
                )
                response.raise_for_status()

                products = response.json()

                if not products:
                    print("✓ (vacía)")
                    break

                all_products.extend(products)
                print(f"✓ ({len(products)} productos)")

                # Si obtuvimos menos productos que el límite, es la última página
                if len(products) < per_page:
                    break

                page += 1

            except Exception as e:
                print(f"❌ Error: {e}")
                break

    print(f"📦 Total productos obtenidos: {len(all_products)}")

    if not all_products:
        print("⚠️  No se obtuvieron productos")
        return

    # Procesar productos y guardar en base de datos
    db = SessionLocal()

    try:
        # Desactivar todos los productos existentes
        db.execute(text("UPDATE tienda_nube_productos SET activo = false"))

        productos_insertados = 0
        productos_actualizados = 0
        productos_relacionados = 0

        for product in all_products:
            product_id = product.get('id')
            product_name = product.get('name', {}).get('es', '')

            for variant in product.get('variants', []):
                variant_id = variant.get('id')
                variant_sku = (variant.get('sku') or '').strip()

                # Precios
                price = float(variant.get('price', 0) or 0)
                compare_at_price = variant.get('compare_at_price')
                promotional_price = variant.get('promotional_price')

                if compare_at_price:
                    compare_at_price = float(compare_at_price)
                if promotional_price:
                    promotional_price = float(promotional_price)

                # Buscar item_id por SKU en productos_erp
                item_id = None
                if variant_sku:
                    # Intentar match exacto primero
                    result = db.execute(
                        text("SELECT item_id FROM productos_erp WHERE codigo = :sku LIMIT 1"),
                        {"sku": variant_sku}
                    ).fetchone()

                    # Si no encuentra y el SKU tiene 0 al inicio, intentar sin el 0
                    if not result and variant_sku.startswith('0') and len(variant_sku) > 1:
                        result = db.execute(
                            text("SELECT item_id FROM productos_erp WHERE codigo = :sku LIMIT 1"),
                            {"sku": variant_sku[1:]}
                        ).fetchone()

                    # Si no encuentra y el SKU NO tiene 0 al inicio, intentar con 0
                    if not result and not variant_sku.startswith('0'):
                        result = db.execute(
                            text("SELECT item_id FROM productos_erp WHERE codigo = :sku LIMIT 1"),
                            {"sku": '0' + variant_sku}
                        ).fetchone()

                    if result:
                        item_id = result[0]
                        productos_relacionados += 1

                # Verificar si existe
                existing = db.execute(
                    text("""
                        SELECT id FROM tienda_nube_productos
                        WHERE product_id = :product_id AND variant_id = :variant_id
                    """),
                    {"product_id": product_id, "variant_id": variant_id}
                ).fetchone()

                if existing:
                    # Actualizar
                    db.execute(
                        text("""
                            UPDATE tienda_nube_productos SET
                                product_name = :product_name,
                                variant_sku = :variant_sku,
                                price = :price,
                                compare_at_price = :compare_at_price,
                                promotional_price = :promotional_price,
                                item_id = :item_id,
                                activo = true,
                                fecha_actualizacion = NOW()
                            WHERE product_id = :product_id AND variant_id = :variant_id
                        """),
                        {
                            "product_id": product_id,
                            "variant_id": variant_id,
                            "product_name": product_name,
                            "variant_sku": variant_sku,
                            "price": price,
                            "compare_at_price": compare_at_price,
                            "promotional_price": promotional_price,
                            "item_id": item_id
                        }
                    )
                    productos_actualizados += 1
                else:
                    # Insertar
                    db.execute(
                        text("""
                            INSERT INTO tienda_nube_productos (
                                product_id, product_name, variant_id, variant_sku,
                                price, compare_at_price, promotional_price, item_id, activo
                            ) VALUES (
                                :product_id, :product_name, :variant_id, :variant_sku,
                                :price, :compare_at_price, :promotional_price, :item_id, true
                            )
                        """),
                        {
                            "product_id": product_id,
                            "product_name": product_name,
                            "variant_id": variant_id,
                            "variant_sku": variant_sku,
                            "price": price,
                            "compare_at_price": compare_at_price,
                            "promotional_price": promotional_price,
                            "item_id": item_id
                        }
                    )
                    productos_insertados += 1

        db.commit()

        print("\n✅ Sincronización completada:")
        print(f"  📝 Productos nuevos: {productos_insertados}")
        print(f"  🔄 Productos actualizados: {productos_actualizados}")
        print(f"  🔗 Productos relacionados con ERP: {productos_relacionados}")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Error durante sincronización: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    sync_tienda_nube()
