-- Script para migrar las tablas ERP al esquema correcto

-- 1. tb_brand: reemplazar brand_code por bra_id
ALTER TABLE tb_brand DROP COLUMN IF EXISTS brand_code;
ALTER TABLE tb_brand ADD COLUMN IF NOT EXISTS bra_id INTEGER;

-- 2. tb_tax_name: agregar tax_percentage y eliminar tax_name
ALTER TABLE tb_tax_name ADD COLUMN IF NOT EXISTS tax_percentage NUMERIC(10, 2);
ALTER TABLE tb_tax_name DROP COLUMN IF EXISTS tax_name;

-- 3. tb_item: agregar item_cd y "item_LastUpdate" si no existen
ALTER TABLE tb_item ADD COLUMN IF NOT EXISTS item_cd TIMESTAMP;
ALTER TABLE tb_item ADD COLUMN IF NOT EXISTS "item_LastUpdate" TIMESTAMP;

-- 4. Verificar que las demás tablas tengan las columnas correctas
-- (el script create_erp_master_tables.sql ya tiene la estructura correcta)
