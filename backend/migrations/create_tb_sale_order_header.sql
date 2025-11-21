-- Crear tabla tb_sale_order_header
-- Cabecera de órdenes de venta desde el ERP

CREATE TABLE IF NOT EXISTS tb_sale_order_header (
    soh_id BIGINT PRIMARY KEY,
    comp_id INTEGER,
    bra_id INTEGER,
    soh_cd TIMESTAMP,
    soh_deliveryDate TIMESTAMP,
    soh_observation1 TEXT,
    soh_observation2 TEXT,
    soh_observation3 TEXT,
    soh_observation4 TEXT,
    soh_quotation VARCHAR(100),
    sm_id INTEGER,
    cust_id INTEGER,
    st_id INTEGER,
    disc_id INTEGER,
    dl_id INTEGER,
    cb_id INTEGER,
    soh_lastUpdate TIMESTAMP,
    soh_limitDate TIMESTAMP,
    tt_id INTEGER,
    tt_class VARCHAR(10),
    soh_StatusOf INTEGER,
    user_id INTEGER,
    soh_isEditing BOOLEAN,
    soh_isEditingCd TIMESTAMP,
    df_id INTEGER,
    soh_total NUMERIC(18, 6),
    ssos_id INTEGER,
    soh_ExchangeToCustomerCurrency NUMERIC(18, 6),
    chp_id INTEGER,
    soh_PL_df_Id INTEGER,
    soh_CustomerCurrency INTEGER,
    soh_WithCollection BOOLEAN,
    soh_WithCollectionGUID VARCHAR(100),
    soh_discount NUMERIC(18, 6),
    soh_loan NUMERIC(18, 6),
    soh_packagesQty INTEGER,
    soh_internalAnnotation TEXT,
    curr_id4Exchange INTEGER,
    curr_idExchange INTEGER,
    soh_ATotal NUMERIC(18, 6),
    df_id4PL INTEGER,
    somp_id INTEGER,
    soh_FEIdNumber VARCHAR(100),
    soh_inCash BOOLEAN,
    custf_id INTEGER,
    cust_id_guarantor INTEGER,
    ccp_id INTEGER,
    soh_MLdeliveryLabel VARCHAR(255),
    soh_deliveryAddress TEXT,
    soh_MLQuestionsAndAnswers TEXT,
    aux_3RDSales_lastCTTransaction BIGINT,
    soh_MLId VARCHAR(100),
    soh_MLGUIA VARCHAR(100),
    pro_id INTEGER,
    aux_collectionInterest_lastCTTransaction BIGINT,
    ws_cust_Id INTEGER,
    ws_internalID VARCHAR(100),
    ws_paymentGateWayStatusID VARCHAR(100),
    ws_paymentGateWayReferenceID VARCHAR(100),
    ws_IPFrom VARCHAR(100),
    ws_st_id INTEGER,
    ws_dl_id INTEGER,
    soh_htmlNote TEXT,
    prli_id INTEGER,
    stor_id INTEGER,
    mlo_id BIGINT,
    MLShippingID BIGINT,
    soh_exchange2Currency4Total NUMERIC(18, 6),
    soh_Currency4Total INTEGER,
    soh_uniqueID VARCHAR(100),
    soh_note4ExternalUse TEXT,
    soh_autoprocessLastOrder BOOLEAN,
    dc_id INTEGER,
    soh_isPrintedFromSOPreparation BOOLEAN,
    soh_persistExchange NUMERIC(18, 6),
    ct_transaction_preCollection BIGINT,
    soh_iseMailEnvied BOOLEAN,
    soh_deliveryLabel VARCHAR(255),
    ct_transaction_preInvoice BIGINT
);

-- Crear índices
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_soh_id ON tb_sale_order_header(soh_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_soh_cd ON tb_sale_order_header(soh_cd);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_comp_id ON tb_sale_order_header(comp_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_cust_id ON tb_sale_order_header(cust_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_prli_id ON tb_sale_order_header(prli_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_header_mlo_id ON tb_sale_order_header(mlo_id);

-- Comentarios
COMMENT ON TABLE tb_sale_order_header IS 'Cabecera de órdenes de venta desde ERP (tbSaleOrderHeader)';
COMMENT ON COLUMN tb_sale_order_header.soh_id IS 'ID de la orden de venta';
COMMENT ON COLUMN tb_sale_order_header.comp_id IS 'ID de compañía';
COMMENT ON COLUMN tb_sale_order_header.soh_cd IS 'Fecha de creación de la orden';
COMMENT ON COLUMN tb_sale_order_header.cust_id IS 'ID de cliente';
COMMENT ON COLUMN tb_sale_order_header.prli_id IS 'ID de lista de precios';
COMMENT ON COLUMN tb_sale_order_header.mlo_id IS 'ID de orden MercadoLibre (si aplica)';
COMMENT ON COLUMN tb_sale_order_header.soh_total IS 'Total de la orden';
