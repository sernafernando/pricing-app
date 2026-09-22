# Exploration: feat-compras-oc-match-renglones-ean

Follow-up to `feat-compras-oc-match` (PR #1304) and ops-ux expand-below (`feat-compras-oc-match-ops-ux`). Operators want the expanded **renglones** table to work more like a **carga review surface**: denser columns, matched EAN visible, and quantity formatted as units.

Product facts: backend already returns `ean` (matched GBP) and `ean_extract` (proforma). This change remains **FE-only** for the table/layout/formatters. Excel/acta text generation stay unchanged unless a later decision expands “herramienta de carga”. New branch from `upstream/main`.

---

## Exploration: Renglones as carga-oriented review table

### Current State

**Detail UX.** Expand-below full-width detail with sections “Renglones” (`DataTable` + `RENGLON_COLUMNS`) and “Acta” (`<pre className={styles.acta}>`).

**Columns today:** `indice`, `descripcion`, `cantidad`, `precio_unitario`, `moneda`, `match_estado`, `confianza`, `item_id` — **no EAN**.

**Cell render.** `confianza` → badge; all else → `String(value)` or "—". Decimal strings from API (e.g. `"2.0000"`) show with trailing zeros — quantity looks like money precision.

**Payload.** `OcMatchRenglonResponse` already has `ean`, `ean_extract`, amounts. No API gap for EAN or formatting (format on FE).

**Precedent.** `TabRecepcionDeposito` `formatUnidades` uses `toLocaleString('es-AR', { maximumFractionDigits: 2 })` for unit quantities.

### Operator correction (2026-09-21)

Halt prior propose lock (`ean` after `item_id`). New intent:

1. **Column order / headers:** `#` ; **EAN** ; Descripción ; Cantidad ; P Unit ; Moneda ; Match ; confianza ; item  
   - EAN **before** Descripción (not after Item).
2. **Density:** Descripción has too much empty width; rebalance widths so the row reads as a carga grid.
3. **Cantidad:** do **not** show ~4 decimal places; units are rarely fractional (reuse unidades-style formatting; keep rare fractions with ≤2 digits if needed).
4. **P. unit.:** 4 decimals OK.
5. **Item / confianza:** keep as-is functionally.
6. **Acta / “herramienta de carga”:** operator wants the sector to evolve toward a load tool — **pending clarification** (see Open questions). In this change, at minimum densify renglones so they carry the carga identity (EAN + qty + match). Full acta redesign may be same change or follow-up.

### Affected Areas

- `TabOcMatch.jsx` — reorder/widths `RENGLON_COLUMNS`; add `ean`; format `cantidad` (and optionally `precio_unitario` with 4 fraction digits); maybe bump `minWidth`.
- `TabOcMatch.module.css` — only if table density needs local helpers (prefer column `width` props first).
- `TabOcMatch.test.jsx` — fixture `ean`; assert order/header; assert cantidad without trailing `.0000`.
- Later delta spec: `compras-oc-match-ui`.
- Unchanged: hook, backend schema/model, Excel writer, acta generator (unless acta UX is in-scoped after clarification).

### Approaches

**A. Dense renglones only (recommended for this PR if acta stays text)**  
Reorder columns; add matched `ean`; tighten widths; format cantidad as unidades; keep acta `<pre>`.

**B. Dense renglones + light acta affordances**  
Same as A + clearer acta heading/copy or collapse (“Acta de matching”) without rewriting acta content.

**C. Acta → interactive carga tool**  
Replace or augment acta with editable/review grid aligned to Excel (Código/EAN, cant, stock, costo…). **Out of scope until operator confirms**; larger design.

### Recommendation

Ship **Approach A** (optionally B) in this change once column locks are confirmed. Field for EAN column: matched **`ean`**. Format cantidad via unidades-style formatter (max 2 fraction digits, trim trailing zeros). Place EAN immediately after `#`. Cap Descripción flex so numeric/match columns stay readable.

Hold Approach C until Gabe clarifies “herramienta de carga”.

### Risks

- Binding `ean_extract` by mistake.
- Over-tight Descripción truncates useful text — use `title` for full string if truncated.
- Fractional qty (e.g. 0.5 kg) must still display with ≤2 decimals, not forced integers.
- Shared `DataTable` must not gain global style changes that break other tabs.

### Test plan sketch

- Fixture with `ean`, `cantidad: '2.0000'` → UI shows EAN value and `2` (or `2` without four zeros).
- Headers appear in locked order including EAN before Descripción.
- Null `ean` → "—".

### Open questions

None. Gabe (2026-09-21): acta block stays as-is; this change is renglones only (EAN + density + cantidad without trailing decimals).

### Ready for Proposal

Yes — **Approach A** locked. Column order and formatters locked.
