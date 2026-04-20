# Módulo de Compras — Checklist post-deploy (24h + 48h)

> **Cuándo usarlo:** durante las primeras 48 horas tras aplicar el deploy
> de v1 a producción.
> **Dueño:** responsable del deploy (ops/backend).
> **Objetivo:** detectar regresiones temprano, antes de que el módulo
> acumule datos inconsistentes.

Cada ítem debe chequearse objetivamente. Anotar en la columna de
resultado: ✓ OK / ✗ FALLA / — N/A, con timestamp.

---

## Fase A — T+0 a T+1h (smoke inmediato tras restart)

### Migraciones y seeds

- [ ] `alembic current` imprime `compras_014_vfactvig (head)`.
  - Comando: `cd backend && alembic current`
  - Resultado esperado: una sola línea con `compras_014_vfactvig`.
- [ ] `SELECT COUNT(*) FROM tb_sale_document` retorna **≥ 43**.
  - Comando: `psql -c "SELECT COUNT(*) FROM tb_sale_document;"`
- [ ] Los 2 permisos críticos existen con `es_critico = true`:
  - `administracion.aprobar_ordenes_compra`
  - `administracion.ejecutar_pagos`
  - Comando: `SELECT codigo, es_critico FROM permisos WHERE codigo IN (...)`
- [ ] Cajas USD activas = 1 por empresa mapeada:
  - Comando:
    ```sql
    SELECT empresa_id, COUNT(*) FROM cajas
    WHERE moneda='USD' AND activo=true GROUP BY empresa_id;
    ```
  - Esperado: 1 fila por cada `empresa_id` en `EMPRESA_A_COMP_BRA_MAP`
    (1 y 2 según config actual).

### Servicios

- [ ] Backend responde `GET /api/administracion/compras/health` con
      `status: "ok"` y `catalogos.tb_sale_document: 43` (o más).
- [ ] Nginx sirve la ruta `/administracion/compras` (200 → index.html del frontend).
- [ ] Logs del backend no muestran errores 500 en los últimos 5 min
      (`journalctl -u pricing-backend --since "5 min ago" | grep ERROR`).

### Frontend

- [ ] `/administracion/compras` carga en < 2s sin errores JS en consola.
- [ ] Navbar muestra el dropdown "Administración" con entrada "Compras"
      para usuarios con `ver_ordenes_compra`.
- [ ] Para un usuario SIN ningún permiso del módulo → no ve el dropdown
      (o no ve la entrada "Compras").

---

## Fase B — T+1h a T+6h (permisos + primer uso real)

### Asignación de permisos (manual post-deploy)

- [ ] Admin asignó `administracion.aprobar_ordenes_compra` al rol acordado
      (ej. GERENTE).
- [ ] Admin asignó `administracion.ejecutar_pagos` al rol acordado
      (ej. ADMIN / tesorería).
- [ ] Validar con el script:
      ```bash
      python -m app.scripts.verificar_permisos_compras
      ```
      Esperado: `✅ Todos los permisos críticos tienen al menos una asignación.`

### Primer uso — pedido de prueba controlado

Ejecutar **con un usuario piloto** (PM + aprobador + tesorero coordinados):

- [ ] PM crea pedido de prueba con JUKEBOX (supp_id=18) → número
      `P-XX-2026-00001` generado.
- [ ] Pedido se ve en la tabla del tab Pedidos con estado BORRADOR.
- [ ] PM envía a aprobación → estado PENDIENTE_APROBACION.
- [ ] Aprobador ve el pedido y lo aprueba → estado APROBADO.
- [ ] Verificar en `cc_proveedor_movimientos` que se insertó 1 DEBE:
      ```sql
      SELECT * FROM cc_proveedor_movimientos
      WHERE entidad_tipo='pedido_compra' AND entidad_id=<pedido_id>;
      ```
- [ ] PM crea OP específica imputando al pedido → número `OP-XX-2026-00001`.
- [ ] Tesorería paga la OP desde caja ARS → estado PAGADA.
- [ ] Verificar los **5 artefactos post-pago** (REQ-CAJ-001):
  1. 1 `CajaMovimiento` egreso por el monto total.
  2. 1 `CajaDocumento` con `entidad_tipo='orden_pago'` + `entidad_id`.
  3. N filas en `cc_proveedor_movimientos` HABER.
  4. N filas en `imputaciones`.
  5. Eventos en `compras_eventos` para la OP y el pedido.
- [ ] Navegar de Caja → click "Ver OP" en el egreso → redirige al tab
      OPs con la OP correcta filtrada.
- [ ] Saldo CC del proveedor = 0 (el DEBE del aprobado se canceló con el HABER del pago).

---

## Fase C — T+6h a T+24h (cron + sync ERP)

### Cron de reconciliación (03:00 AM)

- [ ] El cron corrió a las 03:00 AM Argentina (verificar `/var/log/compras/reconciliacion.log`):
      ```bash
      tail -50 /var/log/compras/reconciliacion.log
      ```
      Esperado: una corrida completa con `✓ Reconciliación OK` o
      `divergencias detectadas: N` (N pequeño aceptable el primer día).
- [ ] `cc_reconciliacion_log` tiene al menos 1 fila con `fecha_corrida = hoy`.
- [ ] Si hubo divergencias: revisar cada una en el tab Reconciliación,
      validar que sean esperadas (primer día suele tener drift normal).

### Hook de matching ERP inline

