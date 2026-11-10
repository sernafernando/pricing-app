# Gestión Full Planificación tools

Objective: Planificación gains gestor bulk reset (override+Qty PM), tienda filter, sortable headers, and top-1-by-sales filter.
Branch: `feat/gestion-full-planificacion-tools` (from `upstream/main`)
Delivery: `ask-on-risk` (forecast >400 authored lines → chain)
Test runner: backend `pytest` focused modules; frontend `vitest run` only named files (no full suite)

## Specs

S1. Bulk reset: gestor-only (`gestion_full.gestor`) action clears **all** stored overrides **and** all Qty PM / `pm_ready` rows so planning starts from zero. PMs must not bulk-clear. Quote: "borrar la carta override actual de todos" + "borrar qty PM tambien" + "solo lo tienen los que tienen permiso de gestion full completo, los pms no pueden borrar masivamente" + "el responsable general del proceso completo" (= gestor).

S2. Tienda filter: filter Planificación to MLAUs / inventory_ids of the selected official store(s). Quote: "filtro de tienda para filtrar solo los MLAUs inventory_ids de la tienda que corresponda".

S3. Sortable headers: plan table column headers can sort. Quote: "agregar a las cabeceras la posibilidad de ordenarse".

S4. Top-1 sales filter: on top of already active filters, show only the **top 1** publication by the selected sales metric. Selector: 7d / 30d × Full / Colecta+Flex. Quote: "filtrar a partir de los filtros ya activos, que solo se vean las publicaciones con mas ventas (con un selector de 7d, 30d y full y colecta+flex)" + "mostrasr el top 1".

## Tasks

- T1 S1 — route: inline — Bulk reset API+UI+tests+ayuda slice — done `e052c8b77` (PR 1/2)
- T2 S2 — route: inline — Tienda filter (CTE + FE chips) — pending
- T3 S3-S4 — route: inline — Sort + top_by params + FE — pending
- T4 docs/PR — route: inline — novedad + PR(s) per delivery strategy — pending (PR1 opened)

## Log

L1. User: "necesitaria que agregaramos en la seccion de planificacion algo para borrar la carta override actual de todos, y necesitaria tener un filtro de tienda para filtrar solo los MLAUs inventory_ids de la tienda que corresponda habria que agregar a las cabeceras la posibilidad de ordenarse y por ultimo filtrar a partir de los filtros ya activos, que solo se vean las publicaciones con mas ventas (con un selector de 7d, 30d y full y colecta+flex) son pedidos que estimo son simples, no se si entran enuna sola pr, se entendieron todos los requerimientos?"

L2. User: "mostrasr el top 1 respecto de tu pregunta, y por las dudas borrar para empezar de cero bora qty PM tambien y solo lo tienen los que tienen permiso de gsetion full completo, los pms no pueden borrar masivamente, de acuerdo?"

L3. User: "si correcto, el responsable general del proceso completo" (= `gestion_full.gestor`).

L4. Explorer: store filter must be inside `_LINKED_CTE` before DISTINCT ON (`ml_items.official_store_id`); Qty PM clear = delete `pm_ready`; reuse Publicaciones `tiendas` CSV pattern; sort/top_by are list SQL contracts.

L5. 2026-11-10 Fernando #2168 PASS advisories incorporated: DB-backed plan-reset postgres test; modal/ayuda/novedad say global wipe (not filter-scoped); FE distinguishes 403 vs generic reset error.
