-- Migración: Crear tabla ml_ventas_metricas
-- Propósito: Almacenar métricas precalculadas de ventas ML con markup, costos y comisiones
-- Fecha: 2025-11-12

CREATE TABLE IF NOT EXISTS ml_ventas_metricas (
    id SERIAL PRIMARY KEY,

    -- Identificadores de la venta
    id_operacion BIGINT NOT NULL UNIQUE,
    ml_order_id VARCHAR(50),
    pack_id BIGINT,

    -- Información del producto
    item_id INTEGER,
    codigo VARCHAR(100),
    descripcion TEXT,
    marca VARCHAR(255),
    categoria VARCHAR(255),
    subcategoria VARCHAR(255),

    -- Fecha y timing
    fecha_venta TIMESTAMP WITH TIME ZONE NOT NULL,
    fecha_calculo DATE,

    -- Cantidades
    cantidad INTEGER NOT NULL,

    -- Montos de venta (sin IVA)
    monto_unitario NUMERIC(18, 2),
    monto_total NUMERIC(18, 2) NOT NULL,

    -- Cotización
    cotizacion_dolar NUMERIC(10, 4),

    -- Costos del producto (sin IVA)
    costo_unitario_sin_iva NUMERIC(18, 6),
    costo_total_sin_iva NUMERIC(18, 2),
    moneda_costo VARCHAR(10),

    -- Comisiones y costos ML
    tipo_lista VARCHAR(50),
    porcentaje_comision_ml NUMERIC(5, 2),
    comision_ml NUMERIC(18, 2),
    costo_envio_ml NUMERIC(18, 2),
    tipo_logistica VARCHAR(50),

    -- Cálculos finales
    monto_limpio NUMERIC(18, 2),
    costo_total NUMERIC(18, 2),
    ganancia NUMERIC(18, 2),
    markup_porcentaje NUMERIC(10, 2),

    -- Información adicional
    prli_id INTEGER,
    mla_id VARCHAR(50),

    -- Auditoría
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices para mejorar performance de consultas del dashboard
CREATE INDEX IF NOT EXISTS idx_ml_metricas_id_operacion ON ml_ventas_metricas(id_operacion);
CREATE INDEX IF NOT EXISTS idx_ml_metricas_fecha_venta ON ml_ventas_metricas(fecha_venta);
CREATE INDEX IF NOT EXISTS idx_ml_metricas_fecha_calculo ON ml_ventas_metricas(fecha_calculo);
CREATE INDEX IF NOT EXISTS idx_ml_metricas_marca ON ml_ventas_metricas(marca);
CREATE INDEX IF NOT EXISTS idx_ml_metricas_categoria ON ml_ventas_metricas(categoria);
CREATE INDEX IF NOT EXISTS idx_ml_metricas_item_id ON ml_ventas_metricas(item_id);
CREATE INDEX IF NOT EXISTS idx_ml_metricas_ml_order_id ON ml_ventas_metricas(ml_order_id);
CREATE INDEX IF NOT EXISTS idx_ml_metricas_pack_id ON ml_ventas_metricas(pack_id);

-- Índice compuesto para queries del dashboard por rango de fechas y marca
CREATE INDEX IF NOT EXISTS idx_ml_metricas_fecha_marca ON ml_ventas_metricas(fecha_venta, marca);

-- Permisos
GRANT ALL PRIVILEGES ON TABLE ml_ventas_metricas TO pricing_user;
GRANT USAGE, SELECT ON SEQUENCE ml_ventas_metricas_id_seq TO pricing_user;

-- Comentarios
COMMENT ON TABLE ml_ventas_metricas IS 'Métricas precalculadas de ventas MercadoLibre con markup, comisiones y costos';
COMMENT ON COLUMN ml_ventas_metricas.monto_limpio IS 'Monto total - comisión ML - costo envío';
COMMENT ON COLUMN ml_ventas_metricas.ganancia IS 'Monto limpio - costo total sin IVA';
COMMENT ON COLUMN ml_ventas_metricas.markup_porcentaje IS 'Porcentaje de ganancia sobre el costo (ganancia / costo * 100)';
COMMENT ON COLUMN ml_ventas_metricas.fecha_calculo IS 'Fecha en que se calcularon las métricas (para históricos)';
