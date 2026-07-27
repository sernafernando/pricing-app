-- Crear tabla tb_item_cost_list
-- Lista de costos actual de items desde el ERP

CREATE TABLE IF NOT EXISTS tb_item_cost_list (
    comp_id INTEGER NOT NULL,
    coslis_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    coslis_price NUMERIC(18, 6),
    curr_id INTEGER,
    coslis_cd TIMESTAMP,
    PRIMARY KEY (comp_id, coslis_id, item_id)
);

-- Crear índices
CREATE INDEX IF NOT EXISTS idx_tb_item_cost_list_coslis_id ON tb_item_cost_list(coslis_id);
CREATE INDEX IF NOT EXISTS idx_tb_item_cost_list_item_id ON tb_item_cost_list(item_id);

-- Comentarios
COMMENT ON TABLE tb_item_cost_list IS 'Lista de costos actual de items desde ERP (tbItemCostList)';
COMMENT ON COLUMN tb_item_cost_list.comp_id IS 'ID de compañía';
COMMENT ON COLUMN tb_item_cost_list.coslis_id IS 'ID de lista de costos (1 = principal)';
COMMENT ON COLUMN tb_item_cost_list.item_id IS 'ID de item/producto';
COMMENT ON COLUMN tb_item_cost_list.coslis_price IS 'Precio/costo actual';
COMMENT ON COLUMN tb_item_cost_list.curr_id IS 'ID de moneda (1=ARS, 2=USD)';
COMMENT ON COLUMN tb_item_cost_list.coslis_cd IS 'Fecha de creación/actualización';
