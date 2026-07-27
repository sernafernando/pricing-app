-- Tabla para tbItemTransactionDetails del ERP
-- Contiene descripciones y detalles adicionales de cada item transaction

CREATE TABLE tb_item_transaction_details (
    comp_id INT,
    bra_id INT,
    ct_transaction BIGINT,
    it_transaction BIGINT,
    itm_transaction BIGINT PRIMARY KEY,
    itm_desc TEXT,
    itm_desc1 TEXT,
    itm_desc2 TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para mejorar el rendimiento
CREATE INDEX idx_item_transaction_details_it_transaction ON tb_item_transaction_details(it_transaction);
CREATE INDEX idx_item_transaction_details_ct_transaction ON tb_item_transaction_details(ct_transaction);
CREATE INDEX idx_item_transaction_details_comp_bra ON tb_item_transaction_details(comp_id, bra_id);

-- Trigger para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_tb_item_transaction_details_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tb_item_transaction_details_updated_at
    BEFORE UPDATE ON tb_item_transaction_details
    FOR EACH ROW
    EXECUTE FUNCTION update_tb_item_transaction_details_updated_at();

-- Asignar permisos al usuario de la aplicación
ALTER TABLE tb_item_transaction_details OWNER TO pricing_user;
