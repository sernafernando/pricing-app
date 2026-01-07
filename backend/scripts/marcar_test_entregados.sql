-- Script para marcar algunos envíos TEST como entregados
-- Esto permite probar los markers verdes en el mapa

-- Ver estado actual de envíos TEST
SELECT 
    mlshippingid,
    mlstatus,
    mlreceiver_name,
    mlcity_name
FROM mercadolibre_order_shipping
WHERE mlshippingid LIKE 'TEST_%'
ORDER BY mlshippingid;

-- Marcar 3 envíos TEST como entregados (verdes en el mapa)
UPDATE mercadolibre_order_shipping
SET mlstatus = 'delivered'
WHERE mlshippingid IN (
    'TEST_NORTE_001',
    'TEST_ESTE_002', 
    'TEST_SUR_003'
);

-- Verificar cambios
SELECT 
    mlshippingid,
    mlstatus,
    mlreceiver_name,
    mlcity_name
FROM mercadolibre_order_shipping
WHERE mlshippingid IN ('TEST_NORTE_001', 'TEST_ESTE_002', 'TEST_SUR_003');

-- Resultado esperado:
-- TEST_NORTE_001: delivered (debería aparecer verde en el mapa)
-- TEST_ESTE_002: delivered (debería aparecer verde en el mapa)
-- TEST_SUR_003: delivered (debería aparecer verde en el mapa)
