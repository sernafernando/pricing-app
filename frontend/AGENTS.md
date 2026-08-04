# Pricing App Frontend - AI Agent Ruleset

> **Skills Reference**: For detailed patterns, use these skills:
> - [`pricing-app-frontend`](../skills/pricing-app-frontend/SKILL.md) - React + Zustand + CSS Modules + Tesla Design
> - [`react-19`](../skills/react-19/SKILL.md) - React 19 patterns, React Compiler
> - [`zustand-5`](../skills/zustand-5/SKILL.md) - Zustand state management
> - [`typescript`](../skills/typescript/SKILL.md) - TypeScript patterns (if migrating)

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Checking user permissions in backend | `pricing-app-permissions` |
| Creating custom hooks | `pricing-app-frontend` |
| Creating design tokens | `pricing-app-design` |
| Creating/modifying React components | `pricing-app-frontend` |
| Implementing dark mode | `pricing-app-frontend` |
| Implementing dark mode theming | `pricing-app-design` |
| Implementing permission checks | `pricing-app-permissions` |
| Managing user permission overrides | `pricing-app-permissions` |
| Styling with CSS Modules or Tesla Design | `pricing-app-frontend` |
| Styling with Tesla Design System | `pricing-app-design` |
| Using CSS composition | `pricing-app-design` |
| Using PermisosContext | `pricing-app-permissions` |
| Using PermisosContext or ThemeContext | `pricing-app-frontend` |
| Working with Zustand store | `pricing-app-frontend` |

---

## CRITICAL RULES - NON-NEGOTIABLE

### JavaScript Fundamentals
- ALWAYS: Use **`const`** by default, **`let`** only when reassigning
- ALWAYS: Prefer **arrow functions**: `const handleClick = () => {}`
- ALWAYS: Use **destructuring** everywhere: `const { name, email } = user`
- ALWAYS: Use **template literals** over string concatenation: `` `Hello ${name}` ``
- ALWAYS: Use **optional chaining**: `user?.address?.city`
- NEVER: Use `var` — it's 2026, come on
- NEVER: Leave `console.log` in production code (use only for debugging, then remove)

### React Imports
- ALWAYS: `import { useState, useEffect } from 'react'`
- NEVER: `import React from 'react'` or `import * as React`

### Components
- ALWAYS: Functional components with hooks
- ALWAYS: Prop destructuring: `function Button({ label, onClick })`
- ALWAYS: Use **controlled components** for forms (value + onChange)
- ALWAYS: Extract complex logic into **custom hooks**: `useDebounce`, `usePermisos`
- NEVER: Class components
- NEVER: God components — split when a component exceeds ~200 lines

### State Management
- ALWAYS: Zustand for global state (auth)
- ALWAYS: React Context for theme, permissions
- ALWAYS: Local state for component-specific data
- NEVER: Lift state unnecessarily
- NEVER: Store derived state — compute it instead

### Styling
- ALWAYS: CSS Modules: `import styles from './Component.module.css'`
- ALWAYS: Design tokens: prefer **CF (Cloudflare) tokens** for new/refactored code (see table below)
- ALWAYS: Tesla components when available (`buttons-tesla.css`, `forms-tesla.css`, `modals-tesla.css`, `table-tesla.css`)
- ALWAYS: Use `composes` for composition: `composes: btn-primary from '../../styles/buttons-tesla.css'`
- ALWAYS: CamelCase class names: `.modalHeader`, `.btnPrimary`
- NEVER: Inline styles (except dynamic values)
- NEVER: Hardcoded colors — always use design tokens
- CSS Modules is the primary convention for component-scoped styles; Tailwind 4 is installed (`@tailwind` directives in `src/index.css`) and used as utility classes in a handful of components/pages (e.g. `Layout.jsx`, `PanelComisiones.jsx`, `Calculos.jsx`, `Tienda.jsx`, `Productos.jsx`) for layout/spacing. When touching one of those files, follow its existing convention; for new components default to CSS Modules unless you're extending an already-Tailwind file
- NEVER: Introduce Tailwind utilities into a CSS-Modules component just for convenience — pick one convention per file, don't mix
- NEVER: Deeply nested selectors — keep CSS flat
- NEVER: Use `className="input-tesla"` or `className="select-tesla"` — these are phantom classes with NO styles. Form controls come from `forms-tesla.css` via `composes:`, not from a global class (see below)

