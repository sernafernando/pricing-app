-- Tabla simple para pedidos del Export 87
-- Guardamos TAL CUAL los datos que vienen del ERP
-- Sin complicaciones, sin JOINs, TODO EN UNA TABLA

DROP TABLE IF EXISTS tb_pedidos_export CASCADE;

CREATE TABLE tb_pedidos_export (
    -- PK compuesta: pedido + item
    id_pedido INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    
    -- Info del cliente
    id_cliente INTEGER,
    nombre_cliente TEXT,
    
    -- Info del item
    cantidad NUMERIC(10,2),
    -- EAN y Descripción los sacamos de tb_productos_erp via item_id si hace falta
    
    -- Info de envío
    tipo_envio TEXT,
    direccion_envio TEXT,
    fecha_envio TIMESTAMP,
    
    -- Observaciones
    observaciones TEXT,
    
    -- TiendaNube
    orden_tn TEXT,          -- Número visible en TN (ej: "NRO-12345")
    order_id_tn TEXT,       -- orderID de TN (para API)
    
    -- Control
    activo BOOLEAN DEFAULT true,
    fecha_sync TIMESTAMP DEFAULT NOW(),
    
    PRIMARY KEY (id_pedido, item_id)
);

-- Índices para performance
CREATE INDEX idx_pedidos_export_activo ON tb_pedidos_export(activo);
CREATE INDEX idx_pedidos_export_order_id_tn ON tb_pedidos_export(order_id_tn);
CREATE INDEX idx_pedidos_export_id_cliente ON tb_pedidos_export(id_cliente);
CREATE INDEX idx_pedidos_export_fecha_envio ON tb_pedidos_export(fecha_envio);

COMMENT ON TABLE tb_pedidos_export IS 'Pedidos del Export 87 - Datos raw del ERP sin transformaciones';
COMMENT ON COLUMN tb_pedidos_export.id_pedido IS 'IDPedido del ERP (soh_id)';
COMMENT ON COLUMN tb_pedidos_export.order_id_tn IS 'orderID de TiendaNube para llamar a la API';
COMMENT ON COLUMN tb_pedidos_export.orden_tn IS 'Orden TN visible (ej: NRO-12345)';
COMMENT ON COLUMN tb_pedidos_export.activo IS 'true = pedido activo en el export, false = archivado';
