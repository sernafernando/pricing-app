# Design: Batch-Prefetch the N+1 Query Sites in the Rentabilidad/Offset Dashboards

> Change: `dashboard-batch-prefetch`
> Phase: design (architecture-level HOW). Verified against actual code on branch
> `fix/security-quick-wins-1` (line numbers below are current, re-grep before editing).
> No schema change, no migration, no response-shape change.

---

## 1. Architecture approach

**Pattern:** Extract-and-reuse the batch-prefetch idiom already proven inline in
`productos_listing.py` (T-3..T-7) into a small **stateless service module**
(`app/services/offset_resumen_service.py`), then rewrite each N+1 call site to the
canonical shape:

```
collect keys BEFORE the loop → one .in_() query in the service → {key: row} dict → dict.get(key) INSIDE the loop
```

**Layering / boundaries (respects the existing `services/` convention):**

```
endpoints/ (rentabilidad_*, offsets_ganancia/_consumo_*)   ← call sites
        │  import
        ▼
services/offset_resumen_service.py                          ← NEW: pure read helpers
        │  import
        ▼
models/ (OffsetGrupoResumen, OffsetIndividualResumen, OffsetGanancia)
```

The service depends only on models (the standard downward direction). No endpoint
logic moves into the service — only the *fetch-by-key-set* mechanics. All
business/limit logic stays exactly where it is in the endpoints.

### 1.1 The `productos_listing.py` idiom, extracted verbatim

Verified at `productos_listing.py` L692–717 (T-7). The repo's exact idiom:

```python
all_item_ids_page = [r[0].item_id for r in results]          # collect keys before loop
all_pubs = (
    db.query(PublicacionML).filter(PublicacionML.item_id.in_(all_item_ids_page)).all()
    if all_item_ids_page else []                             # empty guard: skip the query
)
pubs_by_item: dict = {}
for pub in all_pubs:
    pubs_by_item.setdefault(pub.item_id, []).append(pub)     # 1:N → setdefault(list)
...
ofertas_by_mla: dict = {}
for oferta in all_ofertas:
    if oferta.mla not in ofertas_by_mla:                     # 1:1 → keep first
        ofertas_by_mla[oferta.mla] = oferta
```

Extracted conventions this change adopts:
- Collect keys into a plain `list`/`set` **before** the loop.
- **Empty guard**: if the key collection is empty, return `{}` / `[]` and **do not
  issue the query** (matches the `if all_item_ids_page else []` guard).
- **1:1** shape → `dict[key] = row`; **1:N** shape → `setdefault(key, []).append(row)`
  or (for "first wins") the `if key not in dict` guard.
- **No `.in_()` chunking.** `productos_listing.py` does not chunk `.in_()`, and neither
  should this change. Justification: these dashboards key off **distinct offset-group
  count** and **distinct individual-offset count**, both bounded by how many offset
  groups/offsets exist in the business (observed: tens, realistically < a few hundred).
  PostgreSQL's bind-parameter ceiling is ~32,767; an `.in_()` of a few hundred ids is
  three orders of magnitude below it. Chunking would be premature complexity. **If a
  future data explosion pushes distinct groups past ~30k this must be revisited** — but
  that is not a current or near-term condition and is called out here so the assumption
  is explicit, not silent.

---

## 2. The new service module — exact signatures

`backend/app/services/offset_resumen_service.py`