### Form Inputs / Selects / Textareas

**Compose from `styles/forms-tesla.css`. Never redefine the control.**

```css
/* MyComponent.module.css */
.input {
  composes: input from '../../styles/forms-tesla.css';
}

.select {
  composes: select from '../../styles/forms-tesla.css';
}

/* Dense inline rows (table cells, tree panels) — compose both */
.inputDense {
  composes: input inputSm from '../../styles/forms-tesla.css';
}

/* A label bound to its control. Use a LARGER gap between field units than
   the gap inside one, or the pairing is unreadable. */
.field {
  composes: field from '../../styles/forms-tesla.css';
}

.fieldLabel {
  composes: label from '../../styles/forms-tesla.css';
}
```

Then in JSX: `className={styles.input}`, `className={styles.inputDense}`, etc.

`forms-tesla.css` provides `.input` / `.select` / `.textarea`, the `Sm` dense variants, `.field` / `.label`, and the `:focus`, `:disabled` and invalid (`.inputError` or `aria-invalid="true"`) states. It is **not** imported globally — it exists only to be composed, so it leaks no global class names.

- NEVER: Hand-write `padding` / `border` / `border-radius` / `background` / `color` / `font-size` on a form control in a CSS Module. That is how the codebase ended up with 56 private `.input` definitions across 19 different `padding` values and 6 different `border-radius` values.
- NEVER: Copy a block of control styles from another module. Copy-paste is not a distribution mechanism — it guarantees drift.
- NEVER: Ship a control without a visible focus state. Keyboard users cannot see where they are. Composing from `forms-tesla.css` gives you one; rolling your own usually does not.
- NEVER: Hardcode the focus ring as `rgba(59, 130, 246, 0.1)`. The token `--cf-accent-blue-light` is exactly that value and has light/dark variants.
- If the primitive genuinely cannot express what you need, **change `forms-tesla.css`** so every consumer benefits — do not fork it locally.

**Migration note**: 56 modules still carry their own `.input`. They are being migrated deliberately, not in bulk (jsdom does no layout, so there is no visual regression net). When you touch one of those modules for another reason, migrate its controls to `composes:` as part of that change.

### These two rules are MACHINE-ENFORCED (not just prose)

The rules above used to exist only in this file, so the tree drifted to 56 CSS
modules each defining their own `.input` — 19 different `padding` values for the
same control. Two checks now block that in CI:

| Check | Enforces | Run locally |
|---|---|---|
| stylelint | No hardcoded colors (hex, named, `rgb()`, `hsl()`) in `src/**/*.css` | `pnpm run lint:css` |
| vitest `css-guard` | No `padding` / `border-radius` / `background` on an `.input`/`.select`/`.textarea` class in a `*.module.css` outside `src/styles/` | `pnpm test css-guard` |

Both are **ratchets**: files that already violate are grandfathered in
`css-guard/allowlist.js`, so they pass on the current tree and only fail on NEW
violations. The allowlist may only SHRINK — a listed file that no longer
violates fails the test as a stale entry, so cleanup can't be left half-done.

**When it fails: fix the CSS. Do NOT add the file to the allowlist.**
- Hardcoded color → use a token (`var(--cf-accent-blue)`); for alpha use
  `rgba(var(--token-rgb), 0.1)`, which is allowed.
- Control box styling → `composes:` the primitive instead of re-declaring it.

Adding an allowlist entry is a visible line in the diff and will be treated as a
regression in review.

### Design Token Preference (CF > legacy)

When writing NEW CSS or refactoring existing CSS, prefer CF tokens over legacy tokens:

| Legacy token (avoid) | CF token (prefer) |
|---|---|
| `var(--bg-primary)` | `var(--cf-bg-app)` |
| `var(--bg-secondary)` | `var(--cf-bg-card)` |
| `var(--bg-tertiary)` | `var(--cf-bg-hover)` |
| `var(--border-color)` | `var(--cf-border-default)` |
| `var(--text-primary)` | `var(--cf-text-primary)` |
| `var(--text-secondary)` | `var(--cf-text-secondary)` |
| `var(--text-tertiary)` | `var(--cf-text-tertiary)` |
| `#3b82f6` (blue) | `var(--cf-accent-blue)` |
| `#22c55e` (green) | `var(--cf-accent-green)` |
| `#ef4444` (red) | `var(--cf-accent-red)` |
| `#f59e0b` (orange) | `var(--cf-accent-orange)` |

