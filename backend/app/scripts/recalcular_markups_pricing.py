"""
Script para recalcular TODOS los markup_calculado en productos_pricing
usando las constantes actualizadas de pricing_constants.

Ejecutar:
    python app/scripts/recalcular_markups_pricing.py
"""
import sys
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

# Cargar variables de entorno desde .env
from dotenv import load_dotenv
env_path = backend_path / '.env'
load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal
from app.models.producto import ProductoERP, ProductoPricing
from app.services.pricing_calculator import (
    obtener_constantes_pricing,
    obtener_tipo_cambio_actual,
    convertir_a_pesos,
    obtener_grupo_subcategoria,
    obtener_comision_base,
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup
)


def main():
    print("=" * 60)
    print("RECALCULAR MARKUPS - Usando constantes actualizadas")
    print("=" * 60)

    db = SessionLocal()

    try:
        # Mostrar constantes actuales
        constantes = obtener_constantes_pricing(db)
        print(f"\nConstantes de pricing actuales:")
        print(f"  Tier1: ${constantes['monto_tier1']:,.0f} -> comisión ${constantes['tier1']:,.0f}")
        print(f"  Tier2: ${constantes['monto_tier2']:,.0f} -> comisión ${constantes['tier2']:,.0f}")
        print(f"  Tier3: ${constantes['monto_tier3']:,.0f} -> comisión ${constantes['tier3']:,.0f}")
        print(f"  Varios: {constantes['varios']}%")

        # Obtener tipo de cambio
        tc_usd = obtener_tipo_cambio_actual(db, "USD")
        print(f"  Tipo de cambio USD: ${tc_usd:,.2f}" if tc_usd else "  Tipo de cambio: No disponible")

        # Obtener productos con precio
        productos = db.query(ProductoPricing, ProductoERP).join(
            ProductoERP, ProductoERP.item_id == ProductoPricing.item_id
        ).filter(
            ProductoPricing.precio_lista_ml.isnot(None)
        ).all()

        print(f"\nProductos a procesar: {len(productos)}")

        actualizados = 0
        errores = 0

        for pricing, producto_erp in productos:
            try:
                if not producto_erp.costo or producto_erp.costo <= 0:
                    continue

                if not pricing.precio_lista_ml or pricing.precio_lista_ml <= 0:
                    continue

                # Convertir costo a pesos
                costo_ars = convertir_a_pesos(
                    producto_erp.costo,
                    producto_erp.moneda_costo,
                    tc_usd if producto_erp.moneda_costo == "USD" else None
                )

                # Obtener grupo
                grupo_id = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)

                # Obtener comisión base (lista 4 = clásica)
                comision_base = obtener_comision_base(db, 4, grupo_id)
                if not comision_base:
                    continue

                # Calcular comisión con constantes de BD
                comisiones = calcular_comision_ml_total(
                    float(pricing.precio_lista_ml),
                    comision_base,
                    float(producto_erp.iva),
                    db=db  # Esto obtiene las constantes actualizadas
                )

                # Calcular limpio
                limpio = calcular_limpio(
                    float(pricing.precio_lista_ml),
                    float(producto_erp.iva),
                    float(producto_erp.envio or 0),
                    comisiones["comision_total"],
                    db=db,
                    grupo_id=grupo_id
                )

                # Calcular markup
                markup = calcular_markup(limpio, costo_ars)
                markup_porcentaje = round(markup * 100, 2)

                # Solo actualizar si cambió
                if pricing.markup_calculado is None or abs(float(pricing.markup_calculado) - markup_porcentaje) > 0.01:
                    pricing.markup_calculado = markup_porcentaje
                    actualizados += 1

            except Exception as e:
                errores += 1
                if errores <= 10:  # Mostrar solo los primeros 10 errores
                    print(f"  Error en item_id {producto_erp.item_id}: {e}")

        db.commit()

        print(f"\n" + "=" * 60)
        print(f"COMPLETADO")
        print(f"=" * 60)
        print(f"Productos actualizados: {actualizados}")
        print(f"Errores: {errores}")

    except Exception as e:
        print(f"\nError general: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
