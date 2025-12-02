-- Agregar nuevos campos para tipos de offset
ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS tipo_offset VARCHAR(20) DEFAULT 'monto_fijo';
-- tipo_offset: 'monto_fijo', 'monto_por_unidad', 'porcentaje_costo'

ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS moneda VARCHAR(3) DEFAULT 'ARS';
-- moneda: 'ARS', 'USD'

ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS tipo_cambio FLOAT;
-- tipo_cambio: para conversión USD -> ARS

ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS porcentaje FLOAT;
-- porcentaje: para offsets tipo porcentaje_costo

-- Comentarios explicativos:
-- tipo_offset = 'monto_fijo': usa campo 'monto' directamente en ARS
-- tipo_offset = 'monto_por_unidad': usa 'monto' * cantidad vendida * tipo_cambio (si USD)
-- tipo_offset = 'porcentaje_costo': usa 'porcentaje' * costo_total
