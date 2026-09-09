# Delta: productos-acciones-masivas-markup-objetivo

## MODIFIED Requirements

### Requirement: Accept zero and negative markup_objetivo

The Acciones masivas modal and `AplicarMarkupMasivoRequest` MUST accept finite 0 and negative `markup_objetivo` within the schema floor. The modal MUST NOT reject, toast-block, or blur-reset 0 or a negative finite number ≥ −100. Positive finite values MUST still apply without the non-positive confirm.

#### Scenario: Zero markup requires non-positive confirm when count ≤ 50

- GIVEN markup apply is enabled, `markup_objetivo` is 0, and write-set size ≤ 50
- WHEN the operator applies
- THEN the system MUST show the same Tesla confirm pane used for negative markup
- AND MUST NOT write until the operator confirms
- AND MUST NOT treat 0 as invalid

#### Scenario: Positive markup still applies

- GIVEN markup apply is enabled, `markup_objetivo` is a positive finite number, and write-set size ≤ 50
- WHEN the operator applies
- THEN the system MUST apply that markup without the non-positive confirm

#### Scenario: Backend schema accepts zero and negative within floor

- GIVEN `AplicarMarkupMasivoRequest` with `markup_objetivo` 0, −5, or −100 and valid `item_ids`
- WHEN the request is validated
- THEN validation MUST succeed
- AND values below −100 MUST fail validation
- AND Inf/NaN MUST fail validation

#### Scenario: Blur preserves zero and negative

- GIVEN the markup field shows 0 or a negative finite number
- WHEN the field blurs
- THEN the value MUST remain 0 or that negative number
- AND MUST NOT reset to `5.0`

### Requirement: Negative markup requires Tesla in-modal confirm

Non-positive `markup_objetivo` (`<= 0`) MUST require explicit in-modal Tesla confirmation before writes. Copy MUST align with Productos CS-4 (**MarkUp Negativo** / **Guardar de todas formas**). The system MUST NOT use `window.confirm` or `confirm()`.

#### Scenario: Zero markup proceeds after confirm

- GIVEN markup apply is enabled, `markup_objetivo` is 0, and write-set size ≤ 50
- WHEN the operator applies and confirms the non-positive pane
- THEN the system MUST write with markup 0
- AND MUST NOT use `window.confirm`

#### Scenario: Negative markup proceeds after confirm

- GIVEN markup apply is enabled, `markup_objetivo` is negative, and write-set size ≤ 50
- WHEN the operator applies and confirms the non-positive pane
- THEN the system MUST write with that negative markup
- AND MUST NOT use `window.confirm`

#### Scenario: Non-positive markup cancel aborts

- GIVEN the non-positive Tesla confirm is visible
- WHEN the operator cancels or goes back
- THEN the system MUST NOT write
- AND MUST return to the form with the entered value intact

### Requirement: Negative and >50 confirms stack independently

The existing >50 Tesla confirm MUST remain. Non-positive markup (`<= 0`) and >50 MUST stack when both apply. Cancel/Volver on either pane MUST abort writes. Stacking order MUST be non-positive first, then >50 if still required.

#### Scenario: Zero plus >50 stacks

- GIVEN `markup_objetivo` is 0 and write-set size > 50
- WHEN the operator applies
- THEN the non-positive Tesla confirm MUST appear first
- AND after proceed, the >50 confirm MUST appear before writes
- AND writes MUST NOT start until both are confirmed

#### Scenario: Negative plus >50 stacks

- GIVEN negative `markup_objetivo` and write-set size > 50
- WHEN the operator applies
- THEN the non-positive Tesla confirm MUST appear
- AND after proceed, the >50 confirm MUST appear before writes
- AND cancel on either pane MUST abort writes

#### Scenario: Positive plus >50 uses volume only

- GIVEN positive `markup_objetivo` and write-set size > 50
- WHEN the operator applies
- THEN only the >50 confirm MUST appear
- AND the non-positive pane MUST NOT appear
