#!/usr/bin/env python3
"""
Script para sincronizar productos de Tienda Nube.
Ejecutar: python backend/scripts/sync_tienda_nube.py

Usa UPSERT (INSERT ON CONFLICT DO UPDATE) para actualizar precios
sin ventana de datos vacíos. Los productos que ya no existen en TN
se marcan como activo=false solo si se obtuvo la lista completa.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Agregar el directorio backend al path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Cargar variables de entorno
dotenv_path = backend_dir / ".env"
load_dotenv(dotenv_path)

DATABASE_URL = os.getenv("DATABASE_URL")
TN_STORE_ID = os.getenv("TN_STORE_ID")
TN_ACCESS_TOKEN = os.getenv("TN_ACCESS_TOKEN")

if not all([DATABASE_URL, TN_STORE_ID, TN_ACCESS_TOKEN]):
    print(f"[{datetime.now()}] ❌ Error: Faltan variables de entorno (DATABASE_URL, TN_STORE_ID, TN_ACCESS_TOKEN)")
    sys.exit(1)

# Configurar base de datos
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def fetch_all_products() -> tuple[list, bool]:
    """
    Obtiene todos los productos de Tienda Nube con paginación.
    Retorna (products, fetch_complete) — fetch_complete=False si hubo error a mitad.
    """
    base_url = f"https://api.tiendanube.com/v1/{TN_STORE_ID}/products"
    headers = {"Authentication": f"bearer {TN_ACCESS_TOKEN}", "User-Agent": "GAUSS Pricing App (Python Script)"}

    all_products = []
    page = 1
    per_page = 200
    fetch_complete = True

    print(f"[{datetime.now()}] 📥 Obteniendo productos de Tienda Nube...")

    with httpx.Client(timeout=30.0) as client:
        while True:
            try:
                response = client.get(base_url, headers=headers, params={"page": page, "per_page": per_page})
                response.raise_for_status()

                products = response.json()

                if not products:
                    break

                all_products.extend(products)
                print(f"  Página {page}: {len(products)} productos")

                if len(products) < per_page:
                    break

                page += 1

            except httpx.HTTPStatusError as e:
                print(f"[{datetime.now()}] ❌ Error HTTP {e.response.status_code}: {e.response.text[:200]}")
                fetch_complete = False
                break
            except httpx.RequestError as e:
                print(f"[{datetime.now()}] ❌ Error de conexión: {e}")
                fetch_complete = False
                break

    print(f"[{datetime.now()}] 📦 Total productos obtenidos: {len(all_products)} (completo: {fetch_complete})")
    return all_products, fetch_complete


# Upsert SQL for one variant row. `published` uses COALESCE against the
# already-stored value — NOT a bare `= EXCLUDED.published` — because
# `_extract_variantes` maps a missing/non-bool `published` field to `None`,
# and a plain assignment would let that `None` silently overwrite a
# previously-known `True`/`False` as NULL on every sync run that happens to
# hit an API response missing the field. COALESCE is what actually
# guarantees "never clears a known value with unknown data";
# `_extract_variantes` alone only guarantees it produces `None` instead of
# `False` — the two work together, and losing either one reintroduces the
# bug.
UPSERT_VARIANTES_SQL = text("""
    INSERT INTO tienda_nube_productos (
        product_id, product_name, variant_id, variant_sku,
        price, compare_at_price, promotional_price, activo, published
    ) VALUES (
        :product_id, :product_name, :variant_id, :variant_sku,
        :price, :compare_at_price, :promotional_price, true, :published
    )
    ON CONFLICT (product_id, variant_id) DO UPDATE SET
        product_name = EXCLUDED.product_name,
        variant_sku = EXCLUDED.variant_sku,
        price = EXCLUDED.price,
        compare_at_price = EXCLUDED.compare_at_price,
        promotional_price = EXCLUDED.promotional_price,
        activo = true,
        published = COALESCE(EXCLUDED.published, tienda_nube_productos.published)
