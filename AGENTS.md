# Repository Guidelines - Pricing App

## How to Use This Guide

- Start here for cross-project norms
- Each component has an `AGENTS.md` file with specific guidelines (e.g., `backend/AGENTS.md`, `frontend/AGENTS.md`)
- Component docs override this file when guidance conflicts
- Use skills for detailed patterns on-demand

---

## Available Skills

Use these skills for detailed patterns on-demand:

### Generic Skills (Any Project)

| Skill | Description | URL |
|-------|-------------|-----|
| `typescript` | Const types, flat interfaces, utility types | [SKILL.md](skills/typescript/SKILL.md) |
| `react-19` | No useMemo/useCallback, React Compiler | [SKILL.md](skills/react-19/SKILL.md) |
| `nextjs-15` | App Router, Server Actions, streaming | [SKILL.md](skills/nextjs-15/SKILL.md) |
| `tailwind-4` | cn() utility, no var() in className | [SKILL.md](skills/tailwind-4/SKILL.md) |
| `playwright` | Page Object Model, MCP workflow, selectors | [SKILL.md](skills/playwright/SKILL.md) |
| `pytest` | Fixtures, mocking, markers, parametrize | [SKILL.md](skills/pytest/SKILL.md) |
| `django-drf` | ViewSets, Serializers, Filters | [SKILL.md](skills/django-drf/SKILL.md) |
| `zod-4` | New API (z.email(), z.uuid()) | [SKILL.md](skills/zod-4/SKILL.md) |
| `zustand-5` | Persist, selectors, slices | [SKILL.md](skills/zustand-5/SKILL.md) |
| `ai-sdk-5` | UIMessage, streaming, LangChain | [SKILL.md](skills/ai-sdk-5/SKILL.md) |

### Pricing App-Specific Skills

| Skill | Description | URL |
|-------|-------------|-----|
| `pricing-app-backend` | FastAPI + SQLAlchemy + Alembic + auth patterns | [SKILL.md](skills/pricing-app-backend/SKILL.md) |
| `pricing-app-frontend` | React + Zustand + CSS Modules + Tesla Design | [SKILL.md](skills/pricing-app-frontend/SKILL.md) |
| `pricing-app-ml-integration` | MercadoLibre API - OAuth, webhooks, item sync | [SKILL.md](skills/pricing-app-ml-integration/SKILL.md) |
| `pricing-app-pricing-logic` | Pricing calculations - markup, fees, tiers, currency | [SKILL.md](skills/pricing-app-pricing-logic/SKILL.md) |
| `pricing-app-permissions` | Hybrid permission system - roles + overrides | [SKILL.md](skills/pricing-app-permissions/SKILL.md) |

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| After creating/modifying a skill | `skill-sync` |
| Calculating product prices | `pricing-app-pricing-logic` |
| Checking user permissions in backend | `pricing-app-permissions` |
| Computing ML commissions | `pricing-app-pricing-logic` |
| Creating Alembic migrations | `pricing-app-backend` |
| Creating branches | `git-workflow` |
| Creating custom hooks | `pricing-app-frontend` |
| Creating design tokens | `pricing-app-design` |
| Creating git commits | `git-workflow` |
| Creating new skills | `skill-creator` |
| Creating/modifying FastAPI endpoints | `pricing-app-backend` |
| Creating/modifying React components | `pricing-app-frontend` |
| Creating/modifying SQLAlchemy models | `pricing-app-backend` |
| Currency conversion (USD/ARS) | `pricing-app-pricing-logic` |
| Git workflow questions | `git-workflow` |
| Implementing ML OAuth flow | `pricing-app-ml-integration` |
| Implementing dark mode | `pricing-app-frontend` |
| Implementing dark mode theming | `pricing-app-design` |
| Implementing permission checks | `pricing-app-permissions` |
| Managing user permission overrides | `pricing-app-permissions` |
| Opening pull requests | `git-workflow` |
| Processing ML webhooks | `pricing-app-ml-integration` |
| Regenerate AGENTS.md Auto-invoke tables (sync.sh) | `skill-sync` |
| Styling with CSS Modules or Tesla Design | `pricing-app-frontend` |
| Styling with Tesla Design System | `pricing-app-design` |
| Syncing items to/from MercadoLibre | `pricing-app-ml-integration` |
| Troubleshoot why a skill is missing from AGENTS.md auto-invoke | `skill-sync` |
| Using CSS composition | `pricing-app-design` |
| Using PermisosContext | `pricing-app-permissions` |
| Using PermisosContext or ThemeContext | `pricing-app-frontend` |
| Using Zustand stores | `zustand-5` |
| Working with MercadoLibre API | `pricing-app-ml-integration` |
| Working with Zustand store | `pricing-app-frontend` |
| Working with auth/permissions in backend | `pricing-app-backend` |
| Working with pricing tiers | `pricing-app-pricing-logic` |
| Writing Python tests with pytest | `pytest` |
| Writing React components | `react-19` |
| Writing TypeScript types/interfaces | `typescript` |
| Writing backend business logic | `pricing-app-backend` |

