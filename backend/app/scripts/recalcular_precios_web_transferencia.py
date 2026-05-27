"""
Recalcula precio_web_transferencia para todos los productos con
participa_web_transferencia = True usando la fórmula actual con las
constantes vigentes de pricing_constants (comision_tienda_nube + varios_porcentaje).

Necesario despues de mover COMISION_WEB e IIBB del hardcode a DB:
los precios guardados se calcularon con 0.73% y 5% en vez de los valores actuales.

Ejecutar:
    python -m app.scripts.recalcular_precios_web_transferencia

Opciones:
    --dry-run    Calcula y muestra cambios sin escribir en DB
    --quiet      No imprime por producto, solo resumen final
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

import argparse
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.producto import ProductoERP, ProductoPricing
from app.services.pricing_calculator import (
    calcular_precio_web_transferencia,
    convertir_a_pesos,
    obtener_constantes_pricing,
    obtener_tipo_cambio_actual,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="No persiste cambios")
    parser.add_argument("--quiet", action="store_true", help="Solo imprime resumen final")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        constantes = obtener_constantes_pricing(db)
        comision_web = constantes["comision_tienda_nube"]
        iibb = constantes["varios"]
        print(f"Constantes vigentes: comision_web={comision_web}% iibb={iibb}%")

        tipo_cambio_usd = obtener_tipo_cambio_actual(db, "USD")
        if not tipo_cambio_usd:
            print("ERROR: no se encontro tipo de cambio USD")
            return 1
        print(f"Tipo de cambio USD: {tipo_cambio_usd}")

        productos = (
            db.query(ProductoPricing, ProductoERP)
            .join(ProductoERP, ProductoPricing.item_id == ProductoERP.item_id)
            .filter(ProductoPricing.participa_web_transferencia.is_(True))
            .all()
        )
        print(f"Productos a recalcular: {len(productos)}")

        actualizados = 0
        sin_cambios = 0
        sin_porcentaje = 0
        errores = 0

        for pricing, producto_erp in productos:
            try:
                if pricing.porcentaje_markup_web is None:
                    sin_porcentaje += 1
                    continue

                tipo_cambio = tipo_cambio_usd if producto_erp.moneda_costo == "USD" else None
                costo_ars = convertir_a_pesos(float(producto_erp.costo), producto_erp.moneda_costo, tipo_cambio)

                markup_clasica = (
                    float(pricing.markup_calculado) / 100
                    if pricing.markup_calculado is not None and pricing.precio_lista_ml is not None
                    else 0
                )
                markup_objetivo = markup_clasica + (float(pricing.porcentaje_markup_web) / 100)

                resultado = calcular_precio_web_transferencia(
                    costo_ars=costo_ars,
                    iva=float(producto_erp.iva),
                    markup_objetivo=markup_objetivo,
                    comision_web=comision_web,
                    iibb=iibb,
                )

                nuevo_precio = resultado["precio"]
                nuevo_markup_real = resultado["markup_real"]
                precio_anterior = (
                    float(pricing.precio_web_transferencia) if pricing.precio_web_transferencia is not None else None
                )

                if precio_anterior == nuevo_precio:
                    sin_cambios += 1
                    continue

                if not args.quiet:
                    print(
                        f"item_id={pricing.item_id}  "
                        f"{precio_anterior} -> {nuevo_precio}  "
                        f"markup_real={nuevo_markup_real}%"
                    )

                if not args.dry_run:
                    pricing.precio_web_transferencia = Decimal(str(nuevo_precio))
                    pricing.markup_web_real = Decimal(str(nuevo_markup_real))

                actualizados += 1

            except (ValueError, TypeError, ZeroDivisionError) as exc:
                errores += 1
                print(f"ERROR item_id={pricing.item_id}: {exc}")
                continue

        if args.dry_run:
            print("\n[DRY-RUN] No se persisten cambios")
        else:
            db.commit()

        print("\nResumen:")
        print(f"  Actualizados:    {actualizados}")
        print(f"  Sin cambios:     {sin_cambios}")
        print(f"  Sin porcentaje:  {sin_porcentaje}")
        print(f"  Errores:         {errores}")
        return 0

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
