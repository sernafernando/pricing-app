"""
Limpieza one-off: decodifica entidades HTML en productos_erp.descripcion.

El espejo del ERP guardó descripciones HTML-encodeadas (p. ej.
"BLACK &AMP; DECKER"). La ingesta (erp_sync.py) ya decodifica de ahora en más,
pero las filas existentes siguen sucias. Este script las normaliza.

Por defecto corre en DRY-RUN: muestra qué cambiaría sin tocar nada.
Pasá --commit para persistir los cambios.

Ejecutar:
    python app/scripts/limpiar_html_entities_productos.py            # dry-run
    python app/scripts/limpiar_html_entities_productos.py --commit   # aplica
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import argparse

from app.core.database import SessionLocal
from app.models.producto import ProductoERP
from app.utils.text import decode_html_entities


def limpiar(commit: bool) -> None:
    db = SessionLocal()
    try:
        productos = db.query(ProductoERP).all()
        cambios = []

        for p in productos:
            limpio = decode_html_entities(p.descripcion)
            if limpio != p.descripcion:
                cambios.append((p.item_id, p.descripcion, limpio))

        print(f"Productos revisados: {len(productos)}")
        print(f"Descripciones con entidades HTML a corregir: {len(cambios)}")
        print()

        # Muestra hasta 30 ejemplos para inspección
        for item_id, antes, despues in cambios[:30]:
            print(f"  [{item_id}] {antes!r}  ->  {despues!r}")
        if len(cambios) > 30:
            print(f"  ... y {len(cambios) - 30} más")

        if not cambios:
            print("✅ Nada que limpiar.")
            return

        if not commit:
            print()
            print("DRY-RUN: no se modificó nada. Volvé a correr con --commit para aplicar.")
            return

        for item_id, _antes, despues in cambios:
            producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
            if producto is not None:
                producto.descripcion = despues

        db.commit()
        print()
        print(f"✅ {len(cambios)} descripciones actualizadas.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Decodifica entidades HTML en productos_erp.descripcion")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Aplica los cambios. Sin este flag corre en dry-run.",
    )
    args = parser.parse_args()
    limpiar(commit=args.commit)


if __name__ == "__main__":
    main()
