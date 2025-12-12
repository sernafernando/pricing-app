-- Crear tabla para asignación de PMs a marcas
CREATE TABLE IF NOT EXISTS marcas_pm (
    id SERIAL PRIMARY KEY,
    marca VARCHAR(100) UNIQUE NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    fecha_asignacion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    fecha_modificacion TIMESTAMP WITH TIME ZONE
);

-- Índices para mejorar rendimiento
CREATE INDEX idx_marcas_pm_marca ON marcas_pm(marca);
CREATE INDEX idx_marcas_pm_usuario_id ON marcas_pm(usuario_id);

-- Insertar todas las marcas existentes sin asignar
INSERT INTO marcas_pm (marca, usuario_id)
SELECT DISTINCT marca, NULL::INTEGER
FROM productos_erp
WHERE marca IS NOT NULL
ON CONFLICT (marca) DO NOTHING;
