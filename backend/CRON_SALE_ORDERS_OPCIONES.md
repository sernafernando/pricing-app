# ⚡ Sale Orders - Configuraciones para Tiempo Real

## 🎯 Objetivo

Mantener las órdenes de venta **lo más actualizadas posible** (cada 5-10 minutos) para tener visibilidad casi en tiempo real del ERP.

---

## 📊 Opciones de Configuración

### Opción A: BALANCEADA (RECOMENDADA 👍)

**Frecuencia:** Cada 10 minutos  
**Ventana de tiempo:** Últimos 7 días  
**Duración estimada:** ~1-3 minutos  
**Pros:** Equilibrio perfecto entre velocidad y carga del servidor  
**Contras:** Delay máximo de 10 minutos

```bash
*/10 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all >> /var/log/pricing-app/sale_orders.log 2>&1
```

**Cuándo usar:** 
- ✅ Volumen medio-alto de órdenes por hora
- ✅ Necesitas datos casi en tiempo real pero sin saturar el servidor
- ✅ Balance entre freshness y rendimiento

---

### Opción B: AGRESIVA ⚡

**Frecuencia:** Cada 5 minutos  
**Ventana de tiempo:** Últimos 3 días  
**Duración estimada:** ~30-90 segundos  
**Pros:** Datos ultra frescos (delay máximo 5 minutos)  
**Contras:** Mayor carga en el servidor y ERP

```bash
*/5 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 3 >> /var/log/pricing-app/sale_orders.log 2>&1
```

**Cuándo usar:**
- ✅ Alto volumen de órdenes por hora
- ✅ Necesitas datos lo más frescos posible
- ✅ El servidor y ERP pueden manejar la carga extra

---

### Opción C: ULTRA RÁPIDA 🚀

**Frecuencia:** Cada 5 minutos  
**Ventana de tiempo:** Solo hoy (1 día)  
**Duración estimada:** ~20-60 segundos  
**Pros:** Máxima velocidad, mínima carga  
**Contras:** Solo sincroniza órdenes del día actual

```bash
*/5 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 1 >> /var/log/pricing-app/sale_orders.log 2>&1
```

**Cuándo usar:**
- ✅ Solo te importan las órdenes del día
- ✅ Máxima velocidad requerida
- ✅ Tienes otro proceso para backfill histórico

⚠️ **IMPORTANTE:** Si usas esta opción, agregar un segundo cron para sincronizar histórico una vez al día:

```bash
# Backfill histórico - 1 vez al día a las 3 AM (30 días)
0 3 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 30 >> /var/log/pricing-app/sale_orders_backfill.log 2>&1
```

---

### Opción D: CONSERVADORA 🐢

**Frecuencia:** Cada 30 minutos  
**Ventana de tiempo:** Últimos 15 días  
**Duración estimada:** ~3-5 minutos  
**Pros:** Mínima carga, máxima estabilidad  
**Contras:** Delay de hasta 30 minutos

```bash
*/30 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 15 >> /var/log/pricing-app/sale_orders.log 2>&1
```

**Cuándo usar:**
- ✅ Bajo volumen de órdenes
- ✅ No necesitas datos en tiempo real
- ✅ Quieres minimizar carga en el servidor

---

## 📈 Comparación de Opciones

| Opción | Frecuencia | Días | Delay máx | Carga | Duración | Recomendación |
|--------|------------|------|-----------|-------|----------|---------------|
| **A - Balanceada** | 10 min | 7 | 10 min | Media | 1-3 min | ✅ **RECOMENDADA** |
| **B - Agresiva** | 5 min | 3 | 5 min | Alta | 30-90 seg | Para alto volumen |
| **C - Ultra Rápida** | 5 min | 1 | 5 min | Baja | 20-60 seg | Solo órdenes del día |
| **D - Conservadora** | 30 min | 15 | 30 min | Muy baja | 3-5 min | Bajo volumen |

---

## 🎯 ¿Cuál elegir?

### Si tu empresa tiene...

**🔥 100+ órdenes por día:**  
→ **Opción B (Agresiva)** - Cada 5 min, 3 días

**📊 30-100 órdenes por día:**  
→ **Opción A (Balanceada)** - Cada 10 min, 7 días ← **RECOMENDADA**

