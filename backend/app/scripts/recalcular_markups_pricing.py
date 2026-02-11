"""
Script para recalcular TODOS los markups en productos_pricing:
- markup_calculado (precio web clásico)
- markup_pvp (precio PVP clásico)
- markup_pvp_3_cuotas, markup_pvp_6_cuotas, markup_pvp_9_cuotas, markup_pvp_12_cuotas

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
    print("RECALCULAR MARKUPS - Web clásico + PVP + Cuotas PVP")
    print("=" * 60)

    db = SessionLocal()

    try:
        # Mostrar constantes actuales
        constantes = obtener_constantes_pricing(db)
        print("\nConstantes de pricing actuales:")
        print(f"  Tier1: ${constantes['monto_tier1']:,.0f} -> comisión ${constantes['tier1']:,.0f}")
        print(f"  Tier2: ${constantes['monto_tier2']:,.0f} -> comisión ${constantes['tier2']:,.0f}")
        print(f"  Tier3: ${constantes['monto_tier3']:,.0f} -> comisión ${constantes['tier3']:,.0f}")
        print(f"  Varios: {constantes['varios']}%")
        print(f"  Markup adicional cuotas: {constantes['markup_adicional_cuotas']}%")

        # Obtener tipo de cambio
        tc_usd = obtener_tipo_cambio_actual(db, "USD")
        print(f"  Tipo de cambio USD: ${tc_usd:,.2f}" if tc_usd else "  Tipo de cambio: No disponible")

        # Obtener productos con precio web o PVP
        productos = db.query(ProductoPricing, ProductoERP).join(
            ProductoERP, ProductoERP.item_id == ProductoPricing.item_id
        ).filter(
            (ProductoPricing.precio_lista_ml.isnot(None)) | (ProductoPricing.precio_pvp.isnot(None))
        ).all()

        print(f"\nProductos a procesar: {len(productos)}")

        actualizados_web = 0
        actualizados_pvp = 0
        actualizados_cuotas_pvp = 0
        productos_modificados = 0
        errores = 0

        for pricing, producto_erp in productos:
            producto_tuvo_cambios = False
            try:
                if not producto_erp.costo or producto_erp.costo <= 0:
                    continue

                # Convertir costo a pesos
                costo_ars = convertir_a_pesos(
                    producto_erp.costo,
                    producto_erp.moneda_costo,
                    tc_usd if producto_erp.moneda_costo == "USD" else None
                )

                # Obtener grupo
                grupo_id = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)

                # ========== RECALCULAR MARKUP WEB CLÁSICO ==========
                if pricing.precio_lista_ml and pricing.precio_lista_ml > 0:
                    # Obtener comisión base (lista 4 = clásica web)
                    comision_base = obtener_comision_base(db, 4, grupo_id)
                    if comision_base:
                        # Calcular comisión con constantes de BD
                        comisiones = calcular_comision_ml_total(
                            float(pricing.precio_lista_ml),
                            comision_base,
                            float(producto_erp.iva),
                            db=db,
                            constantes=constantes
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

                        # Actualizar
                        old_markup = float(pricing.markup_calculado) if pricing.markup_calculado else None
                        pricing.markup_calculado = markup_porcentaje
                        if old_markup is None or abs(old_markup - markup_porcentaje) > 0.01:
                            actualizados_web += 1
                            producto_tuvo_cambios = True

                # ========== RECALCULAR MARKUP PVP CLÁSICO ==========
                if pricing.precio_pvp and pricing.precio_pvp > 0:
                    # Obtener comisión base (lista 12 = clásica PVP)
                    comision_base_pvp = obtener_comision_base(db, 12, grupo_id)
                    if comision_base_pvp:
                        comisiones_pvp = calcular_comision_ml_total(
                            float(pricing.precio_pvp),
                            comision_base_pvp,
                            float(producto_erp.iva),
                            db=db,
                            constantes=constantes
                        )

                        limpio_pvp = calcular_limpio(
                            float(pricing.precio_pvp),
                            float(producto_erp.iva),
                            float(producto_erp.envio or 0),
                            comisiones_pvp["comision_total"],
                            db=db,
                            grupo_id=grupo_id
                        )

                        markup_pvp = calcular_markup(limpio_pvp, costo_ars)
                        markup_pvp_porcentaje = round(markup_pvp * 100, 2)

                        old_markup_pvp = float(pricing.markup_pvp) if pricing.markup_pvp else None
                        pricing.markup_pvp = markup_pvp_porcentaje
                        if old_markup_pvp is None or abs(old_markup_pvp - markup_pvp_porcentaje) > 0.01:
                            actualizados_pvp += 1
                            producto_tuvo_cambios = True

                # ========== RECALCULAR MARKUPS CUOTAS PVP ==========
                if pricing.precio_pvp and pricing.precio_pvp > 0:
                    cuotas_config = [
                        (pricing.precio_pvp_3_cuotas, 18, 'markup_pvp_3_cuotas'),
                        (pricing.precio_pvp_6_cuotas, 19, 'markup_pvp_6_cuotas'),
                        (pricing.precio_pvp_9_cuotas, 20, 'markup_pvp_9_cuotas'),
                        (pricing.precio_pvp_12_cuotas, 21, 'markup_pvp_12_cuotas')
                    ]

                    for precio_cuota, pricelist_id, nombre_markup in cuotas_config:
                        if precio_cuota and float(precio_cuota) > 0:
                            try:
                                comision_base_cuota = obtener_comision_base(db, pricelist_id, grupo_id)
                                if comision_base_cuota:
                                    comisiones_cuota = calcular_comision_ml_total(
                                        float(precio_cuota),
                                        comision_base_cuota,
                                        float(producto_erp.iva),
                                        db=db,
                                        constantes=constantes
                                    )

                                    limpio_cuota = calcular_limpio(
                                        float(precio_cuota),
                                        float(producto_erp.iva),
                                        float(producto_erp.envio or 0),
                                        comisiones_cuota["comision_total"],
                                        db=db,
                                        grupo_id=grupo_id
                                    )

                                    markup_cuota = calcular_markup(limpio_cuota, costo_ars)
                                    markup_cuota_porcentaje = round(markup_cuota * 100, 2)

                                    old_markup_cuota = float(getattr(pricing, nombre_markup)) if getattr(pricing, nombre_markup) else None
                                    setattr(pricing, nombre_markup, markup_cuota_porcentaje)
                                    
                                    if old_markup_cuota is None or abs(old_markup_cuota - markup_cuota_porcentaje) > 0.01:
                                        actualizados_cuotas_pvp += 1
                                        producto_tuvo_cambios = True
                            except Exception:
                                # Si falla una cuota, continuar con las demás
                                pass

            except Exception as e:
                errores += 1
                if errores <= 10:  # Mostrar solo los primeros 10 errores
                    print(f"  Error en item_id {producto_erp.item_id}: {e}")
            
            # Contar producto si tuvo algún cambio
            if producto_tuvo_cambios:
                productos_modificados += 1

        db.commit()

        print("\n" + "=" * 60)
        print("COMPLETADO")
        print("=" * 60)
        print(f"Productos modificados: {productos_modificados}")
        print(f"Markups Web actualizados: {actualizados_web}")
        print(f"Markups PVP clásico actualizados: {actualizados_pvp}")
        print(f"Markups Cuotas PVP actualizados: {actualizados_cuotas_pvp}")
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
