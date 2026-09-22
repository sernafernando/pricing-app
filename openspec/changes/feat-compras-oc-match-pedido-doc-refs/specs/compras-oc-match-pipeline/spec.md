# Delta for compras-oc-match-pipeline

## ADDED Requirements

### Requirement: Extract tipo_documento and pass it through

Extract MUST return `tipo_documento` as one of `factura`, `pedido`, `proforma`, `nota_venta`, `comprobante_pago`, or `otro`. Existing `nro_documento` and `nro_pedido` MUST still be extracted. Match MUST pass `tipo_documento` through. The acta MUST include one `Tipo documento:` line. Persist MUST lowercase/strip `tipo_documento` and MUST map aliases `nv`, `nota de venta`, `nota_de_venta` → `nota_venta` and `comprobante`, `constancia`, `recibo`, `transferencia` → `comprobante_pago`. Null or unknown MUST be treated as `otro`.

#### Scenario: Factura extract includes tipo

- GIVEN a PDF that is a supplier invoice
- WHEN extract and match complete
- THEN `tipo_documento` is `factura` and `nro_documento` / `nro_pedido` remain present
- AND the acta contains one `Tipo documento:` line

#### Scenario: Alias and unknown normalize

- GIVEN extract returns `tipo_documento` `nv` or null
- WHEN persist classifies the paper
- THEN `nv` becomes `nota_venta`
- AND null or unknown becomes `otro`

### Requirement: Route extracted numbers onto PedidoCompra

When extract produced routeable numbers, persist MUST write them onto the job's `PedidoCompra` even if the job later becomes `error` after Excel rejection. Persist MUST NOT write if extract never ran. Empty extract numbers MUST be a no-op. MIME enqueue MUST stay unchanged.

| tipo_documento | nro_documento | nro_pedido |
|---|---|---|
| `factura` | `facturas_documento` | `pedidos_documento` if present |
| `pedido`, `proforma`, `nota_venta` | `pedidos_documento` | `pedidos_documento` |
| `comprobante_pago`, `otro`, unknown | no write | no write |

#### Scenario: Factura routes both numbers

- GIVEN extract `tipo_documento=factura`, `nro_documento=0001-99`, `nro_pedido=PED-184465`
- WHEN persist write-back runs
- THEN `facturas_documento` receives `0001-99`
- AND `pedidos_documento` receives `PED-184465`

#### Scenario: Proforma writes only Pedido/s

- GIVEN extract `tipo_documento=proforma` with both numbers
- WHEN persist write-back runs
- THEN both tokens append to `pedidos_documento`
- AND `facturas_documento` is unchanged

#### Scenario: Payment receipt skips write-back

- GIVEN extract `tipo_documento=comprobante_pago` or `otro` with numbers present
- WHEN persist write-back would run
- THEN both columns stay unchanged
- AND the job still enqueued and ran extract/match

#### Scenario: Excel error still writes; missing extract does not

- GIVEN extract produced routeable numbers and Excel then fails
- WHEN persist runs
- THEN write-back still applies
- AND if extract never ran, no column is written

### Requirement: Append-only write-back never touches numero_factura

Write-back MUST append unique tokens only. Stored values MUST join with `; `. Parse MUST split on `;` then strip. Dedupe MUST be case-insensitive after strip and MUST keep first-seen casing. Persist MUST NOT replace, wipe, reorder, or normalize number formats. Concurrent jobs on the same pedido MUST serialize with `SELECT FOR UPDATE`. The worker MUST write columns in the persist session and MUST NOT call `editar_pedido`. Persist MUST NEVER write `numero_factura`. Each eligible PDF job MUST append independently. A duplicate job with the same tokens MUST be a no-op.

#### Scenario: Append unique and ignore casefold duplicate

- GIVEN `facturas_documento` is `A; B` and a `factura` job returns `nro_documento` `a` then `C`
- WHEN write-back runs twice
- THEN the first pass leaves `A; B`
- AND the second pass stores `A; B; C`

#### Scenario: Never writes numero_factura or EDITADO

- GIVEN a routeable extract on a pedido that already has `numero_factura`
- WHEN persist write-back runs
- THEN `numero_factura` is unchanged
- AND `editar_pedido` is not called
