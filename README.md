# Pricing App

Sistema interno para gestion de precios, rentabilidad e integraciones e-commerce (MercadoLibre, ERP, logistica y metricas).

Este README ahora es corto a proposito: quickstart + mapa de documentacion.

## TL;DR

- Backend: FastAPI + SQLAlchemy + Alembic
- Frontend: React + Vite + Zustand + CSS Modules
- Dominio: pricing, permisos, syncs, analytics

## Quickstart

### 1) Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8002
```

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend local: `http://localhost:5173`

Backend docs: `http://localhost:8002/docs`

## Configuracion minima

Variables criticas en `backend/.env`:

- `DATABASE_URL`
- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REFRESH_TOKEN_EXPIRE_DAYS` (si aplica en tu branch)

Variables frontend:

- `VITE_API_URL`

## Comandos utiles

### Backend

```bash
cd backend
source venv/bin/activate

# migraciones
alembic history
alembic upgrade head

# tests (ejemplo)
pytest -q
```

### Frontend

```bash
cd frontend

# desarrollo
npm run dev

# quality checks (si estan definidos en package.json)
npm run lint
```

## Documentacion (mapa)

### Operacion y arquitectura

- Guia de contribucion: `CONTRIBUTING.md`
- Reglas AI globales: `AGENTS.md`
- Reglas backend AI: `backend/CLAUDE.md`
- Reglas frontend AI: `frontend/CLAUDE.md`
- Runbooks de incidentes: `docs/RUNBOOKS.md`
- ADRs: `docs/adr/`
- Backlog tecnico 30/60/90: `TECH_BACKLOG_30_60_90.md`

### Skills AI

- Catalogo: `skills/README.md`
- Backend: `skills/pricing-app-backend/SKILL.md`
- Frontend: `skills/pricing-app-frontend/SKILL.md`
- Auth/Security: `skills/pricing-app-auth-security/SKILL.md`
- Testing/CI: `skills/pricing-app-testing-ci/SKILL.md`
- Pricing logic: `skills/pricing-app-pricing-logic/SKILL.md`
- Permissions: `skills/pricing-app-permissions/SKILL.md`
- ML integration: `skills/pricing-app-ml-integration/SKILL.md`

### Scripts e integraciones

- Backend scripts: `backend/scripts/README.md`

## Seguridad (minimo no negociable)

- No exponer endpoints protegidos sin auth.
- No saltear permisos en writes.
- No wildcard CORS en produccion.
- No loguear secretos/tokens/PII.
- No subir secretos al repo.

## Pull Requests

Usar template oficial:

- `.github/pull_request_template.md`

El PR debe incluir:

- Scope
- Validation (comandos exactos)
- Risks
- Rollback

## Notas

- Este README se simplifico para onboarding rapido.
- El detalle operativo vive en `docs/`, `AGENTS.md` y docs de componente.
- La version completa anterior se preserva en `docs/README.full-legacy.md`.
