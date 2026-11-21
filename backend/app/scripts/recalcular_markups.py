import sys
from pathlib import Path

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

# Cargar variables de entorno desde .env ANTES de importar settings
from dotenv import load_dotenv

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

import psycopg2
from app.core.config import settings
from app.services.costo_si import lote

# Parsear DATABASE_URL
db_url = settings.DATABASE_URL.replace("postgresql://", "")
user_pass, host_db = db_url.split("@")
user, password = user_pass.split(":")
host_port, database = host_db.split("/")
host, port = host_port.split(":")

conn = psycopg2.connect(host=host, port=port, database=database, user=user, password=password)
cursor = conn.cursor()

# Obtener productos con precio. The cost is costo SI in pesos (S13; list cost without one, Q1), today's FX:
# the reader's own SQL, so this script and the app never disagree.
cursor.execute(f"""
    SELECT rm_pp.id, rm_pp.item_id, rm_pp.precio_lista_ml,
           rm_cs.costo_si_ars, rm_pe.subcategoria_id, rm_pe.iva, COALESCE(rm_pe.envio, 0) as envio
    FROM productos_pricing rm_pp
    JOIN productos_erp rm_pe ON rm_pe.item_id = rm_pp.item_id
    LEFT JOIN LATERAL ({lote.sql_en_fecha("rm_pp.item_id", "CURRENT_DATE")}) rm_cs ON true
    WHERE rm_pp.precio_lista_ml IS NOT NULL
""")

actualizados = 0
VARIOS_DEFAULT = {"impuestos": 0.03, "financiero": 0.02, "logistica": 0.01}

for row in cursor.fetchall():
    pricing_id, item_id, precio, costo_ars, subcat_id, iva, envio = row

    try:
        if not costo_ars or costo_ars <= 0:
            print(f"Sin costo en pesos para item_id {item_id}: markup no recalculado")
            continue

        # Obtener comisión
        cursor.execute(
            """
            SELECT clg.comision_porcentaje 
            FROM comisiones_lista_grupo clg
            JOIN subcategorias_grupos sg ON sg.grupo_id = clg.grupo_id
            WHERE clg.pricelist_id = 4 AND sg.subcat_id = %s
        """,
            (subcat_id,),
        )

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
        markup = ((limpio - costo_ars) / costo_ars) * 100

        # Actualizar
        cursor.execute(
            "UPDATE productos_pricing SET markup_calculado = %s WHERE id = %s", (round(markup, 2), pricing_id)
        )
        actualizados += 1

    except Exception as e:
        print(f"Error en item_id {item_id}: {e}")
        conn.rollback()
        continue

conn.commit()
cursor.close()
conn.close()

print(f"✅ Markups recalculados para {actualizados} productos")
