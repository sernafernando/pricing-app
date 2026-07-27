# Configuración del Cron para Catalog Status

## Scripts disponibles

### 1. `refresh_and_sync_catalog.py` (RECOMENDADO)
Script completo que:
1. Consulta la API de ML a través del webhook para actualizar `ml_previews`
2. Sincroniza los datos desde `ml_previews` a `ml_catalog_status` en pricing

**Uso:**
```bash
cd /var/www/html/pricing-app/backend
source venv/bin/activate
python scripts/refresh_and_sync_catalog.py
```

### 2. `sync_catalog_status.py`
Solo sincroniza desde `ml_previews` (ya existente).
**NOTA:** Solo funciona si ml_previews ya tiene datos actualizados.

## Configuración del Cron

### Opción 1: Ejecutar cada 4 horas (recomendado)
```bash
# Editar crontab
crontab -e

# Agregar esta línea (ejecuta a las 00:00, 04:00, 08:00, 12:00, 16:00, 20:00)
0 */4 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python scripts/refresh_and_sync_catalog.py >> /var/log/pricing_catalog_sync.log 2>&1
```

### Opción 2: Ejecutar cada 6 horas
```bash
# Ejecuta a las 00:00, 06:00, 12:00, 18:00
0 */6 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python scripts/refresh_and_sync_catalog.py >> /var/log/pricing_catalog_sync.log 2>&1
```

### Opción 3: Ejecutar 2 veces al día (más conservador)
```bash
# Ejecuta a las 08:00 y 20:00
0 8,20 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python scripts/refresh_and_sync_catalog.py >> /var/log/pricing_catalog_sync.log 2>&1
```

## Verificación del Cron

Ver los crons activos:
```bash
crontab -l
```

Ver el log de ejecución:
```bash
tail -f /var/log/pricing_catalog_sync.log
```

## Ejecución manual

Para ejecutar manualmente y ver el progreso:
```bash
cd /var/www/html/pricing-app/backend
source venv/bin/activate
python scripts/refresh_and_sync_catalog.py
```

## Notas importantes

1. **ML_WEBHOOK_URL**: El script usa por defecto `https://ml-webhook.gaussonline.com.ar`.
   Si tu webhook está en otra URL, agregá en el `.env`:
   ```
   ML_WEBHOOK_URL=https://tu-webhook.com
   ```

2. **Rate limiting**: El script procesa en batches de 50 MLAs con pausas de 0.5s entre batches
   para no saturar la API de MercadoLibre.

3. **Logs**: Se recomienda rotar el log con logrotate:
   ```bash
   sudo nano /etc/logrotate.d/pricing-catalog
   ```

   Contenido:
   ```
   /var/log/pricing_catalog_sync.log {
       daily
       rotate 7
       compress
       missingok
       notifempty
   }
   ```

4. **Monitoreo**: Revisar regularmente el log para detectar errores:
   ```bash
   grep "ERROR\|❌" /var/log/pricing_catalog_sync.log
   ```

## Troubleshooting

### Error: "No se encontró DATABASE_URL"
Verificar que el `.env` existe y tiene DATABASE_URL configurado:
```bash
cat /var/www/html/pricing-app/backend/.env | grep DATABASE_URL
```

### Error: "Connection refused" al webhook
Verificar que ml-webhook está corriendo:
```bash
curl https://ml-webhook.gaussonline.com.ar/api/health
```

### Sin datos sincronizados
1. Verificar que hay publicaciones de catálogo:
   ```sql
   SELECT COUNT(*) FROM tb_mercadolibre_items_publicados
   WHERE mlp_catalog_listing = true
   AND mlp_catalog_product_id IS NOT NULL;
   ```

2. Verificar que ml-webhook tiene datos:
   ```sql
   -- En la BD mlwebhook
   SELECT COUNT(*) FROM ml_previews
   WHERE resource LIKE '/items/%/price_to_win%';
   ```
