-- Agregar columna cantidad a calculos_pricing
ALTER TABLE calculos_pricing
ADD COLUMN IF NOT EXISTS cantidad INTEGER DEFAULT 0;

-- Actualizar los registros existentes con cantidad 0
UPDATE calculos_pricing SET cantidad = 0 WHERE cantidad IS NULL;
