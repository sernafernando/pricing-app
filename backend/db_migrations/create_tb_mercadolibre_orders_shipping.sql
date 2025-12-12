-- Tabla para tbMercadoLibre_ordersShipping del ERP
-- Contiene información de envío de cada orden de MercadoLibre

CREATE TABLE tb_mercadolibre_orders_shipping (
    comp_id INT,
    mlm_id BIGINT PRIMARY KEY,
    mlo_id BIGINT,
    mlshippingid VARCHAR(50),
    mlshipment_type VARCHAR(50),
    mlshipping_mode VARCHAR(50),
    mlm_json TEXT,
    mlcost DECIMAL(18, 4),
    mllogistic_type VARCHAR(50),
    mlstatus VARCHAR(50),
    mlestimated_handling_limit TIMESTAMP,
    mlestimated_delivery_final TIMESTAMP,
    mlestimated_delivery_limit TIMESTAMP,
    mlreceiver_address VARCHAR(500),
    mlstreet_name VARCHAR(255),
    mlstreet_number VARCHAR(50),
    mlcomment TEXT,
    mlzip_code VARCHAR(50),
    mlcity_name VARCHAR(255),
    mlstate_name VARCHAR(255),
    mlcity_id VARCHAR(255),
    mlstate_id VARCHAR(50),
    mlconuntry_name VARCHAR(100),
    mlreceiver_name VARCHAR(255),
    mlreceiver_phone VARCHAR(50),
    mllist_cost DECIMAL(18, 4),
    mldelivery_type VARCHAR(50),
    mlshipping_method_id VARCHAR(50),
    mltracking_number VARCHAR(100),
    mlshippmentcost4buyer DECIMAL(18, 4),
    mlshippmentcost4seller DECIMAL(18, 4),
    mlshippmentgrossamount DECIMAL(18, 4),
    mlfulfilled VARCHAR(50),
    mlcross_docking VARCHAR(50),
    mlself_service VARCHAR(50),
    ml_logistic_type VARCHAR(50),
    ml_tracking_method VARCHAR(50),
    ml_date_first_printed TIMESTAMP,
    ml_base_cost DECIMAL(18, 4),
    ml_estimated_delivery_time_date TIMESTAMP,
    ml_estimated_delivery_time_shipping INT,
    mlos_lastupdate TIMESTAMP,
    mlshippmentcolectadaytime TIMESTAMP,
    mlturbo VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para mejorar el rendimiento
CREATE INDEX idx_ml_orders_shipping_mlo_id ON tb_mercadolibre_orders_shipping(mlo_id);
CREATE INDEX idx_ml_orders_shipping_mlshippingid ON tb_mercadolibre_orders_shipping(mlshippingid);
CREATE INDEX idx_ml_orders_shipping_mlstatus ON tb_mercadolibre_orders_shipping(mlstatus);
CREATE INDEX idx_ml_orders_shipping_mlestimated_handling_limit ON tb_mercadolibre_orders_shipping(mlestimated_handling_limit);
CREATE INDEX idx_ml_orders_shipping_comp_id ON tb_mercadolibre_orders_shipping(comp_id);

-- Trigger para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_tb_mercadolibre_orders_shipping_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tb_mercadolibre_orders_shipping_updated_at
    BEFORE UPDATE ON tb_mercadolibre_orders_shipping
    FOR EACH ROW
    EXECUTE FUNCTION update_tb_mercadolibre_orders_shipping_updated_at();

-- Asignar permisos al usuario de la aplicación
ALTER TABLE tb_mercadolibre_orders_shipping OWNER TO pricing_user;
