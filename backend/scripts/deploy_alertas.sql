-- ============================================================================
-- DEPLOYMENT SCRIPT: Sistema de Alertas
-- ============================================================================
-- Este script crea las tablas del sistema de alertas e inserta los permisos.
-- Ejecutar en el servidor de producción DESPUÉS de hacer git pull.
--
-- Uso:
--   psql -U usuario -d database_name -f scripts/deploy_alertas.sql
-- ============================================================================

BEGIN;

-- 1. Agregar 'alertas' al ENUM categoriapermiso (si no existe)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e 
        JOIN pg_type t ON e.enumtypid = t.oid 
        WHERE t.typname = 'categoriapermiso' AND e.enumlabel = 'alertas'
    ) THEN
        ALTER TYPE categoriapermiso ADD VALUE 'alertas';
    END IF;
END$$;

-- 2. Crear tabla alertas
CREATE TABLE IF NOT EXISTS alertas (
    id SERIAL PRIMARY KEY,
    titulo VARCHAR(200) NOT NULL,
    mensaje TEXT NOT NULL,
    variant VARCHAR(20) NOT NULL DEFAULT 'info' CHECK (variant IN ('info', 'warning', 'success', 'error')),
    action_label VARCHAR(100),
    action_url VARCHAR(500),
    dismissible BOOLEAN NOT NULL DEFAULT true,
    persistent BOOLEAN NOT NULL DEFAULT false,
    roles_destinatarios JSONB NOT NULL DEFAULT '[]'::jsonb,
    activo BOOLEAN NOT NULL DEFAULT false,
    fecha_desde TIMESTAMP WITH TIME ZONE NOT NULL,
    fecha_hasta TIMESTAMP WITH TIME ZONE,
    prioridad INTEGER NOT NULL DEFAULT 0,
    created_by_id INTEGER REFERENCES usuarios(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_alertas_id ON alertas(id);

-- 4. Crear tabla alertas_usuarios_destinatarios (M2M)
CREATE TABLE IF NOT EXISTS alertas_usuarios_destinatarios (
    id SERIAL PRIMARY KEY,
    alerta_id INTEGER NOT NULL REFERENCES alertas(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(alerta_id, usuario_id)
);

CREATE INDEX IF NOT EXISTS ix_alertas_usuarios_destinatarios_id ON alertas_usuarios_destinatarios(id);
CREATE INDEX IF NOT EXISTS ix_alertas_usuarios_destinatarios_alerta_id ON alertas_usuarios_destinatarios(alerta_id);
CREATE INDEX IF NOT EXISTS ix_alertas_usuarios_destinatarios_usuario_id ON alertas_usuarios_destinatarios(usuario_id);

-- 5. Crear tabla alertas_usuarios_estado (track de quién cerró)
CREATE TABLE IF NOT EXISTS alertas_usuarios_estado (
    id SERIAL PRIMARY KEY,
    alerta_id INTEGER NOT NULL REFERENCES alertas(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    cerrada BOOLEAN NOT NULL DEFAULT false,
    fecha_cerrada TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(alerta_id, usuario_id)
);

CREATE INDEX IF NOT EXISTS ix_alertas_usuarios_estado_id ON alertas_usuarios_estado(id);
CREATE INDEX IF NOT EXISTS ix_alertas_usuarios_estado_alerta_id ON alertas_usuarios_estado(alerta_id);
CREATE INDEX IF NOT EXISTS ix_alertas_usuarios_estado_usuario_id ON alertas_usuarios_estado(usuario_id);

-- 6. Crear tabla configuracion_alertas (singleton)
CREATE TABLE IF NOT EXISTS configuracion_alertas (
    id INTEGER PRIMARY KEY DEFAULT 1,
    max_alertas_visibles INTEGER NOT NULL DEFAULT 1,
    updated_by_id INTEGER REFERENCES usuarios(id),
    updated_at TIMESTAMP WITH TIME ZONE,
    CHECK (id = 1)  -- Asegurar que solo exista una fila
);

-- Insertar configuración por defecto
INSERT INTO configuracion_alertas (id, max_alertas_visibles)
VALUES (1, 1)
ON CONFLICT (id) DO NOTHING;

-- 7. Insertar permisos de alertas
INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
VALUES 
    ('alertas.gestionar', 'Gestionar alertas', 'Crear, editar, activar/desactivar y eliminar alertas del sistema', 'alertas', 90, true),
    ('alertas.configurar', 'Configurar sistema de alertas', 'Modificar configuración global de alertas (máximo visibles, etc.)', 'alertas', 91, true)
ON CONFLICT (codigo) DO NOTHING;

-- 8. Asignar permisos a roles ADMIN (SUPERADMIN ya tiene todos)
DO $$
DECLARE
    perm_gestionar_id INTEGER;
    perm_configurar_id INTEGER;
    rol_admin_id INTEGER;
BEGIN
    -- Obtener IDs de permisos
    SELECT id INTO perm_gestionar_id FROM permisos WHERE codigo = 'alertas.gestionar';
    SELECT id INTO perm_configurar_id FROM permisos WHERE codigo = 'alertas.configurar';
    
    -- Obtener ID del rol ADMIN
    SELECT id INTO rol_admin_id FROM roles WHERE codigo = 'ADMIN';
    
    -- Asignar permisos al rol ADMIN (si existe)
    IF rol_admin_id IS NOT NULL THEN
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        VALUES 
            (rol_admin_id, perm_gestionar_id),
            (rol_admin_id, perm_configurar_id)
        ON CONFLICT DO NOTHING;
    END IF;
END$$;

COMMIT;

-- ============================================================================
-- VERIFICACIÓN
-- ============================================================================
\echo '✅ Tablas de alertas creadas:'
SELECT tablename FROM pg_tables WHERE tablename LIKE 'alertas%' OR tablename = 'configuracion_alertas';

\echo ''
\echo '✅ Permisos de alertas:'
SELECT codigo, nombre FROM permisos WHERE codigo LIKE 'alertas.%';

\echo ''
\echo '✅ Configuración por defecto:'
SELECT * FROM configuracion_alertas;

\echo ''
\echo '✅ Deployment completado exitosamente!'