```python
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Iterable

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_consumo import OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualResumen


def fetch_resumenes_grupo(
    db: Session, grupo_ids: Iterable[int]
) -> dict[int, OffsetGrupoResumen]:
    """
    Batch-load OffsetGrupoResumen rows keyed by grupo_id.

    Replaces the per-group `OffsetGrupoResumen.filter(grupo_id == x).first()`
    lookups. grupo_id is UNIQUE per resumen row (see model: unique=True), so the
    dict is a safe 1:1 mapping.

    Returns {} without querying when grupo_ids is empty.
    """
    ids = list({gid for gid in grupo_ids if gid is not None})
    if not ids:
        return {}
    rows = db.query(OffsetGrupoResumen).filter(OffsetGrupoResumen.grupo_id.in_(ids)).all()
    return {row.grupo_id: row for row in rows}


def fetch_resumenes_individuales(
    db: Session, offset_ids: Iterable[int]
) -> dict[int, OffsetIndividualResumen]:
    """
    Batch-load OffsetIndividualResumen rows keyed by offset_id.

    Replaces the per-offset `OffsetIndividualResumen.filter(offset_id == x).first()`
    lookups. offset_id is UNIQUE per resumen row (see model: unique=True), safe 1:1.

    Returns {} without querying when offset_ids is empty.
    """
    ids = list({oid for oid in offset_ids if oid is not None})
    if not ids:
        return {}
    rows = (
        db.query(OffsetIndividualResumen)
        .filter(OffsetIndividualResumen.offset_id.in_(ids))
        .all()
    )
    return {row.offset_id: row for row in rows}


def fetch_offsets_limite_por_grupo(
    db: Session, grupo_ids: Iterable[int]
) -> dict[int, OffsetGanancia]:
    """
    Batch-load the *limit-bearing* offset for each group — the deterministic
    replacement for the per-group `offset_con_limite` `.first()` tie-break.

    One query filters offsets in `grupo_ids` that carry a limit
    (max_unidades OR max_monto_usd not null), ordered by (grupo_id, id ASC), then
    groups in Python taking the FIRST (lowest id) offset per group.

    ORDER BY id ASC pins the previously non-deterministic `.first()` tie-break to
    "lowest id wins" (see design §4). Returns {} without querying when empty.
    """
    ids = list({gid for gid in grupo_ids if gid is not None})
    if not ids:
        return {}
    rows = (
        db.query(OffsetGanancia)
        .filter(
            OffsetGanancia.grupo_id.in_(ids),
            or_(
                OffsetGanancia.max_unidades.isnot(None),
                OffsetGanancia.max_monto_usd.isnot(None),
            ),
        )
        .order_by(OffsetGanancia.grupo_id, OffsetGanancia.id.asc())
        .all()
    )
    result: dict[int, OffsetGanancia] = {}
    for row in rows:
        result.setdefault(row.grupo_id, row)  # ordered id ASC → first seen = lowest id
    return result
```

### 2.1 Model key columns (confirmed by reading the model files)

| Model | Table | PK | Batch key | Cardinality |
|-------|-------|----|-----------|-------------|
| `OffsetGrupoResumen` | `offset_grupo_resumen` | `id` | `grupo_id` (`unique=True, index=True`) | **1:1** per grupo |
| `OffsetIndividualResumen` | `offset_individual_resumen` | `id` | `offset_id` (`unique=True, index=True`) | **1:1** per offset |
| `OffsetGanancia` | `offsets_ganancia` | `id` | `grupo_id` (FK, `index=True`, nullable) | **1:N** per grupo (needs ordered take-first) |

The `unique=True` on both resumen `key` columns is what makes `fetch_resumenes_*`
safe as a strict `dict[int, Model]` (never drops a row).

---

## 3. Per-site integration — VERIFIED site inventory (correction to the proposal)

**Finding (design-time correction):** reading the actual code found **more sites than
the proposal's "6".** The proposal missed one individual-loop site in
`rentabilidad_dashboard.py`, one in `rentabilidad_fuera.py`, and a **second
`offset_con_limite` tie-break** in `_consumo_individual.py`. The real inventory is
**10 in-loop query sites across 6 endpoint functions in 5 files.** All are in scope
(same mechanical pattern); the spec/tasks must cover all 10, not 6.

**Post-PR1 update:** adversarial review of PR1 found an **11th site**, also in
`_consumo_individual.py` (`obtener_resumen_offsets_individuales`, the
`/offset-individuales-resumen` route) — a separate function from site 9/10's
`obtener_resumen_todos_offsets_con_limites`, not caught in the original
inventory pass. Scoped into PR2 (Task 4); the count is now **11 sites across 6
endpoint functions in 5 files**.

