# Delta for pedidos-compra

## MODIFIED Requirements

### Requirement: Empresa name is two-line centered without ellipsis

On the Pedidos list, **Empresa** MUST show `empresa_nombre` (fallback `#id`). The same wrap-and-clip rule MUST apply to every name: wrap on at most two centered lines, then clip. The cell MUST NOT use ellipsis or `text-overflow: ellipsis`. A short name MUST stay on one line when it fits the existing Empresa column. A longer name MUST wrap (on spaces, or anywhere if a token does not fit) and MUST clip after two lines. The cell MUST NOT overflow into **Proveedor**. Column widths MUST stay as they are. The UI MUST NOT special-case any company name.

(Previously: required full visibility of hardcoded worst-case names Grupo Gauss and Pastoriza, width capped to those names, and MUST NOT clip.)

#### Scenario: Two-word name wraps on the space

- GIVEN a pedido whose empresa name has two words that do not fit one line
- WHEN the Pedidos Empresa cell renders
- THEN the painted text MUST include both words
- AND the cell content MUST be horizontally centered
- AND the name MUST occupy at most two lines

#### Scenario: Short name stays one line when it fits

- GIVEN a pedido whose empresa name fits the existing Empresa column on one line
- WHEN the Pedidos Empresa cell renders
- THEN the full name MUST appear on one centered line
- AND MUST NOT be truncated with ellipsis

#### Scenario: Long name clips after two lines without overflowing

- GIVEN a pedido whose empresa name exceeds two lines in the existing Empresa column
- WHEN the Pedidos Empresa cell renders
- THEN the cell MUST clip after two centered lines
- AND MUST NOT show ellipsis
- AND MUST NOT paint over the Proveedor cell

#### Scenario: Wrap rule is name-agnostic

- GIVEN two pedidos with different empresa names
- WHEN both Empresa cells render
- THEN both MUST use the same wrap-and-clip rule
- AND neither cell MUST depend on a particular company name
