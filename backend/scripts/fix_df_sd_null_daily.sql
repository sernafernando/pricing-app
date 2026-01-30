-- ============================================================================
-- SCRIPT DIARIO: Corregir df_id y sd_id NULL
-- ============================================================================
-- Este script se ejecuta diariamente para corregir registros con df_id/sd_id
-- NULL que se crean desde GAUSSONLINE.
--
-- Usar en cron: psql -U usuario -d pricing_db -f fix_df_sd_null_daily.sql
-- ============================================================================

-- Procesar solo los últimos 7 días para ser eficiente
\set ventana_dias 7

BEGIN;

-- ============================================================================
-- PASO 1: Actualizar df_id NULL (últimos N días)
-- ============================================================================

UPDATE tb_commercial_transactions
SET df_id = 2
WHERE df_id IS NULL
  AND ct_kindof = 'B'
  AND ct_pointofsale = 5
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 1
WHERE df_id IS NULL
  AND ct_kindof = 'A'
  AND ct_pointofsale = 5
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 129
WHERE df_id IS NULL
  AND ct_kindof = 'A'
  AND ct_pointofsale = 3
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 130
WHERE df_id IS NULL
  AND ct_kindof = 'B'
  AND ct_pointofsale = 3
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 8
WHERE df_id IS NULL
  AND ct_kindof = 'X'
  AND ct_pointofsale = 5
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 112
WHERE df_id IS NULL
  AND ct_kindof = 'X'
  AND ct_pointofsale = 3
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 75
WHERE df_id IS NULL
  AND ct_kindof = 'X'
  AND ct_pointofsale = 2
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 7
WHERE df_id IS NULL
  AND ct_kindof = 'R'
  AND ct_pointofsale = 5
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 107
WHERE df_id IS NULL
  AND ct_kindof = 'R'
  AND ct_pointofsale = 10
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 65
WHERE df_id IS NULL
  AND ct_kindof = 'A'
  AND ct_pointofsale = 2
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET df_id = 69
WHERE df_id IS NULL
  AND ct_kindof = 'B'
  AND ct_pointofsale = 2
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

-- ============================================================================
-- PASO 2: Actualizar sd_id NULL (últimos N días)
-- ============================================================================

UPDATE tb_commercial_transactions
SET sd_id = 1
WHERE sd_id IS NULL
  AND ct_kindof IN ('A', 'B')
  AND df_id IN (1, 2, 65, 69, 129, 130)
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET sd_id = 1
WHERE sd_id IS NULL
  AND ct_kindof = 'X'
  AND df_id IN (8, 75, 112)
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET sd_id = 3
WHERE sd_id IS NULL
  AND df_id IN (5, 6, 73, 115, 116)
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

UPDATE tb_commercial_transactions
SET sd_id = 1
WHERE sd_id IS NULL
  AND ct_kindof = 'R'
  AND df_id IN (7, 60, 64, 78, 107, 110)
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';

COMMIT;

-- ============================================================================
-- REPORTE: Mostrar cuántos registros se corrigieron
-- ============================================================================

SELECT 
    'Registros con df_id NULL (últimos 7 días)' as metrica,
    COUNT(*) as cantidad
FROM tb_commercial_transactions
WHERE df_id IS NULL
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days'
UNION ALL
SELECT 
    'Registros con sd_id NULL (últimos 7 días)' as metrica,
    COUNT(*) as cantidad
FROM tb_commercial_transactions
WHERE sd_id IS NULL
  AND ct_date >= CURRENT_DATE - INTERVAL '7 days';
