-- Script para migrar las tablas ERP al esquema correcto

-- 1. tb_brand: reemplazar brand_code por bra_id
ALTER TABLE tb_brand DROP COLUMN IF EXISTS brand_code;
ALTER TABLE tb_brand ADD COLUMN IF NOT EXISTS bra_id INTEGER;

-- 2. Verificar que las demás tablas tengan las columnas correctas
-- (el script create_erp_master_tables.sql ya tiene la estructura correcta)

-- Si las tablas ya existen con columnas incorrectas, las dejamos
-- para que el script create_erp_master_tables.sql las actualice
