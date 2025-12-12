-- Script para crear la tabla tb_supplier

CREATE TABLE IF NOT EXISTS tb_supplier (
    comp_id INTEGER NOT NULL,
    supp_id INTEGER NOT NULL,
    supp_name VARCHAR(255) NOT NULL,
    supp_tax_number VARCHAR(50),
    PRIMARY KEY (comp_id, supp_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_supplier_supp_id ON tb_supplier(supp_id);
CREATE INDEX IF NOT EXISTS idx_tb_supplier_supp_name ON tb_supplier(supp_name);

-- Permisos para el usuario de la aplicación
GRANT SELECT, INSERT, UPDATE, DELETE ON tb_supplier TO pricing_user;
