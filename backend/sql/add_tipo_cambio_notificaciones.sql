-- Agregar campos de tipo de cambio a la tabla notificaciones
-- Para trackear qué TC se usó al calcular los costos

ALTER TABLE notificaciones
ADD COLUMN IF NOT EXISTS tipo_cambio_operacion NUMERIC(12, 4),
ADD COLUMN IF NOT EXISTS tipo_cambio_actual NUMERIC(12, 4);

COMMENT ON COLUMN notificaciones.tipo_cambio_operacion IS 'Tipo de cambio usado para calcular costo_operacion (al momento de la venta)';
COMMENT ON COLUMN notificaciones.tipo_cambio_actual IS 'Tipo de cambio usado para calcular costo_actual (al momento de crear la notificación)';
