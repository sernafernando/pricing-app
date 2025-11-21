-- Crear tabla tb_sale_order_detail_history
-- Historial de cambios en detalle de órdenes de venta desde el ERP (líneas/items)

CREATE TABLE IF NOT EXISTS tb_sale_order_detail_history (
    comp_id INTEGER NOT NULL,
    bra_id INTEGER NOT NULL,
    soh_id BIGINT NOT NULL,
    sohh_id BIGINT NOT NULL,
    sod_id BIGINT NOT NULL,
    sod_priority INTEGER,
    item_id INTEGER,
    sod_itemdesc TEXT,
    sod_detail TEXT,
    curr_id INTEGER,
    sod_initqty NUMERIC(18, 6),
    sod_qty NUMERIC(18, 6),
    prli_id INTEGER,
    sod_price NUMERIC(18, 6),
    stor_id INTEGER,
    sod_lastupdate TIMESTAMP,
    sod_isediting BOOLEAN,
    sod_insertdate TIMESTAMP,
    user_id INTEGER,
    sod_quotation VARCHAR(100),
    sod_iscredit BOOLEAN,
    sod_cost NUMERIC(18, 6),
    sod_costtax NUMERIC(18, 6),
    rmah_id INTEGER,
    rmad_id INTEGER,
    sod_note1 TEXT,
    sod_note2 TEXT,
    sod_itemdiscount NUMERIC(18, 6),
    sod_tis_id_origin BIGINT,
    sod_item_id_origin INTEGER,
    sod_isparentassociate BOOLEAN,
    is_id INTEGER,
    it_transaction BIGINT,
    sod_ismade BOOLEAN,
    sod_expirationdate TIMESTAMP,
    acc_count_id INTEGER,
    sod_packagesqty INTEGER,
    item_id_ew INTEGER,
    tis_idofthisew BIGINT,
    camp_id INTEGER,
    sod_ewaddress TEXT,
    sod_mlcost NUMERIC(18, 6),
    sdlmt_id INTEGER,
    sops_id BIGINT,
    sops_supp_id INTEGER,
    sops_bra_id INTEGER,
    sops_date TIMESTAMP,
    mlo_id BIGINT,
    sod_mecost NUMERIC(18, 6),
    sod_mpcost NUMERIC(18, 6),
    sod_isdivided BOOLEAN,
    sod_isdivided_date TIMESTAMP,
    user_id_division INTEGER,
    sodi_id BIGINT,
    sod_isdivided_costcoeficient NUMERIC(18, 6),
    sops_poh_bra_id INTEGER,
    sops_poh_id BIGINT,
    sops_note TEXT,
    sops_user_id INTEGER,
    sops_lastupdate TIMESTAMP,
    PRIMARY KEY (comp_id, bra_id, soh_id, sohh_id, sod_id)
);

-- Crear índices
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_soh_id ON tb_sale_order_detail_history(soh_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_sohh_id ON tb_sale_order_detail_history(sohh_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_sod_id ON tb_sale_order_detail_history(sod_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_bra_id ON tb_sale_order_detail_history(bra_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_comp_id ON tb_sale_order_detail_history(comp_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_item_id ON tb_sale_order_detail_history(item_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_prli_id ON tb_sale_order_detail_history(prli_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_history_mlo_id ON tb_sale_order_detail_history(mlo_id);

-- Comentarios
COMMENT ON TABLE tb_sale_order_detail_history IS 'Historial de cambios en detalle de órdenes de venta desde ERP (tbSaleOrderDetailHistory)';
COMMENT ON COLUMN tb_sale_order_detail_history.soh_id IS 'ID de la orden de venta (header)';
COMMENT ON COLUMN tb_sale_order_detail_history.sohh_id IS 'ID del registro de historial del header';
COMMENT ON COLUMN tb_sale_order_detail_history.sod_id IS 'ID de la línea de detalle';
COMMENT ON COLUMN tb_sale_order_detail_history.item_id IS 'ID del item/producto';
COMMENT ON COLUMN tb_sale_order_detail_history.prli_id IS 'ID de lista de precios';
COMMENT ON COLUMN tb_sale_order_detail_history.mlo_id IS 'ID de orden MercadoLibre (si aplica)';
COMMENT ON COLUMN tb_sale_order_detail_history.sod_qty IS 'Cantidad vendida';
COMMENT ON COLUMN tb_sale_order_detail_history.sod_price IS 'Precio unitario';
