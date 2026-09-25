# Design: Generic Empresa two-line wrap

## Technical Approach

Local CSS + JSX cleanup on Pedidos only. Keep `COLUMNS` as-is (`empresa` `104px`). Drop the name branch that Chicho flagged on #1348. Amends `pedidos-compra` “Empresa name is two-line centered without ellipsis”.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| Wrap mechanism | Keep regex + `<br>` vs CSS wrap | Regex only covers one name; others overflow | **CSS only** — locked `.empresaCell`; delete `.empresaCellGrupoGauss` |
| Clip vs full visibility | Never clip Gauss/Pastoriza vs clip after 2 lines | Archived spec forbade clip | **Clip after 2.5em** (Gabe 2026-09-25). No ellipsis |
| Column width | Retune `COLUMNS.empresa` vs keep 104px | Width retune is out of scope | **Do not touch `COLUMNS`** |
| Test hook | Keep `data-wrap` vs drop it | `data-wrap` *is* the name branch | **Remove `data-wrap`**. Visual test uses computed style + geometry |
| Comments | Document Gauss/Pastoriza in CSS | Encodes a special case | **No company names in JSX or CSS comments** |

## Data Flow

```
empresa_nombre || #empresa_id
        │
        ▼
<span class=empresaCell data-testid="empresa-cell">{nombre}</span>
        │
        ▼
.empresaCell  (normal wrap, anywhere, center, max-height 2.5em, hidden)
        │
        ├── fits 1 line → stays 1 centered line
        ├── 2 words / long token → wrap ≤ 2 lines
        └── taller than 2.5em → clip (no ellipsis, no spill to Proveedor)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modify | `case 'empresa'`: render `nombre` only. Remove `isGrupoGauss`, `<br>`, `data-wrap`, extra class. Keep `data-testid="empresa-cell"` |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modify | Replace `.empresaCell` + `.empresaCellGrupoGauss` with the locked rule. Remove Gauss/Pastoriza comments |
| `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Modify | Drop `data-wrap` / `nowrap` branch. Assert shared computed style on every empresa cell. Keep two-word + short-name fixtures as *examples* of wrap vs fit. Add a long-name fixture that proves 2-line clip (height ≤ 2.5em, no Proveedor overlap, no ellipsis) |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modify (cheap) | jsdom: raw name text, no `<br>`, no `data-wrap` (css:false — cannot prove wrap geometry here) |

## Interfaces / Contracts

Locked CSS (only empresa cell rule):

```css
.empresaCell {
  display: block;
  text-align: center;
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.25;
  max-height: 2.5em;
  overflow: hidden;
}
```

JSX contract: `{nombre}` as a text child. No name regex. No `data-wrap`.

Do not change:

```js
{ key: 'empresa', label: 'Empresa', width: '104px' }
{ key: 'fecha_pago', width: '110px' }
{ key: 'moneda', width: '60px' }
{ key: 'estado', width: '152px' }
{ key: 'proceso', width: '220px' }
{ key: 'acciones', width: '104px' }
```

Visual fixtures MAY still include a two-word name and a short name as examples. They MUST NOT assert `data-wrap=grupo-gauss` or `white-space: nowrap` for a named company.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| jsdom | No `<br>`, no `data-wrap`; text is the raw name | `TabPedidosCompra.test.jsx` |
| Visual | Shared computed style; 2-word wrap; short name 1 line when it fits; long name clips ≤ 2.5em; no Proveedor overlap | Playwright visual at existing 1360 wrapper |
| Out of scope | Fecha pago `110px` literal; Acciones 2×2 changes | Do not add or retune those asserts |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No schema. Follow-up commit on `feat/compras-pedidos-layout-y-alerta-factura` / PR #1348 → **main**. Do not open a new PR.

## Open Questions

- None — CSS and “no name branch” are locked.
