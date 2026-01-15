-- Verificar si estas operaciones tienen Sale Order y qué prli_id tienen
SELECT 
    tmloh.ml_id,
    tmloh.mlo_id,
    tsoh.sales_order_id,
    tsoh.prli_id as sale_order_prli_id,
    tsoh.sales_date
FROM tb_mercadolibre_orders_header tmloh
LEFT JOIN tb_sale_order_header tsoh
    ON tsoh.comp_id = tmloh.comp_id
    AND tsoh.mlo_id = tmloh.mlo_id
WHERE tmloh.ml_id IN ('2000014725630648', '2000014724988736');
