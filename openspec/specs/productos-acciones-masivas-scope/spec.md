# productos-acciones-masivas-scope Specification

## Purpose

Acciones masivas (markup ML + config-cuotas) write-set = full active-filter result (or full listing if unfiltered); modal count matches that set; confirm if target > 50; fail-closed filter resolve; 100-ID chunks. Out of scope: Calcular Web/PVP, selection XOR, raising `item_ids` max_length.

## Requirements

### Requirement: Write-set equals full active filter result

The Acciones masivas write-set MUST equal the full population matching active listing filters (`totalProductos` / “Mostrando X de N”), NOT the page buffer alone. Filtered “Mostrando 50 de 200” → apply MUST target 200. Unfiltered listing total N → apply MUST target N.

#### Scenario: Paginated filtered listing applies full filtered set

- GIVEN filters with totalProductos = 200 and page buffer = 50 (“Mostrando 50 de 200”)
- WHEN Acciones masivas apply completes (after any required confirm)
- THEN write-set size MUST be 200 (not 50)

#### Scenario: Unfiltered listing applies full listing total

- GIVEN no active filters and totalProductos = N
- WHEN Acciones masivas apply completes (after any required confirm)
- THEN write-set size MUST be N

### Requirement: Modal target count matches resolved write-set

The modal MUST show a target count equal to the resolved write-set. It MUST NOT derive that count solely from `productos.length` when it differs from the resolved set. Copy MUST NOT claim “página actual” / page-only visibles as scope when the write-set is the full filtered or full unfiltered set.

#### Scenario: Modal count matches filtered total not page buffer

- GIVEN filters with totalProductos = 18
- WHEN Acciones masivas modal opens
- THEN modal target count MUST be 18
- AND MUST NOT show catalog-scale (~4291) inconsistent with Total

### Requirement: Modal open must not desync listing buffer from filtered stats

Opening Acciones masivas MUST NOT widen/reload `productos` to an unfiltered or larger-than-filter set while Total/stats stay filtered. After open or cancel without apply, Total/stats and filter semantics MUST match the pre-open filtered state.

#### Scenario: Open modal preserves filtered Total vs buffer sync

- GIVEN filtered Total = 18
- WHEN user opens Acciones masivas then closes without applying
- THEN Total/stats MUST remain 18
- AND `productos` MUST NOT widen to unfiltered catalog scale while stats stay 18

### Requirement: Confirm apply when target count exceeds 50

If resolved target count > 50, the system MUST require explicit confirmation before any write. If count ≤ 50, the system MUST NOT require that confirm gate.

#### Scenario: Target greater than 50 requires confirm

- GIVEN resolved write-set size = 200
- WHEN user initiates apply
- THEN confirmation MUST appear before writes
- AND apply MUST NOT proceed until confirmed

#### Scenario: Target at most 50 skips confirm gate

- GIVEN resolved write-set size = 18
- WHEN user initiates apply
- THEN the >50 confirm gate MUST NOT be required

### Requirement: Fail-closed filter resolve and chunked apply

Filter/ID resolve MUST fail closed (sibling masivos class): missing/unsafe resolve MUST NOT silently widen to catalog scale. Apply MUST chunk at most 100 item IDs per request. MUST NOT change Calcular Web/PVP/recalcular-cuotas; MUST NOT add selection XOR; MUST NOT raise `item_ids` max_length beyond chunking.

#### Scenario: Unresolvable filters do not widen write-set

- GIVEN active filters that cannot resolve to a safe ID set
- WHEN Acciones masivas would apply
- THEN system MUST fail closed
- AND MUST NOT apply to unfiltered catalog scale

#### Scenario: Large apply uses 100-ID chunks

- GIVEN resolved write-set size = 200
- WHEN apply proceeds after confirmation
- THEN writes MUST use chunks of at most 100 IDs

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