---

## Project Overview

Pricing App is an internal ERP/pricing management system for e-commerce operations. It handles product pricing, inventory sync with MercadoLibre, sales tracking, and profitability analysis.

| Component | Location | Tech Stack |
|-----------|----------|------------|
| Backend | `backend/` | FastAPI, SQLAlchemy, Alembic, PostgreSQL |
| Frontend | `frontend/` | React 18, Vite, Zustand, CSS Modules |

---

## Backend Development

```bash
# Setup
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Development
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Database migrations
alembic revision --autogenerate -m "description"
alembic upgrade head

# Code quality
# (pending: add pre-commit hooks, black, flake8)
```

**See**: [`backend/AGENTS.md`](backend/AGENTS.md) for detailed backend rules.

---

## Frontend Development

```bash
# Setup
cd frontend
npm install

# Development
npm run dev

# Build
npm run build
npm run preview

# Linting
npm run lint
```

**See**: [`frontend/AGENTS.md`](frontend/AGENTS.md) for detailed frontend rules.

---

## Commit & Pull Request Guidelines

Follow conventional-commit style: `<type>[scope]: <description>`

**Types:** `feat`, `fix`, `docs`, `chore`, `perf`, `refactor`, `style`, `test`

**Examples:**
- `feat: add pre-armado manual modal`
- `fix: corregir colores de markup en calculadora`
- `refactor: extraer lógica de pricing a service`
- `chore: actualizar dependencias`
- `docs: agregar documentación de API`

Before creating a PR:
1. Test changes locally
2. Run all relevant linters
3. Write descriptive commit messages
4. Update documentation if needed

---

## Project Architecture

### Backend Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app initialization
│   ├── api/                 # (legacy - being migrated to routers/)
│   ├── routers/             # Route handlers (NEW pattern)
│   │   ├── auth.py
│   │   ├── productos.py
│   │   ├── ventas.py
│   │   └── ...
│   ├── models/              # SQLAlchemy models
│   │   ├── user.py
│   │   ├── producto.py
│   │   └── ...
│   ├── services/            # Business logic
│   │   ├── pricing_service.py
│   │   ├── ml_service.py
│   │   └── ...
│   ├── core/                # Config, security, database
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── security.py
│   │   └── deps.py
│   ├── utils/               # Helper functions
│   ├── scripts/             # Cron jobs, data sync
│   └── tickets/             # Ticketing system
├── alembic/
│   ├── versions/            # DB migrations
│   └── env.py
├── migrations/              # Manual SQL migrations (legacy)
└── requirements.txt
```

### Frontend Structure

```
frontend/src/
├── pages/                 # Full page components
│   ├── Productos.jsx
│   ├── Ventas.jsx
│   ├── Admin.jsx
│   └── ...
├── components/            # Reusable components
│   ├── ModalTesla.jsx
│   ├── PricingModal.jsx
│   ├── Navbar.jsx
│   └── turbo/             # Domain-specific components
├── contexts/              # React contexts
│   ├── ThemeContext.jsx   # Dark mode
│   └── PermisosContext.jsx # User permissions
├── hooks/                 # Custom hooks
│   ├── useDebounce.js
│   ├── usePermisos.js
│   └── useServerPagination.js
├── store/                 # Zustand stores
│   └── authStore.js       # Auth state
├── services/              # API client
│   └── api.js             # Axios instance
└── styles/                # Global CSS, design tokens
    ├── design-tokens.css
    ├── buttons-tesla.css
    ├── modals-tesla.css
    └── table-tesla.css
