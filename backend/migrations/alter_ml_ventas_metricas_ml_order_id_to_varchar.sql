-- Migración: Cambiar ml_order_id de BIGINT a VARCHAR(50)
-- Motivo: ml_order_id puede contener caracteres no numéricos
-- Fecha: 2025-11-21

-- Cambiar tipo de columna
ALTER TABLE ml_ventas_metricas
ALTER COLUMN ml_order_id TYPE VARCHAR(50) USING ml_order_id::VARCHAR(50);

-- Comentario
COMMENT ON COLUMN ml_ventas_metricas.ml_order_id IS 'ID de la orden en ml_orders_header (puede contener caracteres)';
