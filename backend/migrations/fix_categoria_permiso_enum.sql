-- Fix: Actualizar el enum categoriapermiso para usar minúsculas
-- El código Python usa valores en minúsculas pero el enum en la DB estaba en mayúsculas

-- Crear un nuevo enum con los valores correctos
CREATE TYPE categoriapermiso_new AS ENUM (
    'productos',
    'ventas_ml',
    'ventas_fuera',
    'ventas_tn',
    'administracion',
    'reportes',
    'configuracion'
);

-- Actualizar la columna para usar el nuevo enum
ALTER TABLE permisos
    ALTER COLUMN categoria TYPE categoriapermiso_new
    USING categoria::text::categoriapermiso_new;

-- Eliminar el enum viejo
DROP TYPE categoriapermiso;

-- Renombrar el nuevo enum al nombre original
ALTER TYPE categoriapermiso_new RENAME TO categoriapermiso;
