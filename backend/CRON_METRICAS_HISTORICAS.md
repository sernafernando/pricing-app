# 📊 Backfill de Métricas Históricas - Pricing App

**Fecha:** 2026-01-21  
**Versión:** 1.0  
**Estado:** NUEVO - Pendiente de instalación

---

## 🎯 **Objetivo**

Agregar capas de **backfill histórico** para garantizar que las métricas de ventas (ML, Tienda Nube, Fuera de ML) se mantengan actualizadas incluso cuando:
- Hay devoluciones o cancelaciones de ventas antiguas
- Cambian costos en el ERP (históricos)
- Cambia el tipo de cambio retroactivamente
- Se ajustan comisiones o markups

---

## 🔄 **Estrategia de 4 Capas**

```
┌─────────────────────────────────────────────────────────┐
│  CAPA 1: TIEMPO REAL (cada 5 min, 6-21hs)              │
│  ✅ YA EXISTE - Captura ventas nuevas                  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  CAPA 2: BACKUP DIARIO (cada 30 min, 6-21hs)           │
│  ✅ YA EXISTE - Reprocesa día actual (solo ML)         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  CAPA 3: BACKFILL MENSUAL (diario 5:00 AM) - NUEVO     │
│  🆕 Reprocesa últimos 30 días                          │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  CAPA 4: BACKFILL TRIMESTRAL (Domingos 4:00 AM) - NUEVO│
│  🆕 Reprocesa últimos 90 días                          │
└─────────────────────────────────────────────────────────┘
```

---

## 📋 **Nuevas Líneas de Cron (6 en total)**

### **1. Backfill Mensual (Diario a las 5 AM)**

Reprocesa métricas de los últimos **30 días** cada noche.

```bash
# ML Métricas - Mes actual completo (5:00 AM diario)
0 5 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_ml_local --days 30 >> /var/log/pricing-app/ml_metricas_backfill_30d.log 2>&1

# Tienda Nube Métricas - Mes actual completo (5:15 AM diario)
15 5 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_tienda_nube --days 30 >> /var/log/pricing-app/tn_metricas_backfill_30d.log 2>&1

# Fuera ML Métricas - Mes actual completo (5:30 AM diario)
30 5 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_fuera_ml --days 30 >> /var/log/pricing-app/fuera_ml_metricas_backfill_30d.log 2>&1
```

**¿Por qué 30 días?**
- Captura cambios en ventas del mes actual (devoluciones, ajustes)
- No es pesado (corre en ~3-5 minutos)
- Horario 5 AM evita solapamiento con otros scripts

### **2. Backfill Trimestral (Domingos a las 4 AM)**

Reprocesa métricas de los últimos **90 días** cada domingo.

```bash
# ML Métricas - Últimos 90 días (Domingos 4:00 AM)
0 4 * * 0 cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_ml_local --days 90 >> /var/log/pricing-app/ml_metricas_backfill_90d.log 2>&1

# Tienda Nube Métricas - Últimos 90 días (Domingos 4:20 AM)
20 4 * * 0 cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_tienda_nube --days 90 >> /var/log/pricing-app/tn_metricas_backfill_90d.log 2>&1

# Fuera ML Métricas - Últimos 90 días (Domingos 4:40 AM)
40 4 * * 0 cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_fuera_ml --days 90 >> /var/log/pricing-app/fuera_ml_metricas_backfill_90d.log 2>&1
```

**¿Por qué 90 días?**
- Mantiene actualizado el trimestre completo (clave para reportes trimestrales)
- Corre solo 1 vez por semana (domingo madrugada)
- Horario 4 AM evita conflictos con backfills de 5 AM

---

## ⚙️ **Instalación**

### **Paso 1: Backup del cron actual**
```bash
crontab -l > ~/crontab_backup_metricas_$(date +%Y%m%d_%H%M).txt
```

### **Paso 2: Editar cron**
```bash
EDITOR=nvim crontab -e
```

### **Paso 3: Agregar las 6 líneas nuevas**

Buscar la sección de **MÉTRICAS** y agregar después de las líneas existentes:

