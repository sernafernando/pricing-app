# Performance Baseline — Módulo Compras (Fase 7.9)

Documento vivo: baseline de performance de las queries y servicios críticos
del módulo. Ejecutar contra **DB de producción** o réplica para obtener
números confiables.

> **Estado actual**: documento inicial. Las mediciones reales se agregan
> durante F8 (deploy) cuando haya acceso a la réplica readonly con el
> dataset completo (45 proveedores activos, 234 compras en 30 días,
> ~458k filas en `tb_commercial_transactions`).

## Endpoints / queries a medir

### 1. `v_facturas_compra_vigentes` — scan completo

**Ejecutar**:

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM v_facturas_compra_vigentes
WHERE supp_id = 18 AND ct_date >= CURRENT_DATE - INTERVAL '60 days';
```

**Threshold esperado**: < 200ms con `supp_id` indexado.
**Acción si falla**: revisar índices en `tb_commercial_transactions` —
agregar `idx_ct_supp_date (supp_id, ct_date DESC)` si no existe.
Verificar que el CTE de contrapartes no hace full scan.

### 2. `distribuir_fifo` — 100 pedidos pendientes

**Escenario**: OP con `modo=a_cuenta` y 100 pedidos pendientes en CC del
proveedor.

**Acción**:

```python
from app.services import ordenes_pago_service
import time
t0 = time.perf_counter()
ordenes_pago_service.distribuir_fifo(db, op_id=X)
print(f"Duración: {(time.perf_counter() - t0) * 1000:.2f}ms")
```

**Threshold esperado**: < 500ms para 100 pedidos. Más allá de eso, perfil
con `cProfile` y decidir si vale la pena bulk-update vs loop por pedido.

### 3. Cron de reconciliación — 45 proveedores activos

**Escenario**: `reconciliar_cc_proveedor` corre para todos los proveedores
activos en el cron diario.

**Measurement**: medir en prod con logs timestamped.

**Threshold esperado**: < 60s total. Si excede, paralelizar por proveedor
con `concurrent.futures.ThreadPoolExecutor(max_workers=5)` — cada
proveedor es idempotente e independiente.

### 4. Listar OPs paginado (endpoint)

```bash
curl -w "%{time_total}\n" -o /dev/null -s \
  "http://localhost:8000/api/administracion/compras/ordenes-pago?page=1&page_size=50" \
  -H "Authorization: Bearer $TOKEN"
```

**Threshold esperado**: < 300ms al p95.

## Índices ya definidos (baseline)

De las migraciones Alembic de F1-F5:

- `pedidos_compra (empresa_id, proveedor_id, estado, created_at)`
- `ordenes_pago (empresa_id, proveedor_id, estado, fecha_emision)`
- `compras_numeracion (tipo, empresa_id, anio)` — unique
- `imputaciones (proveedor_id, origen_tipo, origen_id)`
- `imputaciones (destino_tipo, destino_id)`
- `cc_proveedor_movimientos (proveedor_id, empresa_id, moneda, fecha)`
- `compras_eventos (tipo, entidad_tipo, entidad_id, created_at)`

## Indices candidatos si faltan (confirmar en prod)

- `tb_commercial_transactions (supp_id, ct_date DESC)` — para la vista
  vigentes y matching forward.
- `tb_commercial_transactions (supp_id, ct_docnumber)` — para el anti-dup.

## Acciones pendientes para F8

- [ ] Correr los 4 benchmarks contra la réplica de producción.
- [ ] Si la vista excede 200ms, agregar índice y rerun.
- [ ] Si `distribuir_fifo` excede 500ms en 100 pedidos, profilear con
      `py-spy` y decidir estrategia (bulk vs loop).
- [ ] Documentar los números reales acá (reemplazar "threshold esperado"
      por "medido").
- [ ] Si el cron excede 60s, paralelizar.
