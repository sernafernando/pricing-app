# Costeo de combos en vivo + historial de costos propio

**Creado:** 2026-09-25 · **Estado:** en curso
**TDD:** estricto (config de sesión) · **Runner:** `cd backend && source venv/bin/activate && python -m pytest`
**Estrategia de entrega:** `ask-on-risk` · **Rama base:** `origin/main`

## Problema

El usuario reportó una operación de ML **sin costo congelado**. La investigación encontró tres
cosas, verificadas en código:

1. **Combos sin costear (causa dominante).** Un pack/combo no tiene costo propio: su costo es la
   suma de sus componentes vía `tb_item_association`. El backfill sabe sumarlos
   (`FUENTE_BACKFILL_COMBO`); `congelar()` en vivo no — lee `producto.costo`, lo encuentra nulo y
   sale sin escribir. Cifra medida en el propio código (`costeo_service.py:64-70`):
   **3.470 de 4.249** ventas que el backfill no pudo costear son combos.
2. **El sync real no registra los cambios de costo.** `cost_history_manager.py` existe y su
   docstring dice "Crea registros automáticamente cuando se actualiza el costo en productos_erp",
   pero el único que lo llama es el script manual `sync_costos_faltantes.py`. `erp_sync.py:392`
   pisa `producto_existente.costo` sin registrar nada. El valor anterior se pierde.
3. **Cuando sí registra, escribe en la tabla del ERP.** `crear_registro_historial_costo` inserta en
   `item_cost_list_history` (tabla de GBP) fabricando el id con `max(iclh_id) + 1`. Eso mezcla
   historia real del ERP con escrituras nuestras, y el `max + 1` es una carrera.

## Por qué importa

El costo congelado es la base del markup de una venta. Sin él, `CostoMercaderiaDeduccion` devuelve
`None` para toda la orden (nunca una suma parcial), y eso bloquea el Total Gauss y el markup.

El sync corre cada 5 minutos, así que la ventana en la que se congela un costo desactualizado es
chica. Lo que la hace fea es que es **silenciosa e irreversible**: no queda rastro y, como no
guardamos el valor anterior, después no se puede corregir.

## Alcance autorizado

Autorizado por el usuario: "dale, arrancá con la lógica de combos y usá la lista de costos manager
nuestro pero que sirva de verdad".

**Fuera de alcance** (decisión explícita del usuario, queda para pricing 2 junto con la limpieza de
la base): el registro de costos completo y autosuficiente, con doble fecha (`vigente_desde` /
`observado_at`) y multi-fuente. Ver la observación de Engram `pricing/registro-historico-costos-propio`.

## Tareas

### Parte 1 — Costeo de combos en vivo (esta rama)

- [x] T1 RED: una orden cuyo ítem es un combo con componentes costeados no congela ninguna fila hoy.
- [x] T2 Extraer la resolución de componentes (`_componentes_por_combo`, hoy privada del backfill en
      `backfill_costo_congelado.py:243`) a un lugar compartido, sin duplicar la lógica. Movida a
      `costeo_service.componentes_por_combo` (pública); el backfill la importa en vez de definir su
      propia copia.
- [x] T3 GREEN: `congelar()` suma los componentes cuando el producto no tiene costo propio, con una
      `fuente` distinta (`FUENTE_COMBO = "combo"`) que permite distinguir un costo SUMADO de uno LEÍDO.
- [x] T4 RED/GREEN: si **algún** componente no tiene costo, no se escribe nada — misma disciplina
      all-or-nothing que ya aplica `SKIP_COMBO_COMPONENT_NO_COST` en el backfill. Nunca una suma parcial.
- [x] T5 RED/GREEN: combo con componentes en USD — el tipo de cambio se resuelve una vez, no por
      componente (`usd_rate_cache` memoizado, verificado con un spy de llamadas).
- [x] T6 Verificación por mutación de cada test nuevo: 4 mutaciones aplicadas y revertidas, las 4
      pusieron en rojo el test correspondiente (ver reporte final de la sesión).

### Parte 1b — Guarda del costo cero en el camino del dinero (misma rama)