| # | File · function | Line | Query | Helper | In proposal? |
|---|-----------------|------|-------|--------|--------------|
| 1 | `rentabilidad_dashboard.py` · `obtener_rentabilidad` (grupo loop L322) | 330 | `OffsetGrupoResumen` per grupo | `fetch_resumenes_grupo` | yes |
| 2 | `rentabilidad_dashboard.py` · `obtener_rentabilidad` (individual loop L464) | 473 | `OffsetIndividualResumen` per offset | `fetch_resumenes_individuales` | **MISSED** |
| 3 | `rentabilidad_tienda_nube.py` (grupo loop L325) | 332 | `OffsetGrupoResumen` per grupo | `fetch_resumenes_grupo` | yes |
| 4 | `rentabilidad_tienda_nube.py` (individual loop L408) | 416 | `OffsetIndividualResumen` per offset | `fetch_resumenes_individuales` | yes |
| 5 | `rentabilidad_fuera.py` (grupo loop L377) | 385 | `OffsetGrupoResumen` per grupo | `fetch_resumenes_grupo` | yes |
| 6 | `rentabilidad_fuera.py` (individual loop L463) | 472 | `OffsetIndividualResumen` per offset | `fetch_resumenes_individuales` | **MISSED** |
| 7 | `offsets_ganancia/_consumo_grupos.py` · `obtener_resumen_grupos` (loop L71) | 73 | `OffsetGrupoResumen` per grupo | `fetch_resumenes_grupo` | yes |
| 8 | `offsets_ganancia/_consumo_grupos.py` · `obtener_resumen_grupos` (loop L71) | 76–83 | `offset_con_limite` per grupo (tie-break) | `fetch_offsets_limite_por_grupo` | yes |
| 9 | `offsets_ganancia/_consumo_individual.py` · `obtener_resumen_todos_offsets_con_limites` (grupo loop L384) | 385 & 387–394 | `OffsetGrupoResumen` **and** `offset_limite` per grupo (2nd tie-break) | `fetch_resumenes_grupo` + `fetch_offsets_limite_por_grupo` | **MISSED** |
| 10 | `offsets_ganancia/_consumo_individual.py` · same fn (individual loop L425) | 426 | `OffsetIndividualResumen` per offset | `fetch_resumenes_individuales` | yes (as "L426") |
| 11 | `offsets_ganancia/_consumo_individual.py` · `obtener_resumen_offsets_individuales` (loop ~L29-36) | 58 | `OffsetIndividualResumen` per offset | `fetch_resumenes_individuales` | **MISSED — found post-PR1** |

### 3.1 Keys are all available before the loop (verified)

Prerequisite for prefetch is that keys are known *before* iterating. Confirmed for
every site:

- **Sites 1–6 (rentabilidad):** each function fetches `offsets = db.query(...).all()`
  (materialized list — dashboard L155–162, tienda_nube L255, fuera L296) **before** the
  loops. So a first-pass comprehension over the already-in-memory `offsets` yields the
  keys with **zero extra queries**:
  ```python
  grupo_ids  = {o.grupo_id for o in offsets if o.grupo_id}
  offset_ids = {o.id for o in offsets
                if o.grupo_id is None and (o.max_unidades or o.max_monto_usd)}
  ```
- **Sites 7–10 (consumo resumen endpoints):** `grupos_con_limites` (a `.all()`) and
  `offsets_individuales` (a `.all()`) are fully materialized before their loops, so
  `[g.id for g in grupos_con_limites]` / `[o.id for o in offsets_individuales]` are known.

No site "discovers" keys mid-loop → **no two-pass restructuring needed.**

### 3.2 Before / after — representative site (Site 1, dashboard grupo loop)

**BEFORE** (`rentabilidad_dashboard.py` L321–330):
```python
# Pre-calcular offsets por grupo para aplicar límites a nivel grupo
for offset in offsets:
    if not offset.grupo_id:
        continue
    if offset.grupo_id not in offsets_grupo_calculados:
        tc = float(offset.tipo_cambio) if offset.tipo_cambio else 1.0
        # Primero intentamos usar la tabla de resumen para obtener el consumo total
        resumen = db.query(OffsetGrupoResumen).filter(
            OffsetGrupoResumen.grupo_id == offset.grupo_id
        ).first()
        ...
```

**AFTER** (prefetch built before loop; in-loop query → `dict.get`):
```python
from app.services.offset_resumen_service import fetch_resumenes_grupo

# Prefetch all group resúmenes in ONE query (keys already in `offsets`)
_grupo_ids = {o.grupo_id for o in offsets if o.grupo_id}
_resumenes_grupo = fetch_resumenes_grupo(db, _grupo_ids)

# Pre-calcular offsets por grupo para aplicar límites a nivel grupo
for offset in offsets:
    if not offset.grupo_id:
        continue
    if offset.grupo_id not in offsets_grupo_calculados:
        tc = float(offset.tipo_cambio) if offset.tipo_cambio else 1.0
        # Primero intentamos usar la tabla de resumen para obtener el consumo total
        resumen = _resumenes_grupo.get(offset.grupo_id)   # was .first()
        ...
```

