# Cambio: Price List ID Histórico en Órdenes ML

## Problema Detectado

Las operaciones de MercadoLibre mostraban comisiones incorrectas porque:

1. El query obtenía `prli_id` de `tb_mercadolibre_items_publicados` (pricelist ACTUAL)
2. Si una publicación cambió de "12 cuotas" a "Clásica", TODAS las ventas antiguas mostraban comisión incorrecta
3. No había registro histórico del pricelist al momento de la venta

**Ejemplo del problema:**
- Venta realizada en Enero 2026 con "12 cuotas" (prli_id 14, comisión 34.3%)
- En Marzo 2026 se cambia la publicación a "Clásica" (prli_id 13, comisión 12.5%)
- ❌ La venta de Enero mostraba comisión 12.5% (INCORRECTO)

## Solución Implementada

### 1. Migración de Base de Datos

**Archivo:** `backend/alembic/versions/20260115132009_add_prli_id_to_ml_orders_header.py`

Agrega columna `prli_id` a `tb_mercadolibre_orders_header`:

```sql
ALTER TABLE tb_mercadolibre_orders_header ADD COLUMN prli_id INTEGER;
CREATE INDEX ix_tb_mercadolibre_orders_header_prli_id ON tb_mercadolibre_orders_header (prli_id);
```

### 2. Modificación del Modelo SQLAlchemy

**Archivo:** `backend/app/models/mercadolibre_order_header.py`

```python
prli_id = Column(Integer, index=True)  # Price List ID histórico de la venta
```

### 3. Actualización de Scripts de Sincronización

**Archivos modificados:**
- `backend/app/scripts/sync_ml_orders_incremental.py`
- `backend/app/scripts/sync_ml_orders_2025.py`

Ambos scripts ahora capturan `prli_id` del ERP:

```python
prli_id=to_int(order_json.get("prli_id")),  # Price List histórico
```

### 4. Query de Métricas con Fallback

**Archivo:** `backend/app/api/endpoints/ventas_ml.py`

Nuevo query con prioridad:

```sql
COALESCE(
    tmloh.prli_id,  -- HISTÓRICO: guardado al momento de la venta
    tsoh.prli_id,   -- FALLBACK 1: Sale Order (puede ser NULL)
    CASE WHEN tmloh.mlo_ismshops = TRUE 
        THEN tmlip.prli_id4mercadoshop 
        ELSE tmlip.prli_id 
    END  -- FALLBACK 2: publicación actual
) as pricelist_id
```

**Prioridad:**
1. ✅ `tmloh.prli_id`: Capturado del ERP al momento de sincronizar la orden
2. ✅ `tsoh.prli_id`: Sale Order del ERP (puede ser NULL en órdenes viejas)
3. ⚠️ `tmlip.prli_id`: Pricelist ACTUAL de la publicación (último recurso, puede ser incorrecto)

### 5. Script de Backfill Opcional

**Archivo:** `backend/app/scripts/backfill_ml_orders_prli_id.py`

Script para rellenar `prli_id` en órdenes históricas usando:
1. `tb_ml_publication_snapshots`: busca snapshot más cercano a fecha de venta
2. `tb_mercadolibre_items_publicados`: pricelist actual (último recurso)

⚠️ **ADVERTENCIA:** El backfill es "best effort" y puede no ser 100% preciso.

## Pasos para Aplicar el Cambio

### 1. Ejecutar Migración

```bash
cd /var/www/html/pricing-app/backend
source venv/bin/activate
alembic upgrade head
```

Esto crea la columna `prli_id` en `tb_mercadolibre_orders_header`.

### 2. (Opcional) Backfill de Órdenes Viejas

```bash
python -m app.scripts.backfill_ml_orders_prli_id
```

Esto intenta rellenar el `prli_id` de órdenes históricas usando snapshots.

### 3. Sincronizar Órdenes Nuevas

Las próximas sincronizaciones YA capturarán el `prli_id` correcto:

```bash
python -m app.scripts.sync_ml_orders_incremental
```

### 4. Regenerar Métricas

