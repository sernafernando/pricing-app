# Scripts de Sincronización

## sync_catalog_status.py

Script optimizado para sincronizar el estado de competencia en catálogos de MercadoLibre.

### Funcionamiento

1. **Filtra publicaciones de catálogo** desde `tb_mercadolibre_items_publicados` usando:
   - `mlp_catalog_listing = true`
   - `mlp_catalog_product_id IS NOT NULL`

2. **Consulta directamente la BD del ml-webhook** para obtener los status actualizados desde la tabla `ml_previews`

3. **Guarda los datos** en la tabla `ml_catalog_status` de pricing-app

### Ventajas

- ✅ **Mucho más rápido**: consulta BD en lugar de hacer requests HTTP
- ✅ **Solo procesa publicaciones de catálogo**: usa el flag `mlp_catalog_listing`
- ✅ **Usa datos actualizados por webhooks**: el ml-webhook actualiza automáticamente ml_previews

### Configuración

Agregá esta variable al `.env`:

```bash
ML_WEBHOOK_DB_URL=postgresql://usuario:password@host:5432/ml_webhook
```

### Uso

**Sincronizar todas las publicaciones de catálogo:**

```bash
cd backend
python scripts/sync_catalog_status.py
```

**Sincronizar un MLA específico:**

```bash
python scripts/sync_catalog_status.py --mla MLA123456789
```

### Ejemplo de salida

```
INFO:__main__:Encontradas 1250 publicaciones de catálogo...
INFO:__main__:Procesando MLA1532226449...
INFO:__main__:✓ MLA1532226449 - Status: winning
INFO:__main__:Procesando MLA1532226450...
INFO:__main__:✓ MLA1532226450 - Status: competing
...
============================================================
Sincronización completada:
  - Total publicaciones de catálogo: 1250
  - Sincronizadas: 1180
  - Sin datos en webhook: 70
  - Errores: 0
============================================================
```

### Automatización

Para ejecutar automáticamente cada hora, agregá un cron job:

```bash
crontab -e
```

```cron
# Sincronizar catalog status cada hora
0 * * * * cd /ruta/al/proyecto/backend && /ruta/al/venv/bin/python scripts/sync_catalog_status.py >> /var/log/catalog-sync.log 2>&1
```

### Notas

- El script **no hace requests a la API de ML**, solo consulta la BD del webhook
- Los datos son actualizados automáticamente por los webhooks de ML
- Si un MLA no tiene datos en `ml_previews`, se saltea (puede ser porque el webhook aún no se disparó)

## Otros Scripts

### sync_catalog_via_api.py

Script alternativo que usa el endpoint HTTP del backend para sincronizar. Requiere autenticación.

**Uso:**

```bash
python scripts/sync_catalog_via_api.py -u tu_usuario -p tu_password
```

O con token JWT:

```bash
python scripts/sync_catalog_via_api.py -t "tu_token_jwt"
```
