-- Tabla para productos de Tienda Nube
CREATE TABLE IF NOT EXISTS tienda_nube_productos (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL,
    product_name VARCHAR(500),
    variant_id INTEGER NOT NULL,
    variant_sku VARCHAR(100),
    price NUMERIC(18, 2),
    compare_at_price NUMERIC(18, 2),
    promotional_price NUMERIC(18, 2),
    item_id INTEGER,  -- Relación con productos_erp
    activo BOOLEAN DEFAULT TRUE,
    fecha_sync TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    fecha_actualizacion TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Índice único: un producto + variante solo puede aparecer una vez
    UNIQUE(product_id, variant_id)
);

-- Índices para mejorar el rendimiento
CREATE INDEX IF NOT EXISTS idx_tn_productos_product_id ON tienda_nube_productos(product_id);
CREATE INDEX IF NOT EXISTS idx_tn_productos_variant_id ON tienda_nube_productos(variant_id);
CREATE INDEX IF NOT EXISTS idx_tn_productos_variant_sku ON tienda_nube_productos(variant_sku);
CREATE INDEX IF NOT EXISTS idx_tn_productos_item_id ON tienda_nube_productos(item_id);
CREATE INDEX IF NOT EXISTS idx_tn_productos_activo ON tienda_nube_productos(activo);

-- Trigger para actualizar fecha_actualizacion automáticamente
CREATE OR REPLACE FUNCTION update_tienda_nube_productos_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.fecha_actualizacion = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tienda_nube_productos_timestamp
    BEFORE UPDATE ON tienda_nube_productos
    FOR EACH ROW
    EXECUTE FUNCTION update_tienda_nube_productos_timestamp();

-- Vista para obtener el precio final (promocional si existe, sino normal)
CREATE OR REPLACE VIEW v_tienda_nube_precios_finales AS
SELECT
    id,
    product_id,
    product_name,
    variant_id,
    variant_sku,
    item_id,
    price,
    compare_at_price,
    promotional_price,
    -- Precio final: promocional si existe, sino price
    COALESCE(promotional_price, price) as precio_final,
    -- Indicador de si tiene promoción activa
    CASE
        WHEN promotional_price IS NOT NULL AND promotional_price > 0 THEN true
        ELSE false
    END as tiene_promocion,
    activo,
    fecha_sync,
    fecha_actualizacion
FROM tienda_nube_productos
WHERE activo = true;

COMMENT ON TABLE tienda_nube_productos IS 'Productos y variantes sincronizados desde Tienda Nube';
COMMENT ON COLUMN tienda_nube_productos.price IS 'Precio normal de la variante';
COMMENT ON COLUMN tienda_nube_productos.compare_at_price IS 'Precio comparativo (se muestra tachado en la web)';
COMMENT ON COLUMN tienda_nube_productos.promotional_price IS 'Precio promocional activo (tiene prioridad sobre price)';
COMMENT ON COLUMN tienda_nube_productos.item_id IS 'ID del producto en el ERP (si está relacionado)';
COMMENT ON VIEW v_tienda_nube_precios_finales IS 'Vista con el precio final considerando promociones activas';
