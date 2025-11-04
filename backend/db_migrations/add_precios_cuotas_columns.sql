-- Agregar columnas para almacenar precios con cuotas
-- Estas columnas almacenarán los precios calculados para 3, 6, 9 y 12 cuotas

ALTER TABLE productos_pricing
    ADD COLUMN IF NOT EXISTS precio_3_cuotas NUMERIC(15, 2) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS precio_6_cuotas NUMERIC(15, 2) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS precio_9_cuotas NUMERIC(15, 2) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS precio_12_cuotas NUMERIC(15, 2) DEFAULT NULL;

-- Crear índices para mejorar el rendimiento en consultas
CREATE INDEX IF NOT EXISTS idx_productos_pricing_precio_3_cuotas ON productos_pricing(precio_3_cuotas);
CREATE INDEX IF NOT EXISTS idx_productos_pricing_precio_6_cuotas ON productos_pricing(precio_6_cuotas);

COMMENT ON COLUMN productos_pricing.precio_3_cuotas IS 'Precio calculado con el adicional de cuotas para 3 cuotas';
COMMENT ON COLUMN productos_pricing.precio_6_cuotas IS 'Precio calculado con el adicional de cuotas para 6 cuotas';
COMMENT ON COLUMN productos_pricing.precio_9_cuotas IS 'Precio calculado con el adicional de cuotas para 9 cuotas';
COMMENT ON COLUMN productos_pricing.precio_12_cuotas IS 'Precio calculado con el adicional de cuotas para 12 cuotas';
