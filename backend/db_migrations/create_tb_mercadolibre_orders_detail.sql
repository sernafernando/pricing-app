-- Tabla para tbMercadoLibre_ordersDetail del ERP
-- Contiene el detalle de productos/items de cada orden de MercadoLibre

CREATE TABLE tb_mercadolibre_orders_detail (
    comp_id INT,
    mlo_id BIGINT,
    mlod_id BIGINT PRIMARY KEY,
    mlp_id BIGINT,
    item_id INT,
    mlo_unit_price DECIMAL(18, 4),
    mlo_quantity DECIMAL(18, 4),
    mlo_currency_id VARCHAR(10),
    mlo_cd TIMESTAMP,
    mlo_note TEXT,
    mlo_is4availablestock BOOLEAN DEFAULT FALSE,
    stor_id INT,
    mlo_listing_fee_amount DECIMAL(18, 4),
    mlo_sale_fee_amount DECIMAL(18, 4),
    mlo_title VARCHAR(500),
    mlvariationid VARCHAR(50),
    mlod_lastupdate TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para mejorar el rendimiento
CREATE INDEX idx_ml_orders_detail_mlo_id ON tb_mercadolibre_orders_detail(mlo_id);
CREATE INDEX idx_ml_orders_detail_item_id ON tb_mercadolibre_orders_detail(item_id);
CREATE INDEX idx_ml_orders_detail_mlo_cd ON tb_mercadolibre_orders_detail(mlo_cd);
CREATE INDEX idx_ml_orders_detail_comp_id ON tb_mercadolibre_orders_detail(comp_id);

-- Trigger para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_tb_mercadolibre_orders_detail_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tb_mercadolibre_orders_detail_updated_at
    BEFORE UPDATE ON tb_mercadolibre_orders_detail
    FOR EACH ROW
    EXECUTE FUNCTION update_tb_mercadolibre_orders_detail_updated_at();

-- Asignar permisos al usuario de la aplicación
ALTER TABLE tb_mercadolibre_orders_detail OWNER TO pricing_user;
