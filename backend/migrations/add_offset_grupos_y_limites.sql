-- Crear tabla offset_grupos
CREATE TABLE IF NOT EXISTS offset_grupos (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    descripcion VARCHAR(255),
    usuario_id INTEGER REFERENCES usuarios(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Agregar nuevos campos a offsets_ganancia
ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS grupo_id INTEGER REFERENCES offset_grupos(id);

ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS max_unidades INTEGER;
-- max_unidades: Máximo de unidades que aplica el offset (para tipo monto_por_unidad)

ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS max_monto_usd FLOAT;
-- max_monto_usd: Máximo monto en USD que aplica el offset

-- Campos para indicar en qué canales aplica el offset
ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS aplica_ml BOOLEAN DEFAULT TRUE;
-- aplica_ml: Si el offset aplica en Métricas ML

ALTER TABLE offsets_ganancia
ADD COLUMN IF NOT EXISTS aplica_fuera BOOLEAN DEFAULT TRUE;
-- aplica_fuera: Si el offset aplica en Ventas por Fuera de ML

-- Índice para grupo_id
CREATE INDEX IF NOT EXISTS idx_offsets_ganancia_grupo ON offsets_ganancia(grupo_id);

-- Permitir que monto sea NULL (ya que ahora permitimos porcentaje_costo sin monto)
ALTER TABLE offsets_ganancia ALTER COLUMN monto DROP NOT NULL;

-- Comentarios explicativos:
-- grupo_id: permite agrupar múltiples offsets que comparten límites (max_unidades, max_monto_usd)
-- Cuando se calcula el offset, se suman las unidades/montos de todos los offsets del grupo
-- y se aplica el límite de forma conjunta.
--
-- Ejemplo: Producto A y B en grupo "Rebate ASUS Q4"
-- - Offset por unidad: USD 20
-- - max_unidades (del grupo): 200
-- - Se venden 180 de A y 30 de B = 210 total
-- - Solo aplica para las primeras 200 unidades
