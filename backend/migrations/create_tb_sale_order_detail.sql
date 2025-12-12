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
    sdlmt_id INTEGER,
    sreas_id INTEGER,
    sod_loannumberofpays INTEGER,
    sod_loandateoffirstpay TIMESTAMP,
    sod_loandayofmonthofnextpays INTEGER,
    sod_itemdeliverydate TIMESTAMP,
    sod_idofthisew BIGINT,
    sod_isfrompconfigctrlid INTEGER,
    sod_ewaddress TEXT,
    sod_pcconfgistransfered2branch BOOLEAN,
    sod_mlcost NUMERIC(18, 6),
    sod_itemassociationcoeficient NUMERIC(18, 6),
    ws_price NUMERIC(18, 6),
    ws_curr_id INTEGER,
    sops_id BIGINT,
    mlo_id BIGINT,
    sops_supp_id INTEGER,
    sops_bra_id INTEGER,
    sops_date TIMESTAMP,
    sod_mecost NUMERIC(18, 6),
    sod_mpcost NUMERIC(18, 6),
    sod_isdivided BOOLEAN,
    sod_isdivided_date TIMESTAMP,
    user_id_division INTEGER,
    sodi_id BIGINT,
    sod_isdivided_costcoeficient NUMERIC(18, 6),
    sod_deliverycharge BOOLEAN,
    sod_itemdesc TEXT,
    sops_poh_bra_id INTEGER,
    sops_poh_id BIGINT,
    sops_note TEXT,
    sops_user_id INTEGER,
    sops_lastupdate TIMESTAMP,
    ct_transaction_selectfrompacking BIGINT,
    sodt_qty NUMERIC(18, 6),
    sod_disableprintinemmition BOOLEAN,
    sod_discountbyitem NUMERIC(18, 6),
    sod_discountbytotal NUMERIC(18, 6),
    sod_creditint NUMERIC(18, 6),
    sod_creditintplus NUMERIC(18, 6),
    sod_priceneto NUMERIC(18, 6),
    sod_combocoeficient NUMERIC(18, 6),
    sod_montlypaymentfrom NUMERIC(18, 6),
    sod_montlypaymentto NUMERIC(18, 6),
    wscup_id INTEGER,
    sod_candeletecomboinso BOOLEAN,
    sod_exclude4availablestock BOOLEAN,
    sod_discountplan NUMERIC(18, 6),
    tax_id4iva INTEGER,
    sod_pending4pod_idrelation BOOLEAN,
    sod_mercadolibre_mustupdatestock BOOLEAN,
    sod_auxtmpvalue NUMERIC(18, 6),
    sod_itemdiscount2 NUMERIC(18, 6),
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
