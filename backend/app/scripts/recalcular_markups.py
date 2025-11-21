import sys
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

# Cargar variables de entorno desde .env ANTES de importar settings
from dotenv import load_dotenv
env_path = backend_path / '.env'
load_dotenv(dotenv_path=env_path)

import psycopg2
from app.core.config import settings

# Parsear DATABASE_URL
db_url = settings.DATABASE_URL.replace("postgresql://", "")
user_pass, host_db = db_url.split("@")
user, password = user_pass.split(":")
host_port, database = host_db.split("/")
host, port = host_port.split(":")

conn = psycopg2.connect(host=host, port=port, database=database, user=user, password=password)
cursor = conn.cursor()

# Obtener tipo de cambio USD
cursor.execute("SELECT venta FROM tipo_cambio WHERE moneda = 'USD' ORDER BY fecha DESC LIMIT 1")
tc_result = cursor.fetchone()
tc_usd = tc_result[0] if tc_result else 1100

# Obtener productos con precio
cursor.execute("""
    SELECT pp.id, pp.item_id, pp.precio_lista_ml, 
           pe.costo, pe.moneda_costo, pe.subcategoria_id, pe.iva, COALESCE(pe.envio, 0) as envio
    FROM productos_pricing pp
    JOIN productos_erp pe ON pe.item_id = pp.item_id
    WHERE pp.precio_lista_ml IS NOT NULL
""")

actualizados = 0
VARIOS_DEFAULT = {"impuestos": 0.03, "financiero": 0.02, "logistica": 0.01}

for row in cursor.fetchall():
    pricing_id, item_id, precio, costo, moneda, subcat_id, iva, envio = row
    
    try:
        costo_ars = costo if moneda == "ARS" else costo * tc_usd
        
        # Obtener comisión
        cursor.execute("""
            SELECT clg.comision_porcentaje 
            FROM comisiones_lista_grupo clg
            JOIN subcategorias_grupos sg ON sg.grupo_id = clg.grupo_id
            WHERE clg.pricelist_id = 4 AND sg.subcat_id = %s
        """, (subcat_id,))
        
        comision_result = cursor.fetchone()
        if not comision_result:
            continue
            
        comision_base = comision_result[0]
        
        # Calcular comisión total
        comision_ml = precio * comision_base
        iva_comision = comision_ml * iva
        varios = precio * sum(VARIOS_DEFAULT.values())
        comision_total = comision_ml + iva_comision + varios
        
        # Calcular limpio
        iva_precio = precio * iva / (1 + iva)
        limpio = precio - iva_precio - envio - comision_total
        
        # Calcular markup
        markup = ((limpio - costo_ars) / costo_ars) * 100 if costo_ars > 0 else 0
        
        # Actualizar
        cursor.execute("UPDATE productos_pricing SET markup_calculado = %s WHERE id = %s", 
                      (round(markup, 2), pricing_id))
        actualizados += 1
        
    except Exception as e:
        print(f"Error en item_id {item_id}: {e}")
        conn.rollback()
        continue

conn.commit()
cursor.close()
conn.close()

print(f"✅ Markups recalculados para {actualizados} productos")