- [ ] `sync_commercial_transactions_guid.py` corrió al menos 6 veces en
      la última hora (cada 10 min):
      ```bash
      grep "sync_commercial_transactions" /var/log/syslog | tail -10
      ```
- [ ] El hook NO logueó errores 500 ni excepciones:
      ```bash
      grep -i "error\|traceback" /var/log/compras/matching.log | tail -20
      ```
      Esperado: 0 líneas.
- [ ] `MAX(ct_date)` en `tb_commercial_transactions` está dentro de las
      últimas 24h.

### Vista SQL

- [ ] `SELECT COUNT(*) FROM v_facturas_compra_vigentes` retorna > 0 y
      se resuelve en < 500ms:
      ```sql
      EXPLAIN ANALYZE SELECT COUNT(*) FROM v_facturas_compra_vigentes;
      ```
- [ ] Tab Catálogo SD → alerta de faltantes = 0 (o lista acotada
      investigable).

---

## Fase D — T+24h a T+48h (monitoring extendido)

### Concurrencia de numeración

- [ ] `pg_stat_activity` no muestra queries `wait_event='Lock'` sostenidos
      sobre `numeracion_contadores`:
      ```sql
      SELECT pid, state, wait_event, query, now() - query_start AS duracion
      FROM pg_stat_activity
      WHERE query LIKE '%numeracion_contadores%'
        AND state = 'active'
        AND now() - query_start > interval '5 seconds';
      ```
      Esperado: 0 filas. Bajo volumen <100 compras/día no debería haber contention.
- [ ] `pg_locks` no muestra locks exclusivos retenidos > 5s:
      ```sql
      SELECT * FROM pg_locks WHERE relation='numeracion_contadores'::regclass;
      ```

### Errores 500 y alertas

- [ ] Logs del backend de las últimas 24h: 0 errores 500 sobre rutas
      `/api/administracion/compras/*`:
      ```bash
      journalctl -u pricing-backend --since "24 hours ago" | grep "ERROR.*compras"
      ```
- [ ] Alertas del sistema: 0 alertas bloqueantes nuevas relacionadas a
      compras (banner rojo en frontend).
- [ ] Notificaciones a usuarios con `ver_cuentas_corrientes`: llegaron
      correctamente si hubo divergencias.

### Métricas de uso

- [ ] Al menos 2 pedidos reales creados en producción (fuera del piloto).
- [ ] Al menos 1 OP pagada exitosamente.
- [ ] Tab Reconciliación métricas visibles y calculadas:
      - `dias_consecutivos_sin_divergencia` ≥ 0.
      - `cobertura_porcentaje` calculada (puede ser baja el primer día).

### Performance-baseline (muestreo)

Medir los 4 benchmarks documentados en
`openspec/changes/modulo-compras/performance-baseline.md` contra prod
real (o réplica readonly). Actualizar el archivo con los números medidos:

- [ ] `SELECT COUNT(*) FROM v_facturas_compra_vigentes` → tiempo real medido.
- [ ] `distribuir_fifo(100 pedidos)` → tiempo real medido.
- [ ] Cron reconciliación (~45 proveedores) → tiempo real medido.
- [ ] `GET /ordenes-pago?page=1&page_size=100` → tiempo real medido.

---

## Rollback — criterios de decisión

Abortar y revertir SI se cumple alguno:

- [ ] Errores 500 continuos en endpoints de compras (> 5% de requests).
- [ ] `cc_proveedor_movimientos` quedó inconsistente (saldos negativos
      donde no corresponde, o movs sin entidad_id).
- [ ] `numeracion_contadores` genera duplicados (ver si hay alguna
      colisión de PK en `pedidos_compra.numero` o `ordenes_pago.numero`).
- [ ] Cron de reconciliación falla 3 días seguidos sin que sea por datos.
- [ ] Divergencias sistemáticas imposibles de justificar (> 20 proveedores
      con delta > 10x tolerancia).

Procedimiento de rollback: ver `openspec/changes/modulo-compras/deploy-setup.md` §Rollback plan.

---

## Cierre — ¿el deploy se considera estable?

Cuando **todos los ítems de las Fases A..D** están ✓ (o justificadamente
— por ejemplo N/A porque no hubo OPs reales todavía) → marcar el deploy
como **estable** y archivar el change con `sdd-archive`.

Firmar abajo con nombre + fecha:

```
Deploy cerrado por: _______________________
Fecha: ____________________________________
Comentarios / excepciones: _______________
____________________________________________
```

---

## Checklist resumen

### Fase A (T+0..T+1h)
- [ ] Migraciones head correcta
- [ ] Seeds aplicados (43 sd_id, 2 permisos, cajas USD)
- [ ] Health OK
- [ ] Frontend carga sin errores

### Fase B (T+1h..T+6h)
- [ ] Permisos asignados a roles
- [ ] Flujo completo de prueba pedido→OP→pago
- [ ] Link "Ver OP" desde caja funciona
- [ ] 5 artefactos post-pago OK

### Fase C (T+6h..T+24h)
- [ ] Cron reconciliación corrió a las 03:00
- [ ] Hook matching ERP sin errores
- [ ] Vista SQL responde < 500ms

### Fase D (T+24h..T+48h)
- [ ] Sin contention en numeracion_contadores
- [ ] 0 errores 500 en 24h
- [ ] ≥ 2 pedidos reales + 1 OP pagada
- [ ] Performance-baseline actualizado
