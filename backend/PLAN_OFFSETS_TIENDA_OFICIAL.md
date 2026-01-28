# Plan: Implementar Filtro de Tienda Oficial en Offsets de Rentabilidad

## Contexto

Actualmente, cuando filtrás por tienda oficial en la tab de Rentabilidad, los offsets se calculan sobre **TODAS** las operaciones, no solo las de la tienda filtrada. Esto es incorrecto porque:

1. Los límites de offsets (max_unidades, max_monto_usd) se están calculando globalmente
2. Los montos de offsets mostrados no corresponden solo a la tienda filtrada
3. Las tablas de consumo precalculadas (`offset_grupo_consumo`, `offset_individual_consumo`) no tienen el campo de tienda oficial

## Objetivo

Hacer que los offsets se calculen correctamente cuando hay filtro de tienda oficial:
- Los límites deben respetarse **por tienda** (no globalmente)
- Los montos de offset mostrados deben corresponder solo a la tienda filtrada
- Los consumos precalculados deben incluir tienda oficial para consultas rápidas

---

## ✅ COMPLETADO (Hoy 27/01/2025)

### 1. Migración de Base de Datos
- ✅ Creada migración `20250127_add_tienda_oficial_fields.py`
- ✅ Agrega `mlp_official_store_id` a `ml_ventas_metricas`
- ✅ Agrega `tienda_oficial` a `offset_grupo_consumo`
- ✅ Agrega `tienda_oficial` a `offset_individual_consumo`
- ✅ Crea índices para mejorar performance de queries

### 2. Modelos SQLAlchemy
- ✅ Actualizado `MLVentaMetrica` con campo `mlp_official_store_id`
- ✅ Actualizado `OffsetGrupoConsumo` con campo `tienda_oficial`
- ✅ Actualizado `OffsetIndividualConsumo` con campo `tienda_oficial`

---

## 🔴 PENDIENTE (Para mañana)

### 3. Aplicar Migración y Popular Datos Históricos

**Archivo:** `/home/mns/proyectos/pricing-app/backend/alembic/versions/20250127_add_tienda_oficial_fields.py`

**Pasos:**
```bash
cd backend
# Verificar que la migración esté bien
alembic upgrade head

# Esto va a crear las columnas pero dejarlas en NULL
```

**IMPORTANTE:** Después de aplicar la migración, hay que popular `ml_ventas_metricas.mlp_official_store_id` con los datos históricos. Ver script en paso 4.

---

### 4. Script de Backfill para `ml_ventas_metricas.mlp_official_store_id`

**Crear:** `backend/scripts/backfill_ml_ventas_tienda_oficial.py`

Este script debe:
1. Leer todas las filas de `ml_ventas_metricas` donde `mlp_official_store_id IS NULL`
2. Para cada fila:
   - Buscar en `mercadolibre_items_publicados` el `mlp_official_store_id` usando `mla_id = CAST(mlp_id AS TEXT)`
   - Actualizar `ml_ventas_metricas.mlp_official_store_id`
3. Hacer commits cada 1000 filas para no trabar la base

**Pseudocódigo:**
```python
# Batch de 1000
while True:
    ventas = db.query(MLVentaMetrica).filter(
        MLVentaMetrica.mlp_official_store_id.is_(None),
        MLVentaMetrica.mla_id.isnot(None)
    ).limit(1000).all()
    
    if not ventas:
        break
    
    for venta in ventas:
        # Buscar tienda oficial
        item = db.query(MercadoLibreItemPublicado).filter(
            cast(MercadoLibreItemPublicado.mlp_id, String) == venta.mla_id
        ).first()
        
        if item:
            venta.mlp_official_store_id = item.mlp_official_store_id
    
    db.commit()
    print(f"Procesadas {len(ventas)} ventas")
```

**Tiempo estimado:** Depende del tamaño de la tabla, probablemente 10-30 minutos.

---

### 5. Modificar Script que Genera `ml_ventas_metricas`

**Buscar:** Script que inserta/actualiza `ml_ventas_metricas` (probablemente en `backend/app/scripts/`)

**Archivos candidatos:**
- `backend/app/scripts/sync_ml_*.py`
- Buscar scripts que hagan `INSERT INTO ml_ventas_metricas`

**Modificación:**
- Al insertar nuevas filas en `ml_ventas_metricas`, incluir el JOIN con `mercadolibre_items_publicados` para popular `mlp_official_store_id`

