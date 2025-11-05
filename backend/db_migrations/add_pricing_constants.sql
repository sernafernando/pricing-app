-- Agregar constantes de pricing a la tabla de configuración
INSERT INTO configuracion (clave, valor, descripcion, tipo)
VALUES
    ('monto_tier1', '15000', 'Monto límite para tier 1 de comisión ML', 'float'),
    ('monto_tier2', '24000', 'Monto límite para tier 2 de comisión ML', 'float'),
    ('monto_tier3', '33000', 'Monto límite para tier 3 de comisión ML (envío gratis)', 'float'),
    ('comision_tier1', '1095', 'Comisión adicional tier 1 (precios < $15000)', 'float'),
    ('comision_tier2', '2190', 'Comisión adicional tier 2 (precios entre $15000 y $24000)', 'float'),
    ('comision_tier3', '2628', 'Comisión adicional tier 3 (precios entre $24000 y $33000)', 'float'),
    ('varios_porcentaje', '6.5', 'Porcentaje de varios (costos adicionales ML)', 'float'),
    ('grupo_comision_default', '1', 'Grupo de comisión por defecto si la subcategoría no está asignada', 'integer')
ON CONFLICT (clave) DO NOTHING;
