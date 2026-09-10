# Compras OC Match Pipeline Specification

## Purpose

Extract proforma lines, match against `tb_item`, generate GBP carga-masiva Excel, and persist renglones plus acta. Pricing DB is the source of truth. Mail is OFF.

## Requirements

### Requirement: Async extract with 3-key Gemini pool

The worker MUST run extract → match → excel → persist in its own database session. Gemini MUST use a three-key pool that rotates on 429/503. Gemini MUST NOT run inside the upload request.

#### Scenario: Pipeline runs after enqueue

- GIVEN a `queued` PDF job
- WHEN the background worker starts
- THEN extract, match, excel, and persist run outside the upload request
- AND Gemini keys are rotated on 429 or 503

### Requirement: tb_item maestro without fabricante exact-match

Maestro MUST load `tb_item` joined to brand, category, and subcategory. EAN MUST equal `item_code`. The system MUST NOT use `productos_erp` as maestro. Exact fabricante-code match MUST be skipped. Unmatched packs and colors MUST be flagged in the acta.

#### Scenario: Match uses tb_item item_code

- GIVEN extracted lines and `tb_item` rows
- WHEN matching runs
- THEN candidates use `item_code` as EAN and Gemini among candidates
- AND `productos_erp` is not queried as maestro
- AND no fabricante-code exact match is applied

#### Scenario: Unmatched packs flagged in acta

- GIVEN a line that does not uniquely match a `tb_item` row
- WHEN the pipeline persists results
- THEN the acta flags the unmatched line

### Requirement: Empresa map, Excel, acta, USD TC, mail OFF

Empresa MUST map `pedido.empresa_id` `1` to `PASTORIZA` and `2` to `GRUPO GAUSS`. Excel MUST use the vendored Automations GBP carga-masiva template and MUST be written to a sibling of `COMPRAS_UPLOADS_DIR`. Renglones, acta, and Excel path MUST persist in Pricing DB. USD without TC MUST become job `error` plus acta, not a successful empty xlsx. The pipeline MUST NOT send mail.

#### Scenario: Golden PDF produces SoT artifacts

- GIVEN a valid PDF job and a mapped empresa
- WHEN the pipeline completes
- THEN renglones, acta, and an xlsx path are persisted in Pricing DB
- AND no mail is sent

#### Scenario: USD without TC is error

- GIVEN a job whose moneda is USD and TC is missing
- WHEN excel generation would run
- THEN the job is `error` with acta
- AND no empty xlsx is treated as success
