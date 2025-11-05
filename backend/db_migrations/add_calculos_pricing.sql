-- Tabla para cálculos de pricing guardados
CREATE TABLE IF NOT EXISTS calculos_pricing (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    descripcion VARCHAR(500) NOT NULL,
    ean VARCHAR(50),

    -- Inputs del cálculo
    costo DECIMAL(12, 2) NOT NULL,
    moneda_costo VARCHAR(3) NOT NULL, -- 'ARS' o 'USD'
    iva DECIMAL(4, 2) NOT NULL, -- 10.5 o 21
    comision_ml DECIMAL(5, 2) NOT NULL,
    costo_envio DECIMAL(12, 2) DEFAULT 0,
    precio_final DECIMAL(12, 2) NOT NULL,

    -- Resultados calculados
    markup_porcentaje DECIMAL(8, 2),
    limpio DECIMAL(12, 2),
    comision_total DECIMAL(12, 2),

    fecha_creacion TIMESTAMP DEFAULT NOW(),
    fecha_modificacion TIMESTAMP DEFAULT NOW(),

    CONSTRAINT chk_moneda CHECK (moneda_costo IN ('ARS', 'USD')),
    CONSTRAINT chk_iva CHECK (iva IN (10.5, 21)),
    CONSTRAINT chk_descripcion_o_ean CHECK (descripcion IS NOT NULL OR ean IS NOT NULL)
);

CREATE INDEX idx_calculos_usuario ON calculos_pricing(usuario_id);
CREATE INDEX idx_calculos_fecha ON calculos_pricing(fecha_creacion DESC);

COMMENT ON TABLE calculos_pricing IS 'Cálculos de pricing guardados por los usuarios';

-- Permisos
GRANT ALL PRIVILEGES ON TABLE calculos_pricing TO pricing_user;
GRANT USAGE, SELECT ON SEQUENCE calculos_pricing_id_seq TO pricing_user;
