# Delta for compras-oc-match-pipeline

## MODIFIED Requirements

### Requirement: Extract tipo_documento and pass it through

Extract MUST return `tipo_documento` as one of `factura`, `pedido`, `proforma`, `nota_venta`, `comprobante_pago`, `nota_credito`, `nota_debito`, or `otro`. `nro_documento` and `nro_pedido` MUST still be extracted. `nro_pedido` MUST stay a string; leading zeros MUST survive. Match MUST pass `tipo_documento` through. The acta MUST include one `Tipo documento:` line. Persist MUST lowercase/strip and map `nv`/`nota de venta`/`nota_de_venta`→`nota_venta`; `comprobante`/`constancia`/`recibo`/`transferencia`→`comprobante_pago`; `nc`/`nota de credito`/`nota_de_credito`→`nota_credito`; `nd`/`nota de debito`/`nota_de_debito`→`nota_debito`. Null or unknown MUST be `otro`.

(Previously: enum omitted NC/ND; `nro_pedido` could lose zeros.)

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

#### Scenario: NC and ND normalize as non-factura

- GIVEN extract returns `tipo_documento` `nc` or `nd`
- WHEN persist classifies the paper
- THEN `nc` becomes `nota_credito`
- AND `nd` becomes `nota_debito`

#### Scenario: Leading zeros survive extract

- GIVEN extract JSON would parse `00184465` as a number
- WHEN extract normalizes `nro_pedido`
- THEN the token MUST be the string `00184465`

### Requirement: Route extracted numbers onto PedidoCompra

When extract is routeable and stamp is unset, persist MUST write tokens onto the job's `PedidoCompra` even if Excel errors. Persist MUST NOT write if extract never ran or numbers are empty. MIME enqueue MUST stay unchanged. A set stamp MUST skip write-back and MUST still replace renglones, Excel, and acta. Persist MUST stamp only after a routeable write-back, and MUST NOT stamp when extract is missing, tipo is non-routeable, numbers are empty, or the claim fence lost. A second adjunto job MUST still write. For `nota_credito` or `nota_debito`, persist MUST NOT call `persist_factura_documento`.

| tipo_documento | nro_documento | nro_pedido |
|---|---|---|
| `factura` | `facturas_documento` | `pedidos_documento` if present |
| `pedido`, `proforma`, `nota_venta` | `pedidos_documento` | `pedidos_documento` |
| `comprobante_pago`, `nota_credito`, `nota_debito`, `otro`, unknown | no write | no write |

(Previously: NC/ND were routeable; persist could insert factura.)

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

#### Scenario: NC and ND skip write-back and factura persist

- GIVEN extract `tipo_documento=nota_credito` or `nota_debito` with numbers present
- WHEN persist write-back would run
- THEN both columns stay unchanged
- AND `persist_factura_documento` MUST NOT run
- AND the job is not stamped
