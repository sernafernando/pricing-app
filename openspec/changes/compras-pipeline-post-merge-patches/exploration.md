# Exploration: compras-pipeline-post-merge-patches

Post-merge operator patches after stack landed via #1340. Explore only — 2026-09-24.

## Intent

Fix Gabe-reported UX/data bugs in Compras without amending archived/merged changes
(`compras-faltantes-responsable-cas`, `compras-pipeline-reqs-closure`). Do not regress
factura-cargada 5m timer, CAS resolver, or migration freeze agreements.

## Items

| # | Symptom | Likely locus | Domain |
|---|---------|--------------|--------|
| 1 | NC/ND treated as factura and attached to pedido | `oc_match/extract.py` PROMPT enum; `doc_refs.py` TIPOS_*; `worker._persist` → `persist_factura_documento` | compras-oc-match-pipeline, compras-factura-documentos |
| 2 | Depósito chips drop leading zeros on pedido numbers | Extract JSON number → string; `oc_poh_id` int; chip is `String(trim)` | recepcion-deposito, compras-oc-match-pipeline |
| 3 | OC-match job select opens panel below whole list | `TabOcMatch.jsx` + CSS column layout — **shipped lock** expand-below | compras-oc-match-ui |
| 4 | Pedidos filter should be all estados except cancelado | `TabPedidosCompra` `filtroEstado=''` includes cancelado; missing recibido/con_faltantes/controlado in select | pedidos-compra |
| 5 | Banner fijo: Ver no lo saca; refresh lo deja; solo X. Fix: Ver → `/ok` + navigate (dismissibles) | `AppLayout` Ver onClick vs `onDismiss`/`handleOkComprasAlerta` | compras-pipeline-alerts |
| 6 | Ver / banner buttons often no-op; faltantes Ver works | `AppLayout.deepLinkForCompras`; close modal leaves `?pedido=`; navigate no-op if URL unchanged | compras-pipeline-alerts, pedidos-compra |
| 7 | Banner open → switch Compras tab → back to Pedidos reopens pedido | `handleCloseDetalle` does not clear query; remount re-reads `pedido` | pedidos-compra, compras-pipeline-alerts |
| 8 | Depósito toggle "Incluir cuenta corriente" default false → want true | `TabRecepcionDeposito.jsx` `useState(false)` for `incluirCC` | recepcion-deposito |

## Key paths

- BE: `backend/app/services/oc_match/{extract,doc_refs,worker}.py`, `pedidos_service.py`, `compras_alertas_service.py`
- FE: `TabPedidosCompra.jsx`, `TabRecepcionDeposito.jsx`, `TabOcMatch.jsx`, `ModalPedidoDetalle.jsx`, `AppLayout.jsx`, `AlertBanner.jsx`

## Ownership note (item 3)

Accordion-per-row **amends** `feat-compras-oc-match-ops-ux` lock (*Expand-below full-width*).
Recommend: **defer to oc-match owners**. Optional in-scope polish only: scroll selected row / detail into view — not a layout rewrite.

## Risks

- Broadening Gemini enum may need prompt+tests; false `factura` still possible → defense in depth at writeback/persist.
- Clearing `?pedido=` on close/tab change must not break intentional deep-links from notifications.
- Default exclude-cancelado must remain overridable (user can still pick Cancelado explicitly).
