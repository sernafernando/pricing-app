# ML activity — un evento de envío no es una orden

## Problema (medido en producción, 2026-09-30)

`ml_ops_divergence` tiene 393 deudas `activity_unresolved` abiertas y
creciendo (329 a la mañana, 338 a la tarde, 393 a la noche). La pantalla de
Ventas ML las muestra como "N ventas no pudieron ingresar".

**No falta ninguna venta.** Diagnóstico:

- Muestra de 30 consultada contra el proxy: 30 de 30 devuelven
  `HTTP 404 {"error":"order_not_found","message":"Order do not exists"}` en
  0,2 s. Es ML contestando, no un timeout ni el proxy.
- 337 de las 393 son el `shipping_id` de una orden que SÍ tenemos. Los ids
  tienen 11 dígitos (`48137554327`); un order_id real tiene 16 (`2000…`).
- En la tabla `webhooks` del bridge, cada uno es un evento
  `topic=shipments`, `resource=/shipments/48137554327` (y a veces
  `topic=flex-handshakes`, `resource=/flex/sites/MLA/shipments/<id>/…`).

## Causa

`activity_receiver_service.drain_activity` llama a `get_activity(since=…)`
SIN filtro de topics, y `_collect_new_order_ids` toma `event.get("order_id")`
de TODOS los eventos. Para un evento de envío ese campo trae el id del envío.
El receptor le pide a ML `/orders/<id_de_envío>`, ML contesta 404, y queda
anotado como deuda. El docstring del módulo lo asumía textual: "an activity
event carries only an `order_id`".

Nadie reintenta esas deudas y ningún camino las cierra: solo se acumulan.

## Arreglo (decidido)

- El receptor decide por el `resource`, que dice QUÉ es el id; no por el
  campo `order_id`, que para un envío trae otra cosa.
- `/orders/<id>` → como hoy.
- Un evento de envío NO se descarta: se traduce a su pedido con
  `ml_orders_ops.shipping_id` (UNA consulta en bloque por página, CERO
  llamadas extra a ML) y se refresca ese pedido. Es para lo que sirve el
  evento: enterarse de que el envío cambió.
- Envío sin pedido en la base todavía → se ignora SIN anotar deuda. El evento
  de la orden va a llegar, y el sweep lo cubre igual.
- Cualquier otro resource → se ignora sin anotar deuda.
- Las deudas falsas existentes se autolimpian en la pasada del sweep, con la
  misma lógica que `_clear_resolved_unresolved_debts`: si el id es el
  `shipping_id` de un pedido que tenemos, no es una venta faltante.

Fuera de alcance: que `get_order` distinga 404 de error transitorio. Sigue
siendo una mejora válida, pero NO es la causa de estas deudas.

## Tareas

- [x] T1 — Clasificar eventos por `resource`. Test con eventos reales:
      `orders_v2`, `shipments`, `flex-handshakes`, y uno de otro topic.
- [x] T2 — Evento de envío → pedido vía `shipping_id`, en bloque por página.
      Test: el pedido se refresca; ningún `get_order` con un id de envío.
- [x] T3 — Envío sin pedido → sin deuda. Test explícito.
- [x] T4 — Autolimpieza de las deudas que son `shipping_id`. Test de
      seguridad: una deuda cuyo id NO es un shipping_id conocido NO se toca.
- [x] T5 — Tests contra Postgres para la consulta nueva.

## Checks

- `python -m pytest tests/ -q -p no:randomly` SOLA (dos suites de Postgres en
  paralelo contra la misma base se pisan)
- `ruff format app/ tests/ && ruff check app/ tests/`

## Estado

Implementado 2026-09-30, sin commitear (a la espera del parent).

Evidencia (TDD):
- RED inicial contra el código viejo: `assert 48137554327 not in [48137554327]`
  (se llamaba `get_order` con el id del envío). 19 tests nuevos en rojo antes
  de implementar (13 por el receptor, 4 por la limpieza, 1 sweep, más Postgres).
- Mutaciones, cada una pone rojo al menos un test:
  M1 envío tratado como orden; M2 envíos descartados; M3 sin dedup de las
  órdenes traducidas; M4 otros resources caen al campo `order_id`; M5 limpieza
  SIN filtro de pertenencia (tests de seguridad rojos, SQLite y Postgres);
  M6 limpieza sin fijar kind/field; M7 el sweep no llama a la limpieza;
  M8 traducción de a una consulta por envío (test Postgres cuenta sentencias).
- Tests Postgres reales (ids de 16 y 11 dígitos):
  `test_activity_receiver_shipments_postgres.py`.
- Tocado de paso: `tests/conftest.py` `pg_orders_ops_engine` no llamaba a
  `_restore_pristine_pg_types`, y `order_id` (PK BigInteger) quedaba Integer
  (`integer out of range` con ids reales). Sumado ese restore.
- Rama puesta al día con origin/main (fast-forward) para traer 3cc7c215.