Everything downstream of `resumen = ...` is byte-for-byte unchanged (`if resumen:`
branch reads the same attributes). The `individual` loop (Site 2) gets the
symmetric treatment with `fetch_resumenes_individuales(db, offset_ids)` and
`resumen = _resumenes_indiv.get(offset.id)`.

### 3.3 Before / after — Site 8, the tie-break (`_consumo_grupos.py`)

**BEFORE** (`_consumo_grupos.py` L71–86, inside `obtener_resumen_grupos`):
```python
for grupo in grupos_con_limites:
    resumen = db.query(OffsetGrupoResumen).filter(
        OffsetGrupoResumen.grupo_id == grupo.id
    ).first()

    # Obtener límites del offset (asumimos que todos los offsets del grupo tienen el mismo límite)
    offset_con_limite = (
        db.query(OffsetGanancia)
        .filter(
            OffsetGanancia.grupo_id == grupo.id,
            or_(OffsetGanancia.max_unidades.isnot(None),
                OffsetGanancia.max_monto_usd.isnot(None)),
        )
        .first()                                    # ← NON-DETERMINISTIC tie-break
    )

    max_unidades = offset_con_limite.max_unidades if offset_con_limite else None
    max_monto_usd = offset_con_limite.max_monto_usd if offset_con_limite else None
    ...
```

**AFTER** (both queries batched before the loop):
```python
from app.services.offset_resumen_service import (
    fetch_resumenes_grupo,
    fetch_offsets_limite_por_grupo,
)

_grupo_ids = [g.id for g in grupos_con_limites]
_resumenes = fetch_resumenes_grupo(db, _grupo_ids)
_offsets_limite = fetch_offsets_limite_por_grupo(db, _grupo_ids)   # ORDER BY id ASC

for grupo in grupos_con_limites:
    resumen = _resumenes.get(grupo.id)                # was .first()
    offset_con_limite = _offsets_limite.get(grupo.id) # was .first(), now lowest-id

    max_unidades = offset_con_limite.max_unidades if offset_con_limite else None
    max_monto_usd = offset_con_limite.max_monto_usd if offset_con_limite else None
    ...
```

**Non-tie case preservation (proof):** for a group with exactly ONE limit-bearing
offset, the filtered `.in_()` returns that single row → `setdefault` stores it →
`get` returns the identical object the old `.first()` returned. For a group with
ZERO limit-bearing offsets, the old `.first()` returned `None` and `get` returns
`None` → identical `else None` branch. Behavior changes **only** for groups with ≥2
limit-bearing offsets (see §4). Site 9's second query (`offset_limite`) is the same
shape and uses the same helper.

---

## 4. ADR — deterministic tie-break for `offset_con_limite`

**Decision:** `fetch_offsets_limite_por_grupo` adds `ORDER BY grupo_id, id ASC` and
takes the first (lowest id) offset per group.

**Context:** The legacy `.first()` at sites 8 and 9 has **no `ORDER BY`**. Which row
wins for a group with multiple limit-bearing offsets is undefined — it depends on the
storage engine's physical row order / query plan. There is no guaranteed behavior to
preserve.

**Rationale:** Pinning to lowest-id is a strict improvement: it cannot regress a
guaranteed behavior (none exists), it makes the endpoint output reproducible, and
`id ASC` is the minimal choice that matches "first row" semantics without inventing a
new product rule ("which limit wins").

**Rejected alternatives:**
- *Semantic ORDER BY (e.g. largest `max_monto_usd`)* — REJECTED: that redefines
  behavior and introduces a product decision this refactor explicitly avoids.
- *Leave `.first()` unordered inside the batch (rely on `.in_()` scan order)* —
  REJECTED: still non-deterministic and undermines the byte-identical-output guarantee.

**Consequence / test obligation:** requires an explicit **tie-case test** — a group with
≥2 limit-bearing offsets (distinct `max_unidades`) asserting the LOWEST-id offset's
limits are returned.

