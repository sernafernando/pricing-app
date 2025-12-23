-- Agregar campos de override de dirección de envío
-- Estos campos tienen prioridad SOLO para visualización
-- Las etiquetas ZPL deben usar los datos reales (TN/ERP)

ALTER TABLE tb_sale_order_header
ADD COLUMN IF NOT EXISTS override_shipping_address TEXT,
ADD COLUMN IF NOT EXISTS override_shipping_city VARCHAR(255),
ADD COLUMN IF NOT EXISTS override_shipping_province VARCHAR(255),
ADD COLUMN IF NOT EXISTS override_shipping_zipcode VARCHAR(20),
ADD COLUMN IF NOT EXISTS override_shipping_phone VARCHAR(100),
ADD COLUMN IF NOT EXISTS override_shipping_recipient VARCHAR(255),
ADD COLUMN IF NOT EXISTS override_notes TEXT,
ADD COLUMN IF NOT EXISTS override_modified_by INTEGER,
ADD COLUMN IF NOT EXISTS override_modified_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN tb_sale_order_header.override_shipping_address IS 'Dirección de envío sobrescrita manualmente (prioridad para visualización)';
COMMENT ON COLUMN tb_sale_order_header.override_modified_by IS 'Usuario que modificó el override (tb_user.user_id)';
COMMENT ON COLUMN tb_sale_order_header.override_modified_at IS 'Fecha de modificación del override';
