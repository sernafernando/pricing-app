#!/usr/bin/env python3
"""
Script para verificar el estado de TODAS las sincronizaciones del ERP
Ejecutar en el servidor: python check_full_sync_status.py
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.core.database import SessionLocal


def print_header(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_subheader(title):
    print(f"\n{title}")
    print("-" * 80)


def check_commercial_transactions(db):
    """Verificar Commercial Transactions"""
    print_header("COMMERCIAL TRANSACTIONS (tb_commercial_transactions)")
    
    # Total y rango
    stats = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            MIN(ct_date) as primera_transaccion,
            MAX(ct_date) as ultima_transaccion,
            COUNT(DISTINCT DATE(ct_date)) as dias_con_datos
        FROM tb_commercial_transactions
    """)).fetchone()
    
    print(f"📊 Total registros: {stats[0]:,}")
    print(f"📆 Primera transacción: {stats[1]}")
    print(f"📆 Última transacción:  {stats[2]}")
    print(f"📅 Días con datos: {stats[3]:,}")
    
    # Últimos 30 días
    print_subheader("📈 Transacciones últimos 30 días:")
    ultimos_30 = db.execute(text("""
        SELECT 
            DATE(ct_date) as fecha,
            COUNT(*) as cantidad,
            SUM(CASE WHEN sd_id IN (1, 4, 21, 56) THEN 1 ELSE 0 END) as ventas,
            SUM(CASE WHEN sd_id IN (3, 6, 23, 66) THEN 1 ELSE 0 END) as devoluciones
        FROM tb_commercial_transactions
        WHERE ct_date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY DATE(ct_date)
        ORDER BY fecha DESC
        LIMIT 10
    """)).fetchall()
    
    print(f"{'Fecha':<15} {'Total':>8} {'Ventas':>8} {'Devoluc':>8}")
    print("-" * 45)
    for row in ultimos_30:
        print(f"{str(row[0]):<15} {row[1]:>8,} {row[2]:>8,} {row[3]:>8,}")
    
    # Gaps últimos 30 días
    print_subheader("🔍 Gaps (días sin transacciones últimos 30 días):")
    gaps = db.execute(text("""
        WITH fecha_serie AS (
            SELECT generate_series(
                CURRENT_DATE - INTERVAL '30 days',
                CURRENT_DATE,
                '1 day'::interval
            )::date as fecha
        )
        SELECT fs.fecha
        FROM fecha_serie fs
        LEFT JOIN tb_commercial_transactions tct ON DATE(tct.ct_date) = fs.fecha
        WHERE tct.ct_transaction IS NULL
        ORDER BY fs.fecha DESC
    """)).fetchall()
    
    if gaps:
        print(f"  ⚠️  {len(gaps)} días sin datos:")
        for row in gaps[:5]:
            print(f"    - {row[0]}")
        if len(gaps) > 5:
            print(f"    ... y {len(gaps) - 5} días más")
    else:
        print("  ✅ No hay gaps")


