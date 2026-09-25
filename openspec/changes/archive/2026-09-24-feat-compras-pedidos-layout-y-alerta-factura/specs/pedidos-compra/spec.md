# Delta for pedidos-compra

## ADDED Requirements

### Requirement: Empresa name is two-line centered without ellipsis

On the Pedidos list, **Empresa** MUST show the full `empresa_nombre` (fallback `#id`). The name MUST wrap on at most two centered lines. The cell MUST NOT use ellipsis, `text-overflow: ellipsis`, or clip the worst-case known names **Grupo Gauss** and **Pastoriza**. Column width MUST be capped to those names (wrapped), not to a long single-line string.

#### Scenario: Grupo Gauss is fully visible on two centered lines

- GIVEN a pedido whose empresa is `Grupo Gauss`
- WHEN the Pedidos Empresa cell renders
- THEN the painted text MUST contain `Grupo` and `Gauss` with no ellipsis
- AND the cell content MUST be horizontally centered
- AND both words MUST remain fully visible (wrap allowed)

#### Scenario: Pastoriza is fully visible

- GIVEN a pedido whose empresa is `Pastoriza`
- WHEN the Pedidos Empresa cell renders
- THEN the full word `Pastoriza` MUST be visible
- AND MUST NOT be truncated with ellipsis

### Requirement: Acciones icons use a two-by-two grid

Pedidos **Acciones** MUST lay out icon buttons in a CSS grid of **two columns** (2×2 when four icons show). Extra icons MAY add rows. The Acciones column MUST be narrower than the current one-row ~180px layout.

#### Scenario: Four icons occupy two columns

- GIVEN a row that shows four action icons
- WHEN the Acciones cell renders
- THEN the icons MUST occupy two columns, not four in one row
- AND the Acciones `<col>` width MUST be less than `180px`

### Requirement: Pedidos column budget fits 1280–1400

Fixed Pedidos columns MUST leave leftover width for **Proveedor** at ~1280–1400 useful table width. **Fecha pago** MUST stay `110px`, **Mon.** `60px`, **Estado** `152px`, **Proceso** `220px` unless a measured cut is recorded in this change’s design. Número, Empresa, Saldo, Plazo, and Acciones MUST stay width-capped. Proveedor MUST remain the only flexible absorber. Proveedor text and **Mon.** MUST NOT overlap.

#### Scenario: No Proveedor/Mon collision at 1280–1400

- GIVEN a Pedidos row with a long proveedor name and a moneda value
- WHEN the table is painted at 1280–1400px useful width
- THEN Proveedor ink and the Mon. cell MUST have positive width
- AND their overlap area MUST be 0

#### Scenario: Locked columns stay

- GIVEN Pedidos columns are rendered
- WHEN `<col>` widths are read
- THEN Fecha pago MUST be `110px`
- AND Mon. MUST be `60px`
- AND Estado MUST be `152px`
- AND Proceso MUST be `220px`
