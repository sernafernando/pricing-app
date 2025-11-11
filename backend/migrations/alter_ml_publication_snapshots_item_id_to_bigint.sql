-- Migración: Cambiar tipo de columna item_id de INTEGER a BIGINT
-- Propósito: Permitir valores de SKU más grandes que el límite de INTEGER (2,147,483,647)
-- Fecha: 2025-11-11

-- Solo ejecutar si la tabla ya existe
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_name = 'ml_publication_snapshots') THEN
        ALTER TABLE ml_publication_snapshots
        ALTER COLUMN item_id TYPE BIGINT;

        RAISE NOTICE 'Columna item_id cambiada a BIGINT exitosamente';
    ELSE
        RAISE NOTICE 'Tabla ml_publication_snapshots no existe, no se requiere migración';
    END IF;
END $$;
