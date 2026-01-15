-- Debug: Ver por qué las operaciones de 12 cuotas se muestran como "Clásica"
-- Ejecutar: psql -U postgres -d pricing -f debug_pricelist_cuotas.sql
-- 
-- Buscar operaciones específicas que tienen el problema

WITH sales_data AS (
    SELECT DISTINCT ON (tmlod.mlo_id)
        tmlod.mlo_id as id_operacion,
        tmloh.ml_id,
        tmloh.mlo_cd as fecha_venta,
        ti.item_code as codigo,
        
        -- Price lists para debug
        tsoh.prli_id as sale_order_prli_id,
        tmlip.prli_id as ml_prli_id_normal,
        tmlip.prli_id4mercadoshop as ml_prli_id_mercadoshop,
        tmloh.mlo_ismshops,
        
        -- Pricelist ACTUAL usado (la lógica nueva del endpoint)
        CASE
            WHEN COALESCE(
                CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END
            ) IN (13, 14, 17, 23) THEN 
                CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END
            ELSE
                COALESCE(
                    tsoh.prli_id,
                    CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END
                )
        END as pricelist_id_final

    FROM tb_mercadolibre_orders_detail tmlod

    LEFT JOIN tb_mercadolibre_orders_header tmloh
        ON tmloh.comp_id = tmlod.comp_id
        AND tmloh.mlo_id = tmlod.mlo_id

    LEFT JOIN tb_sale_order_header tsoh
        ON tsoh.comp_id = tmlod.comp_id
        AND tsoh.mlo_id = tmlod.mlo_id

    LEFT JOIN tb_item ti
        ON ti.comp_id = tmlod.comp_id
        AND ti.item_id = tmlod.item_id

    LEFT JOIN tb_mercadolibre_items_publicados tmlip
        ON tmlip.comp_id = tmlod.comp_id
        AND tmlip.mlp_id = tmlod.mlp_id

    WHERE tmloh.comp_id = 1
      AND tmloh.ml_id IN ('2000014725630648', '2000014724988736')
    
    ORDER BY tmlod.mlo_id, tmlod.mlo_line DESC
)
SELECT 
    ml_id,
    codigo,
    fecha_venta,
    sale_order_prli_id,
    ml_prli_id_normal,
    ml_prli_id_mercadoshop,
    mlo_ismshops,
    pricelist_id_final,
    CASE pricelist_id_final
        WHEN 4 THEN 'Clásica'
        WHEN 12 THEN 'Clásica'
        WHEN 13 THEN '9 Cuotas'
        WHEN 14 THEN '6 Cuotas'
        WHEN 17 THEN '3 Cuotas'
        WHEN 23 THEN '12 Cuotas'
        ELSE 'Lista ' || pricelist_id_final::text
    END as tipo_publicacion
FROM sales_data;
