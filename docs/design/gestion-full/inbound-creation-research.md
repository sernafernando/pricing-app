# Full inbound creation — API research (MLA)

**Date:** 2026-10-30  
**Context:** Gestión Full already computes **Sugerido** (units to send so Full stock reaches last inbound Target). Question: can Pricing **create** the shipment to ML warehouses without Seller Center?

## Verdict

| Capability | Available for MLA (Argentina local Full)? |
|------------|-------------------------------------------|
| Create inbound / ship-to-warehouse via public API | **No** (docs: Seller Center only) |
| Read stock + inbound reception history | **Yes** (already used) |
| Create inbound via `POST /marketplace/fbm/inbounds` | **China FBM only** — not local LATAM Full |
| Semi-automate the manual Seller Center flow | **Yes** (prep data / export / deep links) |

Official LATAM wording (developers.mercadolibre.* fulfillment pages): the seller ships products to ML warehouses **through Seller Center (front)**; APIs only **consult** fulfillment stock and operations.

China-only create flow: [Fulfilment Inbound Creation](https://global-selling.mercadolibre.com/devsite/api-docs/fulfilment-inbound-creation) → `POST /marketplace/fbm/inbounds` + poll `GET .../process/{process_id}`. Explicitly limited to **Fulfillment China**.

## What Pricing already does (read path)

| Piece | Role |
|-------|------|
| `GET /stock/fulfillment/operations/search?type=INBOUND_RECEPTION` | Last reception → **Target** (`gestion_full/inbound.py`) |
| `GET /inventories/{id}/stock/fulfillment` (via existing stock sync) | **Stock Full** |
| Listing `sugerido = max(0, target − stock_full)` | Units to send |
| `GET /marketplace/fbm/user-products/{id}/replenishment` | ML replenishment payload (sweep/bundle; read-only) |

There is **no** POST/create inbound in this repo (confirmed by codebase search).

## If product wants “one-click send to Full”

### Blocked without ML partnership

1. Confirm with ML account manager whether MLA will ever expose create-inbound (or a private app scope).
2. If granted: OAuth scopes, sandbox seller, rate limits, label/PDF pickup, multi-SKU shipment rules, error codes.
3. Integrate create + poll + persist `inbound_id` / shipment id; reconcile with `INBOUND_RECEPTION` when stock lands.
4. Permissions: new write perm (e.g. `gestion_full.enviar`), audit log, kill switch.

**Do not** call China `fbm/inbounds` against a local MLA seller expecting it to work — wrong product model.

### Viable without create API (max acceleration of manual work)

These use data Pricing already has or can surface:

1. **Worklist export** — CSV/clipboard of `sku | inventory_id | mla | sugerido | override` sorted by priority, for paste into Seller Center “enviar a Full”.
2. **Deep link** — open Seller Center Full shipping UI in a new tab (URL pattern to confirm against current ML front; no stable public doc).
3. **Show ML replenishment** — surface `.../replenishment` next to Sugerido so ops compares Pricing Target vs ML suggestion.
4. **Batch checklist UI** — mark rows “cargado en SC” locally (soft state) until `INBOUND_RECEPTION` catches up via weekend drip / refresh.
5. **Optional browser extension** (out of Pricing) — fill SC form from clipboard; higher maintenance, not preferred.

### Suggested next product slice (if approved)

**“Gestión Full → exportar para envío”** (no ML write):

- Endpoint or FE action: export selected rows (sugerido > 0).
- Columns: SKU ERP, título, MLA, inventory_id, Target, Stock Full, Sugerido, override flag.
- Formats: CSV + copy table.
- Ayuda: short steps “abrir Enviar a Full en ML → pegar/cargar”.
- Still depends on human completing shipment + labels in Seller Center.

## Sources

- [Envíos Fulfillment (MLA)](https://developers.mercadolibre.com.ar/es_ar/como-empezar/envios-fulfillment) — consult stock/operations only.
- Same statement on EN/BR/UY fulfillment developer pages: ship via Seller Center; API consult-only.
- [Fulfilment Inbound Creation (Global Selling / China)](https://global-selling.mercadolibre.com/devsite/api-docs/fulfilment-inbound-creation).
- Repo: `backend/app/services/gestion_full/inbound.py`, `backend/app/services/ml_publications/bundle.py` (replenishment GET).
