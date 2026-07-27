-- Agregar campos de configuración individual para productos
-- Permite que cada producto tenga su propia configuración de recálculo de cuotas y markup adicional

ALTER TABLE productos_pricing
ADD COLUMN IF NOT EXISTS recalcular_cuotas_auto BOOLEAN DEFAULT NULL,
ADD COLUMN IF NOT EXISTS markup_adicional_cuotas_custom DECIMAL(5,2) DEFAULT NULL;

COMMENT ON COLUMN productos_pricing.recalcular_cuotas_auto IS
'Configuración individual de recálculo automático de cuotas. NULL = usar global, TRUE = siempre recalcular, FALSE = nunca recalcular';

COMMENT ON COLUMN productos_pricing.markup_adicional_cuotas_custom IS
'Markup adicional personalizado para cuotas de este producto. NULL = usar global, número = valor personalizado';
