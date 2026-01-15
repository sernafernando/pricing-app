# Pricing App Backend - AI Agent Ruleset

> **Skills Reference**: For detailed patterns, use these skills:
> - [`pricing-app-backend`](../skills/pricing-app-backend/SKILL.md) - FastAPI + SQLAlchemy + Alembic patterns
> - [`pytest`](../skills/pytest/SKILL.md) - Testing patterns (fixtures, mocking, markers)

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Writing Python tests with pytest | `pytest` |

---

## CRITICAL RULES - NON-NEGOTIABLE

### Type Hints
- ALWAYS: Full type hints everywhere: `def get_user(user_id: int) -> User:`
- NEVER: Missing return types or parameter types

### Exception Handling
- ALWAYS: Specific exceptions: `except ValueError:`, `except HTTPException:`
- NEVER: Bare `except:` blocks

### FastAPI Endpoints
- ALWAYS: Explicit response models: `@router.get("/users", response_model=List[UserResponse])`
- ALWAYS: Dependency injection: `current_user: User = Depends(get_current_user)`
- ALWAYS: Proper HTTP status codes (200, 201, 400, 401, 403, 404, 422, 500)
- ALWAYS: Docstrings explaining business logic

### Database
- ALWAYS: Explicit column types: `Column(String(255))` not `Column(String)`
- ALWAYS: Create Alembic migrations for schema changes
- ALWAYS: Name migrations: `YYYYMMDD_description.py`
- ALWAYS: Add indexes for foreign keys and frequent queries
- NEVER: Alter DB manually

### Security
- ALWAYS: Hash passwords with bcrypt
- ALWAYS: Validate JWT with `get_current_user` dependency
- ALWAYS: Check permissions: `tienePermiso(user, "config")`
- NEVER: Store plain text passwords
- NEVER: Log sensitive data

---

## TECH STACK

FastAPI 0.100+ | SQLAlchemy 2.0+ | Alembic 1.12+ | Python 3.9+ | PostgreSQL | bcrypt | PyJWT

---

## PROJECT STRUCTURE

```
backend/
├── app/
│   ├── main.py              # FastAPI app
│   ├── routers/             # Route handlers (NEW)
│   ├── models/              # SQLAlchemy models
│   ├── services/            # Business logic
│   ├── core/                # Config, DB, security
│   └── utils/               # Helpers
├── alembic/versions/        # Migrations
└── scripts/                 # Cron jobs
```

---

## COMMANDS

```bash
# Dev
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Database
alembic revision --autogenerate -m "description"
alembic upgrade head

# Dependencies
pip install -r requirements.txt
```

---

## QA CHECKLIST

- [ ] Type hints on all functions
- [ ] Endpoints have response models
- [ ] Auth/permissions checked
- [ ] No bare `except:` blocks
- [ ] Migrations created for schema changes
- [ ] Indexes added for foreign keys
- [ ] No hardcoded config values
- [ ] No sensitive data in logs

---

## REFERENCES

- FastAPI: https://fastapi.tiangolo.com
- SQLAlchemy: https://docs.sqlalchemy.org
- Alembic: https://alembic.sqlalchemy.org
- Backend skill: [`../skills/pricing-app-backend/SKILL.md`](../skills/pricing-app-backend/SKILL.md)
