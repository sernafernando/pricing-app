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

### Pydantic v2 Syntax (CRITICAL)
- ALWAYS: Use `model_config = ConfigDict(...)` instead of `class Config:`
- ALWAYS: Use `.model_dump()` instead of `.dict()`
- ALWAYS: Use `.model_dump_json()` instead of `.json()`
- ALWAYS: Use `from_attributes=True` in ConfigDict (not `orm_mode = True`)
- ALWAYS: Use `datetime.now(UTC)` instead of `datetime.utcnow()` (deprecated Python 3.12+)
- NEVER: Mix Pydantic v1 and v2 syntax in the same codebase

### Security
- ALWAYS: Hash passwords with bcrypt
- ALWAYS: Validate JWT with `get_current_user` dependency
- ALWAYS: Check permissions: `tienePermiso(user, "config")`
- NEVER: Store plain text passwords
- NEVER: Log sensitive data

### Performance
- ALWAYS: Use `async/await` for I/O operations
- ALWAYS: Add pagination to list endpoints: `?page=1&page_size=50`
- ALWAYS: Use `joinedload()` or `selectinload()` to avoid N+1 queries
- NEVER: Query DB inside loops — use bulk operations
- NEVER: Return entire DB models — use Pydantic response models
- NEVER: Use `select *` — specify columns explicitly

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

## COMMON PATTERNS (always available — no skill needed)

### Pydantic v2 Response Model

```python
from pydantic import BaseModel, ConfigDict, Field

class ProductoResponse(BaseModel):
    id: int
    codigo: str
    descripcion: str
    precio: float = Field(gt=0)

    model_config = ConfigDict(from_attributes=True)

# Usage: producto.model_dump(), producto.model_dump_json()
# NEVER: producto.dict(), producto.json(), class Config: orm_mode = True
```

### Endpoint with Auth + Permissions

```python
@router.get("/productos", response_model=List[ProductoResponse])
async def get_productos(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
) -> List[ProductoResponse]:
    """Retrieve productos with pagination. Requires authentication."""
    productos = await fetch_productos(skip, limit)
    return productos

@router.post("/productos", response_model=ProductoResponse)
async def create_producto(
    producto: ProductoCreate,
    current_user: User = Depends(get_current_user),
):
    """Create producto. Requires 'config' permission."""
    if not tienePermiso(current_user, "config"):
        raise HTTPException(status_code=403, detail="Sin permiso")
    return created_producto
```

---

## QA CHECKLIST

- [ ] Type hints on all functions
- [ ] Endpoints have response models
- [ ] Auth/permissions checked
- [ ] No bare `except:` blocks
- [ ] Pydantic v2 syntax (no `.dict()`, `class Config:`, or `datetime.utcnow()`)
- [ ] Migrations created for schema changes
- [ ] Indexes added for foreign keys
- [ ] No hardcoded config values
- [ ] No sensitive data in logs
- [ ] No N+1 queries (use joinedload/bulk ops)

---

## REFERENCES

- FastAPI: https://fastapi.tiangolo.com
- SQLAlchemy: https://docs.sqlalchemy.org
- Alembic: https://alembic.sqlalchemy.org
- Backend skill: [`../skills/pricing-app-backend/SKILL.md`](../skills/pricing-app-backend/SKILL.md)
