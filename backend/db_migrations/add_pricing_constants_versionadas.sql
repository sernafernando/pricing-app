-- Crear tabla de constantes de pricing con versionado
CREATE TABLE IF NOT EXISTS pricing_constants (
    id SERIAL PRIMARY KEY,
    monto_tier1 DECIMAL(12, 2) NOT NULL DEFAULT 15000,
    monto_tier2 DECIMAL(12, 2) NOT NULL DEFAULT 24000,
    monto_tier3 DECIMAL(12, 2) NOT NULL DEFAULT 33000,
    comision_tier1 DECIMAL(12, 2) NOT NULL DEFAULT 1095,
    comision_tier2 DECIMAL(12, 2) NOT NULL DEFAULT 2190,
    comision_tier3 DECIMAL(12, 2) NOT NULL DEFAULT 2628,
    varios_porcentaje DECIMAL(5, 2) NOT NULL DEFAULT 6.5,
    grupo_comision_default INTEGER NOT NULL DEFAULT 1,
    markup_adicional_cuotas DECIMAL(5, 2) NOT NULL DEFAULT 4.0,
    fecha_desde DATE NOT NULL,
    fecha_hasta DATE,
    fecha_creacion TIMESTAMP DEFAULT NOW(),
    creado_por INTEGER REFERENCES usuarios(id),
    CONSTRAINT chk_fecha_hasta CHECK (fecha_hasta IS NULL OR fecha_hasta >= fecha_desde)
);

-- Insertar valores por defecto con fecha desde hoy
INSERT INTO pricing_constants (
    monto_tier1,
    monto_tier2,
    monto_tier3,
    comision_tier1,
    comision_tier2,
    comision_tier3,
    varios_porcentaje,
    grupo_comision_default,
    markup_adicional_cuotas,
    fecha_desde
)
VALUES (
    15000,
    24000,
    33000,
    1095,
    2190,
    2628,
    6.5,
    1,
    4.0,
    CURRENT_DATE
);

-- Crear índice para búsquedas por fecha
CREATE INDEX IF NOT EXISTS idx_pricing_constants_fecha_desde ON pricing_constants(fecha_desde);
CREATE INDEX IF NOT EXISTS idx_pricing_constants_fecha_hasta ON pricing_constants(fecha_hasta);

-- Dar permisos
GRANT ALL PRIVILEGES ON TABLE pricing_constants TO pricing_user;
GRANT USAGE, SELECT ON SEQUENCE pricing_constants_id_seq TO pricing_user;

COMMENT ON TABLE pricing_constants IS 'Constantes de pricing versionadas por fecha';
COMMENT ON COLUMN pricing_constants.monto_tier1 IS 'Monto límite para tier 1 (< este monto aplica comision_tier1)';
COMMENT ON COLUMN pricing_constants.monto_tier2 IS 'Monto límite para tier 2 (< este monto aplica comision_tier2)';
COMMENT ON COLUMN pricing_constants.monto_tier3 IS 'Monto límite para tier 3 (>= este monto no aplica tier adicional ni envío)';
COMMENT ON COLUMN pricing_constants.comision_tier1 IS 'Comisión adicional para precios < monto_tier1';
COMMENT ON COLUMN pricing_constants.comision_tier2 IS 'Comisión adicional para precios entre monto_tier1 y monto_tier2';
COMMENT ON COLUMN pricing_constants.comision_tier3 IS 'Comisión adicional para precios entre monto_tier2 y monto_tier3';
COMMENT ON COLUMN pricing_constants.varios_porcentaje IS 'Porcentaje de varios (costos adicionales ML) aplicado sobre precio sin IVA';
COMMENT ON COLUMN pricing_constants.grupo_comision_default IS 'Grupo de comisión por defecto cuando subcategoría no está asignada';
COMMENT ON COLUMN pricing_constants.markup_adicional_cuotas IS 'Porcentaje de markup adicional para precios de cuotas';
COMMENT ON COLUMN pricing_constants.fecha_desde IS 'Fecha desde la cual aplican estos valores';
COMMENT ON COLUMN pricing_constants.fecha_hasta IS 'Fecha hasta la cual aplican estos valores (NULL = vigente)';
