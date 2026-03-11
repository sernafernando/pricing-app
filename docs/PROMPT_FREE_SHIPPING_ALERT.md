# CONTEXTO: Alertas de free_shipping_error desde ml-webhook

Tenemos un servicio webhook (`ml-webhook`) que recibe notificaciones de MercadoLibre y almacena previews enriquecidos en PostgreSQL. Para cada item (topics: `items`, `items_prices`) se extraen datos de shipping y del sale_term `ALL_METHODS_REBATE_PRICE`.

Cuando un item tiene `free_shipping: true` pero su precio de rebate (el precio real con todos los descuentos aplicados) es **menor a $33.000**, se marca como `free_shipping_error: true`. Esto indica que el producto tiene envío gratis activado pero probablemente no debería, porque el precio es demasiado bajo para absorber el costo logístico.

---

## OPCIÓN 1: Consumo directo desde PostgreSQL (RECOMENDADO)

Ambos sistemas comparten la misma base de datos PostgreSQL.

**Conexión:**
```
postgresql://mluser:GaussDB1214@localhost:5432/mlwebhook
```

### Tabla: `ml_previews`

Los campos de shipping están dentro de la columna `extra_data` (jsonb):

| Campo en extra_data | Tipo | Descripción |
|---------------------|------|-------------|
| `free_shipping` | boolean | Si el item tiene envío gratis activado |
| `free_shipping_error` | boolean | **`true` = ALERTA: envío gratis con precio rebate < $33.000** |
| `logistic_type` | string | Tipo logístico (`cross_docking`, `fulfillment`, `drop_off`, etc.) |
| `shipping_mode` | string | Modo de envío (`me2`, `me1`, `not_specified`, etc.) |
| `shipping_tags` | array | Tags de shipping (`mandatory_free_shipping`, `self_service_in`, etc.) |
| `rebate_value_name` | string | Precio rebate como texto (ej: `"32500.00"`) |
| `rebate_value_struct_number` | number | Precio rebate como número desde `value_struct.number` |
| `rebate_values_name` | string | Precio rebate como texto desde `values[0].name` |
| `rebate_values_struct_number` | number | Precio rebate como número desde `values[0].struct.number` |

### Query: Items con free_shipping_error (las alertas)

```sql
SELECT
    p.resource,
    p.title,
    p.price,
    p.currency_id,
    p.brand,
    p.status,
    p.extra_data->>'free_shipping' AS free_shipping,
    p.extra_data->>'rebate_value_struct_number' AS rebate_price,
    p.extra_data->>'rebate_values_struct_number' AS rebate_price_alt,
    p.extra_data->>'logistic_type' AS logistic_type,
    p.extra_data->>'shipping_mode' AS shipping_mode,
    p.extra_data->'shipping_tags' AS shipping_tags,
    p.last_updated
FROM ml_previews p
WHERE p.resource LIKE '/items/MLA%'
  AND (p.extra_data->>'free_shipping_error')::boolean = true
ORDER BY p.last_updated DESC;
```

### Query: Todos los items con envío gratis para auditoría

```sql
SELECT
    p.resource,
    p.title,
    p.price,
    p.extra_data->>'free_shipping' AS free_shipping,
    p.extra_data->>'free_shipping_error' AS free_shipping_error,
    p.extra_data->>'rebate_value_struct_number' AS rebate_price,
    p.extra_data->>'rebate_values_struct_number' AS rebate_price_alt
FROM ml_previews p
WHERE p.resource LIKE '/items/MLA%'
  AND (p.extra_data->>'free_shipping')::boolean = true
ORDER BY (p.extra_data->>'rebate_value_struct_number')::numeric ASC NULLS LAST;
```

---

## OPCIÓN 2: Consumo vía HTTP API

### Listar webhooks de items con preview incluido

```
GET https://ml-webhook.gaussonline.com.ar/api/webhooks?topic=items&limit=100&offset=0
```

Cada evento en la respuesta trae `db_preview.extra_data` con los campos de shipping y rebate documentados arriba. Filtrá los que tengan `extra_data.free_shipping_error === true`.

### Consultar un item específico en tiempo real (JSON)

Para items viejos que no tengan `extra_data` enriquecido, o para refrescar datos:

```
GET https://ml-webhook.gaussonline.com.ar/api/ml/render?resource=/items/MLA123456789&format=json
```

Esto devuelve el JSON crudo de la API de ML con el token manejado internamente. Buscá en `sale_terms` el objeto con `"id": "ALL_METHODS_REBATE_PRICE"` y en `shipping.free_shipping` para armar la lógica de alerta manualmente.

---

## LÓGICA DE ALERTAS SUGERIDA

### Regla principal
```
SI free_shipping_error == true → GENERAR ALERTA
```

### Datos disponibles para la alerta
- **Título del item**: `ml_previews.title`
- **Precio publicado**: `ml_previews.price`
- **Precio rebate (real)**: `extra_data.rebate_value_struct_number` (o `rebate_values_struct_number` como fallback)
- **Item link**: el `resource` es `/items/MLAxxxxxxxxx`, el permalink se puede armar como `https://articulo.mercadolibre.com.ar/MLAxxxxxxxxx`

### Contexto adicional útil
- `shipping_tags` contiene `"mandatory_free_shipping"` → ML lo fuerza, no es decisión del vendedor
- `logistic_type` = `"fulfillment"` → el producto está en Full, los costos de envío son distintos
- Si `mandatory_free_shipping` está en los tags, la alerta debería indicar que el envío gratis es obligatorio y no se puede quitar, por lo que la solución es **subir el precio** o **revisar si el producto debería estar en esa categoría**