```sql
-- Ejemplo de cómo debería quedar el INSERT
INSERT INTO ml_ventas_metricas (..., mlp_official_store_id)
SELECT ..., mlip.mlp_official_store_id
FROM ml_orders_header moh
LEFT JOIN mercadolibre_items_publicados mlip 
    ON CAST(mlip.mlp_id AS TEXT) = moh.mla_id
WHERE ...
```

---

### 6. Modificar Queries de Consumo en `rentabilidad.py`

**Archivo:** `backend/app/api/endpoints/rentabilidad.py`

#### 6.1. Función `calcular_consumo_grupo_desde_tabla()`

**Líneas:** ~275-291

**Cambio:**
```python
# ANTES
def calcular_consumo_grupo_desde_tabla(grupo_id, desde_dt, hasta_dt):
    consumo = db.query(
        func.sum(OffsetGrupoConsumo.cantidad).label('total_unidades'),
        ...
    ).filter(
        OffsetGrupoConsumo.grupo_id == grupo_id,
        OffsetGrupoConsumo.fecha_venta >= desde_dt,
        OffsetGrupoConsumo.fecha_venta < hasta_dt
    ).first()

# DESPUÉS
def calcular_consumo_grupo_desde_tabla(grupo_id, desde_dt, hasta_dt, tienda_oficial=None):
    query = db.query(
        func.sum(OffsetGrupoConsumo.cantidad).label('total_unidades'),
        ...
    ).filter(
        OffsetGrupoConsumo.grupo_id == grupo_id,
        OffsetGrupoConsumo.fecha_venta >= desde_dt,
        OffsetGrupoConsumo.fecha_venta < hasta_dt
    )
    
    if tienda_oficial:
        query = query.filter(OffsetGrupoConsumo.tienda_oficial == tienda_oficial)
    
    consumo = query.first()
```

**Lugares donde se llama:** Buscar todas las llamadas a `calcular_consumo_grupo_desde_tabla()` y agregar el parámetro `tienda_oficial`.

---

#### 6.2. Función `calcular_offset_grupo_en_tiempo_real()`

**Líneas:** ~293-365

**Cambio:** Agregar filtro por `tienda_oficial` en las queries SQL.

```python
# ANTES (línea ~323)
query_ml = text(f"""
    SELECT
        COALESCE(SUM(cantidad), 0) as total_unidades,
        COALESCE(SUM(costo_total_sin_iva), 0) as total_costo
    FROM ml_ventas_metricas
    WHERE ({where_filtros})
    AND fecha_venta >= :desde AND fecha_venta < :hasta
""")

# DESPUÉS
def calcular_offset_grupo_en_tiempo_real(grupo_id, offset, desde_dt, hasta_dt, tc, tienda_oficial=None):
    ...
    
    # Agregar filtro de tienda oficial al WHERE
    filtro_tienda = ""
    if tienda_oficial:
        filtro_tienda = f"AND mlp_official_store_id = {int(tienda_oficial)}"
    
    query_ml = text(f"""
        SELECT
            COALESCE(SUM(cantidad), 0) as total_unidades,
            COALESCE(SUM(costo_total_sin_iva), 0) as total_costo
        FROM ml_ventas_metricas
        WHERE ({where_filtros})
        AND fecha_venta >= :desde AND fecha_venta < :hasta
        {filtro_tienda}
    """)
```

**También modificar la query de `ventas_fuera_ml_metricas`** si tienen tienda oficial (probablemente no, pero verificar).

---

#### 6.3. Función `calcular_consumo_individual_desde_tabla()`

**Líneas:** ~481-497

**Cambio:** Igual que 6.1, agregar parámetro `tienda_oficial` y filtrar.

```python
def calcular_consumo_individual_desde_tabla(offset_id, desde_dt, hasta_dt, tienda_oficial=None):
    query = db.query(
        func.sum(OffsetIndividualConsumo.cantidad).label('total_unidades'),
        ...
    ).filter(
        OffsetIndividualConsumo.offset_id == offset_id,
        OffsetIndividualConsumo.fecha_venta >= desde_dt,
        OffsetIndividualConsumo.fecha_venta < hasta_dt
    )
    
    if tienda_oficial:
        query = query.filter(OffsetIndividualConsumo.tienda_oficial == tienda_oficial)
    
    consumo = query.first()
```

---

#### 6.4. Actualizar TODAS las llamadas a esas funciones

**Buscar en el archivo:**
- `calcular_consumo_grupo_desde_tabla(` → agregar `, tienda_oficial`
- `calcular_offset_grupo_en_tiempo_real(` → agregar `, tienda_oficial`
- `calcular_consumo_individual_desde_tabla(` → agregar `, tienda_oficial`

