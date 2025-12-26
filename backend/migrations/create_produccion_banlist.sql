-- Tabla de banlist para Producción - Preparación
CREATE TABLE IF NOT EXISTS produccion_banlist (
    id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL UNIQUE,
    motivo TEXT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_produccion_banlist_item_id ON produccion_banlist(item_id);
CREATE INDEX IF NOT EXISTS idx_produccion_banlist_usuario_id ON produccion_banlist(usuario_id);

-- Tabla de productos en pre-armado
CREATE TABLE IF NOT EXISTS produccion_prearmado (
    id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL UNIQUE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_produccion_prearmado_item_id ON produccion_prearmado(item_id);
CREATE INDEX IF NOT EXISTS idx_produccion_prearmado_usuario_id ON produccion_prearmado(usuario_id);

COMMENT ON TABLE produccion_banlist IS 'Items que no deben aparecer en la vista de Producción - Preparación';
COMMENT ON TABLE produccion_prearmado IS 'Items que están siendo pre-armados. Se auto-limpia cuando el producto desaparece del ERP';
