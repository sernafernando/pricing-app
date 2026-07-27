-- Tabla para replicar tbItemTransactions del ERP
-- Contiene el detalle de ítems/productos de cada transacción comercial

DROP TABLE IF EXISTS tb_item_transactions CASCADE;

CREATE TABLE tb_item_transactions (
    -- IDs principales
    comp_id INT,
    bra_id INT,
    ct_transaction BIGINT,  -- FK a tb_commercial_transactions
    it_transaction BIGINT PRIMARY KEY,  -- ID único del item en la transacción
    item_id INT,  -- FK a productos_erp

    -- Cantidades y precios básicos
    it_qty DECIMAL(18, 4),
    it_pricewithoothers DECIMAL(18, 4),
    it_price DECIMAL(18, 4),
    curr_id INT,
    it_exchangetobranchcurrency DECIMAL(18, 10),

    -- Precios de costo
    it_priceofcost DECIMAL(18, 4),
    it_priceofcostpp DECIMAL(18, 4),
    it_priceofcostlastpurchase DECIMAL(18, 4),
    it_pricebofcost DECIMAL(18, 4),
    it_pricebofcostpp DECIMAL(18, 4),
    it_pricebofcostlastpurchase DECIMAL(18, 4),

    -- Precios originales
    it_originalprice DECIMAL(18, 4),
    it_originalpricecurrency INT,
    it_exchangetooriginalpricecurrency DECIMAL(18, 10),

    -- Storage y locación
    stor_id INT,
    it_storeprevious INT,
    prli_id INT,
    byor_id INT,

    -- Flags de tipo
    it_isproduction BOOLEAN DEFAULT FALSE,
    it_isassociation BOOLEAN DEFAULT FALSE,
    it_isassociationgroup BOOLEAN DEFAULT FALSE,

    -- Fechas y órden
    it_cd TIMESTAMP,
    it_packinginvoicepend DECIMAL(18, 4),
    it_order INT,
    so_id INT,

    -- Garantías y descuentos
    it_guarantee INT,
    it_itemdiscounttotal DECIMAL(18, 4),
    it_totaldiscounttotal DECIMAL(18, 4),
    it_creditint DECIMAL(18, 4),
    it_creditintplus DECIMAL(18, 4),

    -- Referencias contables
    puco_id INT,
    it_poh_bra_id INT,
    it_poh_id INT,
    it_soh_id INT,
    it_sod_id INT,

    -- RMA (Return Merchandise Authorization)
    rmah_id INT,
    rmad_id INT,
    it_qty_rma DECIMAL(18, 4),
    it_tis_id_aux INT,

    -- Notas
    it_note1 TEXT,
    it_note2 TEXT,

    -- Packing invoice
    it_packinginvoiceselected DECIMAL(18, 4),
    it_cancelled BOOLEAN DEFAULT FALSE,
    it_priceb DECIMAL(18, 4),
    it_ismade BOOLEAN DEFAULT FALSE,

    -- Referencias de origen
    it_item_id_origin INT,
    tmp_tis_id INT,
    it_packinginvoicependoriginal DECIMAL(18, 4),
    it_packinginvoiceselectedguid UUID,
    it_transaction_original BIGINT,
    it_transaction_nostockdiscount BIGINT,

    -- Moneda de ventas
    it_salescurrid4exchangetobranchcurrency INT,

    -- Tags de uso general
    it_allusetag1 VARCHAR(255),
    it_allusetag2 VARCHAR(255),
    it_allusetag3 VARCHAR(255),
    it_allusetag4 VARCHAR(255),

    -- Descuentos detallados
    it_discount1 DECIMAL(18, 4) DEFAULT 0,
    it_discount2 DECIMAL(18, 4) DEFAULT 0,
    it_discount3 DECIMAL(18, 4) DEFAULT 0,
    it_discount4 DECIMAL(18, 4) DEFAULT 0,

    -- Listas de costos
    coslis_id INT,
    coslis_idb INT,
    supp_id INT,
    camp_id INT,

    -- Transacciones relacionadas
    it_transaction_originalew BIGINT,

    -- Flags de transferencia y ajustes
    it_isinternaltransfer BOOLEAN DEFAULT FALSE,
    it_isrmasuppliercreditnote BOOLEAN DEFAULT FALSE,
    it_isfaststockadjustment BOOLEAN DEFAULT FALSE,
    it_isstockadjustment BOOLEAN DEFAULT FALSE,
    it_isstockcontrol BOOLEAN DEFAULT FALSE,

    -- Stock y préstamos
    sdlmt_id INT,
    sreas_id INT,
    it_loannumberofpays INT,
    sitt_id INT,
    it_deliverydate TIMESTAMP,
    itstkpld_id INT,
    it_nostockcheck BOOLEAN DEFAULT FALSE,

    -- Más transacciones relacionadas
    it_transaction_originaldiv BIGINT,

    -- Recargos
    it_surcharge1 DECIMAL(18, 4) DEFAULT 0,
    it_surcharge2 DECIMAL(18, 4) DEFAULT 0,
    it_surcharge3 DECIMAL(18, 4) DEFAULT 0,
    it_surcharge4 DECIMAL(18, 4) DEFAULT 0,

    -- Transferencias entre sucursales
    stor_id_related4branchtransfer INT,
    it_transaction_related4branchtransfer BIGINT,

    -- Purchase order
    it_pod_id INT,
    pubh_id INT,

    -- eCommerce y seguros
    it_ewaddress TEXT,
    it_insurancedays INT,
    insud_id INT,
    insud_certificatenumber VARCHAR(100),

    -- Pricing
    it_priceofprli_id4creditincash DECIMAL(18, 4),

    -- PC Config
    it_ispcconfig BOOLEAN DEFAULT FALSE,
    it_isblocked4delivery BOOLEAN DEFAULT FALSE,
    it_isfrompconfigctrlid INT,
    item_idfrompreinvoice INT,

    -- MercadoLibre costs
    it_mlcost DECIMAL(18, 4),
    it_iscompensed BOOLEAN DEFAULT FALSE,

    -- Web shop pricing
    ws_price DECIMAL(18, 4),
    ws_curr_id INT,
    mlo_id INT,

    -- Delivery y costos adicionales
    it_deliverycharge DECIMAL(18, 4),
    it_mpcost DECIMAL(18, 4),
    it_mecost DECIMAL(18, 4),

    -- Cancelación de packing invoice
    it_packinginvoicependcancell_user_id INT,
    it_packinginvoicependcancell_cd TIMESTAMP,

    -- Emisión y facturación
    it_disableprintinemission BOOLEAN DEFAULT FALSE,
    it_packinginvoiceqtyinvoiced DECIMAL(18, 4),

    -- Cupón web shop
    wscup_id INT,

    -- Branch transfer
    it_isinbranchtransfertotalizerstorage BOOLEAN DEFAULT FALSE,

    -- Descuento de plan
    tis_itemdiscountplan DECIMAL(18, 4),
    it_itemdiscount DECIMAL(18, 4),

    -- Auditoría local
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para optimizar consultas
CREATE INDEX idx_it_ct_transaction ON tb_item_transactions(ct_transaction);
CREATE INDEX idx_it_item_id ON tb_item_transactions(item_id);
CREATE INDEX idx_it_cd ON tb_item_transactions(it_cd);
CREATE INDEX idx_it_item_ct ON tb_item_transactions(item_id, ct_transaction);

-- Foreign keys (opcional, comentadas para no bloquear si no existen las tablas)
-- ALTER TABLE tb_item_transactions
--   ADD CONSTRAINT fk_it_ct_transaction
--   FOREIGN KEY (ct_transaction) REFERENCES tb_commercial_transactions(ct_transaction);

-- ALTER TABLE tb_item_transactions
--   ADD CONSTRAINT fk_it_item_id
--   FOREIGN KEY (item_id) REFERENCES productos_erp(item_id);

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_tb_item_transactions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER trigger_update_tb_item_transactions_updated_at
    BEFORE UPDATE ON tb_item_transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_tb_item_transactions_updated_at();

-- Comentarios
COMMENT ON TABLE tb_item_transactions IS 'Réplica de tbItemTransactions del ERP - Detalle de items por transacción';
COMMENT ON COLUMN tb_item_transactions.it_transaction IS 'ID único del item en la transacción (PK)';
COMMENT ON COLUMN tb_item_transactions.ct_transaction IS 'ID de la transacción comercial (FK)';
COMMENT ON COLUMN tb_item_transactions.item_id IS 'ID del producto (FK)';
COMMENT ON COLUMN tb_item_transactions.it_qty IS 'Cantidad del item';
COMMENT ON COLUMN tb_item_transactions.it_price IS 'Precio del item';

-- Dar permisos al usuario
ALTER TABLE tb_item_transactions OWNER TO pricing_user;
