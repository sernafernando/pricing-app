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

## Progreso

- 2026-09-25 — Documento creado tras la investigación. Sin código todavía.
- 2026-09-25 — Parte 1 completa (T1-T6). `congelar()` ahora costea combos sumando sus componentes
  vía la ERP `tb_item_association`, resolviendo la lógica compartida con el backfill. Suite completa
  verde (`ml_orders_ingestion` 408, resto del backend 6065 passed/2 skipped, integración 1284
  passed/14 skipped), `ruff format`/`ruff check` limpios. 4 mutaciones verificadas manualmente sobre
  los 4 tests nuevos (suma de qty, all-or-nothing, memoización de TC, `fuente` distinguible) — las 4
  rompieron el test correspondiente.
