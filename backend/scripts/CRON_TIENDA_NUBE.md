# Configuración de Cron para Sincronización de Tienda Nube

## Descripción

El script `sync_tienda_nube.py` sincroniza automáticamente los precios de productos desde Tienda Nube hacia la base de datos de pricing-app.

## Configuración del Cron (cada 15 minutos de 6 AM a 9 PM)

```bash
crontab -e
```

Agregar la siguiente línea:

```
*/15 6-21 * * * cd /var/www/html/pricing-app && /var/www/html/pricing-app/backend/venv/bin/python backend/scripts/sync_tienda_nube.py >> /var/log/sync_tienda_nube.log 2>&1
```

Esto ejecutará la sincronización:
- Cada 15 minutos (en los minutos 0, 15, 30, 45)
- Entre las 6:00 AM y las 9:59 PM
- Todos los días de la semana

## Verificar que el cron está activo

```bash
crontab -l
```

Deberías ver la línea que agregaste.

## Ver el log de ejecución

```bash
tail -f /var/log/sync_tienda_nube.log
```

## Ejecutar manualmente

Si querés ejecutar el script manualmente en cualquier momento:

```bash
cd /var/www/html/pricing-app
python backend/scripts/sync_tienda_nube.py
```

## Notas importantes

1. **Variables de entorno**: El script lee `TN_STORE_ID` y `TN_ACCESS_TOKEN` desde el archivo `.env` del backend
2. **Permisos**: Asegurate de que el usuario que ejecuta el cron tenga permisos de escritura en `/var/log/`
3. **Relación con ERP**: Los productos se relacionan automáticamente con el ERP usando el campo `sku`
4. **Productos inactivos**: Los productos que ya no existen en Tienda Nube se marcan como `activo = false`

## Monitoreo

El script genera logs con:
- 📥 Cantidad de productos obtenidos de Tienda Nube
- 📝 Cantidad de productos nuevos insertados
- 🔄 Cantidad de productos actualizados
- 🔗 Cantidad de productos relacionados con el ERP
- ❌ Errores si los hay

## Ajustar frecuencia

Si en algún momento querés cambiar la frecuencia:

- **Cada 10 minutos (6-21hs)**: `*/10 6-21 * * *`
- **Cada 30 minutos (6-21hs)**: `*/30 6-21 * * *`
- **Cada hora (6-21hs)**: `0 6-21 * * *`
- **Todo el día cada 15 min**: `*/15 * * * *`