def check_sale_orders(db):
    """Verificar Sale Orders"""
    print_header("SALE ORDERS (tb_sale_order_header + tb_sale_order_detail)")
    
    # Stats Header
    stats_header = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            MIN(soh_cd) as primera_orden,
            MAX(soh_cd) as ultima_orden,
            COUNT(DISTINCT DATE(soh_cd)) as dias_con_datos
        FROM tb_sale_order_header
    """)).fetchone()
    
    print(f"📊 Total órdenes (header): {stats_header[0]:,}")
    print(f"📆 Primera orden: {stats_header[1]}")
    print(f"📆 Última orden:  {stats_header[2]}")
    print(f"📅 Días con datos: {stats_header[3]:,}")
    
    # Stats Detail
    stats_detail = db.execute(text("""
        SELECT 
            COUNT(*) as total_lines,
            COUNT(DISTINCT soh_id) as ordenes_con_detalle
        FROM tb_sale_order_detail
    """)).fetchone()
    
    print(f"📊 Total líneas (detail): {stats_detail[0]:,}")
    print(f"📊 Órdenes con detalle: {stats_detail[1]:,}")
    
    # Órdenes huérfanas (header sin detail)
    huerfanas = db.execute(text("""
        SELECT COUNT(*)
        FROM tb_sale_order_header soh
        LEFT JOIN tb_sale_order_detail sod ON soh.soh_id = sod.soh_id AND soh.comp_id = sod.comp_id AND soh.bra_id = sod.bra_id
        WHERE sod.soh_id IS NULL
    """)).scalar()
    
    if huerfanas > 0:
        print(f"⚠️  Órdenes SIN detalle: {huerfanas:,}")
    else:
        print(f"✅ Todas las órdenes tienen detalle")
    
    # Últimos 30 días
    print_subheader("📈 Órdenes últimos 30 días:")
    ultimos_30 = db.execute(text("""
        SELECT 
            DATE(soh_cd) as fecha,
            COUNT(*) as cantidad_ordenes,
            COUNT(DISTINCT cust_id) as clientes_unicos
        FROM tb_sale_order_header
        WHERE soh_cd >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY DATE(soh_cd)
        ORDER BY fecha DESC
        LIMIT 10
    """)).fetchall()
    
    print(f"{'Fecha':<15} {'Órdenes':>10} {'Clientes':>10}")
    print("-" * 40)
    for row in ultimos_30:
        print(f"{str(row[0]):<15} {row[1]:>10,} {row[2]:>10,}")
    
    # Gaps
    print_subheader("🔍 Gaps (días sin órdenes últimos 30 días):")
    gaps = db.execute(text("""
        WITH fecha_serie AS (
            SELECT generate_series(
                CURRENT_DATE - INTERVAL '30 days',
                CURRENT_DATE,
                '1 day'::interval
            )::date as fecha
        )
        SELECT fs.fecha
        FROM fecha_serie fs
        LEFT JOIN tb_sale_order_header soh ON DATE(soh.soh_cd) = fs.fecha
        WHERE soh.soh_id IS NULL
        ORDER BY fs.fecha DESC
    """)).fetchall()
    
    if gaps:
        print(f"  ⚠️  {len(gaps)} días sin datos:")
        for row in gaps[:5]:
            print(f"    - {row[0]}")
        if len(gaps) > 5:
            print(f"    ... y {len(gaps) - 5} días más")
    else:
        print("  ✅ No hay gaps")


def check_customers(db):
    """Verificar Customers"""
    print_header("CUSTOMERS (tb_customer)")
    
    stats = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(DISTINCT comp_id) as companias,
            SUM(CASE WHEN cust_blocked = true THEN 1 ELSE 0 END) as bloqueados
        FROM tb_customer
    """)).fetchone()
    
    print(f"📊 Total clientes: {stats[0]:,}")
    print(f"🏢 Compañías: {stats[1]}")
    print(f"🚫 Bloqueados: {stats[2]:,}")
    
    # Top 10 clientes por ventas (últimos 30 días)
    print_subheader("🏆 Top 10 clientes por órdenes (últimos 30 días):")
    top_clientes = db.execute(text("""
        SELECT 
            c.cust_name,
            COUNT(DISTINCT soh.soh_id) as cantidad_ordenes,
            COUNT(DISTINCT DATE(soh.soh_cd)) as dias_activo
        FROM tb_customer c
        INNER JOIN tb_sale_order_header soh ON c.cust_id = soh.cust_id AND c.comp_id = soh.comp_id
        WHERE soh.soh_cd >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY c.cust_name
        ORDER BY cantidad_ordenes DESC
        LIMIT 10
    """)).fetchall()
    
    print(f"{'Cliente':<40} {'Órdenes':>10} {'Días':>6}")
    print("-" * 60)
    for row in top_clientes:
        nombre = row[0][:38] if row[0] else 'N/A'
        print(f"{nombre:<40} {row[1]:>10,} {row[2]:>6}")


