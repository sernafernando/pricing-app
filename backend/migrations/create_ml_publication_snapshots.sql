-- Migración: Crear tabla ml_publication_snapshots
-- Propósito: Guardar snapshots de publicaciones de MercadoLibre para comparar
--            con los datos actuales del sistema (listas y campañas)

CREATE TABLE IF NOT EXISTS ml_publication_snapshots (
    id SERIAL PRIMARY KEY,

    -- Datos de la publicación
    mla_id VARCHAR(50) NOT NULL,
    title TEXT,
    price NUMERIC(12, 2),
    base_price NUMERIC(12, 2),
    available_quantity INTEGER,
    sold_quantity INTEGER,
    status VARCHAR(50),
    listing_type_id VARCHAR(50),
    permalink VARCHAR(500),

    -- Datos de campaña y lista
    installments_campaign VARCHAR(100),

    -- SKU del seller
    seller_sku VARCHAR(100),

    -- Item ID del ERP (si lo podemos obtener del SKU)
    item_id INTEGER,

    -- Metadata del snapshot
    snapshot_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Auditoría
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices para mejorar performance
CREATE INDEX IF NOT EXISTS idx_ml_snapshots_mla_id ON ml_publication_snapshots(mla_id);
CREATE INDEX IF NOT EXISTS idx_ml_snapshots_seller_sku ON ml_publication_snapshots(seller_sku);
CREATE INDEX IF NOT EXISTS idx_ml_snapshots_item_id ON ml_publication_snapshots(item_id);
CREATE INDEX IF NOT EXISTS idx_ml_snapshots_snapshot_date ON ml_publication_snapshots(snapshot_date);

-- Permisos
GRANT ALL PRIVILEGES ON TABLE ml_publication_snapshots TO pricing_user;
GRANT USAGE, SELECT ON SEQUENCE ml_publication_snapshots_id_seq TO pricing_user;

-- Comentarios
COMMENT ON TABLE ml_publication_snapshots IS 'Snapshots de publicaciones de MercadoLibre para comparar con datos actuales';
COMMENT ON COLUMN ml_publication_snapshots.mla_id IS 'ID de la publicación en MercadoLibre (ej: MLA2016945208)';
COMMENT ON COLUMN ml_publication_snapshots.installments_campaign IS 'Campaña de cuotas (3x_campaign, 6x_campaign, 12x_campaign, etc)';
COMMENT ON COLUMN ml_publication_snapshots.seller_sku IS 'SKU del vendedor configurado en ML';
COMMENT ON COLUMN ml_publication_snapshots.item_id IS 'ID del item en el ERP (extraído del SKU si es numérico)';
COMMENT ON COLUMN ml_publication_snapshots.snapshot_date IS 'Fecha y hora en que se tomó el snapshot';
