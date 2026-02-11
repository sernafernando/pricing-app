"""
Script para corregir datos faltantes en ml_ventas_metricas.
Actualiza codigo, descripcion, marca, categoria, subcategoria
usando datos de productos_erp como fallback.

Ejecutar:
    python app/scripts/fix_ml_metricas_datos_faltantes.py
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

from sqlalchemy import text
from app.core.database import SessionLocal


def main():
    print("=" * 60)
    print("FIX ML METRICAS - Datos Faltantes")
    print("=" * 60)

    db = SessionLocal()

    try:
        # Contar registros con datos faltantes
        count_query = text("""
            SELECT COUNT(*) as total
            FROM ml_ventas_metricas m
            WHERE (m.codigo IS NULL OR m.codigo = '')
               OR (m.descripcion IS NULL OR m.descripcion = '')
               OR (m.marca IS NULL OR m.marca = '')
        """)
        result = db.execute(count_query).fetchone()
        total_faltantes = result[0] if result else 0

        print(f"\nRegistros con datos faltantes: {total_faltantes}")

        if total_faltantes == 0:
            print("No hay registros para corregir.")
            return

        # Actualizar codigo desde productos_erp
        print("\nActualizando codigo...")
        update_codigo = text("""
            UPDATE ml_ventas_metricas m
            SET codigo = pe.codigo
            FROM productos_erp pe
            WHERE m.item_id = pe.item_id
              AND (m.codigo IS NULL OR m.codigo = '')
              AND pe.codigo IS NOT NULL
        """)
        result = db.execute(update_codigo)
        db.commit()
        print(f"  Actualizados: {result.rowcount}")

        # Actualizar descripcion desde productos_erp
        print("\nActualizando descripcion...")
        update_descripcion = text("""
            UPDATE ml_ventas_metricas m
            SET descripcion = UPPER(pe.descripcion)
            FROM productos_erp pe
            WHERE m.item_id = pe.item_id
              AND (m.descripcion IS NULL OR m.descripcion = '')
              AND pe.descripcion IS NOT NULL
        """)
        result = db.execute(update_descripcion)
        db.commit()
        print(f"  Actualizados: {result.rowcount}")

        # Actualizar marca desde productos_erp
        print("\nActualizando marca...")
        update_marca = text("""
            UPDATE ml_ventas_metricas m
            SET marca = pe.marca
            FROM productos_erp pe
            WHERE m.item_id = pe.item_id
              AND (m.marca IS NULL OR m.marca = '')
              AND pe.marca IS NOT NULL
        """)
        result = db.execute(update_marca)
        db.commit()
        print(f"  Actualizados: {result.rowcount}")

        # Actualizar categoria desde productos_erp
        print("\nActualizando categoria...")
        update_categoria = text("""
            UPDATE ml_ventas_metricas m
            SET categoria = pe.categoria
            FROM productos_erp pe
            WHERE m.item_id = pe.item_id
              AND (m.categoria IS NULL OR m.categoria = '')
              AND pe.categoria IS NOT NULL
        """)
        result = db.execute(update_categoria)
        db.commit()
        print(f"  Actualizados: {result.rowcount}")

        # Actualizar subcategoria desde tb_subcategory usando subcategoria_id de productos_erp
        print("\nActualizando subcategoria...")
        update_subcategoria = text("""
            UPDATE ml_ventas_metricas m
            SET subcategoria = tsc.subcat_desc
            FROM productos_erp pe
            JOIN tb_subcategory tsc ON tsc.subcat_id = pe.subcategoria_id
            WHERE m.item_id = pe.item_id
              AND (m.subcategoria IS NULL OR m.subcategoria = '')
              AND pe.subcategoria_id IS NOT NULL
        """)
        result = db.execute(update_subcategoria)
        db.commit()
        print(f"  Actualizados: {result.rowcount}")

        # Verificar cuántos quedaron sin corregir
        result = db.execute(count_query).fetchone()
        restantes = result[0] if result else 0

        print("\n" + "=" * 60)
        print("COMPLETADO")
        print("=" * 60)
        print(f"Registros aún con datos faltantes: {restantes}")

        if restantes > 0:
            # Mostrar algunos ejemplos de los que no se pudieron corregir
            ejemplos_query = text("""
                SELECT m.item_id, m.codigo, m.descripcion, m.marca
                FROM ml_ventas_metricas m
                WHERE (m.codigo IS NULL OR m.codigo = '')
                   OR (m.descripcion IS NULL OR m.descripcion = '')
                   OR (m.marca IS NULL OR m.marca = '')
                LIMIT 10
            """)
            ejemplos = db.execute(ejemplos_query).fetchall()
            print("\nEjemplos de registros que no pudieron ser corregidos:")
            for ej in ejemplos:
                print(f"  item_id: {ej[0]}, codigo: {ej[1]}, desc: {ej[2]}, marca: {ej[3]}")

    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback

        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
