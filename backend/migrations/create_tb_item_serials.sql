-- Crear tabla tb_item_serials
CREATE TABLE IF NOT EXISTS tb_item_serials (
    comp_id INTEGER NOT NULL,
    is_id BIGINT NOT NULL,
    bra_id INTEGER NOT NULL,
    ct_transaction BIGINT,
    it_transaction BIGINT,
    item_id INTEGER,
    stor_id INTEGER,
    is_serial VARCHAR(100),
    is_cd TIMESTAMP,
    is_available BOOLEAN,
    is_guid VARCHAR(100),
    is_IsOwnGeneration BOOLEAN,
    is_checked BOOLEAN,
    is_printed BOOLEAN,
    PRIMARY KEY (comp_id, is_id, bra_id)
);

-- Índices para mejorar performance
CREATE INDEX IF NOT EXISTS idx_item_serials_serial ON tb_item_serials(is_serial);
CREATE INDEX IF NOT EXISTS idx_item_serials_cd ON tb_item_serials(is_cd);
CREATE INDEX IF NOT EXISTS idx_item_serials_item_id ON tb_item_serials(item_id);
CREATE INDEX IF NOT EXISTS idx_item_serials_it_transaction ON tb_item_serials(it_transaction);
CREATE INDEX IF NOT EXISTS idx_item_serials_ct_transaction ON tb_item_serials(ct_transaction);

COMMENT ON TABLE tb_item_serials IS 'Números de serie de items del ERP';
COMMENT ON COLUMN tb_item_serials.is_serial IS 'Número de serie del item';
COMMENT ON COLUMN tb_item_serials.is_cd IS 'Fecha de creación del serial';
COMMENT ON COLUMN tb_item_serials.is_available IS 'Serial disponible para uso';