```bash
# ============================================
# MÉTRICAS - BACKFILL HISTÓRICO (NUEVOS)
# ============================================

# BACKFILL MENSUAL - Cada noche a las 5:00 AM
# Reprocesa métricas del mes actual completo (captura cambios en ventas, devoluciones, ajustes de costos)

# ML Métricas - Mes actual completo (5:00 AM diario)
0 5 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_ml_local --days 30 >> /var/log/pricing-app/ml_metricas_backfill_30d.log 2>&1

# Tienda Nube Métricas - Mes actual completo (5:15 AM diario)
15 5 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_tienda_nube --days 30 >> /var/log/pricing-app/tn_metricas_backfill_30d.log 2>&1

# Fuera ML Métricas - Mes actual completo (5:30 AM diario)
30 5 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_fuera_ml --days 30 >> /var/log/pricing-app/fuera_ml_metricas_backfill_30d.log 2>&1

# BACKFILL TRIMESTRAL - Domingos a las 4:00 AM
# Reprocesa métricas de los últimos 3 meses (histórico largo para reportes anuales)

# ML Métricas - Últimos 90 días (Domingos 4:00 AM)
0 4 * * 0 cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_ml_local --days 90 >> /var/log/pricing-app/ml_metricas_backfill_90d.log 2>&1

# Tienda Nube Métricas - Últimos 90 días (Domingos 4:20 AM)
20 4 * * 0 cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_tienda_nube --days 90 >> /var/log/pricing-app/tn_metricas_backfill_90d.log 2>&1

# Fuera ML Métricas - Últimos 90 días (Domingos 4:40 AM)
40 4 * * 0 cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_fuera_ml --days 90 >> /var/log/pricing-app/fuera_ml_metricas_backfill_90d.log 2>&1
```

### **Paso 4: Guardar y salir**
```
:wq
```

### **Paso 5: Verificar instalación**
```bash
crontab -l | grep -E "metricas_backfill"
```

Deberías ver **6 líneas** (3 de 30 días + 3 de 90 días).

---

## 🧪 **Testing Manual (Antes de Aplicar al Cron)**

Antes de agregar al cron, probá manualmente cada script para verificar que funcionan:

### **Test 1: ML Métricas (7 días de prueba)**
```bash
cd /var/www/html/pricing-app/backend
/var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_ml_local --days 7
```

### **Test 2: Tienda Nube Métricas (7 días)**
```bash
cd /var/www/html/pricing-app/backend
/var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_tienda_nube --days 7
```

### **Test 3: Fuera ML Métricas (7 días)**
```bash
cd /var/www/html/pricing-app/backend
/var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.agregar_metricas_fuera_ml --days 7
```

**Verificar:**
- ✅ El script corre sin errores
- ✅ Procesa registros correctamente
- ✅ Muestra estadísticas finales (insertados, actualizados, errores)

---

## 📊 **Monitoreo Post-Instalación**

### **1. Verificar logs diarios (backfill 30 días)**

```bash
# ML (corre a las 5:00 AM)
tail -f /var/log/pricing-app/ml_metricas_backfill_30d.log

# Tienda Nube (corre a las 5:15 AM)
tail -f /var/log/pricing-app/tn_metricas_backfill_30d.log

# Fuera ML (corre a las 5:30 AM)
tail -f /var/log/pricing-app/fuera_ml_metricas_backfill_30d.log
```

### **2. Verificar logs semanales (backfill 90 días - Domingos)**

```bash
# ML (corre Domingos 4:00 AM)
tail -f /var/log/pricing-app/ml_metricas_backfill_90d.log

# Tienda Nube (corre Domingos 4:20 AM)
tail -f /var/log/pricing-app/tn_metricas_backfill_90d.log

# Fuera ML (corre Domingos 4:40 AM)
tail -f /var/log/pricing-app/fuera_ml_metricas_backfill_90d.log
```

### **3. Verificar rendimiento**

```bash
# Ver últimas 20 líneas de cada log (resumen final)
tail -20 /var/log/pricing-app/ml_metricas_backfill_30d.log
tail -20 /var/log/pricing-app/tn_metricas_backfill_30d.log
tail -20 /var/log/pricing-app/fuera_ml_metricas_backfill_30d.log
```

