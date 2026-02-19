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
- ALWAYS: Design tokens: `var(--bg-primary)`, `var(--text-primary)`
- ALWAYS: Tesla components when available (`buttons-tesla.css`, `modals-tesla.css`, `table-tesla.css`)
- ALWAYS: Use `composes` for composition: `composes: btn-primary from '../../styles/buttons-tesla.css'`
- ALWAYS: CamelCase class names: `.modalHeader`, `.btnPrimary`
- NEVER: Inline styles (except dynamic values)
- NEVER: Hardcoded colors — always use design tokens
- NEVER: Tailwind utilities (project uses CSS Modules)
- NEVER: Deeply nested selectors — keep CSS flat

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

### Effects & Cleanup
- ALWAYS: Provide dependencies array to `useEffect`
- ALWAYS: Cleanup effects (clear timers, cancel requests, unsubscribe)
- NEVER: Use `useEffect` without dependencies array (causes infinite loops)
- NEVER: Forget cleanup — memory leaks are silent killers

---

## TECH STACK

React 18 | Vite | Zustand 4 | Axios | CSS Modules | Tesla Design System

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
npm install
npm run dev

# Build
npm run build
```

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
cd frontend && npx eslint src/path/to/changed/files.jsx
```

- Fix ALL errors before committing (errors = CI failure = blocked PR)
- Warnings are acceptable (legacy code) but don't add NEW warnings
- Common gotcha: removing `console.error` leaves unused `error` variable → use `catch {` instead of `catch (error) {`

**NEVER skip this step. NEVER.**

---

## QA CHECKLIST

- [ ] **`npm run lint` passes** on changed files (run BEFORE commit)
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
- Tesla components: `src/styles/buttons-tesla.css`, `modals-tesla.css`, `table-tesla.css`
