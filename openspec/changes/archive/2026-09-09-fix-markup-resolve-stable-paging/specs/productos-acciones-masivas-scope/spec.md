# productos-acciones-masivas-scope (delta) — stable resolve paging

## ADDED Requirements

### Requirement: Resolve paging uses stable item_id order

Client resolve MUST request `orden_campos=item_id` and `orden_direcciones=asc` on every paged `listar` call used to build the Acciones masivas write-set.

#### Scenario: Listar params include stable order

- GIVEN any `filtrosActivos` (including empty)
- WHEN `buildListarParamsFromFiltros` / resolve builds listar params
- THEN params MUST include `orden_campos` = `item_id` and `orden_direcciones` = `asc`

### Requirement: Resolve dedupes IDs and fails closed on mismatch always when Total is finite

Resolved IDs MUST be unique (`Set` / equivalent). When `totalProductos` is a finite number, resolved unique count MUST equal that Total whether or not filters are active. Empty resolve without filters MAY succeed (empty catalog). Empty resolve with active filters MUST still fail closed.

#### Scenario: Duplicate page rows become detectable mismatch

- GIVEN `totalProductos` = 3 and listar returns the same `item_id` twice across pages then a third distinct id (unique length 2)
- WHEN resolve completes
- THEN it MUST throw mismatch (not return a silently wrong write-set)

#### Scenario: Unfiltered finite Total still checks mismatch

- GIVEN no active filters and `totalProductos` = 10
- AND resolve collects 9 unique IDs
- WHEN resolve completes
- THEN it MUST throw mismatch

### Requirement: Resolve page loop has a finite ceiling

The resolve page loop MUST stop after a bounded max pages derived from expected Total / page size (with small margin), failing closed if exceeded.

#### Scenario: Full pages without total do not loop forever

- GIVEN listar always returns a full page and `total` is null/absent
- AND `totalProductos` implies a small page budget
- WHEN resolve runs
- THEN it MUST stop within `maxPages` and fail closed rather than hang
