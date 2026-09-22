# Delta for compras-oc-match-pipeline

## MODIFIED Requirements

### Requirement: Route extracted numbers onto PedidoCompra

When extract produced routeable numbers and the job's doc-ref stamp is unset, persist MUST write them onto the job's `PedidoCompra` even if the job later becomes `error` after Excel rejection. Persist MUST NOT write if extract never ran. Empty extract numbers MUST be a no-op. MIME enqueue MUST stay unchanged. When the stamp is set, persist MUST skip write-back and MUST still replace renglones, Excel, and acta. Persist MUST stamp only after a routeable write-back. Persist MUST NOT stamp when extract is missing, tipo is non-routeable, numbers are empty, or the claim fence lost. A second adjunto job MUST still write (guard is per job).

| tipo_documento | nro_documento | nro_pedido |
|---|---|---|
| `factura` | `facturas_documento` | `pedidos_documento` if present |
| `pedido`, `proforma`, `nota_venta` | `pedidos_documento` | `pedidos_documento` |
| `comprobante_pago`, `otro`, unknown | no write | no write |

(Previously: Persist always wrote on first routeable extract; retry re-appended the same tokens.)

#### Scenario: Factura routes both numbers

- GIVEN extract `tipo_documento=factura`, `nro_documento=0001-99`, `nro_pedido=PED-184465`
- WHEN persist write-back runs with stamp unset
- THEN `facturas_documento` receives `0001-99`
- AND `pedidos_documento` receives `PED-184465`

#### Scenario: Proforma writes only Pedido/s

- GIVEN extract `tipo_documento=proforma` with both numbers
- WHEN persist write-back runs with stamp unset
- THEN both tokens append to `pedidos_documento`
- AND `facturas_documento` is unchanged

#### Scenario: Payment receipt skips write-back

- GIVEN extract `tipo_documento=comprobante_pago` or `otro` with numbers present
- WHEN persist write-back would run
- THEN both columns stay unchanged
- AND the job is not stamped

#### Scenario: Excel error still writes; missing extract does not

- GIVEN extract produced routeable numbers and Excel then fails
- WHEN persist runs with stamp unset
- THEN write-back still applies and the job is stamped
- AND if extract never ran, no column is written and no stamp is set

#### Scenario: Stamped persist skips write-back

- GIVEN a job whose stamp is set and extract still has the same routeable numbers
- WHEN persist runs
- THEN Factura/s and Pedido/s stay unchanged
- AND renglones, Excel, and acta still recalculate

#### Scenario: Routeable write stamps the job

- GIVEN stamp is unset and extract is routeable with at least one token
- WHEN persist write-back runs
- THEN tokens append and the stamp is set
- AND a lost claim fence MUST NOT stamp