def check_items(db):
    """Verificar Items"""
    print_header("ITEMS (tb_item + tb_item_cost_list)")
    
    # Stats items
    stats_items = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(DISTINCT cat_id) as categorias,
            COUNT(DISTINCT brand_id) as marcas,
            SUM(CASE WHEN item_active = true THEN 1 ELSE 0 END) as activos
        FROM tb_item
    """)).fetchone()
    
    print(f"📊 Total items: {stats_items[0]:,}")
    print(f"📁 Categorías: {stats_items[1]}")
    print(f"🏷️  Marcas: {stats_items[2]}")
    print(f"✅ Activos: {stats_items[3]:,}")
    
    # Stats costos
    stats_costos = db.execute(text("""
        SELECT 
            COUNT(DISTINCT item_id) as items_con_costo,
            SUM(CASE WHEN curr_id = 1 THEN 1 ELSE 0 END) as costos_ars,
            SUM(CASE WHEN curr_id = 2 THEN 1 ELSE 0 END) as costos_usd,
            MAX(coslis_cd) as ultimo_update_costo
        FROM tb_item_cost_list
        WHERE coslis_id = 1
    """)).fetchone()
    
    print(f"\n💰 Items con costo: {stats_costos[0]:,}")
    print(f"   - En ARS: {stats_costos[1]:,}")
    print(f"   - En USD: {stats_costos[2]:,}")
    print(f"   - Último update: {stats_costos[3]}")
    
    # Items sin costo
    sin_costo = db.execute(text("""
        SELECT COUNT(*)
        FROM tb_item ti
        LEFT JOIN tb_item_cost_list ticl ON ti.item_id = ticl.item_id AND ticl.coslis_id = 1
        WHERE ti.item_active = true AND ticl.item_id IS NULL
    """)).scalar()
    
    if sin_costo > 0:
        print(f"⚠️  Items activos SIN costo: {sin_costo:,}")
    else:
        print(f"✅ Todos los items activos tienen costo")


def check_ml_orders(db):
    """Verificar ML Orders"""
    print_header("ML ORDERS (tb_mercadolibre_orders_header + detail)")
    
    # Stats
    stats = db.execute(text("""
        SELECT 
            COUNT(DISTINCT mloh.mlo_id) as total_ordenes,
            MIN(mloh.mlo_cd) as primera_orden,
            MAX(mloh.mlo_cd) as ultima_orden,
            COUNT(DISTINCT mlod.item_id) as items_distintos,
            SUM(mlod.mlo_quantity) as cantidad_total
        FROM tb_mercadolibre_orders_header mloh
        LEFT JOIN tb_mercadolibre_orders_detail mlod ON mloh.mlo_id = mlod.mlo_id
    """)).fetchone()
    
    print(f"📊 Total órdenes ML: {stats[0]:,}")
    print(f"📆 Primera orden: {stats[1]}")
    print(f"📆 Última orden:  {stats[2]}")
    print(f"📦 Items distintos vendidos: {stats[3]:,}")
    print(f"🔢 Cantidad total vendida: {stats[4]:,}")
    
    # Últimos 7 días
    print_subheader("📈 Órdenes ML últimos 7 días:")
    ultimos_7 = db.execute(text("""
        SELECT 
            DATE(mlo_cd) as fecha,
            COUNT(*) as cantidad_ordenes,
            SUM(CASE WHEN mlo_status = 'paid' THEN 1 ELSE 0 END) as pagadas,
            SUM(CASE WHEN mlo_status = 'cancelled' THEN 1 ELSE 0 END) as canceladas
        FROM tb_mercadolibre_orders_header
        WHERE mlo_cd >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY DATE(mlo_cd)
        ORDER BY fecha DESC
    """)).fetchall()
    
    print(f"{'Fecha':<15} {'Total':>8} {'Pagadas':>8} {'Cancel':>8}")
    print("-" * 45)
    for row in ultimos_7:
        print(f"{str(row[0]):<15} {row[1]:>8,} {row[2]:>8,} {row[3]:>8,}")
    
    # Órdenes sin detalle
    sin_detalle = db.execute(text("""
        SELECT COUNT(*)
        FROM tb_mercadolibre_orders_header mloh
        LEFT JOIN tb_mercadolibre_orders_detail mlod ON mloh.mlo_id = mlod.mlo_id
        WHERE mlod.mlo_id IS NULL
    """)).scalar()
    
    if sin_detalle > 0:
        print(f"\n⚠️  Órdenes ML SIN detalle: {sin_detalle:,}")
    else:
        print(f"\n✅ Todas las órdenes ML tienen detalle")


def check_metricas_ml(db):
    """Verificar Métricas ML"""
    print_header("MÉTRICAS ML (ml_ventas_metricas)")
    
    stats = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            MIN(fecha_venta) as primera_venta,
            MAX(fecha_venta) as ultima_venta,
            MAX(fecha_calculo) as ultimo_calculo,
            COUNT(DISTINCT DATE(fecha_venta)) as dias_con_ventas
        FROM ml_ventas_metricas
    """)).fetchone()
    
    print(f"📊 Total métricas: {stats[0]:,}")
    print(f"📆 Primera venta: {stats[1]}")
    print(f"📆 Última venta:  {stats[2]}")
    print(f"🔄 Último cálculo: {stats[3]}")
    print(f"📅 Días con ventas: {stats[4]:,}")
    
    # Últimos 7 cálculos
    print_subheader("🔄 Últimos cálculos:")
    ultimos = db.execute(text("""
        SELECT 
            fecha_calculo,
            COUNT(*) as registros_calculados,
            MIN(fecha_venta) as venta_mas_antigua,
            MAX(fecha_venta) as venta_mas_reciente
        FROM ml_ventas_metricas
        GROUP BY fecha_calculo
        ORDER BY fecha_calculo DESC
        LIMIT 7
    """)).fetchall()
    
    print(f"{'Fecha Cálculo':<15} {'Registros':>10} {'Desde':<12} {'Hasta':<12}")
    print("-" * 55)
    for row in ultimos:
        print(f"{str(row[0]):<15} {row[1]:>10,} {str(row[2]):<12} {str(row[3]):<12}")


