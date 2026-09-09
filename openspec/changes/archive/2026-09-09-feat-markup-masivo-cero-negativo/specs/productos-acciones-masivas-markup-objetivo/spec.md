# productos-acciones-masivas-markup-objetivo Specification

## Purpose

Acciones masivas MUST accept `markup_objetivo` 0 (break-even) and negative (loss-leader). Invalid/NaN stay rejected. Zero needs no extra confirm beyond the existing >50 Tesla gate. Negative requires in-modal Tesla confirm aligned with Productos CS-4. Sibling `productos-acciones-masivas-scope` is not rewritten. Out of scope: row CS-4, cuotas `markup_adicional` 0–100.

## Requirements

### Requirement: Accept zero and negative markup_objetivo

The Acciones masivas modal and `AplicarMarkupMasivoRequest` MUST accept finite 0 and negative `markup_objetivo`. The modal MUST NOT reject, toast-block, or blur-reset 0 or a negative number. Positive finite values MUST still apply without the negative confirm.

#### Scenario: Zero markup applies without negative confirm

- GIVEN markup apply is enabled, `markup_objetivo` is 0, and write-set size ≤ 50
- WHEN the operator applies
- THEN the system MUST write without a negative-markup confirm
- AND MUST NOT treat 0 as invalid

#### Scenario: Positive markup still applies

- GIVEN markup apply is enabled, `markup_objetivo` is a positive finite number, and write-set size ≤ 50
- WHEN the operator applies
- THEN the system MUST apply that markup without a negative-markup confirm

#### Scenario: Backend schema accepts zero and negative

- GIVEN `AplicarMarkupMasivoRequest` with `markup_objetivo` 0 or a negative finite number and valid `item_ids`
- WHEN the request is validated
- THEN validation MUST succeed
- AND MUST NOT require the value to be greater than 0

#### Scenario: Blur preserves zero and negative

- GIVEN the markup field shows 0 or a negative finite number
- WHEN the field blurs
- THEN the value MUST remain 0 or that negative number
- AND MUST NOT reset to `5.0`

### Requirement: Reject invalid markup_objetivo

When markup apply is enabled, empty, non-numeric, or NaN `markup_objetivo` MUST be rejected before writes. Blur MAY default a non-numeric field to `5.0`.

#### Scenario: NaN or empty markup is rejected

- GIVEN markup apply is enabled and the markup field is empty or not a finite number
- WHEN the operator applies
- THEN the system MUST reject the apply
- AND MUST NOT write prices or show the negative-markup confirm

### Requirement: Negative markup requires Tesla in-modal confirm

Negative `markup_objetivo` MUST require explicit in-modal Tesla confirmation before writes. Copy MUST align with Productos CS-4 (**MarkUp Negativo** / **Guardar de todas formas**). The system MUST NOT use `window.confirm` or `confirm()`. Zero MUST NOT show this pane.

#### Scenario: Negative markup proceeds after confirm

- GIVEN markup apply is enabled, `markup_objetivo` is negative, and write-set size ≤ 50
- WHEN the operator applies and confirms the negative-markup pane
- THEN the system MUST write with that negative markup
- AND MUST NOT use `window.confirm`

#### Scenario: Negative markup cancel aborts

- GIVEN the negative-markup Tesla confirm is visible
- WHEN the operator cancels or goes back
- THEN the system MUST NOT write
- AND MUST return to the form with the entered negative value intact

### Requirement: Negative and >50 confirms stack independently

The existing >50 Tesla confirm MUST remain. Zero MUST NOT add a negative confirm; >50 still applies when count > 50. When both conditions hold, both gates MUST apply. Cancel/Volver on either pane MUST abort writes. Stacking order SHOULD be negative first, then >50 if still required. That order is **product-recommended** (proposal), **not Chicho-locked**; exploration left pane order design-open.

#### Scenario: Negative plus >50 stacks

- GIVEN negative `markup_objetivo` and write-set size > 50
- WHEN the operator applies
- THEN the negative Tesla confirm MUST appear
- AND after proceed, the >50 confirm MUST appear before writes
- AND writes MUST NOT start until both are confirmed
- AND cancel on either pane MUST abort writes

#### Scenario: Zero plus >50 uses only the >50 gate

- GIVEN `markup_objetivo` is 0 and write-set size > 50
- WHEN the operator applies
- THEN the >50 Tesla confirm MUST appear
- AND the negative-markup confirm MUST NOT appear
