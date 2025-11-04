-- Tabla para tbMercadoLibre_ordersHeader del ERP
-- Contiene las órdenes de MercadoLibre

CREATE TABLE tb_mercadolibre_orders_header (
    comp_id INT,
    mlo_id BIGINT PRIMARY KEY,
    mluser_id INT,
    cust_id INT,
    mlo_firstjson JSON,
    mlo_lastjson JSON,
    ml_id VARCHAR(50),
    ml_date_created TIMESTAMP,
    ml_date_closed TIMESTAMP,
    ml_last_updated TIMESTAMP,
    mlo_shippingcost DECIMAL(18, 2),
    mlo_transaction_amount DECIMAL(18, 2),
    mlo_cupon_amount DECIMAL(18, 2),
    mlo_overpaid_amount DECIMAL(18, 2),
    mlo_total_paid_amount DECIMAL(18, 2),
    mlo_status VARCHAR(255),
    mlorder_id VARCHAR(50),
    mlo_issaleordergenerated BOOLEAN DEFAULT FALSE,
    mlo_email VARCHAR(255),
    identificationnumber BIGINT,
    identificationtype VARCHAR(255),
    mlo_ispaid BOOLEAN DEFAULT FALSE,
    mlo_isdelivered BOOLEAN DEFAULT FALSE,
    mlo_islabelprinted BOOLEAN DEFAULT FALSE,
    mlo_isqualified BOOLEAN DEFAULT FALSE,
    mlo_issaleorderemmited BOOLEAN DEFAULT FALSE,
    mlo_iscollected BOOLEAN DEFAULT FALSE,
    mlo_iswithfraud BOOLEAN DEFAULT FALSE,
    mluser_identificationtype VARCHAR(255),
    mluser_identificationnumber BIGINT,
    mluser_address VARCHAR(255),
    mluser_state VARCHAR(255),
    mluser_citi VARCHAR(255),
    mluser_zip_code VARCHAR(255),
    mluser_phone VARCHAR(255),
    mluser_email VARCHAR(255),
    mluser_receiver_name VARCHAR(255),
    mluser_receiver_phone VARCHAR(255),
    mluser_alternative_phone VARCHAR(255),
    mlo_isorderreceiptmessage BOOLEAN DEFAULT FALSE,
    mlo_iscancelled BOOLEAN DEFAULT FALSE,
    mlshippingid VARCHAR(50),
    mlpickupid VARCHAR(50),
    mlpickupperson VARCHAR(255),
    mlbra_id INT,
    ml_pack_id VARCHAR(50),
    mls_id INT,
    mluser_first_name VARCHAR(255),
    mluser_last_name VARCHAR(255),
    mlo_ismshops BOOLEAN DEFAULT FALSE,
    mlo_cd TIMESTAMP,
    mlo_me1_deliverystatus VARCHAR(255),
    mlo_me1_deliverytracking VARCHAR(255),
    mlo_mustprintlabel BOOLEAN DEFAULT FALSE,
    mlo_ismshops_invited BOOLEAN DEFAULT FALSE,
    mlo_orderswithdiscountcouponincludeinpricev2 BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para mejorar el rendimiento
CREATE INDEX idx_ml_orders_header_ml_date_created ON tb_mercadolibre_orders_header(ml_date_created);
CREATE INDEX idx_ml_orders_header_ml_id ON tb_mercadolibre_orders_header(ml_id);
CREATE INDEX idx_ml_orders_header_mlorder_id ON tb_mercadolibre_orders_header(mlorder_id);
CREATE INDEX idx_ml_orders_header_cust_id ON tb_mercadolibre_orders_header(cust_id);
CREATE INDEX idx_ml_orders_header_mlo_status ON tb_mercadolibre_orders_header(mlo_status);
CREATE INDEX idx_ml_orders_header_comp_id ON tb_mercadolibre_orders_header(comp_id);

-- Trigger para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_tb_mercadolibre_orders_header_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tb_mercadolibre_orders_header_updated_at
    BEFORE UPDATE ON tb_mercadolibre_orders_header
    FOR EACH ROW
    EXECUTE FUNCTION update_tb_mercadolibre_orders_header_updated_at();

-- Asignar permisos al usuario de la aplicación
ALTER TABLE tb_mercadolibre_orders_header OWNER TO pricing_user;
