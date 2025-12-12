-- Crear tabla para banlist de items sin MLA
CREATE TABLE IF NOT EXISTS items_sin_mla_banlist (
    id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL UNIQUE,
    motivo TEXT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Crear índices para mejorar rendimiento
CREATE INDEX IF NOT EXISTS idx_items_sin_mla_banlist_item_id ON items_sin_mla_banlist(item_id);
CREATE INDEX IF NOT EXISTS idx_items_sin_mla_banlist_usuario_id ON items_sin_mla_banlist(usuario_id);
CREATE INDEX IF NOT EXISTS idx_items_sin_mla_banlist_fecha ON items_sin_mla_banlist(fecha_creacion);

-- Comentarios para documentación
COMMENT ON TABLE items_sin_mla_banlist IS 'Items que no deben aparecer en el reporte de productos sin MLA asociado';
COMMENT ON COLUMN items_sin_mla_banlist.item_id IS 'ID del item/producto del ERP';
COMMENT ON COLUMN items_sin_mla_banlist.motivo IS 'Razón por la cual se agregó a la banlist (opcional)';
COMMENT ON COLUMN items_sin_mla_banlist.usuario_id IS 'Usuario que agregó el item a la banlist';
COMMENT ON COLUMN items_sin_mla_banlist.fecha_creacion IS 'Fecha y hora en que se agregó a la banlist';