**IMPORTANTE:** El valor de `tienda_oficial` viene del parámetro del endpoint `obtener_rentabilidad()`, que ya lo agregamos en el commit anterior.

---

### 7. Modificar Script que Genera Consumos de Offsets

**Buscar:** Script que inserta en `offset_grupo_consumo` y `offset_individual_consumo`

**Archivos candidatos:**
- Buscar en `backend/app/scripts/` o `backend/scripts/`
- Buscar por `INSERT INTO offset_grupo_consumo` o `OffsetGrupoConsumo(`

**Modificación:**
- Al insertar consumos, popular el campo `tienda_oficial` desde `ml_ventas_metricas.mlp_official_store_id`

```python
# Ejemplo
consumo = OffsetGrupoConsumo(
    grupo_id=grupo_id,
    offset_id=offset.id,
    id_operacion=venta.id_operacion,
    tipo_venta='ml',
    fecha_venta=venta.fecha_venta,
    item_id=venta.item_id,
    cantidad=venta.cantidad,
    monto_offset_aplicado=monto_offset,
    tienda_oficial=str(venta.mlp_official_store_id) if venta.mlp_official_store_id else None  # <-- AGREGAR
)
```

---

### 8. Script de Backfill para Consumos Históricos (OPCIONAL)

**Crear:** `backend/scripts/backfill_offset_consumo_tienda_oficial.py`

Este script es **opcional** si querés tener datos históricos correctos en las tablas de consumo.

**Qué hace:**
1. Leer todos los consumos donde `tienda_oficial IS NULL`
2. Para cada consumo:
   - Si es tipo 'ml', buscar en `ml_ventas_metricas` usando `id_operacion`
   - Obtener el `mlp_official_store_id`
   - Actualizar `tienda_oficial` en el consumo
3. Hacer commits cada 1000 filas

**Pseudocódigo:**
```python
# Para grupo
consumos = db.query(OffsetGrupoConsumo).filter(
    OffsetGrupoConsumo.tienda_oficial.is_(None),
    OffsetGrupoConsumo.tipo_venta == 'ml'
).limit(1000).all()

for consumo in consumos:
    venta = db.query(MLVentaMetrica).filter(
        MLVentaMetrica.id_operacion == consumo.id_operacion
    ).first()
    
    if venta and venta.mlp_official_store_id:
        consumo.tienda_oficial = str(venta.mlp_official_store_id)

db.commit()

# Repetir para OffsetIndividualConsumo
```

**IMPORTANTE:** Si no hacés este backfill, los offsets solo se calcularán correctamente para ventas **nuevas** (posteriores a la implementación). Las ventas históricas no tendrán tienda oficial en los consumos precalculados, así que se calcularán en tiempo real (más lento).

---

## 9. Testing

### Casos de prueba:

1. **Sin filtro de tienda oficial:**
   - Debe funcionar igual que antes
   - Los offsets se calculan sobre todas las operaciones
   - Los límites son globales

2. **Con filtro de tienda oficial = 57997 (Gauss):**
   - Solo debe mostrar operaciones de Gauss
   - Los offsets solo deben aplicar sobre operaciones de Gauss
   - Los límites deben calcularse solo sobre Gauss
   - Si un offset ya llegó al límite en otras tiendas pero no en Gauss, debe seguir aplicando en Gauss

3. **Con filtro de tienda oficial + marca:**
   - Debe filtrar por ambos (tienda Y marca)
   - Los offsets deben calcularse sobre ese subset

4. **Comparar con/sin backfill:**
   - Sin backfill: operaciones históricas se calculan en tiempo real (más lento)
   - Con backfill: operaciones históricas usan tablas precalculadas (más rápido)

---

## 10. Cronograma Sugerido

### Día 1 (mañana):
1. ✅ Aplicar migración (`alembic upgrade head`)
2. ✅ Ejecutar backfill de `ml_ventas_metricas.mlp_official_store_id` (script del paso 4)
3. ✅ Modificar script que genera `ml_ventas_metricas` (paso 5)
4. ✅ Testing básico: verificar que las nuevas ventas tengan `mlp_official_store_id`

### Día 2:
5. ✅ Modificar `calcular_consumo_grupo_desde_tabla()` (paso 6.1)
6. ✅ Modificar `calcular_offset_grupo_en_tiempo_real()` (paso 6.2)
7. ✅ Modificar `calcular_consumo_individual_desde_tabla()` (paso 6.3)
8. ✅ Actualizar todas las llamadas (paso 6.4)
9. ✅ Testing intermedio: probar endpoint de rentabilidad con filtro de tienda

