-- Crear tabla tb_sale_order_header_history
-- Historial de cambios en cabecera de órdenes de venta desde el ERP

CREATE TABLE IF NOT EXISTS tb_sale_order_header_history (
    comp_id INTEGER NOT NULL,
    bra_id INTEGER NOT NULL,
    soh_id BIGINT NOT NULL,
    sohh_id BIGINT NOT NULL,
    sohh_typeofhistory INTEGER,
    soh_cd TIMESTAMP,
    soh_deliverydate TIMESTAMP,
    soh_observation1 TEXT,
    soh_observation2 TEXT,
    soh_observation3 TEXT,
    soh_observation4 TEXT,
    soh_quotation BOOLEAN,
    sm_id INTEGER,
    cust_id INTEGER,
    st_id INTEGER,
    disc_id INTEGER,
    dl_id INTEGER,
    soh_lastupdate TIMESTAMP,
    soh_limitdate TIMESTAMP,
    tt_id INTEGER,
    tt_class VARCHAR(10),
    soh_statusof INTEGER,
    user_id INTEGER,
    soh_isediting BOOLEAN,
    soh_iseditingcd TIMESTAMP,
    df_id INTEGER,
    soh_total NUMERIC(18, 6),
    ssos_id INTEGER,
    soh_exchangetocustomercurrency NUMERIC(18, 6),
    soh_customercurrency INTEGER,
    soh_discount NUMERIC(18, 6),
    soh_packagesqty INTEGER,
    soh_internalannotation TEXT,
    curr_id4exchange INTEGER,
    curr_idexchange NUMERIC(18, 6),
    soh_atotal NUMERIC(18, 6),
    soh_incash NUMERIC(18, 6),
    ct_transaction BIGINT,
    sohh_cd TIMESTAMP,
    sohh_user_id INTEGER,
    soh_mlquestionsandanswers TEXT,
    soh_mlid VARCHAR(100),
    soh_mlguia VARCHAR(100),
    ws_paymentgatewaystatusid INTEGER,
    soh_deliveryaddress TEXT,
    stor_id INTEGER,
    mlo_id BIGINT,
    soh_note4externaluse TEXT,
    sohh_ispackingofpreinvoice BOOLEAN,
    soh_uniqueid INTEGER,
    PRIMARY KEY (comp_id, bra_id, soh_id, sohh_id)
);

-- Crear índices
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_history_soh_id ON tb_sale_order_header_history(soh_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_history_sohh_id ON tb_sale_order_header_history(sohh_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_history_bra_id ON tb_sale_order_header_history(bra_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_history_comp_id ON tb_sale_order_header_history(comp_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_history_cust_id ON tb_sale_order_header_history(cust_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_history_mlo_id ON tb_sale_order_header_history(mlo_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_history_sohh_cd ON tb_sale_order_header_history(sohh_cd);

-- Comentarios
COMMENT ON TABLE tb_sale_order_header_history IS 'Historial de cambios en cabecera de órdenes de venta desde ERP (tbSaleOrderHeaderHistory)';
COMMENT ON COLUMN tb_sale_order_header_history.soh_id IS 'ID de la orden de venta';
COMMENT ON COLUMN tb_sale_order_header_history.sohh_id IS 'ID del registro de historial';
COMMENT ON COLUMN tb_sale_order_header_history.sohh_typeofhistory IS 'Tipo de evento de historial';
COMMENT ON COLUMN tb_sale_order_header_history.sohh_cd IS 'Fecha de creación del registro de historial';
COMMENT ON COLUMN tb_sale_order_header_history.comp_id IS 'ID de compañía';
COMMENT ON COLUMN tb_sale_order_header_history.cust_id IS 'ID de cliente';
COMMENT ON COLUMN tb_sale_order_header_history.mlo_id IS 'ID de orden MercadoLibre (si aplica)';
