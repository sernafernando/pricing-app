-- Agregar campo para preservar porcentaje de markup web en cambios masivos
ALTER TABLE productos_pricing
ADD COLUMN IF NOT EXISTS preservar_porcentaje_web BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN productos_pricing.preservar_porcentaje_web IS 'Si TRUE, el porcentaje de markup web no se modifica en cambios masivos';
