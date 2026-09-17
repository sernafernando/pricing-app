# Sincronización de Publicaciones de MercadoLibre

Este script sincroniza las publicaciones de MercadoLibre y guarda snapshots en la base de datos para poder comparar las campañas y listas configuradas en ML vs las que tiene el sistema.

## Configuración

### 1. Variables de entorno

Agregar al archivo `.env`:

```env
ML_USER_ID=413658225
```

El access token de MercadoLibre NO se maneja acá: lo posee y refresca
exclusivamente el microservicio `ml-webhook` (única fuente de OAuth), que
persiste el token vigente en su propia tabla `ml_tokens`. Este script (y
`sync_ml_publications_full.py` / `sync_ml_publications_incremental.py`) solo
LEE ese access_token de la DB de ml-webhook vía
`app.services.ml_api_client.MercadoLibreAPIClient` — nunca hace su propio
intercambio de `refresh_token` con ML. Hacerlo rotaría el refresh token e
invalidaría la sesión OAuth de ml-webhook.

### 2. Migración de base de datos

Ejecutar la migración SQL:

```bash
psql -h localhost -U pricing_user -d pricing_db -f backend/migrations/create_ml_publication_snapshots.sql
```

## Uso

### Ejecutar sincronización manual

```bash
cd backend
python -m app.scripts.sync_ml_publications
```

### Automatizar con cron

Agregar a crontab para ejecutar diariamente a las 2 AM:

```cron
0 2 * * * cd /path/to/pricing-app/backend && python -m app.scripts.sync_ml_publications >> /var/log/ml_sync.log 2>&1
```

## Qué hace el script

1. **Lee el access token** de la DB de ml-webhook (nunca lo refresca acá)
2. **Obtiene todos los IDs** de publicaciones usando el método `scan` (sin límite de 1050)
3. **Descarga detalles** en batches de 20 publicaciones
4. **Extrae información clave**:
   - Campaña de cuotas (`INSTALLMENTS_CAMPAIGN`)
   - SKU del seller
   - Precios (price y base_price)
   - Stock y ventas
5. **Guarda en DB** con timestamp para comparar después

## Lógica de campañas

El script aplica la misma lógica que el código original de Google Apps Script:

- Si tiene `INSTALLMENTS_CAMPAIGN`: usa ese valor (ej: `3x_campaign`, `6x_campaign`)
- Si NO tiene campaña pero es `gold_pro`: asigna `6x_campaign`
- Si es `gold_special`: asigna `Clásica`
- Si no tiene campaña: asigna `-`

## Estructura de datos guardados

```sql
ml_publication_snapshots:
  - mla_id: ID de ML (MLA2016945208)
  - title: Título de la publicación
  - price: Precio actual
  - base_price: Precio base (antes de descuentos)
  - installments_campaign: Campaña (3x_campaign, 6x_campaign, etc)
  - seller_sku: SKU configurado en ML
  - item_id: ID del ERP (extraído del SKU)
  - snapshot_date: Fecha del snapshot
```

## Comparación con sistema actual

Para comparar ML vs Sistema, puedes hacer queries como:

```sql
-- Ver diferencias de campaña
SELECT
    s.mla_id,
    s.title,
    s.installments_campaign as ml_campaign,
    -- aquí agregar join con tu tabla de campañas actuales
FROM ml_publication_snapshots s
WHERE s.snapshot_date >= CURRENT_DATE
ORDER BY s.mla_id;
```

## Troubleshooting

### Error: "No se pudo obtener access_token de mlwebhook DB"
- El microservicio ml-webhook no tiene un token vigente en su tabla `ml_tokens`
- Re-autenticar en `{ML_WEBHOOK_BASE_URL}/auth` (el mensaje de error imprime la URL exacta)
- Verificar que `ML_WEBHOOK_DB_URL` esté correctamente configurado en `.env`

### Error: "Token expirado" (HTTP 401 de ML)
- El script invalida el token cacheado y relee una vez desde la DB de ml-webhook
- Si el 401 persiste tras el reintento, el problema está en ml-webhook (su token
  puede haber expirado o haber sido revocado) — no en este script

### Error: "Too many requests"
- El script tiene delays de 0.5s entre batches
- Si persiste, aumentar el delay en el código

## Monitoreo

El script imprime logs detallados:
- Total de IDs obtenidos
- Progreso de batches
- Total de publicaciones guardadas
- Errores específicos por batch

Ejemplo de output:
```
============================================================
SINCRONIZACIÓN DE PUBLICACIONES DE MERCADOLIBRE
============================================================
Inicio: 2025-01-11 02:00:00

Obteniendo IDs de publicaciones para user 413658225...
  Obtenidos 500 IDs hasta ahora...
  Obtenidos 1000 IDs hasta ahora...
✓ Total de publicaciones encontradas: 1234

Procesando 1234 publicaciones en batches de 20...
  Procesados 20/1234 - Guardados: 20
  Procesados 40/1234 - Guardados: 40
  ...
✓ Sincronización completada: 1234 publicaciones guardadas

Fin: 2025-01-11 02:05:30
============================================================
```