Regenerar métricas para que usen el nuevo `prli_id`:

```bash
python -m app.scripts.agregar_metricas_ml_local --from-date 2025-01-01
```

## Resultados Esperados

### Antes del Cambio
- ❌ Órdenes con cuotas mostraban comisión de "Clásica" si la publicación cambió
- ❌ Sin registro histórico del pricelist al momento de venta
- ❌ Métricas de rentabilidad incorrectas

### Después del Cambio
- ✅ Nuevas órdenes capturan `prli_id` histórico del ERP
- ✅ Query usa `prli_id` histórico con fallback inteligente
- ✅ Órdenes viejas pueden tener backfill desde snapshots
- ✅ Métricas de rentabilidad correctas

## Impacto en Órdenes Existentes

| Escenario | prli_id | Resultado |
|-----------|---------|-----------|
| Órdenes nuevas (post-migración) | Capturado del ERP | ✅ CORRECTO |
| Órdenes viejas con snapshot cercano | Backfill desde snapshot | ✅ PROBABLE CORRECTO |
| Órdenes viejas sin snapshot | Fallback a publicación actual | ⚠️ PUEDE SER INCORRECTO |
| Órdenes sin publicación en sistema | NULL | ⚠️ NECESITA REVISIÓN MANUAL |

## Notas Técnicas

### ¿Por qué prli_id puede ser NULL?

1. **Órdenes pre-migración:** No tenían la columna, quedan NULL hasta backfill
2. **ERP no envía prli_id:** API del ERP puede no incluir el campo
3. **Publicación eliminada:** Si la publicación no existe en items_publicados

### ¿Qué pasa si prli_id es NULL?

El query usa el fallback en cascada:
```sql
COALESCE(
    tmloh.prli_id,      -- NULL
    tsoh.prli_id,       -- Intenta Sale Order
    tmlip.prli_id       -- Último recurso: publicación actual
)
```

### ¿Cuándo regenerar métricas?

- ✅ Después de ejecutar el backfill
- ✅ Si detectás comisiones incorrectas en el dashboard
- ✅ Después de sincronizar órdenes de periodos históricos

## Testing

### Verificar que la columna existe

```sql
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'tb_mercadolibre_orders_header' 
  AND column_name = 'prli_id';
```

### Ver órdenes con prli_id capturado

```sql
SELECT mlo_id, ml_date_created, prli_id, mlo_ismshops
FROM tb_mercadolibre_orders_header
WHERE prli_id IS NOT NULL
ORDER BY ml_date_created DESC
LIMIT 10;
```

### Contar órdenes sin prli_id

```sql
SELECT COUNT(*) 
FROM tb_mercadolibre_orders_header 
WHERE prli_id IS NULL;
```

### Comparar prli_id histórico vs actual

```sql
SELECT 
    tmloh.mlo_id,
    tmloh.ml_date_created,
    tmloh.prli_id as prli_historico,
    tmlip.prli_id as prli_actual,
    CASE 
        WHEN tmloh.prli_id != tmlip.prli_id THEN '⚠️ DIFERENTE'
        ELSE '✅ IGUAL'
    END as comparacion
FROM tb_mercadolibre_orders_header tmloh
INNER JOIN tb_mercadolibre_orders_detail tmlod 
    ON tmlod.comp_id = tmloh.comp_id 
    AND tmlod.mlo_id = tmloh.mlo_id
INNER JOIN tb_mercadolibre_items_publicados tmlip
    ON tmlip.ml_id = tmlod.ml_id
WHERE tmloh.prli_id IS NOT NULL
ORDER BY tmloh.ml_date_created DESC
LIMIT 20;
```

## Rollback

Si necesitás revertir el cambio:

```bash
cd /var/www/html/pricing-app/backend
alembic downgrade -1
```

Esto elimina la columna `prli_id` y el query vuelve a usar `tmlip.prli_id`.

## Referencias

- Issue original: Comisiones incorrectas en Dashboard Métricas ML
- Fecha: 15/01/2026
- Archivos modificados: 6
- Migración: `20260115132009_add_prli_id_to_ml_orders_header.py`