Hallazgo posterior al commit `8680fd74`: el sync (`erp_sync.py:361`) usa
`convertir_a_numero(producto_data.get("coslis_price", 0))` — default `0`, nunca `None`. Un
producto/combo sin fila de costo en el ERP queda con `producto.costo = 0.0`, JAMÁS `NULL`. El
guard de Parte 1 (`producto.costo is None`) nunca dispara en producción: es código muerto, sus
tests usaban `costo=None`, una forma de dato que el sync nunca produce (fixture inventado, no
capturado).

- [x] T10 RED: tests con `costo=0.0` (la forma real) contra el código de Parte 1 — confirmado en
      rojo antes del fix (ver reporte de la sesión).
- [x] T11 Predicado compartido `tiene_costo_propio(producto)` en `costeo_service.py`
      (`NULL` o `<= 0` → sin costo propio), mismo criterio que `_tiene_precio` del backfill mueve
      a `ItemCostListHistory.iclh_price`. No se pudo compartir código (modelos y columnas
      distintos), sí el criterio.
- [x] T12 Aplicado en los tres lugares: filtro de candidatos a combo en `congelar()`,
      `_resolve_cost` (deja de congelar `costo_unitario_ars == 0` como si fuera real), y
      `_resolver_combo_vivo` (un componente con `costo <= 0` hunde el combo entero).
- [x] T13 Verificación por mutación: 3 mutaciones (revertir cada uno de los 3 puntos a
      `is not None`), las 3 pusieron en rojo el test correspondiente.

**IVA — resuelto**: el dueño del producto decidió "no vendemos exentos", así que un IVA de `0`
se trata igual que un agujero del ERP (misma forma que el costo, razón de negocio distinta).

### Parte 1c — Guarda del IVA cero + pase correctivo (rama `fix/costeo-iva-cero-y-pase-correctivo`)

- [x] T14 RED: test con `iva=0.0` (forma real que escribe `erp_sync.py:362`, default `0`, nunca
      `None`) confirmado en rojo contra el código de Parte 1b.
- [x] T15 Predicado propio `tiene_iva_conocido(producto)` en `costeo_service.py` (`NULL` o `<= 0` →
      IVA desconocido), separado de `tiene_costo_propio` porque la razón de negocio es distinta
      (decisión "no vendemos exentos", no una limitación estructural del ERP); docstring deja
      constancia de la decisión para revisar si algún día cambia.
- [x] T16 Aplicado en `_resolve_cost`, reemplazando el chequeo `producto.iva is None`.
- [x] T17 Verificación por mutación: 2 mutaciones (`is None` en vez del predicado; `>= 0` en vez de
      `> 0` dentro del predicado), las 2 pusieron en rojo el test.
- [x] T18 Script `app/scripts/repair_costo_iva_cero_congelado.py`: borra filas congeladas con
      `costo_unitario_ars <= 0` o `iva_pct <= 0` (mismo criterio del camino en vivo, traducido a las
      columnas congeladas) y re-`congelar()`-ea esos ítems con la lógica actual (combos + guardas).
      Un ítem que sigue sin poder costearse queda SIN fila (hueco visible, no un cero). Reporta por
      motivo: borrado (costo cero / IVA cero / ambos) y hueco (sin vinculación / sin costo ni combo /
      IVA desconocido / otro). Tests: camino feliz (recongela con costo real) + hueco visible.
- [x] T19 Investigado el pipeline de triggers: `ml_order_item_costos` tiene triggers Postgres
      `AFTER INSERT`/`AFTER DELETE` (`app/services/order_metrics/triggers.py:249,265`) que llaman
      `order_metrics_enqueue` — el DELETE + re-INSERT del script disparan el recálculo de
      `ml_order_metrics` solos, sin necesidad de encolar nada a mano.

### Parte 1d — Endurecer el alcance del script correctivo (mismo commit, review posterior)

El review encontró cuatro defectos en `repair_costo_iva_cero_congelado.py`, todos con la misma
raíz: el script borraba por un criterio amplio y reconstruía con `congelar()` (costo de HOY, orden
entera), sin acotar el alcance a lo que en verdad puede repararse sin riesgo.

- [x] T20 **Defecto 1 (pérdida de datos, verificado)**: una fila escrita por el backfill
      (`fuente` en `hist_publicacion`/`hist_sku`/`hist_combo`) con IVA malo tiene un costo
      HISTÓRICO correcto (fechado). El script la borraba y la recongelaba con el costo de HOY.
      Arreglo: `FUENTES_EN_VIVO = {FUENTE_PUBLICACION, FUENTE_SKU, FUENTE_COMBO}` — el script
      SOLO borra/recongela filas con esos `fuente`; una fila `hist_*` queda contada aparte
      (`examined_out_of_scope_backfill`) y completamente intocada. Necesita un re-backfill fechado,
      no este script (deuda declarada abajo).
