-- Tabla para almacenar el estado de competencia en catálogos de MercadoLibre
CREATE TABLE IF NOT EXISTS ml_catalog_status (
    id SERIAL PRIMARY KEY,
    mla VARCHAR(20) NOT NULL,
    catalog_product_id VARCHAR(50),
    status VARCHAR(50),  -- winning, sharing_first_place, competing, not_listed
    current_price NUMERIC(18, 2),
    price_to_win NUMERIC(18, 2),
    visit_share VARCHAR(20),
    consistent BOOLEAN,
    competitors_sharing_first_place INTEGER,
    winner_mla VARCHAR(20),
    winner_price NUMERIC(18, 2),
    fecha_consulta TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(mla, fecha_consulta)
);

CREATE INDEX IF NOT EXISTS idx_ml_catalog_status_mla ON ml_catalog_status(mla);
CREATE INDEX IF NOT EXISTS idx_ml_catalog_status_fecha ON ml_catalog_status(fecha_consulta DESC);
CREATE INDEX IF NOT EXISTS idx_ml_catalog_status_status ON ml_catalog_status(status);

-- Vista para obtener el último estado de cada MLA
CREATE OR REPLACE VIEW v_ml_catalog_status_latest AS
SELECT DISTINCT ON (mla)
    mla,
    catalog_product_id,
    status,
    current_price,
    price_to_win,
    visit_share,
    consistent,
    competitors_sharing_first_place,
    winner_mla,
    winner_price,
    fecha_consulta
FROM ml_catalog_status
ORDER BY mla, fecha_consulta DESC;

-- Permisos
GRANT SELECT, INSERT, UPDATE, DELETE ON ml_catalog_status TO pricing_user;
GRANT SELECT ON v_ml_catalog_status_latest TO pricing_user;
GRANT USAGE, SELECT ON SEQUENCE ml_catalog_status_id_seq TO pricing_user;
