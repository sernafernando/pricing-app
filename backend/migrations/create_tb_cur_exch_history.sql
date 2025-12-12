-- Crear tabla tb_cur_exch_history
-- Historial de tipos de cambio entre monedas desde el ERP

CREATE TABLE IF NOT EXISTS tb_cur_exch_history (
    ceh_id BIGINT PRIMARY KEY,
    comp_id INTEGER,
    curr_id_1 INTEGER,
    curr_id_2 INTEGER,
    ceh_cd TIMESTAMP,
    ceh_exchange NUMERIC(18, 6)
);

-- Crear índices
CREATE INDEX IF NOT EXISTS idx_tb_cur_exch_history_ceh_cd ON tb_cur_exch_history(ceh_cd);
CREATE INDEX IF NOT EXISTS idx_tb_cur_exch_history_ceh_id ON tb_cur_exch_history(ceh_id);

-- Comentarios
COMMENT ON TABLE tb_cur_exch_history IS 'Historial de tipos de cambio entre monedas desde ERP (tbCurExchHistory)';
COMMENT ON COLUMN tb_cur_exch_history.ceh_id IS 'ID del registro de tipo de cambio';
COMMENT ON COLUMN tb_cur_exch_history.comp_id IS 'ID de compañía';
COMMENT ON COLUMN tb_cur_exch_history.curr_id_1 IS 'Moneda origen (ej: 2=USD)';
COMMENT ON COLUMN tb_cur_exch_history.curr_id_2 IS 'Moneda destino (ej: 1=ARS)';
COMMENT ON COLUMN tb_cur_exch_history.ceh_cd IS 'Fecha del tipo de cambio';
COMMENT ON COLUMN tb_cur_exch_history.ceh_exchange IS 'Tipo de cambio (venta)';