- [x] T21 **Defecto 2 (escrituras invisibles)**: `congelar()` corría sobre TODOS los ítems de la
      orden, así que un hueco previo (sin fila) de la misma orden se insertaba con el costo actual
      sin figurar en el conteo. Arreglo: se pasa a `congelar()` únicamente los DTOs de las claves
      que este script borró, nunca el set completo de la orden.
- [x] T22 **Defecto 3 (destruye un snapshot irreversible)**: una fila cuyo ítem ya no está en
      `MlOrderItemOps` (cancelación parcial) se borraba igual, aunque el diseño manda que ese
      snapshot "deliberadamente sobrevive al ítem que describe" y no hay forma de recrearla.
      Arreglo: esa fila NO se borra — se cuenta (`examined_out_of_scope_item_gone`) y se reporta
      como intocable, preservando el cero antes que perder el dato para siempre.
- [x] T23 **Defecto 4 (números que no cierran)**: `items_by_key` se armaba por `(item_id,
      variation_id)` sin `order_id`, así que dos órdenes con el mismo MLA se pisaban. Arreglo:
      la clave ahora es `(order_id, item_id, variation_id)` en todo el script. Identidad aritmética
      verificada con test: `examined == recongelados + huecos + examined_out_of_scope_backfill
      + examined_out_of_scope_item_gone`.
- [x] T24 Prolijidad: se sacaron `Any`/`ProductoERP` sin usar, se corrigió el comentario obsoleto
      ("Run without `--dry-run`" → el flag real es `--apply`) y el docstring de módulo (el ejemplo
      "Run" tenía dos veces el mismo comando).
- [x] T25 5 tests RED nuevos (uno por defecto + uno de identidad aritmética + uno de colisión de
      clave), confirmados en rojo contra el código anterior, luego GREEN. Cuidado especial con la
      aserción en el test del defecto 3: no alcanza con contar filas (borra+reinserta da el mismo
      conteo en los dos casos), hay que afirmar el VALOR que sobrevive.

### Parte 2 — Historial de costos propio (rama aparte, con migración)

- [ ] T7 Tabla propia para el historial de costos (migración Alembic). Deja de escribirse en la
      tabla de GBP y desaparece el `max(iclh_id) + 1`.
- [ ] T8 `erp_sync` registra el cambio cuando detecta que el costo cambió, en el mismo punto donde
      ya compara el hash.
- [ ] T9 Migrar `sync_costos_faltantes` a la tabla nueva.

## Criterios de aceptación

- Una venta de un combo con todos sus componentes costeados queda con costo congelado.
- Una venta de un combo con algún componente sin costo NO queda con un costo inventado ni parcial.
- Se puede distinguir, mirando la fila, si el costo fue leído o sumado.
- La suite de backend sigue verde y `ruff format app/` limpio (CI exige formato sobre `app/`).

## Deuda declarada (no se cierra acá)

- El hueco del propio docstring de `congelar()`: una orden que no congeló nada solo se reintenta si
  ML vuelve a tocarla. Si ML nunca lo hace, la venta queda sin costo para siempre.
- La carrera venta-vs-sync: se cierra recién con la Parte 2.
- **Filas ya congeladas con costo cero en producción** (deuda nueva, Parte 1b): `ml_order_item_costo`
  es INSERT-only (`ON CONFLICT DO NOTHING`), así que las filas escritas ANTES de este fix con
  `costo_unitario_ars = 0` para un combo quedan mintiendo — la guarda solo previene casos nuevos.
  Corregirlas necesita un pase correctivo separado (recongelar esos `order_id`/`item_id` con la
  lógica nueva), fuera de alcance de esta rama. NO implementado.
- La raíz del problema (`erp_sync.py:361`, default `0` en vez de `None` para `coslis_price`) queda
  SIN arreglar a propósito: sería más correcto ahí, pero otros consumidores de `producto.costo`
  pueden estar asumiendo `0` y el radio de impacto excede este PR. La guarda vive en el camino del
  dinero (`costeo_service.py`), no en la raíz.