def check_metricas_fuera_ml(db):
    """Verificar Métricas Fuera ML"""
    print_header("MÉTRICAS FUERA ML (ventas_fuera_ml_metricas)")
    
    stats = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            MIN(fecha_venta) as primera_venta,
            MAX(fecha_venta) as ultima_venta,
            MAX(fecha_calculo) as ultimo_calculo,
            COUNT(DISTINCT DATE(fecha_venta)) as dias_con_ventas
        FROM ventas_fuera_ml_metricas
    """)).fetchone()
    
    print(f"📊 Total métricas: {stats[0]:,}")
    print(f"📆 Primera venta: {stats[1]}")
    print(f"📆 Última venta:  {stats[2]}")
    print(f"🔄 Último cálculo: {stats[3]}")
    print(f"📅 Días con ventas: {stats[4]:,}")
    
    # Últimos 7 cálculos
    print_subheader("🔄 Últimos cálculos:")
    ultimos = db.execute(text("""
        SELECT 
            fecha_calculo,
            COUNT(*) as registros_calculados,
            MIN(fecha_venta) as venta_mas_antigua,
            MAX(fecha_venta) as venta_mas_reciente
        FROM ventas_fuera_ml_metricas
        GROUP BY fecha_calculo
        ORDER BY fecha_calculo DESC
        LIMIT 7
    """)).fetchall()
    
    print(f"{'Fecha Cálculo':<15} {'Registros':>10} {'Desde':<12} {'Hasta':<12}")
    print("-" * 55)
    for row in ultimos:
        print(f"{str(row[0]):<15} {row[1]:>10,} {str(row[2]):<12} {str(row[3]):<12}")


def check_metricas_tienda_nube(db):
    """Verificar Métricas Tienda Nube"""
    print_header("MÉTRICAS TIENDA NUBE (ventas_tienda_nube_metricas)")
    
    stats = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            MIN(fecha_venta) as primera_venta,
            MAX(fecha_venta) as ultima_venta,
            MAX(fecha_calculo) as ultimo_calculo,
            COUNT(DISTINCT DATE(fecha_venta)) as dias_con_ventas
        FROM ventas_tienda_nube_metricas
    """)).fetchone()
    
    print(f"📊 Total métricas: {stats[0]:,}")
    print(f"📆 Primera venta: {stats[1]}")
    print(f"📆 Última venta:  {stats[2]}")
    print(f"🔄 Último cálculo: {stats[3]}")
    print(f"📅 Días con ventas: {stats[4]:,}")
    
    # Últimos 7 cálculos
    print_subheader("🔄 Últimos cálculos:")
    ultimos = db.execute(text("""
        SELECT 
            fecha_calculo,
            COUNT(*) as registros_calculados,
            MIN(fecha_venta) as venta_mas_antigua,
            MAX(fecha_venta) as venta_mas_reciente
        FROM ventas_tienda_nube_metricas
        GROUP BY fecha_calculo
        ORDER BY fecha_calculo DESC
        LIMIT 7
    """)).fetchall()
    
    print(f"{'Fecha Cálculo':<15} {'Registros':>10} {'Desde':<12} {'Hasta':<12}")
    print("-" * 55)
    for row in ultimos:
        print(f"{str(row[0]):<15} {row[1]:>10,} {str(row[2]):<12} {str(row[3]):<12}")


