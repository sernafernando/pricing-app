-- Crear tabla offsets_ganancia
CREATE TABLE IF NOT EXISTS offsets_ganancia (
    id SERIAL PRIMARY KEY,

    -- Nivel de aplicación (solo uno debe tener valor)
    marca VARCHAR(100),
    categoria VARCHAR(100),
    subcategoria_id INTEGER,
    item_id INTEGER REFERENCES productos_erp(item_id),

    -- Monto del offset
    monto FLOAT NOT NULL,

    -- Descripción/concepto
    descripcion VARCHAR(255),

    -- Período de aplicación
    fecha_desde DATE NOT NULL,
    fecha_hasta DATE,

    -- Auditoría
    usuario_id INTEGER REFERENCES usuarios(id),
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    fecha_modificacion TIMESTAMP WITH TIME ZONE
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_offsets_ganancia_marca ON offsets_ganancia(marca);
CREATE INDEX IF NOT EXISTS idx_offsets_ganancia_categoria ON offsets_ganancia(categoria);
CREATE INDEX IF NOT EXISTS idx_offsets_ganancia_subcategoria ON offsets_ganancia(subcategoria_id);
CREATE INDEX IF NOT EXISTS idx_offsets_ganancia_item ON offsets_ganancia(item_id);
CREATE INDEX IF NOT EXISTS idx_offsets_ganancia_fechas ON offsets_ganancia(fecha_desde, fecha_hasta);
