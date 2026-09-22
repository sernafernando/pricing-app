# Delta for compras-oc-match-ui

## ADDED Requirements

### Requirement: Matched EAN column after # before Descripción

The expand-below renglones table MUST show matched GBP `ean` in a column labeled **EAN** immediately after `#` and before Descripción. The column MUST bind to payload `ean`, not `ean_extract`. Null or missing `ean` MUST render as "—".

#### Scenario: Matched ean appears after hash before description

- GIVEN an expanded job with a renglon whose `ean` is `7791234567890`
- WHEN the operator views the renglones table
- THEN the EAN column is after `#` and before Descripción
- AND the cell shows `7791234567890`

#### Scenario: Null ean renders em dash

- GIVEN a renglon with `ean` null
- WHEN the operator views the renglones table
- THEN the EAN cell shows "—"

### Requirement: Locked renglones column order and headers

Renglones columns MUST appear in this field order: `indice`, `ean`, `descripcion`, `cantidad`, `precio_unitario`, `moneda`, `match_estado`, `confianza`, `item_id`. Headers MUST be `#`, `EAN`, `Descripción`, `Cantidad`, `P Unit`, `Moneda`, `Match`, `Confianza`, `Item`.

#### Scenario: Headers appear in locked order

- GIVEN an expanded job with renglones
- WHEN the operator views the table header
- THEN headers are `#`, `EAN`, `Descripción`, `Cantidad`, `P Unit`, `Moneda`, `Match`, `Confianza`, `Item` in that order

### Requirement: Densify Descripción widths

The renglones table MUST reduce empty width on Descripción and rebalance remaining columns so numeric and match columns stay readable. If Descripción text is truncated, the full string MUST remain available via `title`. Shared DataTable styles MUST NOT change.

#### Scenario: Descripción empty width is reduced

- GIVEN an expanded job with renglones
- WHEN the operator views the table
- THEN Descripción occupies less unused width than before
- AND numeric and match columns remain readable

#### Scenario: Truncated Descripción keeps full title

- GIVEN a renglon whose Descripción is truncated
- WHEN the operator inspects the cell `title`
- THEN the full Descripción string is available

### Requirement: Cantidad unidades formatting

The renglones `cantidad` cell MUST format as units: trim trailing zeros from four-decimal API strings, and MUST use at most 2 fraction digits when the value is fractional. `"2.0000"` MUST NOT display with four trailing zeros.

#### Scenario: Integer-like cantidad drops trailing zeros

- GIVEN a renglon with `cantidad` `"2.0000"`
- WHEN the operator views the Cantidad cell
- THEN the displayed value has no four trailing zeros
- AND the value reads as units (e.g. `2`)

#### Scenario: Fractional cantidad keeps at most two digits

- GIVEN a renglon with `cantidad` `"0.5000"`
- WHEN the operator views the Cantidad cell
- THEN at most 2 fraction digits are shown
- AND the value is not forced to an integer

### Requirement: Precio unitario keeps four decimals

The renglones `precio_unitario` cell MAY keep approximately 4 decimal places. This change MUST NOT apply unidades-style trimming to `precio_unitario`.

#### Scenario: Precio unitario still shows four decimals

- GIVEN a renglon with `precio_unitario` `"12.3456"`
- WHEN the operator views the P Unit cell
- THEN approximately 4 decimal places remain visible

### Requirement: Acta, ean_extract, and backend unchanged

This change MUST NOT alter the acta `<pre>` block, MUST NOT add an `ean_extract` column, and MUST NOT change backend, schema, migration, Excel writer, acta generator, or `useOcMatch.js`.

#### Scenario: Acta block stays as-is

- GIVEN an expanded job with acta text
- WHEN the operator views detail
- THEN the acta `<pre>` content and presentation are unchanged

#### Scenario: ean_extract is not a column

- GIVEN an expanded job whose renglones include `ean_extract`
- WHEN the operator views the renglones table
- THEN no `ean_extract` column is shown

#### Scenario: Backend and Excel stay unchanged

- GIVEN this change is applied
- WHEN jobs are listed, downloaded, or retried
- THEN backend, schema, Excel writer, and hook behavior are unchanged