> **Note on SQLite vs PostgreSQL under strict TDD:** on the in-memory SQLite test DB,
> an unordered `.first()` tends to return lowest-rowid first, so an *integration*
> tie-case test may pass incidentally against current code. The genuinely RED-first
> test is therefore a **unit test on `fetch_offsets_limite_por_grupo`** (the function
> does not exist yet → import/attribute error → red), which then asserts lowest-id on
> green. The integration tie-case test is a behavior *pin* layered on top.

---

## 5. ADR — query-count test harness

### 5.1 The counted-queries nuance (critical design point)

The three `rentabilidad_*` endpoints do **not** reduce to O(1) *total* queries, because
their grupo/individual loops also call per-group aggregate helpers
(`calcular_consumo_grupo_desde_tabla` / `_acumulado`, `calcular_consumo_individual_*`)
that issue `func.sum(...)` queries against the *consumo* tables. **Those aggregates are
OUT of scope** (they are period-filtered aggregations, not key lookups) and remain
O(distinct-groups).

Therefore the query-count assertion for sites 1–6 must count **only the resumen-table
queries**, not total queries. The fixture must support filtering statements by table
name. For the two `_consumo_*` resumen endpoints (sites 7–10), the loops contain *only*
the batched queries, so both total-bounded and table-filtered assertions hold.

### 5.2 Reusable `query_counter` conftest fixture

Extract the `before_cursor_execute` counter from
`tests/compras/test_varianza_tc_batch.py` L423–436 into **top-level**
`backend/tests/conftest.py` so all suites inherit it. Upgrade it from a bare int to a
context-manager that also captures statement text for table-filtered assertions.

Why this works: `conftest.py`'s `client` fixture overrides `get_db` to yield the exact
`db` session, which is bound to a single `connection`. The listener on
`db.connection()` therefore observes every query the endpoint runs.

### 5.3 Assertion strategy (RED-first)

- **Sites 1–6 (rentabilidad):** build a fixture with **N ≥ 3 distinct groups** (and ≥ 3
  individual limited offsets). Assert
  `counter.matching("offset_grupo_resumen") <= 1` and
  `counter.matching("offset_individual_resumen") <= 1`.
  Current code issues N of each → `3 > 1` → **RED**. After fix → `1 <= 1` → green.
- **Sites 7–10 (consumo endpoints):** same, plus
  `counter.matching("offsets_ganancia") <= 1` to pin the batched `offset_limite`.
- **O(1) invariance (robustness):** optionally `pytest.mark.parametrize` N over `[2, 5]`
  and assert the resumen count is the **same small constant** for both, so a hidden
  linear term would fail.

---

## 6. Rollback

Pure read-path refactor, **no schema change, no migration** → rollback = **revert the
commit**. The new `offset_resumen_service.py` is additive; reverting deletes it and
restores the inline `.first()` calls. No data migration, no forward-fix needed.

### 6.1 Circular-import safety (assessed)

`offset_resumen_service.py` imports **only models** (`OffsetGanancia`,
`OffsetGrupoResumen`, `OffsetIndividualResumen`), and models import only
`app.core.database.Base` — never services. Endpoints import the service. The dependency
graph stays a DAG (`endpoints → services → models → Base`), matching the existing
`pricing_service.py` / `pedidos_service.py` layering. **No circular import.**

---

## 7. Decisions summary

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | One shared `services/offset_resumen_service.py` with 3 functions | Same fetch-by-key shape repeats across 10 of 11 sites; DRY + single test surface |
| D2 | No `.in_()` chunking | Distinct group/offset counts are tens–hundreds, far below PG's ~32k param limit |
| D3 | Empty input → return `{}` without querying | Matches `productos_listing.py` empty-guard idiom; avoids a pointless round-trip |
| D4 | `ORDER BY grupo_id, id ASC` + take-first for `offset_con_limite` | Pins previously non-deterministic tie-break to lowest-id (safe improvement) |
| D5 | `query_counter` counts by **table-name match**, not total | rentabilidad endpoints keep O(N) aggregate queries out of scope; only resumen queries must be O(1) |
| D6 | Cover **11** sites incl. missed individual loops + 2nd tie-break + 11th site | Verified against actual code; proposal undercounted |
| D7 | RED-first via **unit test on the helpers** | Integration tie-case may pass incidentally on SQLite; unit test guarantees red |
