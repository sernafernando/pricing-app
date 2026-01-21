# 🆕 Nuevos Scripts de Sincronización - Configuración Cron

## Resumen

Se crearon 2 nuevos scripts para completar las sincronizaciones faltantes del ERP:

1. **`sync_master_tables_small.py`**: Tablas maestras pequeñas (sucursales, vendedores, etc.)
2. **`sync_sale_orders_all.py`**: Órdenes de venta (header, detail, history)

---

## 📋 Scripts Creados

### 1. sync_master_tables_small.py

**Ubicación:** `/var/www/html/pricing-app/backend/app/scripts/sync_master_tables_small.py`

**Qué sincroniza:**
- ✅ `tbBranch` - Sucursales
- ✅ `tbSalesman` - Vendedores  
- ✅ `tbState` - Estados/Provincias
- ✅ `tbDocumentFile` - Tipos de documento
- ✅ `tbFiscalClass` - Clases fiscales
- ✅ `tbTaxNumberType` - Tipos de número impositivo
- ✅ `tbItemAssociation` - Asociaciones de items

**Frecuencia recomendada:** 2 veces al día (son tablas que cambian poco)

**Duración estimada:** ~2-5 minutos

**Comando:**
```bash
/var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_master_tables_small
```

---

### 2. sync_sale_orders_all.py

**Ubicación:** `/var/www/html/pricing-app/backend/app/scripts/sync_sale_orders_all.py`

**Qué sincroniza:**
- ✅ `tbSaleOrderHeader` - Cabecera de órdenes de venta
- ✅ `tbSaleOrderDetail` - Detalle de órdenes de venta
- ✅ `tbSaleOrderHeaderHistory` - Historial de cambios en header
- ✅ `tbSaleOrderDetailHistory` - Historial de cambios en detail

**Frecuencia recomendada:** Cada 5-10 minutos (para datos casi en tiempo real)

**Duración estimada:** ~1-3 minutos con 7 días (default optimizado)

**Comandos:**
```bash
# Sincronizar últimos 7 días (default - optimizado para ejecuciones frecuentes)
/var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all

# Sincronizar solo hoy (más rápido aún)
/var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 1

# Sincronizar últimos 30 días (para backfill inicial o recuperación)
/var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 30
```

---

## 📝 Configuración de Cron Recomendada

Agregar estas líneas al crontab:

```bash
# ============================================
# NUEVOS SCRIPTS - Sincronizaciones Faltantes
# ============================================

# Tablas maestras pequeñas - 2 veces al día (8:00 y 16:00)
0 8,16 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_master_tables_small >> /var/log/pricing-app/master_tables_small.log 2>&1

# Sale Orders - cada 10 minutos (horario laboral 6-21) - últimos 7 días
*/10 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all >> /var/log/pricing-app/sale_orders.log 2>&1

# ALTERNATIVA más agresiva - cada 5 minutos con solo 3 días (más rápido):
# */5 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 3 >> /var/log/pricing-app/sale_orders.log 2>&1
```

---

## 🔧 Instalación Paso a Paso

### 1. Editar crontab

```bash
crontab -e
```

### 2. Agregar las nuevas líneas al final del archivo

Copiar las líneas del bloque anterior.

### 3. Verificar que se guardaron correctamente

```bash
crontab -l | grep sync_master_tables_small
crontab -l | grep sync_sale_orders_all
```

### 4. Crear directorios de logs si no existen

```bash
sudo mkdir -p /var/log/pricing-app
sudo chown gauss:gauss /var/log/pricing-app  # Reemplazar gauss por tu usuario
```

### 5. Prueba manual (IMPORTANTE antes de agregar al cron)

```bash
# Probar tablas maestras
cd /var/www/html/pricing-app/backend
source venv/bin/activate
python -m app.scripts.sync_master_tables_small

# Probar sale orders
python -m app.scripts.sync_sale_orders_all --days 7
```

---

## 📊 Monitoreo

### Ver logs en tiempo real

```bash
# Tablas maestras
tail -f /var/log/pricing-app/master_tables_small.log

# Sale Orders
tail -f /var/log/pricing-app/sale_orders.log
```

### Ver ejecuciones del cron

```bash
# Ver últimas ejecuciones exitosas
grep "sync_master_tables_small" /var/log/syslog | tail -20
grep "sync_sale_orders_all" /var/log/syslog | tail -20
```

### Ver errores recientes

```bash
# Errores en tablas maestras
grep "❌" /var/log/pricing-app/master_tables_small.log | tail -10

# Errores en sale orders
grep "❌" /var/log/pricing-app/sale_orders.log | tail -10
```

---

## ⚠️ Consideraciones Importantes

### 1. **Duplicaciones en el cron actual**

En tu cron actual hay algunos scripts que SE SOLAPAN con `sync_all_incremental.py`:

```bash
# ⚠️ DUPLICADO: Ya está en sync_all_incremental.py
*/10 6-21 * * * ... sync_commercial_transactions_guid.py --days 7

# ⚠️ DUPLICADO: Ya está en sync_all_incremental.py  
*/15 6-21 * * * ... sync_customers_hybrid.py --minutes 30
```