**Why CF tokens?** They have proper light/dark mode variants in `design-tokens.css`, consistent naming, and better semantic separation (bg-card vs bg-hover vs bg-app). Legacy tokens still work but are less granular.

**Migration note**: Legacy code still uses old tokens. When touching a file's CSS, migrate to CF tokens.

### API Calls
- ALWAYS: Use axios from `services/api.js`
- ALWAYS: Check token: `localStorage.getItem('token')`
- ALWAYS: Handle loading states: `const [loading, setLoading] = useState(false)`
- ALWAYS: Show user feedback on errors (toast, alert, inline message)
- ALWAYS: Wrap async calls in try/catch/finally (finally for loading = false)
- NEVER: Fetch without error handling
- NEVER: Forget to set loading back to false on error

### Icons & Visual Style
- ALWAYS: Use **`lucide-react`** for all icons: `import { Package, Check, X } from 'lucide-react'`
- ALWAYS: Import only the icons you need (tree-shakeable)
- ALWAYS: Use `size` prop for consistent sizing: `<Package size={16} />`
- ALWAYS: Subtle, minimal aesthetic — the UI should feel **clean and professional**
- NEVER: Use emoji as icons (📦, ✅, ❌, 💰, ⚡, etc.) — use lucide SVGs instead
- NEVER: Use `react-icons` for new code — we're standardizing on `lucide-react`
- NEVER: Use emoji in labels, buttons, headings, or UI elements
- NEVER: Use emoji in toasts/alerts — use text only or lucide icons

**Migration note**: Legacy code still has emojis. When touching a file, replace emojis with lucide icons:

| Old (emoji) | New (lucide-react) |
|---|---|
| `📦` | `<Package size={16} />` |
| `💰` | `<DollarSign size={16} />` |
| `✅` | `<Check size={16} />` or `<CheckCircle size={16} />` |
| `❌` | `<X size={16} />` or `<XCircle size={16} />` |
| `⚡` | `<Zap size={16} />` |
| `🔒` | `<Lock size={16} />` |
| `💡` | `<Lightbulb size={16} />` |
| `🎯` | `<Target size={16} />` |
| `🔥` | `<Flame size={16} />` |
| `📋` | `<ClipboardList size={16} />` |

### Dialogs & User Confirmation
- ALWAYS: Use custom modal components (Tesla Design `modals-tesla.css`) for confirmations and messages
- ALWAYS: For destructive actions (delete, overwrite), show a confirmation modal with clear action buttons
- ALWAYS: For error feedback, use inline messages or toast-style notifications within the UI
- ALWAYS: Modals close ONLY via the X button or a Cancel/Close button — **NEVER on overlay click**
- NEVER: Add `onClick` to `.modalOverlay` to close the modal — users lose data when they accidentally click outside
- NEVER: Use `stopPropagation` on `.modalContent` as a workaround for overlay click-to-close
- NEVER: Use `alert()`, `confirm()`, or `prompt()` — they block the thread, look terrible, and break the design system
- NEVER: Use `window.alert()` or `window.confirm()` — same thing, same problem

**Migration note**: Legacy code still uses `alert()` / `confirm()`. When touching a file, replace them with proper modals:

| Old (native) | New (Tesla Design) |
|---|---|
| `alert('Error: ...')` | Inline error message or toast component |
| `confirm('¿Borrar?')` | Confirmation modal with Cancel/Confirm buttons |
| `prompt('Ingrese valor')` | Form modal with input field |

### Accessibility
- ALWAYS: Alt text on images: `<img src="logo.png" alt="Company logo" />`
- ALWAYS: Semantic HTML: `<button>` not `<div onClick>`
- ALWAYS: ARIA labels for icon-only buttons: `<button aria-label="Close modal">`

### Tabs & Permissions
- ALWAYS: Every tab MUST have its own individual permission check via `tienePermiso('modulo.accion')`
- ALWAYS: Wrap tab buttons in `{tienePermiso('...') && (...)}` so unauthorized users don't see tabs they can't access
- ALWAYS: Guard tab content rendering with the same permission check
- NEVER: Render a tab without a permission gate — no tab is "public by default"
- NEVER: Rely on backend-only permission checks for tab visibility — the UI must hide unauthorized tabs

