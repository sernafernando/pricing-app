-- Crear tabla para versiones de comisiones
CREATE TABLE IF NOT EXISTS comisiones_versiones (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL,
    descripcion TEXT,
    fecha_desde DATE NOT NULL,
    fecha_hasta DATE,
    activo BOOLEAN DEFAULT TRUE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    usuario_creacion VARCHAR(100),
    CONSTRAINT chk_fechas CHECK (fecha_hasta IS NULL OR fecha_hasta >= fecha_desde)
);

-- Tabla para comisiones base (lista 4) por grupo
CREATE TABLE IF NOT EXISTS comisiones_base (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES comisiones_versiones(id) ON DELETE CASCADE,
    grupo_id INTEGER NOT NULL,
    comision_base NUMERIC(5, 2) NOT NULL,
    UNIQUE(version_id, grupo_id)
);

-- Tabla para adicionales por cuota (aplican a todas las listas de cuotas)
CREATE TABLE IF NOT EXISTS comisiones_adicionales_cuota (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES comisiones_versiones(id) ON DELETE CASCADE,
    cuotas INTEGER NOT NULL CHECK (cuotas IN (3, 6, 9, 12)),
    adicional NUMERIC(5, 2) NOT NULL,
    UNIQUE(version_id, cuotas)
);

-- Índices para mejorar performance
CREATE INDEX IF NOT EXISTS idx_comisiones_versiones_fechas ON comisiones_versiones(fecha_desde, fecha_hasta);
CREATE INDEX IF NOT EXISTS idx_comisiones_versiones_activo ON comisiones_versiones(activo);
CREATE INDEX IF NOT EXISTS idx_comisiones_base_version ON comisiones_base(version_id);
CREATE INDEX IF NOT EXISTS idx_comisiones_base_grupo ON comisiones_base(grupo_id);
CREATE INDEX IF NOT EXISTS idx_comisiones_adicionales_version ON comisiones_adicionales_cuota(version_id);

-- Insertar la versión actual (histórica) con los valores que mencionaste
INSERT INTO comisiones_versiones (nombre, descripcion, fecha_desde, fecha_hasta, activo)
VALUES
    ('Comisiones Históricas', 'Comisiones utilizadas hasta la implementación del nuevo sistema', '2020-01-01', CURRENT_DATE - INTERVAL '1 day', FALSE);

-- Obtener el ID de la versión recién creada
DO $$
DECLARE
    v_version_id INTEGER;
BEGIN
    SELECT id INTO v_version_id FROM comisiones_versiones WHERE nombre = 'Comisiones Históricas';

    -- Insertar comisiones base (lista 4) para cada grupo
    INSERT INTO comisiones_base (version_id, grupo_id, comision_base) VALUES
        (v_version_id, 1, 15.5),
        (v_version_id, 2, 12.15),
        (v_version_id, 3, 12.3),
        (v_version_id, 4, 12.5),
        (v_version_id, 5, 13.5),
        (v_version_id, 6, 14.0),
        (v_version_id, 7, 14.15),
        (v_version_id, 8, 14.3),
        (v_version_id, 9, 14.35),
        (v_version_id, 10, 14.5),
        (v_version_id, 11, 15.0),
        (v_version_id, 12, 16.0),
        (v_version_id, 13, 17.0);

    -- Insertar adicionales por cuota (aplican a todos los grupos)
    INSERT INTO comisiones_adicionales_cuota (version_id, cuotas, adicional) VALUES
        (v_version_id, 3, 10.2),
        (v_version_id, 6, 16.2),
        (v_version_id, 9, 22.7),
        (v_version_id, 12, 29.0);
END $$;

COMMENT ON TABLE comisiones_versiones IS 'Versiones de comisiones con vigencia por fechas';
COMMENT ON TABLE comisiones_base IS 'Comisiones base (lista 4) por grupo de subcategorías';
COMMENT ON TABLE comisiones_adicionales_cuota IS 'Adicionales que se suman a la comisión base para calcular comisiones en cuotas';
