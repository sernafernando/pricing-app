-- Seed del permiso para Turbo Routing
-- Ejecutar después de aplicar la migración 20250105_turbo_routing_01

BEGIN;

-- Insertar permiso en catálogo
INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
VALUES (
    'ordenes.gestionar_turbo_routing',
    'Gestionar Routing Turbo',
    'Acceso completo al módulo de routing de envíos Turbo: ver mapa, asignar motoqueros, crear zonas, optimizar rutas',
    'ordenes',
    40,
    false
)
ON CONFLICT (codigo) DO NOTHING;

-- Asignar permiso a roles por defecto
-- SUPERADMIN y ADMIN ya tienen todos los permisos por lógica de código
-- GERENTE: solo visualización (NO agregamos el permiso de gestión)
-- PRICING: agregar el permiso para gestionar Turbo
INSERT INTO roles_permisos_base (rol, permiso_id)
SELECT 'PRICING', id FROM permisos WHERE codigo = 'ordenes.gestionar_turbo_routing'
ON CONFLICT (rol, permiso_id) DO NOTHING;

-- VENTAS: NO tiene acceso a gestionar Turbo

COMMIT;

-- Verificar
SELECT p.codigo, p.nombre, r.rol
FROM permisos p
LEFT JOIN roles_permisos_base r ON r.permiso_id = p.id
WHERE p.codigo = 'ordenes.gestionar_turbo_routing'
ORDER BY r.rol;
