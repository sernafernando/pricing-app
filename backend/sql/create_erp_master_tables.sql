-- Script para crear las tablas maestras del ERP que faltan

-- Tabla de Marcas
CREATE TABLE IF NOT EXISTS tb_brand (
    comp_id INTEGER NOT NULL,
    brand_id INTEGER NOT NULL,
    bra_id INTEGER,
    brand_desc VARCHAR(255) NOT NULL,
    PRIMARY KEY (comp_id, brand_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_brand_brand_id ON tb_brand(brand_id);

-- Tabla de Categorías
CREATE TABLE IF NOT EXISTS tb_category (
    comp_id INTEGER NOT NULL,
    cat_id INTEGER NOT NULL,
    cat_desc VARCHAR(255) NOT NULL,
    PRIMARY KEY (comp_id, cat_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_category_cat_id ON tb_category(cat_id);

-- Tabla de Subcategorías
CREATE TABLE IF NOT EXISTS tb_subcategory (
    comp_id INTEGER NOT NULL,
    cat_id INTEGER NOT NULL,
    subcat_id INTEGER NOT NULL,
    subcat_desc VARCHAR(255) NOT NULL,
    PRIMARY KEY (comp_id, cat_id, subcat_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_subcategory_subcat_id ON tb_subcategory(subcat_id);
CREATE INDEX IF NOT EXISTS idx_tb_subcategory_cat_id ON tb_subcategory(cat_id);

-- Tabla de Items (complementaria a productos_erp)
CREATE TABLE IF NOT EXISTS tb_item (
    comp_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    item_code VARCHAR(100) NOT NULL,
    item_desc VARCHAR(500),
    cat_id INTEGER,
    subcat_id INTEGER,
    brand_id INTEGER,
    item_liquidation VARCHAR(50),
    item_cd TIMESTAMP,
    item_lastupdate TIMESTAMP,
    PRIMARY KEY (comp_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_item_item_id ON tb_item(item_id);
CREATE INDEX IF NOT EXISTS idx_tb_item_brand_id ON tb_item(brand_id);
CREATE INDEX IF NOT EXISTS idx_tb_item_cat_id ON tb_item(cat_id);
CREATE INDEX IF NOT EXISTS idx_tb_item_subcat_id ON tb_item(subcat_id);

-- Tabla de Nombres de Impuestos
CREATE TABLE IF NOT EXISTS tb_tax_name (
    comp_id INTEGER NOT NULL,
    tax_id INTEGER NOT NULL,
    tax_desc VARCHAR(255) NOT NULL,
    tax_percentage NUMERIC(10, 2),
    PRIMARY KEY (comp_id, tax_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_tax_name_tax_id ON tb_tax_name(tax_id);

-- Tabla de Impuestos por Item
CREATE TABLE IF NOT EXISTS tb_item_taxes (
    comp_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    tax_id INTEGER NOT NULL,
    tax_class VARCHAR(50),
    PRIMARY KEY (comp_id, item_id, tax_id)
);

CREATE INDEX IF NOT EXISTS idx_tb_item_taxes_item_id ON tb_item_taxes(item_id);
CREATE INDEX IF NOT EXISTS idx_tb_item_taxes_tax_id ON tb_item_taxes(tax_id);

-- Permisos para el usuario de la aplicación
GRANT SELECT, INSERT, UPDATE, DELETE ON tb_brand TO pricing_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tb_category TO pricing_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tb_subcategory TO pricing_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tb_item TO pricing_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tb_tax_name TO pricing_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tb_item_taxes TO pricing_user;
