#!/usr/bin/env python3
"""
Script para verificar el estado de las métricas en la base de datos
Ejecutar en el servidor: python check_metricas_status.py
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import func, text
from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica


def print_header(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def check_ml_metricas(db):
    """Verificar métricas de ML"""
    print_header("MÉTRICAS ML")
    
    # Total registros
    total = db.query(func.count(MLVentaMetrica.id_operacion)).scalar()
    print(f"📊 Total registros: {total:,}")
    
    # Últimas 10 ventas
    ultimos = db.query(
        MLVentaMetrica.fecha_venta,
        MLVentaMetrica.fecha_calculo,
        MLVentaMetrica.id_operacion,
        MLVentaMetrica.codigo,
        MLVentaMetrica.monto_total
    ).order_by(MLVentaMetrica.fecha_venta.desc()).limit(10).all()
    
    print(f"\n📅 Últimas 10 ventas registradas:")
    print(f"{'Fecha Venta':<20} {'Fecha Cálculo':<15} {'ID Op':<10} {'Código':<15} {'Monto':>12}")
    print("-" * 80)
    for v in ultimos:
        print(f"{str(v.fecha_venta):<20} {str(v.fecha_calculo):<15} {v.id_operacion:<10} {v.codigo or 'N/A':<15} ${float(v.monto_total):>10,.2f}")
    
    # Estadísticas por fecha de cálculo
    print(f"\n🔄 Registros por fecha de cálculo (últimos 7 días):")
    fecha_desde = datetime.now().date() - timedelta(days=7)
    stats = db.execute(text("""
        SELECT fecha_calculo, COUNT(*) as cantidad
        FROM ml_ventas_metricas
        WHERE fecha_calculo >= :fecha_desde
        GROUP BY fecha_calculo
        ORDER BY fecha_calculo DESC
    """), {'fecha_desde': fecha_desde}).fetchall()
    
    print(f"{'Fecha Cálculo':<20} {'Cantidad':>10}")
    print("-" * 35)
    for row in stats:
        print(f"{str(row[0]):<20} {row[1]:>10,}")
    
    # Rango de fechas de ventas
    rango = db.execute(text("""
        SELECT 
            MIN(fecha_venta) as primera_venta,
            MAX(fecha_venta) as ultima_venta,
            MAX(fecha_calculo) as ultimo_calculo
        FROM ml_ventas_metricas
    """)).fetchone()
    
    print(f"\n📆 Rango de datos:")
    print(f"  Primera venta: {rango[0]}")
    print(f"  Última venta:  {rango[1]}")
    print(f"  Último cálculo: {rango[2]}")


def check_fuera_ml_metricas(db):
    """Verificar métricas fuera de ML"""
    print_header("MÉTRICAS FUERA ML")
    
    # Total registros
    total = db.query(func.count(VentaFueraMLMetrica.it_transaction)).scalar()
    print(f"📊 Total registros: {total:,}")
    
    # Últimas 10 ventas
    ultimos = db.query(
        VentaFueraMLMetrica.fecha_venta,
        VentaFueraMLMetrica.fecha_calculo,
        VentaFueraMLMetrica.it_transaction,
        VentaFueraMLMetrica.codigo,
        VentaFueraMLMetrica.monto_total
    ).order_by(VentaFueraMLMetrica.fecha_venta.desc()).limit(10).all()
    
    print(f"\n📅 Últimas 10 ventas registradas:")
    print(f"{'Fecha Venta':<20} {'Fecha Cálculo':<15} {'IT Trans':<10} {'Código':<15} {'Monto':>12}")
    print("-" * 80)
    for v in ultimos:
        print(f"{str(v.fecha_venta):<20} {str(v.fecha_calculo):<15} {v.it_transaction:<10} {v.codigo or 'N/A':<15} ${float(v.monto_total):>10,.2f}")
    
    # Estadísticas por fecha de cálculo
    print(f"\n🔄 Registros por fecha de cálculo (últimos 7 días):")
    fecha_desde = datetime.now().date() - timedelta(days=7)
    stats = db.execute(text("""
        SELECT fecha_calculo, COUNT(*) as cantidad
        FROM ventas_fuera_ml_metricas
        WHERE fecha_calculo >= :fecha_desde
        GROUP BY fecha_calculo
        ORDER BY fecha_calculo DESC
    """), {'fecha_desde': fecha_desde}).fetchall()
    
    print(f"{'Fecha Cálculo':<20} {'Cantidad':>10}")
    print("-" * 35)
    for row in stats:
        print(f"{str(row[0]):<20} {row[1]:>10,}")
    
    # Rango de fechas
    rango = db.execute(text("""
        SELECT 
            MIN(fecha_venta) as primera_venta,
            MAX(fecha_venta) as ultima_venta,
            MAX(fecha_calculo) as ultimo_calculo
        FROM ventas_fuera_ml_metricas
    """)).fetchone()
    
    print(f"\n📆 Rango de datos:")
    print(f"  Primera venta: {rango[0]}")
    print(f"  Última venta:  {rango[1]}")
    print(f"  Último cálculo: {rango[2]}")


def check_tienda_nube_metricas(db):
    """Verificar métricas de Tienda Nube"""
    print_header("MÉTRICAS TIENDA NUBE")
    
    # Total registros
    total = db.query(func.count(VentaTiendaNubeMetrica.it_transaction)).scalar()
    print(f"📊 Total registros: {total:,}")
    
    # Últimas 10 ventas
    ultimos = db.query(
        VentaTiendaNubeMetrica.fecha_venta,
        VentaTiendaNubeMetrica.fecha_calculo,
        VentaTiendaNubeMetrica.it_transaction,
        VentaTiendaNubeMetrica.codigo,
        VentaTiendaNubeMetrica.monto_total
    ).order_by(VentaTiendaNubeMetrica.fecha_venta.desc()).limit(10).all()
    
    print(f"\n📅 Últimas 10 ventas registradas:")
    print(f"{'Fecha Venta':<20} {'Fecha Cálculo':<15} {'IT Trans':<10} {'Código':<15} {'Monto':>12}")
    print("-" * 80)
    for v in ultimos:
        print(f"{str(v.fecha_venta):<20} {str(v.fecha_calculo):<15} {v.it_transaction:<10} {v.codigo or 'N/A':<15} ${float(v.monto_total):>10,.2f}")
    
    # Estadísticas por fecha de cálculo
    print(f"\n🔄 Registros por fecha de cálculo (últimos 7 días):")
    fecha_desde = datetime.now().date() - timedelta(days=7)
    stats = db.execute(text("""
        SELECT fecha_calculo, COUNT(*) as cantidad
        FROM ventas_tienda_nube_metricas
        WHERE fecha_calculo >= :fecha_desde
        GROUP BY fecha_calculo
        ORDER BY fecha_calculo DESC
    """), {'fecha_desde': fecha_desde}).fetchall()
    
    print(f"{'Fecha Cálculo':<20} {'Cantidad':>10}")
    print("-" * 35)
    for row in stats:
        print(f"{str(row[0]):<20} {row[1]:>10,}")
    
    # Rango de fechas
    rango = db.execute(text("""
        SELECT 
            MIN(fecha_venta) as primera_venta,
            MAX(fecha_venta) as ultima_venta,
            MAX(fecha_calculo) as ultimo_calculo
        FROM ventas_tienda_nube_metricas
    """)).fetchone()
    
    print(f"\n📆 Rango de datos:")
    print(f"  Primera venta: {rango[0]}")
    print(f"  Última venta:  {rango[1]}")
    print(f"  Último cálculo: {rango[2]}")


def check_gaps(db):
    """Verificar gaps (días sin datos) en las últimas 4 semanas"""
    print_header("VERIFICACIÓN DE GAPS (últimos 30 días)")
    
    fecha_desde = datetime.now().date() - timedelta(days=30)
    
    # ML Gaps
    print("\n🔍 ML - Días sin ventas registradas:")
    ml_gaps = db.execute(text("""
        WITH fecha_serie AS (
            SELECT generate_series(
                :fecha_desde::date,
                CURRENT_DATE,
                '1 day'::interval
            )::date as fecha
        )
        SELECT fs.fecha
        FROM fecha_serie fs
        LEFT JOIN ml_ventas_metricas mv ON mv.fecha_venta::date = fs.fecha
        WHERE mv.id_operacion IS NULL
        ORDER BY fs.fecha DESC
    """), {'fecha_desde': fecha_desde}).fetchall()
    
    if ml_gaps:
        for row in ml_gaps[:10]:  # Mostrar solo primeros 10
            print(f"  ⚠️  {row[0]}")
        if len(ml_gaps) > 10:
            print(f"  ... y {len(ml_gaps) - 10} días más")
    else:
        print("  ✅ No hay gaps en ML")
    
    # Fuera ML Gaps
    print("\n🔍 Fuera ML - Días sin ventas registradas:")
    fuera_gaps = db.execute(text("""
        WITH fecha_serie AS (
            SELECT generate_series(
                :fecha_desde::date,
                CURRENT_DATE,
                '1 day'::interval
            )::date as fecha
        )
        SELECT fs.fecha
        FROM fecha_serie fs
        LEFT JOIN ventas_fuera_ml_metricas vf ON vf.fecha_venta::date = fs.fecha
        WHERE vf.it_transaction IS NULL
        ORDER BY fs.fecha DESC
    """), {'fecha_desde': fecha_desde}).fetchall()
    
    if fuera_gaps:
        for row in fuera_gaps[:10]:
            print(f"  ⚠️  {row[0]}")
        if len(fuera_gaps) > 10:
            print(f"  ... y {len(fuera_gaps) - 10} días más")
    else:
        print("  ✅ No hay gaps en Fuera ML")
    
    # Tienda Nube Gaps
    print("\n🔍 Tienda Nube - Días sin ventas registradas:")
    tn_gaps = db.execute(text("""
        WITH fecha_serie AS (
            SELECT generate_series(
                :fecha_desde::date,
                CURRENT_DATE,
                '1 day'::interval
            )::date as fecha
        )
        SELECT fs.fecha
        FROM fecha_serie fs
        LEFT JOIN ventas_tienda_nube_metricas vt ON vt.fecha_venta::date = fs.fecha
        WHERE vt.it_transaction IS NULL
        ORDER BY fs.fecha DESC
    """), {'fecha_desde': fecha_desde}).fetchall()
    
    if tn_gaps:
        for row in tn_gaps[:10]:
            print(f"  ⚠️  {row[0]}")
        if len(tn_gaps) > 10:
            print(f"  ... y {len(tn_gaps) - 10} días más")
    else:
        print("  ✅ No hay gaps en Tienda Nube")


def main():
    print("\n" + "=" * 80)
    print("  VERIFICACIÓN DE ESTADO DE MÉTRICAS")
    print("  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 80)
    
    db = SessionLocal()
    
    try:
        check_ml_metricas(db)
        check_fuera_ml_metricas(db)
        check_tienda_nube_metricas(db)
        check_gaps(db)
        
        print("\n" + "=" * 80)
        print("  ✅ VERIFICACIÓN COMPLETADA")
        print("=" * 80 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