### Día 3:
10. ✅ Modificar script que genera consumos de offsets (paso 7)
11. ✅ Ejecutar backfill de consumos históricos (paso 8) - **OPCIONAL**
12. ✅ Testing completo (paso 9)
13. ✅ Revisar performance y optimizar si es necesario

---

## Archivos Clave a Modificar

### Backend:
- ✅ `backend/alembic/versions/20250127_add_tienda_oficial_fields.py` (ya creado)
- ✅ `backend/app/models/ml_venta_metrica.py` (ya modificado)
- ✅ `backend/app/models/offset_grupo_consumo.py` (ya modificado)
- ✅ `backend/app/models/offset_individual_consumo.py` (ya modificado)
- 🔴 `backend/app/api/endpoints/rentabilidad.py` (PENDIENTE - muchos cambios)
- 🔴 Script que genera `ml_ventas_metricas` (PENDIENTE - buscar)
- 🔴 Script que genera consumos de offsets (PENDIENTE - buscar)

### Scripts nuevos a crear:
- 🔴 `backend/scripts/backfill_ml_ventas_tienda_oficial.py`
- 🔴 `backend/scripts/backfill_offset_consumo_tienda_oficial.py` (opcional)

---

## Notas Importantes

1. **Performance:** Las queries con JOIN a `mercadolibre_items_publicados` pueden ser lentas. Los índices que creamos en la migración deberían ayudar.

2. **Datos NULL:** Si una venta no tiene `mla_id` o no se encuentra en `mercadolibre_items_publicados`, el campo `mlp_official_store_id` quedará en NULL. Esas ventas se tratarán como "sin tienda oficial" y solo se incluirán cuando NO hay filtro de tienda.

3. **Límites de Offsets:** Con este cambio, los límites se van a calcular **por tienda**. Si un offset tiene `max_unidades = 100`, eso significa 100 unidades POR TIENDA, no 100 unidades en total. Si esto no es lo que querés, hay que repensar la lógica.

4. **Retrocompatibilidad:** El código debe seguir funcionando sin filtro de tienda oficial. Todas las funciones que modificamos tienen el parámetro `tienda_oficial=None` para mantener compatibilidad.

5. **Ventas Fuera de ML:** Las tablas `ventas_fuera_ml_metricas` probablemente NO tienen tienda oficial (no aplica). Verificar que las queries que las usan no se rompan.

---

## Riesgos y Contingencias

### Riesgo 1: Migración tarda mucho
- **Mitigación:** Ejecutar en horario de bajo tráfico
- **Contingencia:** Hacer rollback con `alembic downgrade -1`

### Riesgo 2: Backfill tarda mucho / traba la base
- **Mitigación:** Hacer batches pequeños (1000 filas), commits frecuentes
- **Contingencia:** Pausar el script, hacer el resto en horario de bajo tráfico

### Riesgo 3: Performance degrada mucho con los JOINs
- **Mitigación:** Monitorear queries lentas, crear índices adicionales si es necesario
- **Contingencia:** Desnormalizar más (agregar campo `tienda_oficial` también en `ml_orders_header`)

### Riesgo 4: Lógica de límites no funciona como se espera
- **Mitigación:** Testing exhaustivo con casos extremos
- **Contingencia:** Agregar feature flag para desactivar filtro por tienda en offsets

---

## Checklist Final

Antes de pushear a producción:

- [ ] Migración aplicada correctamente
- [ ] Backfill de `ml_ventas_metricas.mlp_official_store_id` completado
- [ ] Script de generación de métricas actualizado
- [ ] Todas las funciones de cálculo de offsets modificadas
- [ ] Script de generación de consumos actualizado
- [ ] Backfill de consumos históricos ejecutado (opcional)
- [ ] Testing: sin filtro de tienda funciona igual que antes
- [ ] Testing: con filtro de tienda, offsets se calculan correctamente
- [ ] Testing: límites de offsets funcionan por tienda
- [ ] Testing: performance aceptable (queries < 2s)
- [ ] Documentación actualizada
- [ ] Commit con mensaje descriptivo
- [ ] PR revisado y aprobado

---

## Contacto y Dudas

Si hay dudas durante la implementación:
1. Revisar este plan
2. Revisar el código existente de offsets para entender la lógica
3. Testear en ambiente de desarrollo antes de producción
4. Si algo no está claro, mejor preguntar que asumir

**No hay espacio para parches rápidos acá.** Esto tiene que quedar bien desde el principio porque afecta cálculos de plata.

---

**Éxito con la implementación! 💪**
