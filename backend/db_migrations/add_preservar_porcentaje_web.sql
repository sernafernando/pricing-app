-- Agregar campo para preservar porcentaje de markup web en cambios masivos
ALTER TABLE productos_pricing
ADD COLUMN IF NOT EXISTS preservar_porcentaje_web BOOLEAN DEFAULT FALSE;

-- Actualizar registros existentes que tienen NULL a FALSE
UPDATE productos_pricing
SET preservar_porcentaje_web = FALSE
WHERE preservar_porcentaje_web IS NULL;

-- Hacer el campo NOT NULL para futuros registros
ALTER TABLE productos_pricing
ALTER COLUMN preservar_porcentaje_web SET NOT NULL;

COMMENT ON COLUMN productos_pricing.preservar_porcentaje_web IS 'Si TRUE, el porcentaje de markup web no se modifica en cambios masivos';