- IVA en cero: NO DETERMINADO si hay productos legítimamente exentos — ver sección Parte 1b.
- **Filas `hist_*` (backfill) con IVA congelado en cero** (deuda nueva, Parte 1d): el script
  correctivo las deja completamente afuera a propósito (`examined_out_of_scope_backfill`). Para
  corregirlas hace falta un RE-BACKFILL FECHADO (recorrer `ItemCostListHistory` de nuevo para esas
  filas puntuales, no `congelar()` con el costo de hoy). NO implementado — ver Parte 1d, T20.
- **Filas de ítems ya no vigentes en la orden** (deuda nueva, Parte 1d): si una fila con costo/IVA
  cero corresponde a un ítem que salió de `MlOrderItemOps` (cancelación parcial), el script la deja
  intacta (`examined_out_of_scope_item_gone`) porque no hay forma segura de recrearla. Sigue
  mintiendo un cero para siempre, a propósito — perder el snapshot sería peor. NO implementado.

## Progreso

- 2026-09-25 — Documento creado tras la investigación. Sin código todavía.
- 2026-09-25 — Parte 1 completa (T1-T6). `congelar()` ahora costea combos sumando sus componentes
  vía la ERP `tb_item_association`, resolviendo la lógica compartida con el backfill. Suite completa
  verde (`ml_orders_ingestion` 408, resto del backend 6065 passed/2 skipped, integración 1284
  passed/14 skipped), `ruff format`/`ruff check` limpios. 4 mutaciones verificadas manualmente sobre
  los 4 tests nuevos (suma de qty, all-or-nothing, memoización de TC, `fuente` distinguible) — las 4
  rompieron el test correspondiente.
- 2026-09-25 — Parte 1b: guarda del costo cero. 3 tests RED nuevos con `costo=0.0` (forma real de
  dato) confirmados en rojo contra el código de Parte 1, luego GREEN con `tiene_costo_propio()`
  aplicado en los 3 puntos (filtro de candidatos, `_resolve_cost`, `_resolver_combo_vivo`).
  3 mutaciones verificadas, las 3 rompieron su test. Suite `ml_orders_ingestion` 411 passed (408+3).
  IVA investigado, NO tocado — NO DETERMINADO si hay exentos legítimos, queda para el usuario.
- 2026-09-27 — Parte 1c: guarda del IVA cero (`tiene_iva_conocido`, mismo criterio `<=0`/`NULL`,
  razón de negocio distinta) + pase correctivo (`repair_costo_iva_cero_congelado.py`). RED con
  `iva=0.0` confirmado, GREEN aplicado, 2 mutaciones verificadas. Script borra+recongela filas con
  costo o IVA congelados en cero; hueco visible si sigue sin poder costearse. Confirmado con
  evidencia de código que el trigger Postgres de `ml_order_item_costos` dispara el recálculo de
  métricas solo (no hace falta encolar a mano). Suite completa verde: `ml_orders_ingestion` 416
  passed (412+4), resto del backend 6085 passed/2 skipped, integración 1294 passed/14 skipped,
  `ruff format`/`ruff check` limpios sobre `app/`.
- 2026-09-27 — Parte 1d: el review adversarial encontró 4 defectos en el script correctivo (borraba
  filas del backfill con costo histórico correcto, insertaba filas invisibles fuera del alcance
  borrado, destruía snapshots irrecuperables de ítems cancelados, y el reporte no cerraba
  numéricamente por colisión de clave sin `order_id`). Acotado el alcance del script por
  construcción: `FUENTES_EN_VIVO` restringe borrado/recongelado a los `fuente` que escribe el
  camino en vivo; `congelar()` recibe solo las claves borradas, nunca la orden entera; una fila sin
  ítem vigente no se borra; la clave incluye `order_id`. 5 tests RED confirmados antes del fix,
  luego GREEN. `python -m pytest tests/scripts/ tests/services/ml_orders_ingestion/ -q`: 498
  passed. `python -m pytest tests/ -q --ignore=tests/integration`: 6092 passed, 2 skipped (483s).
  `ruff format app/ && ruff check app/`: limpio (reformateó 1 archivo). Deuda nueva declarada:
  re-backfill fechado para filas `hist_*` con IVA cero, y filas de ítems ya cancelados que quedan
  con cero para siempre.
