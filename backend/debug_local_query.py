"""
Debug: Ver qué valores está obteniendo la query de _local para el producto 6935364080433
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

from sqlalchemy import text
from app.core.database import SessionLocal
from datetime import date

db = SessionLocal()

# Ejecutar solo la parte de la query que obtiene el costo para este producto específico
query = text("""
SELECT
    ti.item_code as codigo,
    tmloh.mlo_cd as fecha_venta,
    tmlod.mlo_unit_price as monto_unitario,
    tmlod.mlo_quantity as cantidad,

    -- Moneda del costo
    (
        SELECT iclh.curr_id
        FROM tb_item_cost_list_history iclh
        WHERE iclh.item_id = tmlod.item_id
          AND iclh.iclh_cd <= tmloh.mlo_cd
          AND iclh.coslis_id = 1
        ORDER BY iclh.iclh_id DESC
        LIMIT 1
    ) as moneda_costo,

    -- Tipo de cambio
    (
        SELECT ceh.ceh_exchange
        FROM tb_cur_exch_history ceh
        WHERE ceh.ceh_cd <= tmloh.mlo_cd
        ORDER BY ceh.ceh_cd DESC
        LIMIT 1
    ) as tc_momento,

    -- Costo calculado (la misma lógica compleja de _local)
    COALESCE(
        (
            SELECT CASE
                WHEN iclh.curr_id = 2 THEN  -- USD
                    CASE
                        WHEN iclh.iclh_price = 0 THEN ticl.coslis_price * (
                            SELECT ceh.ceh_exchange
                            FROM tb_cur_exch_history ceh
                            WHERE ceh.ceh_cd <= tmloh.mlo_cd
                            ORDER BY ceh.ceh_cd DESC
                            LIMIT 1
                        )
                        ELSE iclh.iclh_price * (
                            SELECT ceh.ceh_exchange
                            FROM tb_cur_exch_history ceh
                            WHERE ceh.ceh_cd <= tmloh.mlo_cd
                            ORDER BY ceh.ceh_cd DESC
                            LIMIT 1
                        )
                    END
                ELSE  -- ARS
                    CASE
                        WHEN iclh.iclh_price = 0 THEN ticl.coslis_price
                        ELSE iclh.iclh_price
                    END
            END
            FROM tb_item_cost_list_history iclh
            LEFT JOIN tb_item_cost_list ticl
                ON ticl.item_id = iclh.item_id
                AND ticl.coslis_id = 1
            WHERE iclh.item_id = tmlod.item_id
              AND iclh.iclh_cd <= tmloh.mlo_cd
              AND iclh.coslis_id = 1
            ORDER BY iclh.iclh_id DESC
            LIMIT 1
        ),
        (
            SELECT CASE
                WHEN ticl.curr_id = 2 THEN  -- USD
                    ticl.coslis_price * (
                        SELECT ceh.ceh_exchange
                        FROM tb_cur_exch_history ceh
                        WHERE ceh.ceh_cd <= tmloh.mlo_cd
                        ORDER BY ceh.ceh_cd DESC
                        LIMIT 1
                    )
                ELSE  -- ARS
                    ticl.coslis_price
            END
            FROM tb_item_cost_list ticl
            WHERE ticl.item_id = tmlod.item_id
              AND ticl.coslis_id = 1
        ),
        0
    ) as costo_sin_iva,

    tmlos.mlshippmentcost4seller as costo_envio_sin_iva,
    tmlip.mlp_price4freeshipping as precio_envio_gratis

FROM tb_mercadolibre_orders_detail tmlod
LEFT JOIN tb_mercadolibre_orders_header tmloh
    ON tmloh.comp_id = tmlod.comp_id
    AND tmloh.mlo_id = tmlod.mlo_id
LEFT JOIN tb_item ti
    ON ti.comp_id = tmlod.comp_id
    AND ti.item_id = tmlod.item_id
LEFT JOIN tb_mercadolibre_items_publicados tmlip
    ON tmlip.comp_id = tmlod.comp_id
    AND tmlip.mlp_id = tmlod.mlp_id
LEFT JOIN tb_mercadolibre_orders_shipping tmlos
    ON tmlos.comp_id = tmlod.comp_id
    AND tmlos.mlo_id = tmlod.mlo_id
LEFT JOIN tb_item_cost_list ticl
    ON ticl.comp_id = tmlod.comp_id
    AND ticl.item_id = tmlod.item_id
    AND ticl.coslis_id = 1

WHERE ti.item_code = '6935364080433'
  AND tmloh.mlo_cd >= '2025-11-26'
  AND tmloh.mlo_status <> 'cancelled'
ORDER BY tmloh.mlo_cd DESC
LIMIT 3
""")

result = db.execute(query)
rows = result.fetchall()

print("=" * 100)
print("VALORES QUE OBTIENE LA QUERY DE _LOCAL")
print("=" * 100)

for row in rows:
    print(f"\nCódigo: {row.codigo}")
    print(f"Fecha venta: {row.fecha_venta}")
    print(f"Monto unitario: ${row.monto_unitario:,.2f}")
    print(f"Cantidad: {row.cantidad}")
    print(f"Moneda costo: {row.moneda_costo} (2=USD, 1=ARS)")
    print(f"TC al momento: ${row.tc_momento:,.2f}" if row.tc_momento else "TC: None")
    print(f"Costo sin IVA (calculado por query): ${row.costo_sin_iva:,.2f}")
    print(f"Costo envío sin IVA: ${row.costo_envio_sin_iva:,.2f}" if row.costo_envio_sin_iva else "Sin envío")
    print(f"Precio envío gratis: ${row.precio_envio_gratis:,.2f}" if row.precio_envio_gratis else "Sin precio envío gratis")
    print("-" * 100)

    # El costo esperado es $24,780
    if row.costo_sin_iva != 24780:
        print(f"⚠️ COSTO INCORRECTO! Esperado: $24,780.00, Obtenido: ${row.costo_sin_iva:,.2f}")
        print(f"   Diferencia: ${row.costo_sin_iva - 24780:,.2f}")

db.close()
