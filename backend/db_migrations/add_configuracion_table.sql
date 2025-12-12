-- Crear tabla de configuración general
CREATE TABLE IF NOT EXISTS configuracion (
    clave VARCHAR(100) PRIMARY KEY,
    valor TEXT NOT NULL,
    descripcion TEXT,
    tipo VARCHAR(50) DEFAULT 'string',
    fecha_modificacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insertar configuración por defecto para markup adicional de cuotas
INSERT INTO configuracion (clave, valor, descripcion, tipo)
VALUES
    ('markup_adicional_cuotas', '4.0', 'Porcentaje de markup adicional aplicado a precios de cuotas', 'float')
ON CONFLICT (clave) DO NOTHING;

-- Crear índice para búsquedas rápidas
CREATE INDEX IF NOT EXISTS idx_configuracion_clave ON configuracion(clave);