**📉 < 30 órdenes por día:**  
→ **Opción D (Conservadora)** - Cada 30 min, 15 días

**⚡ Necesitas SOLO tiempo real del día:**  
→ **Opción C (Ultra Rápida)** - Cada 5 min, 1 día + backfill nocturno

---

## 🔧 Instalación

### 1. Elegir opción y agregar al cron

```bash
crontab -e
```

Copiar la línea de la opción elegida.

### 2. Crear directorio de logs

```bash
sudo mkdir -p /var/log/pricing-app
sudo chown $(whoami):$(whoami) /var/log/pricing-app
```

### 3. Probar manualmente antes de agregar al cron

```bash
cd /var/www/html/pricing-app/backend
source venv/bin/activate

# Probar con 1 día (rápido)
time python -m app.scripts.sync_sale_orders_all --days 1

# Ver cuánto tarda, si es < 1 minuto, podes usar cada 5 min
# Si tarda 2-3 minutos, mejor cada 10 min
```

---

## 📊 Monitoreo

### Ver logs en tiempo real

```bash
tail -f /var/log/pricing-app/sale_orders.log
```

### Ver última ejecución

```bash
tail -20 /var/log/pricing-app/sale_orders.log | grep "COMPLETADA"
```

### Ver duración de las ejecuciones

```bash
grep "Duración:" /var/log/pricing-app/sale_orders.log | tail -10
```

### Ver errores

```bash
grep "❌" /var/log/pricing-app/sale_orders.log | tail -10
```

---

## ⚡ Optimización Avanzada

### Si la sincronización tarda mucho, considerar:

1. **Reducir la ventana de días:**
   ```bash
   # En vez de --days 7, usar --days 3
   python -m app.scripts.sync_sale_orders_all --days 3
   ```

2. **Limitar el horario:**
   ```bash
   # En vez de 6-21, solo 8-18 (horario comercial)
   */10 8-18 * * * ...
   ```

3. **Separar los syncs:**
   ```bash
   # Header y Detail cada 5 min (rápido)
   */5 6-21 * * * ... sync_sale_order_header --days 3
   
   # History cada 30 min (menos crítico)
   */30 6-21 * * * ... sync_sale_order_history --days 7
   ```
   
   ⚠️ Requeriría modificar el script para permitir sync individual por tabla.

---

## 🚨 Troubleshooting

### El script tarda más de 5 minutos

❌ **Problema:** Se solapan ejecuciones del cron

✅ **Solución:** 
- Reducir `--days` (de 7 a 3 o 1)
- Aumentar frecuencia del cron (de 5 min a 10 min)
- Agregar timeout al cron:

```bash
timeout 480 python -m app.scripts.sync_sale_orders_all --days 3
```

### Errores de timeout del ERP

❌ **Problema:** El ERP no responde a tiempo

✅ **Solución:**
- Reducir ventana de días
- Verificar carga del ERP (puede estar sincronizando en horario pico)
- Ajustar timeout en el script (línea `timeout=300.0`)

### Datos desactualizados

❌ **Problema:** Las órdenes tardan más de lo esperado en aparecer

✅ **Verificar:**
1. Que el cron esté corriendo: `grep sale_orders /var/log/syslog | tail`
2. Errores en el log: `grep "❌" /var/log/pricing-app/sale_orders.log`
3. Última ejecución exitosa: `grep "COMPLETADA" /var/log/pricing-app/sale_orders.log | tail -1`

---

## ✅ Recomendación Final

**Para la mayoría de los casos:**

```bash
# Opción A - Balanceada: Cada 10 minutos, últimos 7 días
*/10 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all >> /var/log/pricing-app/sale_orders.log 2>&1
```

**Si necesitas más velocidad:**

```bash
# Opción B - Agresiva: Cada 5 minutos, últimos 3 días
*/5 6-21 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python -m app.scripts.sync_sale_orders_all --days 3 >> /var/log/pricing-app/sale_orders.log 2>&1
```

**Empezar con Opción A, monitorear por 1 día, y ajustar según necesidad.**

---

**Fecha:** 2026-01-21  
**Versión:** 1.0 - Optimizado para tiempo real
