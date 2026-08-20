# tn-publisher-ui Specification

## Purpose

Decomposed publisher UI consuming `tn-publish-core` as a client, not its owner. Every
field transmitted to TN has a visible, editable control; profile selection and
blocked-publication states are explicit.

## Requirements

### Requirement: Every transmitted field has an editable control

For each field in the target set — product: `name`, `description`, `categories`,
`images`, `brand`, `visibility`, `free_shipping`, `seo_title`, `seo_description`,
`tags`; variant: `price`, `promotional_price`, `sku`, `barcode`, `cost`, `weight`,
`width`, `height`, `depth`, `inventory_levels[].stock` — the UI MUST render a control
the operator can view and edit before publishing. No field reaching TN may be hidden
or computed without a visible control.

#### Scenario: Field-to-control audit

- GIVEN the full field set defined above
- WHEN the publisher UI renders for an item
- THEN every field has a corresponding input/select/textarea the operator can change

#### Scenario: seo_title and seo_description enforce length limits

- GIVEN the operator types into `seo_title` or `seo_description`
- WHEN the input exceeds 70 or 320 characters respectively
- THEN the UI blocks further input or shows a validation error before publish is allowed

### Requirement: Stored overrides pre-fill and remain editable

When an item has stored per-item overrides, the UI MUST pre-fill those fields with the
stored values (not the raw GBP value) and MUST keep them editable.

#### Scenario: Reopening an item shows the prior override

- GIVEN an item with a stored `weight` override
- WHEN the publisher UI opens for that item
- THEN the `weight` control shows the stored override value, editable

### Requirement: Profile selector with visible category suggestion

A profile selector MUST pre-select the category-suggested profile when one exists, and
MUST remain changeable by the operator at all times.

#### Scenario: Suggested profile is pre-selected but overridable

- GIVEN a category with a suggested profile
- WHEN the publisher UI opens for an item in that category
- THEN the selector shows that profile selected, and the operator can pick another or clear it

### Requirement: Blocked-publication state explains and offers resolution

When required measurements are missing, the UI MUST disable the publish action and
name the missing fields plus a path to resolve them (select a profile or enter values
manually) — not a generic error.

#### Scenario: Missing measurements block the publish button

- GIVEN an item with no resolvable weight or dimensions
- WHEN the publisher UI evaluates publish-readiness
- THEN the publish action is disabled and the missing fields are named with a way to supply them

### Requirement: Nav gate matches the route gate

`Navbar.jsx`, `Sidebar.jsx`, and `SmartRedirect.jsx` MUST gate the Items Sin MLA nav
entry on `admin.ver_items_sin_mla`, matching the route guard in `App.jsx`.

#### Scenario: Route-holder sees the nav entry

- GIVEN a user holding `admin.ver_items_sin_mla` but not `admin.gestionar_mla_banlist`
- WHEN the nav renders
- THEN the Items Sin MLA entry is visible and `SmartRedirect` does not bypass it

#### Scenario: Banlist-only permission no longer shows the entry

- GIVEN a user holding only `admin.gestionar_mla_banlist`
- WHEN the nav renders
- THEN the Items Sin MLA entry is not shown, consistent with the route guard rejecting that user