**Recomendación:** Revisar si realmente necesitas estas sincronizaciones separadas, o si pueden eliminarse del cron.

### 2. **Frecuencia de sync_sale_orders_all**

Para datos **casi en tiempo real**, se configuró para ejecutarse cada 5-10 minutos con ventanas de tiempo optimizadas:

- **Opción A (RECOMENDADA - Balanceada):** Cada 10 minutos con `--days 7` (default)
  ```bash
  */10 6-21 * * * ... sync_sale_orders_all
  ```
  
- **Opción B (Más agresiva):** Cada 5 minutos con `--days 3` (más rápido)
  ```bash
  */5 6-21 * * * ... sync_sale_orders_all --days 3
  ```
  
- **Opción C (Ultra rápida):** Cada 5 minutos con solo 1 día (solo órdenes de hoy)
  ```bash
  */5 6-21 * * * ... sync_sale_orders_all --days 1
  ```

**💡 Recomendación:** Empezar con Opción A (cada 10 min, 7 días). Si necesitas más velocidad, probar Opción B.

### 3. **Orden de ejecución**

Los nuevos scripts **NO dependen** de otros, así que pueden ejecutarse en paralelo con el resto.

Sin embargo, `sync_sale_orders_all` **SÍ necesita** que `tb_item` esté sincronizada (por las foreign keys). Como `sync_all_incremental.py` corre cada 5 minutos, esto no debería ser problema.

---

## 🎯 Scripts que YA EXISTEN pero NO se usan

Estos scripts individuales ya existían en el repo pero no se estaban ejecutando:

- ✅ `sync_branches.py` → Ahora se ejecuta vía `sync_master_tables_small.py`
- ✅ `sync_salesmen.py` → Ahora se ejecuta vía `sync_master_tables_small.py`
- ✅ `sync_states.py` → Ahora se ejecuta vía `sync_master_tables_small.py`
- ✅ `sync_document_files.py` → Ahora se ejecuta vía `sync_master_tables_small.py`
- ✅ `sync_fiscal_classes.py` → Ahora se ejecuta vía `sync_master_tables_small.py`
- ✅ `sync_tax_number_types.py` → Ahora se ejecuta vía `sync_master_tables_small.py`
- ✅ `sync_item_associations.py` → Ahora se ejecuta vía `sync_master_tables_small.py`
- ✅ `sync_sale_order_header.py` → Ahora se ejecuta vía `sync_sale_orders_all.py`
- ✅ `sync_sale_order_detail.py` → Ahora se ejecuta vía `sync_sale_orders_all.py`
- ✅ `sync_sale_order_header_history.py` → Ahora se ejecuta vía `sync_sale_orders_all.py`
- ✅ `sync_sale_order_detail_history.py` → Ahora se ejecuta vía `sync_sale_orders_all.py`

---

## 📈 Impacto Esperado

| Métrica | Antes | Después |
|---------|-------|---------|
| Tablas sincronizadas | 20 | 31 (+11) |
| Cobertura ERP | ~60% | ~95% |
| Scripts en cron | 14 | 16 (+2) |
| Tablas maestras completas | ❌ | ✅ |
| Sale Orders sincronizadas | ❌ | ✅ |

---

## 🚀 Próximos Pasos (Opcional)

Si quieres seguir optimizando, considera:

1. **Agregar Item Serials**: Si usas números de serie
   ```bash
   python -m app.scripts.sync_item_serials
   ```

2. **Tienda Nube Orders**: Si necesitas sincronizar órdenes de Tienda Nube de forma más robusta
   ```bash
   python -m app.scripts.sync_tiendanube_orders
   ```

3. **Proveedores (Suppliers)**: Si trabajas con proveedores y necesitas esa data
   - Crear script similar a los otros para `scriptSupplier`

---

## ✅ Checklist de Validación

Después de agregar al cron, verificar:

- [ ] Los scripts corren sin errores manualmente
- [ ] Los logs se crean en `/var/log/pricing-app/`
- [ ] Las tablas en la DB tienen datos nuevos después de la ejecución
- [ ] No hay colisiones de locks con otros scripts
- [ ] El tiempo de ejecución es aceptable
- [ ] Los errores (si hay) son manejados correctamente

---

## 📞 Troubleshooting

### Error: "Import 'dotenv' could not be resolved"

```bash
cd /var/www/html/pricing-app/backend
source venv/bin/activate
pip install python-dotenv
```

### Error: "No module named 'httpx'"

```bash
pip install httpx
```

### Error: "Table 'tb_branch' doesn't exist"

Ejecutar migraciones de Alembic:
```bash
cd backend
alembic upgrade head
```

### Los scripts no aparecen en los logs

Verificar permisos:
```bash
sudo chmod +x backend/app/scripts/sync_master_tables_small.py
sudo chmod +x backend/app/scripts/sync_sale_orders_all.py
```

---

**Fecha de creación:** 2026-01-21  
**Autor:** Sistema de sincronización Pricing App
