# hay-mejores-refresh-catalog — refresh catalog competition when flagged

Branch: `feat/hay-mejores-refresh-catalog` (from `upstream/main`). PRs → `sernafernando/pricing-app:main`.
Delivery: `ask-on-risk`. Runners: pytest.

## Objective

When `hay_mejores_ofertas` is newly set (or re-marked with a new fingerprint), enqueue a background refresh of `ml_catalog_competition` for that MLA. No UI in this slice.

## Specs

S1. On hay_mejores becoming true or fingerprint novelty: enqueue the MLA for catalog-competition refresh.
S2. A worker drains the queue and persists via existing `refrescar_competencia_catalogo` (same path as the manual refresh button).
S3. No UI changes.

## Tasks

| ID | Specs | Route | Status | Commit |
|----|-------|-------|--------|--------|
| T1 | S1–S3 queue + hook + worker + migration + tests | inline | done | 107d629c7 |

## Log

L1. User: se puede hacer que un worker refreshee el catalogo de la publicacion cuando salta el trigger de que hay promos candidatas mejores? por ahora solo el update, despues vemos como lo metemos en la UI.
