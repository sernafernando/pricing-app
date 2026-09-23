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

The change MUST include exactly one draft at `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md`. The draft file MUST exist. Committing that draft as final operator copy is a process gate and MUST wait until Gabe reviews it.

#### Scenario: Draft path exists

- GIVEN this change is being delivered
- WHEN artifacts are checked
- THEN `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md` MUST exist as a draft

#### Scenario: Commit waits for Gabe review

- GIVEN the draft has not been reviewed by Gabe
- WHEN apply would commit the novedad as final
- THEN that commit MUST NOT proceed

### Requirement: Land on existing main PR chain

Fixes MUST land on the existing stacked PRs #1320–#1324 targeting `main` (Gabe → sernafernando). This change MUST NOT open a new PR chain.

#### Scenario: Existing chain, not a new one

- GIVEN stacked PRs #1320–#1324 already target `main`
- WHEN this change is delivered
- THEN commits MUST land on that chain
- AND a new PR chain MUST NOT be opened

## MODIFIED Requirements

### Requirement: Factura recipients and per-user OK

Factura-cargada recipients MUST be users who hold `administracion.ver_alertas_factura`. The catalog MUST include that permission with no default role assignments. Recipients MUST NOT be hardcoded by role (including MarcaPM, MarcaSubPM, ADMIN, GERENTE, SUPERADMIN). Each recipient MUST dismiss independently (per-user OK). The banner MUST stay stacked until that user OKs.

(Previously: recipients were titular ∪ sub-PM ∪ ADMIN/GERENTE/SUPERADMIN.)

#### Scenario: Fan-out to permission holders

- GIVEN users H1 and H2 hold `administracion.ver_alertas_factura`, and T is titular without that permission
- WHEN factura is loaded with a nonempty number
- THEN H1 and H2 MUST each receive the alert
- AND T MUST NOT

#### Scenario: Role without permission is excluded

- GIVEN user A has role ADMIN and does not hold `administracion.ver_alertas_factura`
- WHEN factura is loaded with a nonempty number
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
