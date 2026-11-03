---
name: Pricing Tesla Ops
colors:
  surface: '#181818'
  surface-dim: '#000000'
  surface-bright: '#2a2a2a'
  surface-container-lowest: '#000000'
  surface-container-low: '#111111'
  surface-container: '#181818'
  surface-container-high: '#1f1f1f'
  surface-container-highest: '#2a2a2a'
  on-surface: '#ffffff'
  on-surface-variant: '#a0a0a0'
  inverse-surface: '#ffffff'
  inverse-on-surface: '#171a20'
  outline: '#2a2a2a'
  outline-variant: '#404040'
  surface-tint: '#3e6ae1'
  primary: '#3e6ae1'
  on-primary: '#ffffff'
  primary-container: '#1e4fc2'
  on-primary-container: '#e8eef9'
  inverse-primary: '#3e6ae1'
  secondary: '#ff9800'
  on-secondary: '#171a20'
  secondary-container: '#f57c00'
  on-secondary-container: '#fff3e0'
  tertiary: '#00cc66'
  on-tertiary: '#006633'
  tertiary-container: '#00b359'
  on-tertiary-container: '#e5f9f0'
  error: '#e31937'
  on-error: '#ffffff'
  error-container: '#c41230'
  on-error-container: '#fce8ec'
  background: '#000000'
  on-background: '#ffffff'
  surface-variant: '#1f1f1f'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 1.25rem
    fontWeight: '600'
    lineHeight: 1.75rem
  headline-md:
    fontFamily: Inter
    fontSize: 1.125rem
    fontWeight: '600'
    lineHeight: 1.5rem
  headline-sm:
    fontFamily: Inter
    fontSize: 0.9375rem
    fontWeight: '600'
    lineHeight: 1.375rem
  body-lg:
    fontFamily: Inter
    fontSize: 0.875rem
    fontWeight: '400'
    lineHeight: 1.25rem
  body-md:
    fontFamily: Inter
    fontSize: 0.8125rem
    fontWeight: '400'
    lineHeight: 1.125rem
  body-sm:
    fontFamily: Inter
    fontSize: 0.75rem
    fontWeight: '400'
    lineHeight: 1rem
  label-lg:
    fontFamily: ui-monospace
    fontSize: 0.8125rem
    fontWeight: '500'
    lineHeight: 1.125rem
  label-md:
    fontFamily: ui-monospace
    fontSize: 0.75rem
    fontWeight: '500'
    lineHeight: 1rem
  label-sm:
    fontFamily: ui-monospace
    fontSize: 0.6875rem
    fontWeight: '500'
    lineHeight: 0.875rem
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.75rem
  gutter-compact: 0.5rem
  margin: 1rem
  margin-compact: 0.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

# Design System: Pricing Tesla Ops

Derived from Pricing App Tesla / CF tokens (`frontend/src/styles/theme.css`, `design-tokens.css`, skill `pricing-app-design`). Dense internal ERP UI for e-commerce operations — not a marketing site.

## Brand & Style

- **Operative density:** maximize rows and columns per viewport; minimize chrome.
- **Tesla restraint:** subtle borders, soft elevation, no decorative gradients or pill clusters.
- **Dark ops canvas:** black app background (`#000`), card surfaces `#181818`, borders `#2a2a2a`.
- **Brand accent:** Tesla electric blue `#3e6ae1` for primary actions and focus.
- **Semantic:** success `#00cc66`, warning `#ff9800`, error `#e31937`.

## Colors

- App background: `#000000`
- Card / table surface: `#181818`
- Hover / inset: `#1f1f1f` / `#111111`
- Border default: `#2a2a2a`
- Text primary / secondary / tertiary: `#ffffff` / `#a0a0a0` / `#707070`
- Primary CTA: `#3e6ae1`

## Typography

- UI copy: Inter (or system sans close to Pricing).
- Codes (EAN, inventory_id, MLAU, stock numbers): monospace, compact.
- Compact table row height ~32px; headers 12–13px medium weight.

## Layout

- Full-width desktop (1280+): left sidebar (Pricing shell) + main content.
- Page under Reportes: title "Gestión Full", thin filter bar, dense data table.
- No hero, no KPI card strip unless essential; filters stay one compact row.

## Components

### Table
- Flush grid, 1px `#2a2a2a` borders, sticky header.
- Grouped product rows: same ERP código consecutive; soft shared tint per product group (subtle left accent or background wash) so multiple `inventory_id` rows read as one product.
- Monospace for EAN, inventory_id, stocks, sales counts.
- Editable override cell: inset input 28px height for PM/admin; read-only for others.

### Filters
- Compact search + optional marca/categoría chips; "everyone sees all" default — filters optional.

### Buttons
- Primary solid `#3e6ae1`, radius 4px, height 32px.
- Ghost/secondary with border `#2a2a2a`.
