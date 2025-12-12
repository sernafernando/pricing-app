-- Agregar columna tipo_cambio_usado a calculos_pricing
ALTER TABLE calculos_pricing
ADD COLUMN IF NOT EXISTS tipo_cambio_usado NUMERIC(10, 2);