""")


def _extract_variantes(product: dict) -> list[dict]:
    """Map one TN /products entry to its per-variant upsert rows.

    TN's `published` boolean lives at the PRODUCT level, but
    `tienda_nube_productos` stores one row per VARIANT, so it's copied onto
    every variant row. Missing/absent `published` maps to `None` (unknown)
    rather than `False` — this function alone does NOT guarantee a known
    `True` survives a sync; that guarantee comes from `UPSERT_VARIANTES_SQL`'s
    `COALESCE`, which keeps the existing stored value whenever the incoming
    one is `None`.
    """
    product_id = product.get("id")
    product_name = product.get("name", {}).get("es", "")
    published = product.get("published")
    if not isinstance(published, bool):
        published = None

    variantes = []
    for variant in product.get("variants", []):
        variant_id = variant.get("id")
        variant_sku = (variant.get("sku") or "").strip()

        price = float(variant.get("price", 0) or 0)
        compare_at_price = variant.get("compare_at_price")
        promotional_price = variant.get("promotional_price")

        if compare_at_price:
            compare_at_price = float(compare_at_price)
        if promotional_price:
            promotional_price = float(promotional_price)

        variantes.append(
            {
                "product_id": product_id,
                "product_name": product_name,
                "variant_id": variant_id,
                "variant_sku": variant_sku,
                "price": price,
                "compare_at_price": compare_at_price,
                "promotional_price": promotional_price,
                "published": published,
            }
        )

    return variantes


def sync_tienda_nube():
    """Sincroniza productos de Tienda Nube usando upsert."""
    start_time = datetime.now()
    print(f"[{start_time}] 🚀 Iniciando sincronización con Tienda Nube...")

    all_products, fetch_complete = fetch_all_products()

    if not all_products:
        print(f"[{datetime.now()}] ⚠️  No se obtuvieron productos. Abortando sin modificar datos existentes.")
        return

    db = SessionLocal()

    try:
        # Contar variantes que vamos a procesar
        variantes = []
        for product in all_products:
            variantes.extend(_extract_variantes(product))

        # Solo marcar inactivos si obtuvimos la lista COMPLETA de TN.
        # Si hubo error de paginación (fetch parcial), solo actualizamos
        # los que sí trajimos sin tocar el flag activo de los demás.
        if fetch_complete:
            db.execute(text("UPDATE tienda_nube_productos SET activo = false"))
            print("  📋 Fetch completo — se marcarán inactivos los que no estén en TN")
        else:
            print("  ⚠️  Fetch parcial — solo se actualizan precios, no se desactivan productos")

        # Upsert todas las variantes (ON CONFLICT usa el unique constraint
        # product_id+variant_id) — ver UPSERT_VARIANTES_SQL arriba para el
        # porqué de su COALESCE en `published`.
        for variante in variantes:
            db.execute(UPSERT_VARIANTES_SQL, variante)

        # Relacionar con ERP por SKU (masivo, 3 queries en vez de N)
        # Match exacto
        db.execute(
            text("""
            UPDATE tienda_nube_productos tn
            SET item_id = pe.item_id
            FROM productos_erp pe
            WHERE tn.variant_sku = pe.codigo
            AND tn.activo = true
            AND tn.variant_sku IS NOT NULL
            AND tn.variant_sku != ''
        """)
        )

        # Match sin 0 inicial (TN: 0123456, ERP: 123456)
        db.execute(
            text("""
            UPDATE tienda_nube_productos tn
            SET item_id = pe.item_id
            FROM productos_erp pe
            WHERE SUBSTRING(tn.variant_sku, 2) = pe.codigo
            AND tn.item_id IS NULL
            AND tn.activo = true
            AND tn.variant_sku LIKE '0%'
            AND LENGTH(tn.variant_sku) > 1
        """)
        )

        # Match agregando 0 inicial (TN: 123456, ERP: 0123456)
        db.execute(
            text("""
            UPDATE tienda_nube_productos tn
            SET item_id = pe.item_id
            FROM productos_erp pe
            WHERE '0' || tn.variant_sku = pe.codigo
            AND tn.item_id IS NULL
            AND tn.activo = true
            AND tn.variant_sku NOT LIKE '0%'
            AND tn.variant_sku IS NOT NULL
            AND tn.variant_sku != ''
        """)
        )

        db.commit()

        # Stats
        stats = db.execute(
            text("""
            SELECT
                COUNT(*) FILTER (WHERE activo = true) as activos,
                COUNT(*) FILTER (WHERE activo = false) as inactivos,
                COUNT(*) FILTER (WHERE item_id IS NOT NULL AND activo = true) as con_erp
            FROM tienda_nube_productos
        """)
        ).fetchone()

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n[{datetime.now()}] ✅ Sincronización completada en {elapsed:.1f}s:")
        print(f"  📝 Variantes procesadas: {len(variantes)}")
        print(f"  ✅ Activos: {stats[0]}")
        print(f"  ❌ Inactivos (no existen en TN): {stats[1]}")
        print(f"  🔗 Relacionados con ERP: {stats[2]}")

    except Exception as e:
        db.rollback()
        print(f"\n[{datetime.now()}] ❌ Error durante sincronización: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    sync_tienda_nube()