def check_tipo_cambio(db):
    """Verificar Tipo de Cambio"""
    print_header("TIPO DE CAMBIO (tipo_cambio + tb_cur_exch_history)")
    
    # tipo_cambio (tabla local)
    tc_local = db.execute(text("""
        SELECT 
            moneda,
            fecha,
            compra,
            venta
        FROM tipo_cambio
        WHERE moneda = 'USD'
        ORDER BY fecha DESC
        LIMIT 5
    """)).fetchall()
    
    print("📊 Últimos 5 registros (tipo_cambio):")
    print(f"{'Moneda':<10} {'Fecha':<12} {'Compra':>10} {'Venta':>10}")
    print("-" * 50)
    for row in tc_local:
        print(f"{row[0]:<10} {str(row[1]):<12} ${row[2]:>9.2f} ${row[3]:>9.2f}")
    
    # tb_cur_exch_history (tabla del ERP)
    tc_erp = db.execute(text("""
        SELECT 
            ceh_cd,
            ceh_exchange
        FROM tb_cur_exch_history
        ORDER BY ceh_cd DESC
        LIMIT 5
    """)).fetchall()
    
    print("\n📊 Últimos 5 registros (tb_cur_exch_history - ERP):")
    print(f"{'Fecha':<25} {'TC':>10}")
    print("-" * 40)
    for row in tc_erp:
        print(f"{str(row[0]):<25} ${row[1]:>9.2f}")


def check_productos_erp(db):
    """Verificar productos_erp (tabla local sincronizada)"""
    print_header("PRODUCTOS ERP (productos_erp - local)")
    
    stats = db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(DISTINCT marca) as marcas,
            COUNT(DISTINCT categoria) as categorias,
            SUM(CASE WHEN costo IS NOT NULL AND costo > 0 THEN 1 ELSE 0 END) as con_costo,
            SUM(CASE WHEN precio_lista_ml IS NOT NULL AND precio_lista_ml > 0 THEN 1 ELSE 0 END) as con_precio_ml
        FROM productos_erp
    """)).fetchone()
    
    print(f"📊 Total productos: {stats[0]:,}")
    print(f"🏷️  Marcas: {stats[1]:,}")
    print(f"📁 Categorías: {stats[2]:,}")
    print(f"💰 Con costo: {stats[3]:,} ({stats[3]*100/stats[0]:.1f}%)")
    print(f"🏷️  Con precio ML: {stats[4]:,} ({stats[4]*100/stats[0]:.1f}%)")
    
    # Sin costo
    sin_costo = db.execute(text("""
        SELECT COUNT(*)
        FROM productos_erp
        WHERE costo IS NULL OR costo = 0
    """)).scalar()
    
    if sin_costo > 0:
        print(f"\n⚠️  Productos SIN costo: {sin_costo:,}")


def check_sync_health(db):
    """Verificar salud general de sincronización"""
    print_header("SALUD GENERAL DE SINCRONIZACIÓN")
    
    now = datetime.now()
    
    # Última actividad por tabla
    print("⏰ Última actividad por tabla:")
    print(f"{'Tabla':<40} {'Última Actividad':<25} {'Hace':<15}")
    print("-" * 85)
    
    tables = [
        ('Commercial Transactions', 'SELECT MAX(ct_date) FROM tb_commercial_transactions'),
        ('Sale Orders', 'SELECT MAX(soh_cd) FROM tb_sale_order_header'),
        ('ML Orders', 'SELECT MAX(mlo_cd) FROM tb_mercadolibre_orders_header'),
        ('ML Métricas', 'SELECT MAX(fecha_calculo) FROM ml_ventas_metricas'),
        ('Fuera ML Métricas', 'SELECT MAX(fecha_calculo) FROM ventas_fuera_ml_metricas'),
        ('TN Métricas', 'SELECT MAX(fecha_calculo) FROM ventas_tienda_nube_metricas'),
        ('Tipo Cambio', 'SELECT MAX(fecha) FROM tipo_cambio'),
    ]
    
    for tabla, query in tables:
        result = db.execute(text(query)).scalar()
        if result:
            if isinstance(result, datetime):
                hace = now - result
                hace_str = f"{hace.days}d {hace.seconds//3600}h"
            else:
                # Es date
                hace = now.date() - result
                hace_str = f"{hace.days} días"
            print(f"{tabla:<40} {str(result):<25} {hace_str:<15}")
        else:
            print(f"{tabla:<40} {'Sin datos':<25} {'N/A':<15}")


def main():
    print("\n" + "=" * 80)
    print("  VERIFICACIÓN COMPLETA DE SINCRONIZACIÓN - PRICING APP")
    print("  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 80)
    
    db = SessionLocal()
    
    try:
        # ERP Core Tables
        check_commercial_transactions(db)
        check_sale_orders(db)
        check_customers(db)
        check_items(db)
        
        # ML
        check_ml_orders(db)
        
        # Métricas
        check_metricas_ml(db)
        check_metricas_fuera_ml(db)
        check_metricas_tienda_nube(db)
        
        # Support Tables
        check_tipo_cambio(db)
        check_productos_erp(db)
        
        # Resumen
        check_sync_health(db)
        
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
