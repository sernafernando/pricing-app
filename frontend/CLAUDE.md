# Pricing App Frontend - AI Agent Ruleset

> Precedence: If any rule here conflicts with root `AGENTS.md`, follow `AGENTS.md`.

> **Skills Reference**: For detailed patterns, use these skills:
> - [`pricing-app-frontend`](../skills/pricing-app-frontend/SKILL.md) - React + Zustand + CSS Modules + Tesla Design
> - [`react-19`](../skills/react-19/SKILL.md) - React 19 patterns, React Compiler
> - [`zustand-5`](../skills/zustand-5/SKILL.md) - Zustand state management
> - [`typescript`](../skills/typescript/SKILL.md) - TypeScript patterns (if migrating)

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Adding new backend endpoint behavior | `pricing-app-testing-ci` |
| Changing frontend critical user flows | `pricing-app-testing-ci` |
| Checking user permissions in backend | `pricing-app-permissions` |
| Creating custom hooks | `pricing-app-frontend` |
| Creating design tokens | `pricing-app-design` |
| Creating/modifying React components | `pricing-app-frontend` |
| Fixing production bugs that require regression tests | `pricing-app-testing-ci` |
| Implementing dark mode | `pricing-app-frontend` |
| Implementing dark mode theming | `pricing-app-design` |
| Implementing permission checks | `pricing-app-permissions` |
| Managing user permission overrides | `pricing-app-permissions` |
| Refactoring auth or pricing logic | `pricing-app-testing-ci` |
| Setting up or modifying CI pipelines | `pricing-app-testing-ci` |
| Styling with CSS Modules or Tesla Design | `pricing-app-frontend` |
| Styling with Tesla Design System | `pricing-app-design` |
| Using CSS composition | `pricing-app-design` |
| Using PermisosContext | `pricing-app-permissions` |
| Using PermisosContext or ThemeContext | `pricing-app-frontend` |
| Using Zustand stores | `zustand-5` |
| Working with Zustand store | `pricing-app-frontend` |
| Writing React components | `react-19` |
| Writing TypeScript types/interfaces | `typescript` |

---

## CRITICAL RULES - NON-NEGOTIABLE

### React Imports
- ALWAYS: `import { useState, useEffect } from 'react'`
- NEVER: `import React from 'react'` or `import * as React`

### Components
- ALWAYS: Functional components with hooks
- ALWAYS: Prop destructuring: `function Button({ label, onClick })`
- NEVER: Class components

### State Management
- ALWAYS: Zustand for global state (auth)
- ALWAYS: React Context for theme, permissions
- ALWAYS: Local state for component-specific data
- NEVER: Lift state unnecessarily

### Styling
- ALWAYS: CSS Modules: `import styles from './Component.module.css'`
- ALWAYS: Design tokens: `var(--bg-primary)`, `var(--text-primary)`
- ALWAYS: Tesla components when available
- NEVER: Inline styles (except dynamic values)
- NEVER: Hardcoded colors
- NEVER: Tailwind utilities (project uses CSS Modules)

### API Calls
- ALWAYS: Use axios from `services/api.js`
- ALWAYS: Check token: `localStorage.getItem('token')`
- ALWAYS: Handle loading states
- ALWAYS: Show user feedback on errors
- NEVER: Fetch without error handling

### Accessibility
- ALWAYS: Alt text on images
- ALWAYS: Semantic HTML
- ALWAYS: ARIA labels for icon-only buttons

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

## QA CHECKLIST

- [ ] Functional components with hooks
- [ ] No `import React` statements
- [ ] Error handling on API calls
- [ ] Loading states shown
- [ ] CSS Modules used (no inline styles)
- [ ] Design tokens used (no hardcoded colors)
- [ ] Dark mode works
- [ ] Permissions checked where needed
- [ ] Alt text on images
- [ ] Semantic HTML

---

## REFERENCES

- React: https://react.dev
- Zustand: https://zustand-demo.pmnd.rs
- Frontend skill: [`../skills/pricing-app-frontend/SKILL.md`](../skills/pricing-app-frontend/SKILL.md)
- Design tokens: `src/styles/design-tokens.css`
- Tesla components: `src/styles/buttons-tesla.css`, `modals-tesla.css`, `table-tesla.css`
