# Migración: Items Sin MLA Banlist

## Descripción
Esta migración crea la tabla `items_sin_mla_banlist` para gestionar los items que no deben aparecer en el reporte de productos sin MLA asociado.

## Ejecutar la migración

### En el servidor de producción:

```bash
# Conectarse a PostgreSQL
psql -U pricing_user -d pricing_db -h localhost

# Ejecutar el script
\i /var/www/html/pricing-app/backend/migrations/create_items_sin_mla_banlist.sql
```

### En local:

```bash
# Conectarse a PostgreSQL
psql -U postgres -d pricing_db

# Ejecutar el script
\i /ruta/completa/al/archivo/create_items_sin_mla_banlist.sql
```

## Verificar la migración

```sql
-- Ver la estructura de la tabla
\d items_sin_mla_banlist

-- Verificar que los índices se crearon
\di items_sin_mla_banlist*

-- Verificar que la tabla está vacía (inicialmente)
SELECT COUNT(*) FROM items_sin_mla_banlist;
```

## Rollback (si es necesario)

```sql
-- Eliminar la tabla y todos sus datos
DROP TABLE IF EXISTS items_sin_mla_banlist CASCADE;
```

## Estructura de la tabla

| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | SERIAL | Primary key auto-incremental |
| item_id | INTEGER | ID del item/producto (único) |
| motivo | TEXT | Razón para agregar a banlist (opcional) |
| usuario_id | INTEGER | ID del usuario que agregó el item |
| fecha_creacion | TIMESTAMP | Fecha de creación del registro |

## Funcionalidad

Esta tabla permite:
1. Marcar productos que NO deben aparecer en el reporte de "Items sin MLA"
2. Almacenar el motivo por el cual se excluyeron
3. Auditar quién y cuándo se agregó cada item a la banlist
4. Restaurar items removiéndolos de la banlist
