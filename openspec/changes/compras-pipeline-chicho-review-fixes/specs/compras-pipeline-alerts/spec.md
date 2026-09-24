# Delta for compras-pipeline-alerts

## ADDED Requirements

### Requirement: Compras banner cap and overflow

Visible compras banners MUST be capped at `max_alertas_visibles`. Overflow MUST show “+N más” for the hidden count. Persistent unread compras banners MUST remain until that user dismisses them and MUST NOT timed-rotate out of the visible set solely due to age.

#### Scenario: Cap shows plus-N

- GIVEN 7 unread compras alerts and `max_alertas_visibles` = 3
- WHEN the operator opens the app
- THEN exactly 3 compras banners MUST be visible
- AND the UI MUST show “+4 más”

#### Scenario: Persistent item is not timed away

- GIVEN an unread compras banner older than a rotation interval
- WHEN the rotation clock advances
- THEN that banner MUST remain until the user OKs it

### Requirement: One Novedades draft and Gabe commit gate

The change MUST include exactly one draft at `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md`. The draft file MUST exist. After Gabe’s 2026-09-23 correction, the draft MUST **not** say that OC Match or document persist makes a factura “cargada” or fires an alert. Committing that draft as final operator copy is a process gate and MUST wait until Gabe reviews the **rewritten** draft.

#### Scenario: Draft path exists

- GIVEN this change is being delivered
- WHEN artifacts are checked
- THEN `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md` MUST exist as a draft

#### Scenario: Draft copy matches ERP-check model

- GIVEN Gabe already saw a draft that said Match turns “factura cargada” on
- WHEN the draft is rewritten
- THEN it MUST describe numbers as constancia
- AND it MUST describe “Factura cargada” as the Administración ERP check
- AND it MUST describe the 5-minute pending alert and uncheck-to-cancel
- AND it MUST NOT equate Match identify/persist with cargada

#### Scenario: Commit waits for Gabe review

- GIVEN the rewritten draft has not been reviewed by Gabe
- WHEN apply would commit the novedad as final
- THEN that commit MUST NOT proceed

### Requirement: Land on existing main PR chain

Fixes MUST land on the existing stacked PRs #1320–#1324 targeting `main` (Gabe → sernafernando), plus stacked PR5/PR6 for this amend. This change MUST NOT open a new named PR chain.

#### Scenario: Existing chain, not a new one

- GIVEN stacked PRs #1320–#1324 already target `main`
- WHEN this amend is delivered
- THEN commits MUST stack on that chain (PR5/PR6)
- AND a new PR chain MUST NOT be opened

### Requirement: No factura alert on persist or Match

Identify, upload, persist, seed, and OC Match write-back MUST NOT create `compras.factura_cargada` notifications. The alert MUST start only when Administración checks `cargada` on a factura row.

#### Scenario: Match persist creates no alert

- GIVEN holders of `administracion.ver_alertas_factura` exist
- WHEN OC Match persists `FA-10`
- THEN zero `compras.factura_cargada` notifications MUST be created

#### Scenario: Manual persist creates no alert

- GIVEN holders of `administracion.ver_alertas_factura` exist
- WHEN an operator POSTs `FA-10`
- THEN zero `compras.factura_cargada` notifications MUST be created

### Requirement: Five-minute pending alert after ERP check

The system MUST create `compras.factura_cargada` notifications only after `FACTURA_CARGADA_ALERT_DELAY` (5 minutes) from `cargada_marked_at`, and only if the row is still `cargada` and `alerta_pendiente_hasta` has been reached. Recipients MUST be `administracion.ver_alertas_factura` holders. Uncheck before fire MUST cancel the pending alert. This MUST be a different clock from DELETE undo (`FACTURA_UNDO_WINDOW` from `created_at`).

#### Scenario: Fan-out after timer, not on check

- GIVEN users H1 and H2 hold `administracion.ver_alertas_factura`, and T is titular without that permission
- WHEN Administración checks `FA-10` at T0
- THEN at T0 no notification MUST exist
- WHEN the sweep runs at T0 + 5 minutes
- THEN H1 and H2 MUST each receive the alert
- AND T MUST NOT

#### Scenario: Uncheck cancels pending, not delivered-after-fire

- GIVEN a row checked at T0
- WHEN it is unchecked at T0 + 2 minutes
- THEN the pending alert MUST be cancelled
- AND a later sweep MUST NOT create notifications for that check

## MODIFIED Requirements

### Requirement: Factura recipients and per-user OK

Factura-cargada recipients MUST be users who hold `administracion.ver_alertas_factura`. The catalog MUST include that permission with no default role assignments. Recipients MUST NOT be hardcoded by role (including MarcaPM, MarcaSubPM, ADMIN, GERENTE, SUPERADMIN). Each recipient MUST dismiss independently (per-user OK). The banner MUST stay stacked until that user OKs.

(Previously: recipients were titular ∪ sub-PM ∪ ADMIN/GERENTE/SUPERADMIN. Trigger was persist of a nonempty number. Trigger is now the 5-minute ERP-check timer.)

#### Scenario: Role without permission is excluded

- GIVEN user A has role ADMIN and does not hold `administracion.ver_alertas_factura`
- WHEN a factura-cargada alert fires after the 5-minute timer
- THEN A MUST NOT receive the alert

#### Scenario: Per-user OK does not clear others

- GIVEN T and S both have the same factura alert
- WHEN T OKs
- THEN T’s banner/campanita item MUST clear
- AND S MUST still see the alert until S OKs

### Requirement: Faltantes alert to responsable

Marking faltantes MUST alert `pedido.responsable_id`. The mark MUST include nonempty free text. The alert MUST deep-link to pedido detalle with observaciones visible. Faltantes recipients MUST NOT switch to `administracion.ver_alertas_factura` holders.

(Previously: responsable-only; this change keeps that rule when factura fan-out becomes permission-based.)

#### Scenario: Responsable notified with free text

- GIVEN pedido P with `responsable_id` = R
- WHEN depósito marks faltantes with free text `Faltan 2 cajas`
- THEN R MUST receive an in-app alert
- AND the alert MUST deep-link to P detalle showing observaciones
- AND the free text MUST be visible

#### Scenario: Faltantes without free text rejected

- GIVEN a pedido in a receivable state
- WHEN depósito marks faltantes with empty text
- THEN the system MUST reject the mark
- AND no faltantes alert MUST be created

#### Scenario: Factura permission does not change faltantes recipients

- GIVEN P.responsable_id = R, and H holds `administracion.ver_alertas_factura` but is not R
- WHEN depósito marks faltantes with nonempty free text
- THEN R MUST receive the alert
- AND H MUST NOT receive it solely because of that permission
