-- Crear tabla para historial de costos de items (sincronizada desde ERP)
CREATE TABLE IF NOT EXISTS tb_item_cost_list_history (
    iclh_id BIGINT PRIMARY KEY,
    comp_id INTEGER,
    coslis_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    iclh_lote VARCHAR(50),
    iclh_price NUMERIC(18, 6),
    iclh_price_aw NUMERIC(18, 6),
    curr_id INTEGER,
    iclh_cd TIMESTAMP WITHOUT TIME ZONE,
    user_id_lastUpdate INTEGER
);

-- Índices para optimizar queries de costo histórico
CREATE INDEX IF NOT EXISTS idx_item_cost_history_item_id ON tb_item_cost_list_history(item_id);
CREATE INDEX IF NOT EXISTS idx_item_cost_history_coslis_id ON tb_item_cost_list_history(coslis_id);
CREATE INDEX IF NOT EXISTS idx_item_cost_history_iclh_cd ON tb_item_cost_list_history(iclh_cd);
CREATE INDEX IF NOT EXISTS idx_item_cost_history_item_coslis ON tb_item_cost_list_history(item_id, coslis_id);
CREATE INDEX IF NOT EXISTS idx_item_cost_history_item_date ON tb_item_cost_list_history(item_id, iclh_cd);

-- Comentarios
COMMENT ON TABLE tb_item_cost_list_history IS 'Historial de costos de items sincronizado desde ERP';
COMMENT ON COLUMN tb_item_cost_list_history.iclh_id IS 'ID único del registro';
COMMENT ON COLUMN tb_item_cost_list_history.comp_id IS 'ID de compañía';
COMMENT ON COLUMN tb_item_cost_list_history.coslis_id IS 'ID de la lista de costos (1 = principal)';
COMMENT ON COLUMN tb_item_cost_list_history.item_id IS 'ID del item';
COMMENT ON COLUMN tb_item_cost_list_history.iclh_lote IS 'Número de lote';
COMMENT ON COLUMN tb_item_cost_list_history.iclh_price IS 'Precio/costo sin IVA';
COMMENT ON COLUMN tb_item_cost_list_history.iclh_price_aw IS 'Costo promedio ponderado';
COMMENT ON COLUMN tb_item_cost_list_history.curr_id IS 'ID de moneda (1=ARS, 2=USD)';
COMMENT ON COLUMN tb_item_cost_list_history.iclh_cd IS 'Fecha de creación';
COMMENT ON COLUMN tb_item_cost_list_history.user_id_lastUpdate IS 'Usuario que actualizó';
