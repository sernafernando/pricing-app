-- Tabla para replicar tbCommercialTransactions del ERP
-- Contiene todas las transacciones comerciales (ventas, compras, etc.)

CREATE TABLE IF NOT EXISTS tb_commercial_transactions (
    -- IDs principales
    comp_id INT,
    bra_id INT,
    ct_transaction BIGINT PRIMARY KEY,  -- ID único de la transacción
    ct_pointOfSale INT,
    ct_kindOf VARCHAR(10),  -- Tipo de documento (X, A, B, etc.)
    ct_docNumber VARCHAR(50),

    -- Fechas
    ct_date TIMESTAMP,
    ct_taxDate TIMESTAMP,
    ct_payDate TIMESTAMP,
    ct_deliveryDate TIMESTAMP,
    ct_processingDate TIMESTAMP,
    ct_lastPayDate TIMESTAMP,
    ct_cd TIMESTAMP,  -- Fecha de creación

    -- Relaciones
    supp_id INT,  -- Proveedor
    cust_id INT,  -- Cliente
    cust_id_related INT,
    cust_id_guarantor INT,
    custf_id INT,
    ba_id INT,
    cb_id INT,
    user_id INT,

    -- Montos y totales
    ct_subtotal DECIMAL(18, 2),
    ct_total DECIMAL(18, 2),
    ct_discount DECIMAL(18, 2),
    ct_adjust DECIMAL(18, 2),
    ct_taxes DECIMAL(18, 2),
    ct_ATotal DECIMAL(18, 2),
    ct_ABalance DECIMAL(18, 2),
    ct_AAdjust DECIMAL(18, 2),
    ct_inCash DECIMAL(18, 2),
    ct_optionalValue DECIMAL(18, 2),
    ct_documentTotal DECIMAL(18, 2),

    -- Monedas y tipos de cambio
    curr_id_transaction INT,
    ct_ACurrency INT,
    ct_ACurrencyExchange DECIMAL(18, 10),
    ct_CompanyCurrency INT,
    ct_Branch2CompanyCurrencyExchange DECIMAL(18, 10),
    ct_dfExchange DECIMAL(18, 10),
    curr_id4Exchange INT,
    ct_curr_IdExchange DECIMAL(18, 10),
    curr_id4dfExchange INT,
    ct_dfExchangeOriginal DECIMAL(18, 10),
    ct_curr_IdExchangeOriginal DECIMAL(18, 10),

    -- Referencias contables
    hacc_transaction INT,
    sm_id INT,
    disc_id INT,
    df_id INT,
    dl_id INT,
    st_id INT,
    sd_id INT,
    puco_id INT,

    -- Ubicación
    country_id INT,
    state_id INT,

    -- Estados y flags
    ct_Pending BOOLEAN DEFAULT true,
    ct_isAvailableForImport BOOLEAN DEFAULT false,
    ct_isAvailableForPayment BOOLEAN DEFAULT false,
    ct_isCancelled BOOLEAN DEFAULT false,
    ct_isSelected BOOLEAN DEFAULT false,
    ct_isMigrated BOOLEAN DEFAULT false,
    ct_powerBoardOK BOOLEAN DEFAULT false,
    ct_Fiscal_Check4EmptyNumbers BOOLEAN DEFAULT false,
    ct_DisableExchangeDifferenceInterest BOOLEAN DEFAULT false,

    -- Ventas especiales / ecommerce
    ct_soh_bra_id INT,
    ct_soh_id INT,
    ct_transaction_PackingList VARCHAR(100),
    ws_cust_Id INT,
    ws_internalID VARCHAR(100),
    ws_isLiquidated BOOLEAN DEFAULT false,
    ws_isLiquidatedCD BOOLEAN DEFAULT false,
    ws_is4Liquidation BOOLEAN DEFAULT false,
    ws_LiquidationNumber VARCHAR(100),
    ws_st_id INT,
    ws_dl_id INT,

    -- AFIP / Fiscales
    ct_CAI VARCHAR(100),
    ct_CAIDate TIMESTAMP,
    ct_FEIdNumber VARCHAR(100),

    -- Descuentos detallados
    ct_Discount1 DECIMAL(18, 2) DEFAULT 0,
    ct_Discount2 DECIMAL(18, 2) DEFAULT 0,
    ct_Discount3 DECIMAL(18, 2) DEFAULT 0,
    ct_Discount4 DECIMAL(18, 2) DEFAULT 0,
    ct_discountPlanCoeficient DECIMAL(18, 10) DEFAULT 1,

    -- Paquetes y envíos
    ct_packagesQty INT DEFAULT 0,
    ct_TransactionBarCode VARCHAR(100),

    -- Créditos
    ct_CreditIntPercentage DECIMAL(10, 4) DEFAULT 0,
    ct_CreditIntPlusPercentage DECIMAL(10, 4) DEFAULT 0,
    ctl_daysPastDue INT DEFAULT 0,
    ccp_id INT,

    -- Otros IDs de referencia
    sctt_id INT,
    suppa_id INT,
    pt_id INT,
    fc_id INT,
    pro_id INT,
    supp_id4CreditCardLiquidation INT,
    def_id INT,
    mlo_id INT,
    dc_id INT,

    -- Campos de uso general (tags)
    ct_AllUseTag1 VARCHAR(255),
    ct_AllUseTag2 VARCHAR(255),
    ct_AllUseTag3 VARCHAR(255),
    ct_AllUseTag4 VARCHAR(255),

    -- GUID y documentación
    ct_guid UUID,
    ct_transaction4ThirdSales VARCHAR(100),
    ct_documentNumber VARCHAR(100),
    ct_note TEXT,

    -- Auditoría local
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para optimizar consultas comunes
CREATE INDEX IF NOT EXISTS idx_ct_date ON tb_commercial_transactions(ct_date);
CREATE INDEX IF NOT EXISTS idx_ct_cust_id ON tb_commercial_transactions(cust_id);
CREATE INDEX IF NOT EXISTS idx_ct_kindOf ON tb_commercial_transactions(ct_kindOf);
CREATE INDEX IF NOT EXISTS idx_ct_docNumber ON tb_commercial_transactions(ct_docNumber);
CREATE INDEX IF NOT EXISTS idx_ct_guid ON tb_commercial_transactions(ct_guid);
CREATE INDEX IF NOT EXISTS idx_ct_date_kindof ON tb_commercial_transactions(ct_date, ct_kindOf);

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_tb_commercial_transactions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER trigger_update_tb_commercial_transactions_updated_at
    BEFORE UPDATE ON tb_commercial_transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_tb_commercial_transactions_updated_at();

-- Comentarios sobre campos importantes
COMMENT ON TABLE tb_commercial_transactions IS 'Réplica de tbCommercialTransactions del ERP - Todas las transacciones comerciales';
COMMENT ON COLUMN tb_commercial_transactions.ct_transaction IS 'ID único de la transacción (PK)';
COMMENT ON COLUMN tb_commercial_transactions.ct_kindOf IS 'Tipo de documento: X=Remito, A=Factura A, B=Factura B, etc.';
COMMENT ON COLUMN tb_commercial_transactions.cust_id IS 'ID del cliente';
COMMENT ON COLUMN tb_commercial_transactions.ct_total IS 'Total de la transacción';
COMMENT ON COLUMN tb_commercial_transactions.ct_date IS 'Fecha de la transacción';
