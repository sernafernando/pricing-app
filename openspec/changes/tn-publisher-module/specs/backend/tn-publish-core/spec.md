# tn-publish-core Specification

## Purpose

Framework-agnostic pipeline (extract → resolve → validate → assemble) turning a GBP
report-78 row, stored per-item overrides, an optional measurement profile, and the
operator's in-session edits into a validated Tienda Nube v1 publish payload. Callable
from tests, the single-item modal, and the future bulk publisher alike — no HTTP or
React object in its call path.

## Requirements

### Requirement: Fail-loud report-78 extraction

Extraction MUST raise an explicit error naming the missing key when any field it
depends on (`weight`, `wide`, `large`, `height`, `Marca`, `Stock_Disponible`,
`coslis_price`/`iclh_price`, `Moneda_Costo`, `Código`, `tnr_lastPromotionalPrice`) is
absent from the parsed row. It MUST NOT default to `0`, `None`, or `""`.

#### Scenario: Missing expected key raises

- GIVEN a report-78 row missing `height` (e.g. an ERP column rename)
- WHEN extraction processes that row
- THEN it raises, naming `height`
- AND no downstream stage receives a defaulted value for it

#### Scenario: Complete row extracts cleanly

- GIVEN a row containing every extraction-dependent key
- WHEN extraction processes it
- THEN it returns a typed projection with nothing defaulted

### Requirement: Weight unit conversion (grams to kilograms)

Resolve MUST divide GBP `weight` by 1000 before it reaches the payload.

#### Scenario: Grams-to-kilograms golden conversion

- GIVEN GBP `weight = 1000`
- WHEN resolve computes TN weight
- THEN the result is `1.000` kg, and `weight = 250` resolves to `0.250` kg

### Requirement: GBP-to-TN dimension mapping is intentional, not a bug

GBP `large` MUST map to TN `width`; GBP `wide` MUST map to TN `depth`; GBP `height`
MUST map to TN `height`. The mapping site MUST carry a comment explaining that GBP's
English column names do not match TN's semantics and that 535 live products already
depend on exactly this mapping (36/36 verified). A test MUST assert the exact mapping
with the rationale stated in its name.

#### Scenario: Swapped mapping matches the 535 live products

- GIVEN GBP `large = 13`, `wide = 2`, `height = 8`
- WHEN resolve maps dimensions
- THEN the payload has `width = 13`, `depth = 2`, `height = 8`
- AND the asserting test's name states this is the verified, intentional mapping

#### Scenario: Mapping site carries an explanatory comment

- GIVEN the source location of the dimension assignment
- WHEN that site is inspected
- THEN a comment states the mapping is confirmed correct (36/36 live), not a swap error

### Requirement: Field precedence with persisted overrides

Resolution priority, lowest to highest: empty < profile value < GBP report-78 value <
stored per-item override < the operator's current in-session edit.

#### Scenario: Stored override outranks a fresh GBP value

- GIVEN an item with a stored `weight` override and a GBP `weight` for the same item
- WHEN resolve computes effective `weight`
- THEN the stored override is used, not the GBP value

#### Scenario: In-session edit outranks the stored override

- GIVEN an item with a stored `width` override
- WHEN the operator edits `width` before publishing
- THEN the in-session value is used for this publish

#### Scenario: Profile fills a gap GBP and overrides leave empty

- GIVEN no stored override and no GBP `height` for an item
- AND a selected profile supplies `height`
- WHEN resolve computes effective `height`
- THEN the profile value is used

### Requirement: Overrides persist after a successful publish

Every field value the operator edited in-session MUST be written to the per-item
overrides store immediately after a successful publish, so the next visit and the
future bulk publisher reuse it. Overrides are never written back to GBP.

#### Scenario: Edited field becomes the new stored override

- GIVEN the operator changes `weight` before publishing
- WHEN the publish succeeds
- THEN the overrides store now holds the edited `weight` for that item
- AND no write occurs against any GBP/ERP source

### Requirement: Validation gate blocks publication on missing measurements

Publication MUST be blocked when `weight` or any of `width`/`height`/`depth` resolve
to empty. This gate MUST NOT ship independent of `backend/tn-measurement-profiles` —
without a working fallback, blocking alone permanently strands the ~97 items with no
GBP measurements.

#### Scenario: Missing dimension blocks publish

- GIVEN an item with no override, no GBP dimensions, and no profile applied
- WHEN publish is attempted
- THEN it is rejected before any TN call, naming the missing measurement(s)

#### Scenario: Profile-supplied measurements unblock publish

- GIVEN the same item with a profile applied supplying all four fields
- WHEN publish is attempted
- THEN the measurement check passes

### Requirement: Visibility field exclusivity

The payload MUST include `visibility` and MUST NOT include `published`.

#### Scenario: Payload never mixes visibility and published

- GIVEN a resolved product with visibility `unlisted`
- WHEN the payload is assembled
- THEN it has `visibility: "unlisted"` and no `published` key

### Requirement: USD/ARS cost conversion with defined no-rate behavior

`cost` MUST be sent in ARS. `Moneda_Costo = ARS` passes through unconverted.
`Moneda_Costo = USD` MUST convert via today's `TipoCambio.venta`, falling back to the
latest available rate (existing project pattern) if today's is missing. If no
`TipoCambio` row exists at all, the assembler MUST block that item's cost rather than
send an unconverted USD figure as ARS.

#### Scenario: ARS row passes through

- GIVEN `Moneda_Costo = "ARS"`, `coslis_price = 50000`
- WHEN cost is resolved
- THEN payload `cost = 50000`, unconverted

#### Scenario: USD row converts at today's rate

- GIVEN `Moneda_Costo = "USD"`, `coslis_price = 100`, today's `TipoCambio.venta = 1000`
- WHEN cost is resolved
- THEN payload `cost = 100000`

#### Scenario: No exchange rate blocks the cost field

- GIVEN `Moneda_Costo = "USD"` and an empty `TipoCambio` table
- WHEN cost is resolved
- THEN publication is blocked, naming the missing rate — no unconverted USD is sent

### Requirement: v1 inventory_levels payload assembly

Stock MUST be set via `inventory_levels[].stock`; the deprecated `variant.stock` MUST
NOT be sent. With one location, `location_id` MAY be omitted.

#### Scenario: Stock uses inventory_levels

- GIVEN resolved `Stock_Disponible = 12`
- WHEN the variant payload is assembled
- THEN it has `inventory_levels: [{"stock": 12}]` and no top-level `stock` key

### Requirement: Batching with 429 backoff

The core MUST accept a batch of items as a first-class input and MUST retry on `429`
with backoff, respecting any `Retry-After` header.

#### Scenario: Single-item call is a batch of one

- GIVEN a caller publishes exactly one item
- WHEN the core processes it
- THEN it runs through the same batch execution path as a multi-item call

#### Scenario: 429 triggers backoff without abandoning the batch

- GIVEN a variant-update call returns `429` with `Retry-After: 2`
- WHEN the batch executor handles it
- THEN it waits at least that interval before retrying that item, and continues the rest of the batch

### Requirement: Core is UI-independent

The core MUST be fully invokable from a backend-only test — no FastAPI request object,
no React code in its call path.

#### Scenario: Backend-only test publishes a full payload

- GIVEN a test builds a GBP row, overrides, and a profile directly in Python
- WHEN it calls extract→resolve→validate→assemble
- THEN it receives a complete, valid TN payload with no endpoint or component involved