### Effects & Cleanup
- ALWAYS: Provide dependencies array to `useEffect`
- ALWAYS: Cleanup effects (clear timers, cancel requests, unsubscribe)
- NEVER: Use `useEffect` without dependencies array (causes infinite loops)
- NEVER: Forget cleanup — memory leaks are silent killers

---

## TECH STACK

React 18 | Vite | Zustand 5 | Axios | CSS Modules (primary) + Tailwind 4 utilities (select components/pages) | Tesla Design System

---

## PROJECT STRUCTURE

```
frontend/src/
├── pages/                 # Full pages
├── components/            # Reusable components
├── contexts/              # ThemeContext, PermisosContext
├── hooks/                 # Custom hooks
├── store/                 # Zustand stores
├── services/              # API client
└── styles/                # Design tokens, Tesla components
```

---

## COMMANDS

```bash
# Dev
cd frontend
pnpm install
pnpm run dev

# Build
pnpm run build

# Tests
pnpm test          # vitest run
pnpm test:watch    # vitest watch mode
```

Testing libraries in use: `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom`.

---

## COMMON PATTERNS (always available — no skill needed)

### Component with API Call

```jsx
import { useState, useEffect } from 'react';
import api from '@/services/api';
import styles from './ProductosList.module.css';

export default function ProductosList({ onSelect }) {
  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchProductos = async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get('/api/productos');
        setProductos(data);
      } catch (err) {
        setError('Error al cargar productos');
      } finally {
        setLoading(false);
      }
    };
    fetchProductos();
  }, []);

  if (loading) return <div className={styles.loading}>Cargando...</div>;
  if (error) return <div className={styles.error}>{error}</div>;

  return (
    <div className={styles.container}>
      {productos.map((p) => (
        <div key={p.id} onClick={() => onSelect(p)}>
          {p.descripcion}
        </div>
      ))}
    </div>
  );
}
```

### CSS Module with Design Tokens

```css
/* ProductosList.module.css */
.container {
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: var(--spacing-md);
  border-radius: var(--radius-md);
}

.loading {
  color: var(--text-secondary);
  text-align: center;
  padding: var(--spacing-lg);
}

.error {
  background: var(--error-bg);
  color: var(--error-text);
  padding: var(--spacing-sm);
  border-radius: var(--radius-sm);
}
```

### Custom Hook

```js
import { useState, useEffect } from 'react';

export function useDebounce(value, delay = 500) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler); // ← cleanup!
  }, [value, delay]);

  return debouncedValue;
}
```

---

## PRE-COMMIT: ALWAYS RUN LINT

**BEFORE every commit that touches `.jsx`, `.js`, or `.css` files, you MUST run:**

```bash
cd frontend && pnpm exec eslint src/path/to/changed/files.jsx
```

- Fix ALL errors before committing (errors = CI failure = blocked PR)
- Warnings are acceptable (legacy code) but don't add NEW warnings
- Common gotcha: removing `console.error` leaves unused `error` variable → use `catch {` instead of `catch (error) {`

**NEVER skip this step. NEVER.**

---

## QA CHECKLIST

- [ ] **`pnpm run lint` passes** on changed files (run BEFORE commit)
- [ ] `const` by default, `let` only for reassignment, no `var`
- [ ] No `console.log` left in production code
- [ ] Functional components with hooks
- [ ] No `import React` statements
- [ ] Controlled components for forms
- [ ] Error handling on ALL API calls (try/catch/finally)
- [ ] Loading states shown to user
- [ ] CSS Modules used (no inline styles)
- [ ] Design tokens used (no hardcoded colors)
- [ ] Dark mode works in both themes
- [ ] Permissions checked where needed
- [ ] Every tab has its own `tienePermiso()` gate (no ungated tabs)
- [ ] Effects have dependency arrays and cleanup
- [ ] No emoji used as icons — lucide-react SVGs only
- [ ] No `alert()` / `confirm()` / `prompt()` — use custom modals
- [ ] Alt text on images
- [ ] Semantic HTML (`<button>` not `<div onClick>`)

---

## REFERENCES

- React: https://react.dev
- Zustand: https://zustand-demo.pmnd.rs
- Frontend skill: [`../skills/pricing-app-frontend/SKILL.md`](../skills/pricing-app-frontend/SKILL.md)
- Design tokens: `src/styles/design-tokens.css`
- Tesla components: `src/styles/buttons-tesla.css`, `forms-tesla.css`, `modals-tesla.css`, `table-tesla.css`
