-- Asignar masivamente el usuario ID 2 como PM por defecto a todas las marcas sin asignar
UPDATE marcas_pm
SET usuario_id = 2,
    fecha_modificacion = CURRENT_TIMESTAMP
WHERE usuario_id IS NULL;

-- Ver cuántas marcas fueron actualizadas
SELECT COUNT(*) as marcas_actualizadas
FROM marcas_pm
WHERE usuario_id = 2;

-- Ver resumen de asignaciones
SELECT
    COALESCE(u.nombre, 'Sin asignar') as pm,
    COUNT(mp.id) as cantidad_marcas
FROM marcas_pm mp
LEFT JOIN usuarios u ON mp.usuario_id = u.id
GROUP BY u.nombre
ORDER BY cantidad_marcas DESC;