Deberías ver algo como:
```
✅ COMPLETADO
Insertados: 0
Actualizados: 1234
Errores: 0
🔔 Notificaciones creadas: 5
```

---

## ⚠️ **Consideraciones de Performance**

### **Tiempos Estimados de Ejecución:**

| Script | 30 días | 90 días |
|--------|---------|---------|
| **ML Métricas** | ~3-5 min | ~10-15 min |
| **Tienda Nube** | ~2-3 min | ~5-8 min |
| **Fuera ML** | ~2-3 min | ~5-8 min |

### **Horarios Elegidos (Sin Solapamiento):**

```
2:00 AM ─── Sale Orders 90d (Domingos)
2:10 AM ─── Commercial Transactions 90d (Domingos)
2:20 AM ─── Customers Hybrid Full (Domingos)
3:00 AM ─── Sale Orders 30d (Diario)
3:05 AM ─── Commercial Transactions 30d (Diario)
3:10 AM ─── ML Items Full (Diario)
4:00 AM ─── ML Métricas 90d (Domingos) ← NUEVO
4:20 AM ─── TN Métricas 90d (Domingos) ← NUEVO
4:40 AM ─── Fuera ML Métricas 90d (Domingos) ← NUEVO
5:00 AM ─── ML Métricas 30d (Diario) ← NUEVO
5:15 AM ─── TN Métricas 30d (Diario) ← NUEVO
5:30 AM ─── Fuera ML Métricas 30d (Diario) ← NUEVO
```

**Todo está espaciado para evitar conflictos de CPU/DB.**

---

## 🎯 **Casos de Uso Reales**

### **Caso 1: Devolución de Producto**
- Cliente devuelve producto vendido hace 15 días
- El script incremental (5 min) NO lo captura porque solo mira últimos 10 minutos
- El backfill mensual (5 AM) SÍ lo captura y actualiza la métrica

### **Caso 2: Ajuste de Costo en ERP**
- Se corrige un costo histórico en `tb_item_cost_list_history`
- Los scripts incrementales NO recalculan ventas viejas
- El backfill trimestral (Domingos 4 AM) recalcula todas las métricas afectadas

### **Caso 3: Cambio de Tipo de Cambio Retroactivo**
- Se ajusta el tipo de cambio de hace 2 semanas
- El backfill mensual (5 AM) recalcula todas las ventas en USD/ARS afectadas

---

## ✅ **Checklist de Implementación**

- [ ] Hacer backup del cron actual
- [ ] Testear los 3 scripts manualmente con `--days 7`
- [ ] Verificar que no hay errores en los tests
- [ ] Agregar las 6 líneas al cron
- [ ] Verificar que las líneas se guardaron correctamente
- [ ] Esperar a la primera ejecución (mañana 5 AM para mensual, próximo domingo 4 AM para trimestral)
- [ ] Monitorear logs la primera semana
- [ ] Ajustar frecuencia si es necesario (ej: cambiar 30 días a 15 días si es muy pesado)

---

## 🚨 **Troubleshooting**

### **Problema: Script se demora mucho (>20 min)**
**Solución:** Reducir días procesados (30 → 15, 90 → 60)

### **Problema: Script falla con timeout de BD**
**Solución:** Agregar índices en las tablas (ver DBA)

### **Problema: Logs muestran errores de permisos**
**Solución:** Verificar que `/var/log/pricing-app/` existe y tiene permisos correctos:
```bash
sudo mkdir -p /var/log/pricing-app
sudo chown gauss:gauss /var/log/pricing-app
```

### **Problema: No se crean notificaciones de markup bajo**
**Solución:** Esto es normal - solo se crean notificaciones en tiempo real (incremental), no en backfills

---

## 📚 **Referencias**

- **Script ML:** `backend/app/scripts/agregar_metricas_ml_local.py`
- **Script TN:** `backend/app/scripts/agregar_metricas_tienda_nube.py`
- **Script Fuera ML:** `backend/app/scripts/agregar_metricas_fuera_ml.py`
- **Cron completo:** `backend/CRON_COMPLETO_OPTIMIZADO.md`

---

**Estado:** ✅ Listo para instalar  
**Próximo paso:** Testear manualmente y agregar al cron
