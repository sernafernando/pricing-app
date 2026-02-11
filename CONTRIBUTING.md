# Contributing - Pricing App

Gracias por contribuir. Esta guia es corta, ejecutable y alineada con el estado actual del repo.

## 1) Antes de empezar

- Lee `AGENTS.md` (reglas globales y prioridades).
- Si tocas frontend/backend, lee tambien `frontend/CLAUDE.md` o `backend/CLAUDE.md`.
- Si creas o cambias skills, corre `bash ./skills/skill-sync/assets/sync.sh`.

## 2) Setup rapido

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

## 3) Flujo de trabajo

1. Crea una branch chica y con nombre claro (`feature/...`, `fix/...`, `refactor/...`).
2. Hace cambios minimos y atomicos.
3. Agrega/actualiza tests para cambios de comportamiento.
4. Corre checks relevantes del area tocada.
5. Abri PR con el template de `.github/pull_request_template.md`.

## 4) Reglas de calidad (minimo)

- Cambios criticos (auth/pricing/sync): test de happy path + failure path.
- Bugfix: incluir regression test.
- Nunca exponer endpoints protegidos sin auth.
- Nunca saltear permisos en operaciones de escritura.
- Nunca subir secretos (`.env`, keys, tokens).

## 5) Commits

Usar Conventional Commits:

- `feat:` nueva funcionalidad
- `fix:` correccion de bug
- `refactor:` cambio interno sin feature/bug
- `test:` tests
- `docs:` documentacion
- `chore:` tareas de tooling

Ejemplo:

```bash
git commit -m "fix: enforce refresh token type validation"
```

## 6) Pull Requests

El PR debe incluir:

- Scope: que cambiaste y que dejaste fuera.
- Validation: comandos exactos y resultado.
- Risks: riesgos conocidos o follow-ups.
- Rollback: camino simple para revertir.

Template oficial: `.github/pull_request_template.md`.

## 7) Skills (AI-assisted)

- Catalogo: `skills/README.md`
- Auth/security: `skills/pricing-app-auth-security/SKILL.md`
- Testing/CI: `skills/pricing-app-testing-ci/SKILL.md`
- Backend: `skills/pricing-app-backend/SKILL.md`
- Frontend: `skills/pricing-app-frontend/SKILL.md`

Si agregas/modificas un skill:

```bash
bash ./skills/skill-sync/assets/sync.sh
```

## 8) Docs operativas

- Runbooks: `docs/RUNBOOKS.md`
- ADRs: `docs/adr/`
- Backlog tecnico: `TECH_BACKLOG_30_60_90.md`

---

Si tenes dudas, abrí PR igual con contexto claro. Mejor iterar temprano que mergear tarde con incertidumbre.