```

### Naming Conventions

| Entity | Pattern | Example |
|--------|---------|---------|
| Backend files | `snake_case.py` | `produccion_banlist.py` |
| Frontend files (components) | `PascalCase.jsx` | `ProductosList.jsx` |
| Frontend files (utilities) | `camelCase.js` | `formatCurrency.js` |
| Database tables | `snake_case` or `tb_{entity}` | `productos_erp`, `tb_usuarios` |
| API endpoints | `kebab-case` | `/api/produccion-banlist` |

---

## Security Checklist

- [ ] All endpoints check **authentication** (`Depends(get_current_user)`)
- [ ] Sensitive operations check **permissions** (`tienePermiso()`)
- [ ] Inputs are **validated** (Pydantic models in backend, form validation in frontend)
- [ ] SQL queries use **ORM** or **parameterized queries**
- [ ] Passwords are **hashed** with bcrypt
- [ ] JWT tokens have **expiration** (check config)
- [ ] CORS is configured properly (only allow trusted origins)
- [ ] Sensitive data not logged (passwords, tokens)

---

## Performance Guidelines

### Backend
- Use **async/await** for I/O operations
- Add **pagination** to list endpoints: `?page=1&page_size=50`
- Use **select_related/joinedload** to avoid N+1 queries
- Cache expensive calculations (consider Redis if needed)

### Frontend
- Use **React.memo** for expensive components
- Debounce search inputs: `useDebounce` hook
- Lazy load routes with **React.lazy** (if needed)
- Optimize images: use WebP, add loading="lazy"

---

## Common Pitfalls to Avoid

### Backend
- ❌ Don't query DB in loops → Use `joinedload` or bulk operations
- ❌ Don't return DB models directly → Use Pydantic response models
- ❌ Don't hardcode config values → Use environment variables
- ❌ Don't skip migrations → Always run `alembic upgrade head`

### Frontend
- ❌ Don't use `useEffect` without dependencies array
- ❌ Don't mutate state directly → Use setState functions
- ❌ Don't forget to cleanup effects (unsubscribe, clear timers)
- ❌ Don't store sensitive data in localStorage (only JWT token)
- ❌ Don't use emoji as icons (📦, ✅, ❌, 💰) → Use `lucide-react` SVG components
- ❌ Don't use `var` → Use `const` (default) or `let` (reassignment only)
- ❌ Don't leave `console.log` in production code

---

## Code Review Focus Areas

1. **Security**: Auth checks, input validation, SQL injection prevention
2. **Performance**: N+1 queries, unnecessary re-renders, large payloads
3. **Maintainability**: Clear naming, proper abstractions, documentation
4. **User Experience**: Loading states, error messages, accessibility
5. **Consistency**: Follow existing patterns in the codebase

---

## Key Features

### Pricing & Markup Calculation
- Dynamic markup calculation based on product categories, brands
- MercadoLibre fee integration
- Shipping cost calculations
- Multi-currency support (USD/ARS with exchange rate sync)

### Integrations
- **MercadoLibre**: Product sync, order tracking, sales metrics
- **Tienda Nube**: Order sync, inventory updates
- **ERP**: Product master data, cost updates
- **Pedidos Export**: Logistics integration

### Permission System
- Role-based access control (admin, ventas, logistica, viewer)
- Context-based permissions (PermisosContext in frontend)
- Granular permissions: config, ventas, productos, reportes, usuarios

### Dark Mode
- Full dark mode support via ThemeContext
- Design tokens for consistent theming
- Toggle persisted in localStorage

---

## External Resources

- Original code review rules (backup): [`AGENTS.md.backup`](AGENTS.md.backup)
- Backend skill: [`skills/pricing-app-backend/SKILL.md`](skills/pricing-app-backend/SKILL.md)
- Frontend skill: [`skills/pricing-app-frontend/SKILL.md`](skills/pricing-app-frontend/SKILL.md)
