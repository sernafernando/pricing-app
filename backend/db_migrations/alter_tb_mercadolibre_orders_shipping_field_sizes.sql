-- Aumentar tamaño de campos que pueden contener valores largos
-- Basado en error: mlcity_id recibe direcciones completas

ALTER TABLE tb_mercadolibre_orders_shipping
    ALTER COLUMN mlcity_id TYPE TEXT,
    ALTER COLUMN mlreceiver_address TYPE TEXT,
    ALTER COLUMN mlcomment TYPE TEXT,
    ALTER COLUMN mlstreet_name TYPE VARCHAR(500),
    ALTER COLUMN mlcity_name TYPE VARCHAR(500),
    ALTER COLUMN mlstate_name TYPE VARCHAR(500),
    ALTER COLUMN mlreceiver_name TYPE VARCHAR(500),
    ALTER COLUMN ml_tracking_method TYPE VARCHAR(255);
