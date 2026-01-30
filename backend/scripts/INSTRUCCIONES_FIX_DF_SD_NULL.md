# Solución para df_id y sd_id NULL

## Problema detectado

Desde enero 2025, GAUSSONLINE está sincronizando transacciones con `df_id` y `sd_id` NULL, lo que impide que se calculen las métricas de rentabilidad.

**Impacto:**
- 22,431 transacciones con `df_id NULL`
- 15,620 transacciones con `sd_id NULL`
- Se corrigieron 15,511 (69%) con el primer fix
- Quedan 6,923 registros raros/corruptos sin corregir

## Solución implementada

### 1. Fix masivo histórico (YA APLICADO)

Se ejecutó `/home/mns/scripts/fix_df_id_sd_id_null.sql` que corrigió todas las transacciones legítimas desde enero 2025.

**Resultado:**
- ✅ Transacción 702572 (tu factura) corregida: `df_id=2, sd_id=1`
- ✅ 15,511 transacciones corregidas
- ⚠️ 6,923 registros raros NO corregidos (ct_kindof vacío, puntos de venta raros)

### 2. Fix automático diario (NUEVO - AGREGAR A CRON)

**Script:** `backend/scripts/fix_df_sd_null_daily.py`

Este script:
- Se ejecuta **diariamente a las 3:20 AM** (antes de los rebuilds de métricas)
- Corrige solo los últimos 7 días (eficiente)
- Aplica el mismo mapeo de `ct_kindof + ct_pointofsale → df_id`
- Usa Python + SQLAlchemy (consistente con el resto del proyecto)

**Agregar esta línea al crontab:**

```bash
# Fix df_id/sd_id NULL - diario a las 3:20 AM (ANTES de rebuilds de métricas)
20 3 * * * cd /var/www/html/pricing-app/backend && venv/bin/python scripts/fix_df_sd_null_daily.py >> /var/log/pricing-app/fix_df_sd_null.log 2>&1
```

### 3. Orden de ejecución en cron

```
3:00 AM → Sale Orders Backfill (30 días)
3:05 AM → Commercial Transactions Backfill (30 días)
3:20 AM → FIX df_id/sd_id NULL (NUEVO) ← AGREGAR ESTO
3:30 AM → Rebuild ML Métricas 30d (domingos)
3:40 AM → Rebuild Fuera ML Métricas 30d (domingos)
3:50 AM → Rebuild TN Métricas 30d (domingos)
4:00 AM → Rebuild ML Métricas 7d (diario)
4:10 AM → Rebuild Fuera ML Métricas 7d (diario)
4:20 AM → Rebuild TN Métricas 7d (diario)
```

**Importante:** El fix debe ejecutarse **ANTES** de los rebuilds de métricas para que las transacciones corregidas se procesen.

## Mapeo de corrección

El script aplica este mapeo:

| ct_kindof | ct_pointofsale | df_id | Descripción |
|-----------|----------------|-------|-------------|
| B | 5 | 2 | 01.Fc B 0005 |
| A | 5 | 1 | 01.Fc A 0005 |
| A | 3 | 129 | 21.Fc A 00003 Grupo Gauss mercadolibre |
| B | 3 | 130 | 21.Fc B 00003 Grupo Gauss Mercadolibre |
| X | 5 | 8 | 01.Rc X 0005 |
| X | 3 | 112 | 21.Rc X 0003 |
| X | 2 | 75 | 02.Rc X 0002 S.Nueva |
| R | 5 | 7 | 01.Rm R 0005 |
| R | 10 | 107 | 21-Rm R 0010 |
| A | 2 | 65 | 02Fc A 0002 S.Nueva |
| B | 2 | 69 | 02.Fc B 0001 S.Nueva |

Para `sd_id`:
- Facturas A/B → `sd_id = 1` (venta)
- Recibos X → `sd_id = 1` (venta)
- Notas de crédito → `sd_id = 3` (devolución)
- Remitos R → `sd_id = 1` (entrega)

## Verificación

Después de agregar el cron, verificar que funciona:

```bash
# Ejecutar manualmente el fix
cd /var/www/html/pricing-app/backend
venv/bin/python scripts/fix_df_sd_null_daily.py

# Ver log
tail -f /var/log/pricing-app/fix_df_sd_null.log

# Verificar que no quedan NULL recientes (desde Python o SQL)
# Opción 1: El script ya muestra estadísticas al ejecutarse
# Opción 2: SQL directo
sudo -u postgres psql -d pricing_db -c "
SELECT COUNT(*) FROM tb_commercial_transactions 
WHERE df_id IS NULL AND ct_date >= CURRENT_DATE - INTERVAL '7 days'
"
```

## Próximos pasos (opcional - arreglar la raíz del problema)

Para evitar que se sigan creando registros con NULL, investigar:

1. **Sincronización desde GAUSSONLINE:**
   - ¿Qué script sincroniza `tb_commercial_transactions`?
   - ¿Por qué no está trayendo `df_id` y `sd_id`?
   - Revisar: `/var/www/html/pricing-app/backend/app/scripts/sync_commercial_transactions_guid.py`

2. **Triggers en GAUSSONLINE:**
   - ¿Hay un trigger que debería rellenar `df_id` basándose en `ct_kindof + ct_pointofsale`?
   - Si no existe, crearlo en GAUSSONLINE

3. **Validación en el script de sync:**
   - Agregar lógica para rellenar `df_id`/`sd_id` durante la sincronización
   - Así no dependemos del fix posterior

## Archivos

- `backend/scripts/fix_df_sd_null_daily.py` → Script Python automático (AGREGAR A CRON)
- `backend/scripts/fix_df_sd_null_daily.sql` → Script SQL (alternativa, NO usar en cron)
- `backend/scripts/INSTRUCCIONES_FIX_DF_SD_NULL.md` → Este archivo

**Nota:** Se recomienda usar el script Python (`.py`) en lugar del SQL (`.sql`) porque:
- Es consistente con el resto de los crons del proyecto
- No requiere configurar credenciales de PostgreSQL
- Usa las mismas conexiones que el resto de la app

**Archivos temporales usados durante el debug (ya eliminados):**
- Fix masivo histórico (YA EJECUTADO directamente en el servidor)
- Consultas de investigación y verificación

## Contacto

Si el problema persiste o necesitás ayuda, revisar logs y consultar con el equipo de infraestructura.
