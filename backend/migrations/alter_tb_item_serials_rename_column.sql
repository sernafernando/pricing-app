-- Renombrar columna is_IsOwnGeneration a is_isowngeneration (lowercase)
ALTER TABLE tb_item_serials
RENAME COLUMN "is_IsOwnGeneration" TO is_isowngeneration;
