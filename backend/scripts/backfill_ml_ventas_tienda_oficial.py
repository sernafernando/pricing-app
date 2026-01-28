#!/usr/bin/env python3
"""
Script de backfill para popular ml_ventas_metricas.mlp_official_store_id

Este script:
1. Lee todas las ventas donde mlp_official_store_id IS NULL
2. Busca el mlp_official_store_id en mercadolibre_items_publicados usando mla_id
3. Actualiza ml_ventas_metricas.mlp_official_store_id
4. Hace commits cada 1000 filas para no trabar la base

Uso:
    cd backend
    python3 scripts/backfill_ml_ventas_tienda_oficial.py

IMPORTANTE: Los límites de offsets son GLOBALES. Este campo solo sirve para 
filtrar visualización por tienda, no para calcular límites separados.
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path para importar app
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import cast, String
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado


def backfill_tienda_oficial(batch_size: int = 1000, dry_run: bool = False):
    """
    Popula mlp_official_store_id en ml_ventas_metricas desde mercadolibre_items_publicados.
    
    Args:
        batch_size: Cantidad de filas a procesar por batch (default: 1000)
        dry_run: Si es True, solo muestra qué haría sin modificar la BD
    """
    db: Session = SessionLocal()
    
    try:
        # Contar total de ventas sin tienda oficial
        total_sin_tienda = db.query(MLVentaMetrica).filter(
            MLVentaMetrica.mlp_official_store_id.is_(None),
            MLVentaMetrica.mla_id.isnot(None)
        ).count()
        
        print(f"📊 Total de ventas sin tienda oficial: {total_sin_tienda:,}")
        
        if total_sin_tienda == 0:
            print("✅ No hay ventas para procesar. Todo actualizado!")
            return
        
        if dry_run:
            print("\n🔍 DRY RUN - Solo mostrando qué se haría:")
            # Mostrar sample de 10 ventas
            sample = db.query(
                MLVentaMetrica.id,
                MLVentaMetrica.mla_id,
                MLVentaMetrica.descripcion
            ).filter(
                MLVentaMetrica.mlp_official_store_id.is_(None),
                MLVentaMetrica.mla_id.isnot(None)
            ).limit(10).all()
            
            for venta in sample:
                item = db.query(MercadoLibreItemPublicado).filter(
                    cast(MercadoLibreItemPublicado.mlp_id, String) == venta.mla_id
                ).first()
                
                if item and item.mlp_official_store_id:
                    print(f"  Venta {venta.id} (MLA{venta.mla_id}) → Tienda {item.mlp_official_store_id}")
                else:
                    print(f"  Venta {venta.id} (MLA{venta.mla_id}) → Sin tienda oficial")
            
            print(f"\n⚠️  DRY RUN: No se modificó la base de datos")
            print(f"   Para ejecutar de verdad, quitar el parámetro dry_run=True")
            return
        
        # Procesar en batches
        procesadas = 0
        actualizadas = 0
        sin_match = 0
        
        print(f"\n🚀 Iniciando backfill (batch size: {batch_size})...\n")
        
        while True:
            # Obtener batch de ventas sin tienda oficial
            ventas = db.query(MLVentaMetrica).filter(
                MLVentaMetrica.mlp_official_store_id.is_(None),
                MLVentaMetrica.mla_id.isnot(None)
            ).limit(batch_size).all()
            
            if not ventas:
                break  # No hay más ventas para procesar
            
            # Procesar cada venta del batch
            for venta in ventas:
                procesadas += 1
                
                # Buscar item publicado por mla_id
                # ml_ventas_metricas.mla_id contiene el mlp_id como string (ej: "1234567890")
                item = db.query(MercadoLibreItemPublicado).filter(
                    cast(MercadoLibreItemPublicado.mlp_id, String) == venta.mla_id
                ).first()
                
                if item and item.mlp_official_store_id:
                    venta.mlp_official_store_id = item.mlp_official_store_id
                    actualizadas += 1
                else:
                    sin_match += 1
            
            # Commit del batch
            db.commit()
            
            # Mostrar progreso
            porcentaje = (procesadas / total_sin_tienda) * 100
            print(f"   Procesadas: {procesadas:,}/{total_sin_tienda:,} ({porcentaje:.1f}%) | "
                  f"Actualizadas: {actualizadas:,} | Sin match: {sin_match:,}")
        
        print(f"\n✅ Backfill completado!")
        print(f"   📈 Total procesadas: {procesadas:,}")
        print(f"   ✔️  Actualizadas con tienda: {actualizadas:,}")
        print(f"   ⚠️  Sin match (quedan NULL): {sin_match:,}")
        
        if sin_match > 0:
            print(f"\n💡 Las {sin_match:,} ventas sin match probablemente son:")
            print(f"   - Items que ya no están publicados")
            print(f"   - Ventas muy antiguas sin registro en mercadolibre_items_publicados")
            print(f"   - Estas ventas solo se mostrarán cuando NO hay filtro de tienda")
    
    except Exception as e:
        print(f"\n❌ Error durante el backfill: {e}")
        db.rollback()
        raise
    
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Backfill de tienda oficial en ml_ventas_metricas")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Cantidad de filas a procesar por batch (default: 1000)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo mostrar qué se haría sin modificar la BD"
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("🔧 BACKFILL: ml_ventas_metricas.mlp_official_store_id")
    print("=" * 70)
    
    if args.dry_run:
        print("\n⚠️  MODO DRY RUN ACTIVADO - No se modificará la base de datos\n")
    
    backfill_tienda_oficial(batch_size=args.batch_size, dry_run=args.dry_run)
    
    print("\n" + "=" * 70)
