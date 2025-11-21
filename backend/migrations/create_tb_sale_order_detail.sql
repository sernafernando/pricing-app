-- Crear tabla tb_sale_order_detail
-- Detalle de órdenes de venta desde el ERP (líneas/items)

CREATE TABLE IF NOT EXISTS tb_sale_order_detail (
    comp_id INTEGER NOT NULL,
    bra_id INTEGER NOT NULL,
    soh_id BIGINT NOT NULL,
    sod_id BIGINT NOT NULL,
    sod_priority INTEGER,
    item_id INTEGER,
    sod_detail TEXT,
    curr_id INTEGER,
    sod_initQty NUMERIC(18, 6),
    sod_qty NUMERIC(18, 6),
    prli_id INTEGER,
    sod_price NUMERIC(18, 6),
    stor_id INTEGER,
    sod_lastUpdate TIMESTAMP,
    sod_isEditing BOOLEAN,
    sod_insertDate TIMESTAMP,
    user_id INTEGER,
    sod_quotation VARCHAR(100),
    sod_isCredit BOOLEAN,
    sod_cost NUMERIC(18, 6),
    sod_costTax NUMERIC(18, 6),
    rmah_id INTEGER,
    rmad_id INTEGER,
    sod_note1 TEXT,
    sod_note2 TEXT,
    sod_itemDiscount NUMERIC(18, 6),
    sod_tis_id_origin BIGINT,
    sod_item_id_origin INTEGER,
    sod_isParentAssociate BOOLEAN,
    is_id INTEGER,
    it_transaction BIGINT,
    sod_isMade BOOLEAN,
    sod_expirationDate TIMESTAMP,
    acc_count_id INTEGER,
    sod_packagesQty INTEGER,
    item_id_EW INTEGER,
    tis_idOfThisEW BIGINT,
    camp_id INTEGER,
    sdlmt_id INTEGER,
    sreas_id INTEGER,
    sod_loanNumberOfPays INTEGER,
    sod_loanDateOfFirstPay TIMESTAMP,
    sod_loanDayOfMonthOfNextPays INTEGER,
    sod_itemDeliveryDate TIMESTAMP,
    sod_idOfThisEW BIGINT,
    sod_isFromPCConfigCTRLId INTEGER,
    sod_EWAddress TEXT,
    sod_PCCOnfigIsTransfered2Branch BOOLEAN,
    sod_MLCost NUMERIC(18, 6),
    sod_itemAssociationCoeficient NUMERIC(18, 6),
    ws_price NUMERIC(18, 6),
    ws_curr_Id INTEGER,
    sops_id BIGINT,
    mlo_id BIGINT,
    sops_supp_id INTEGER,
    sops_bra_id INTEGER,
    sops_date TIMESTAMP,
    sod_MECost NUMERIC(18, 6),
    sod_MPCost NUMERIC(18, 6),
    sod_isDivided BOOLEAN,
    sod_isDivided_Date TIMESTAMP,
    user_id_division INTEGER,
    sodi_id BIGINT,
    sod_isDivided_costCoeficient NUMERIC(18, 6),
    sod_DeliveryCharge NUMERIC(18, 6),
    sod_itemDesc TEXT,
    sops_poh_bra_id INTEGER,
    sops_poh_id BIGINT,
    sops_note TEXT,
    sops_user_id INTEGER,
    sops_lastUpdate TIMESTAMP,
    ct_transaction_SelectFromPacking BIGINT,
    sodt_qty NUMERIC(18, 6),
    sod_disablePrintInEmmition BOOLEAN,
    sod_discountByItem NUMERIC(18, 6),
    sod_discountByTotal NUMERIC(18, 6),
    sod_creditInt NUMERIC(18, 6),
    sod_creditIntPlus NUMERIC(18, 6),
    sod_priceNeto NUMERIC(18, 6),
    sod_comboCoeficient NUMERIC(18, 6),
    sod_montlyPaymentFrom NUMERIC(18, 6),
    sod_montlyPaymentTo NUMERIC(18, 6),
    wscup_id INTEGER,
    sod_canDeleteCOMBOInSO BOOLEAN,
    sod_exclude4AvailableStock BOOLEAN,
    sod_discountPlan NUMERIC(18, 6),
    tax_id4IVA INTEGER,
    sod_pending4pod_IdRelation BIGINT,
    sod_MercadoLibre_MustUpdateStock BOOLEAN,
    sod_auxTMPValue NUMERIC(18, 6),
    sod_itemDiscount2 NUMERIC(18, 6),
    PRIMARY KEY (comp_id, bra_id, soh_id, sod_id)
);

-- Crear índices
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_soh_id ON tb_sale_order_detail(soh_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_sod_id ON tb_sale_order_detail(sod_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_bra_id ON tb_sale_order_detail(bra_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_comp_id ON tb_sale_order_detail(comp_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_item_id ON tb_sale_order_detail(item_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_prli_id ON tb_sale_order_detail(prli_id);
CREATE INDEX IF NOT EXISTS idx_tb_sale_order_detail_mlo_id ON tb_sale_order_detail(mlo_id);

-- Comentarios
COMMENT ON TABLE tb_sale_order_detail IS 'Detalle de órdenes de venta desde ERP (tbSaleOrderDetail)';
COMMENT ON COLUMN tb_sale_order_detail.soh_id IS 'ID de la orden de venta (header)';
COMMENT ON COLUMN tb_sale_order_detail.sod_id IS 'ID de la línea de detalle';
COMMENT ON COLUMN tb_sale_order_detail.item_id IS 'ID del item/producto';
COMMENT ON COLUMN tb_sale_order_detail.prli_id IS 'ID de lista de precios';
COMMENT ON COLUMN tb_sale_order_detail.mlo_id IS 'ID de orden MercadoLibre (si aplica)';
COMMENT ON COLUMN tb_sale_order_detail.sod_qty IS 'Cantidad vendida';
COMMENT ON COLUMN tb_sale_order_detail.sod_price IS 'Precio unitario';
