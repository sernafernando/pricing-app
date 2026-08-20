# tn-measurement-profiles Specification

## Purpose

New entity: reusable weight/width/height/depth box profiles, full CRUD behind a
dedicated permission, plus automatic category-based suggestion. Exists to make the
`tn-publish-core` blocking gate survivable — without profiles, ~97 items with no GBP
measurements have no path to publication.

## Requirements

### Requirement: Profile CRUD behind a dedicated permission

Profile create/update/delete MUST be gated by a permission distinct from
`admin.gestionar_tn_publicacion` (working code: `admin.gestionar_tn_perfiles`, pending
final confirmation), so publish access and profile-administration access are
independent.

#### Scenario: Publish permission alone is not enough

- GIVEN a user holding only `admin.gestionar_tn_publicacion`
- WHEN they call a profile create/update/delete endpoint
- THEN the request is rejected with `403`

#### Scenario: Profile permission alone does not grant publish

- GIVEN a user holding only the profile-management permission
- WHEN they call the publish endpoint
- THEN the request is rejected with `403`

### Requirement: Seed data from observed GBP box clusters

The profile-creating migration MUST seed the four de-facto clusters observed in GBP
data: 30×20×20, 30×40×10, 50×40×20, 45×55×25.

#### Scenario: Seed migration creates the four clusters

- GIVEN the migration for this capability has run
- WHEN the profile table is queried
- THEN exactly those four box classes exist, each with all four measurement fields populated

### Requirement: Category-based suggestion

Given a product's category/subcategory, the system MUST be able to return a suggested
profile id for pre-fill, or no suggestion if none applies.

#### Scenario: Suggestion returned for a known category

- GIVEN a category with prior profile usage history
- WHEN a suggestion is requested for an item in that category
- THEN a profile id is returned for the caller to pre-select

#### Scenario: No suggestion available

- GIVEN a category with no prior profile usage
- WHEN a suggestion is requested
- THEN an empty result is returned, not an error, leaving manual selection open

### Requirement: Availability precedes the publish-blocking gate

This capability MUST be usable before or alongside `tn-publish-core`'s validation gate
that blocks publication on missing measurements. The gate MUST NOT ship in isolation.

#### Scenario: Gate ships with profiles present

- GIVEN the publish validation gate is active
- WHEN any item lacking GBP measurements is opened for publishing
- THEN at least one profile exists and is selectable to unblock it
