-- Crear tabla para banlist de MLAs
CREATE TABLE IF NOT EXISTS mla_banlist (
    id SERIAL PRIMARY KEY,
    mla VARCHAR(50) UNIQUE NOT NULL,
    motivo VARCHAR(255),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    activo BOOLEAN DEFAULT TRUE
);

-- Índices para mejorar rendimiento
CREATE INDEX idx_mla_banlist_mla ON mla_banlist(mla);
CREATE INDEX idx_mla_banlist_activo ON mla_banlist(activo);
CREATE INDEX idx_mla_banlist_usuario_id ON mla_banlist(usuario_id);

-- Otorgar permisos
GRANT ALL PRIVILEGES ON TABLE mla_banlist TO pricing_user;
GRANT USAGE, SELECT ON SEQUENCE mla_banlist_id_seq TO pricing_user;
