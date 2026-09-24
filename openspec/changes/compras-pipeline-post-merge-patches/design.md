# Design: Compras Pipeline Post-Merge Patches

## Technical Approach

Patch six post-#1340 operator bugs on existing extract/persist and Pedidos/Depósito/banner surfaces. No new capabilities. No Alembic.

Implements proposal defense-in-depth and deltas: `compras-oc-match-pipeline`, `compras-factura-documentos`, `pedidos-compra`, `recepcion-deposito`, `compras-pipeline-alerts`.

## Out of Scope (locked)

**OC-match expand-below is OUT OF SCOPE / deferred to oc-match owners.** It would amend the `feat-compras-oc-match-ops-ux` expand-below lock. Do not modify `TabOcMatch.jsx` or `TabOcMatch.module.css`.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|---|---|---|---|
| NC/ND ignore | prompt-only / persist-only / triple gate | Gemini may still emit `factura` | Prompt enum + `normalize_tipo` aliases + persist skip |
| Tokens / zeros | `str(int)` after loads / quote lexeme then loads | `json.loads(00184465)` drops zeros | Quote `nro_pedido`/`nro_documento` in raw text when the value is a leading-zero integer; then stringify. Never `int()`/`Number()` |
| Pedidos default | client hide / comma-OR known list / `excluir_estado` | hide lies on `total`; known-list hides future estados | Optional `excluir_estado` on `GET /pedidos`. Default FE sends `excluir_estado=cancelado`. Explicit `estado=` wins |
| Checkbox | rebind / leave | already `row.cargada` | Keep `Boolean(row.cargada)`. Do not touch 5m sweep / PM notify. NC/ND stop creating rows |
| Deep-link | local-only Ver / consume-or-clear + nonce | same-URL `navigate` no-ops; leftover remount-reopens | Consume after open; clear on close and user tab click; banner/Ver add `open=<nonce>` |
| Expand-below | scroll polish / layout rewrite | amends locked UX | Deferred — not this change |
| Incluir CC default | keep false / default true | operators miss CC pedidos | `useState(true)` for `incluirCC` |

## Data Flow

### NC/ND + string tokens

```
Gemini raw JSON
  → quote_numeric_doc_fields ("00184465" stays string)
  → json.loads → stringify nro_*
  → match pass-through (strings)
  → _persist claim fence
       → apply_writeback (TIPOS_ROUTEABLE only)
       → persist_factura_documento IFF normalize_tipo == factura
NC/ND: known, not routeable, no stamp, no factura row
```

### Pedido query lifecycle

```
Inbound / Banner / Ver
  → ?tab=pedidos&pedido=ID[&focus=][&open=nonce]
  → TabPedidos effect opens detalle
  → consume: strip pedido, focus, open (keep tab + other keys)
Close detalle → strip leftover (except clon/related reopen)
User Compras tab click → strip pedido/focus/open
Remount Pedidos → no stale query → no reopen
```

Inbound land opens once, then consume. Query-driven `tab=` sync is not a user tab click — do not strip before that first consume.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/services/oc_match/extract.py` | Modify | Enum + NC/ND copy; `quote_numeric_doc_fields`; stringify tokens |
| `backend/app/services/oc_match/gemini_pool.py` | Modify | Optional `transform_text` before `json.loads` |
| `backend/app/services/oc_match/doc_refs.py` | Modify | Known + aliases for NC/ND; still not routeable |
| `backend/app/services/oc_match/worker.py` | Modify | Explicit NC/ND skip of `persist_factura_documento` |
| `backend/app/services/oc_match/match.py` | Modify | Pass string tokens (no numeric coerce) |
| `backend/app/routers/administracion_compras.py` | Modify | `excluir_estado` Query; `~estado.in_()` when `estado` is None |
| `frontend/src/hooks/useRecepcionDeposito.js` | Modify | Shared strip of `pedido`/`focus`/`open` |
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modify | Default exclude; logistic estados; consume/clear; Ver nonce |
| `frontend/src/pages/AdministracionCompras.jsx` | Modify | User tab click clears `pedido`/`focus`/`open` |
| `frontend/src/components/AppLayout.jsx` | Modify | `deepLinkForCompras` appends `open` nonce |
| `frontend/src/components/compras/TabRecepcionDeposito.jsx` | Modify | Split `pedidos_documento` on `;`; chip each stored string; `incluirCC` default `true` |
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modify | Binding audit only if not already `row.cargada` |

Unchanged: `TabOcMatch.*`, Alembic, `compras_alertas_service` 5m/PM paths, CAS, freeze-migration.

## Interfaces / Contracts

```python
TIPOS_CONOCIDOS |= {"nota_credito", "nota_debito"}
TIPOS_ROUTEABLE = {"factura", "pedido", "proforma", "nota_venta"}  # unchanged
# nc | nota de credito | nota_de_credito → nota_credito
# nd | nota de debito | nota_de_debito → nota_debito
```

`GET /pedidos?excluir_estado=cancelado` ignored when `estado` is set. No schema/Alembic.

Query keys consumed: `pedido`, `focus`, `open` (`replace: true`). Keep `tab`, `eje`, OP keys.

Chips: `parse_tokens` (`split(';')`, strip, drop empty). Render the stored string.

`ESTADOS` adds `recibido`, `con_faltantes`, `controlado`. Empty select = default exclude, not “all including cancelado”.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | NC/ND aliases + skip write-back; quote `00184465` | `test_oc_match_doc_refs.py` + extract helper |
| Integration | NC/ND: no columns, no stamp, no factura row; factura still seeds constancia `cargada=false` | `test_oc_match_worker.py` |
| API | default exclude hides cancelado; explicit `cancelado` + logistic estados | listar tests |
| FE | default filter + dropdown; chips keep zeros / split; checkbox = `cargada`; nonce force-open; close/tab-change no sticky reopen; inbound opens once | existing vitest files |
| Timer | 5m / PM notify | do not edit sweep modules |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration required. No Alembic. Revert the patch PR; extract/persist, filter, and query-lifecycle revert independently.

## Open Questions

- [x] Expand-below deferred to oc-match owners.
- [x] No Alembic.
- [ ] Residual: Gemini labels NC as `factura` — persist gate cannot see the paper; accept + prompt tests only.
