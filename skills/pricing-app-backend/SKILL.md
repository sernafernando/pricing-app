# Pricing App Backend - FastAPI + SQLAlchemy

## Metadata

```yaml
name: pricing-app-backend
description: FastAPI backend patterns for Pricing App - SQLAlchemy, Alembic, auth, permissions
version: 1.0.0
triggers:
  - "backend"
  - "fastapi"
  - "sqlalchemy"
  - "alembic"
  - "api endpoint"
  - "database model"
  - "migration"
scope: pricing-app/backend
auto_invoke:
  - "Creating/modifying FastAPI endpoints"
  - "Creating/modifying SQLAlchemy models"
  - "Creating Alembic migrations"
  - "Working with auth/permissions in backend"
  - "Writing backend business logic"
```

---

## CRITICAL RULES - NON-NEGOTIABLE

### Type Hints
- ALWAYS: Full type hints on all functions: `def get_user(user_id: int) -> User:`
- NEVER: Missing return types or parameter types

### Exception Handling
- ALWAYS: Specific exceptions: `except ValueError:`, `except HTTPException:`
- NEVER: Bare `except:` blocks

### FastAPI Endpoints
- ALWAYS: Explicit response models: `@router.get("/users", response_model=List[UserResponse])`
- ALWAYS: Use dependency injection: `current_user: User = Depends(get_current_user)`
- ALWAYS: Proper HTTP status codes (200, 201, 400, 401, 403, 404, 422, 500)
- ALWAYS: Docstrings explaining business logic

### Database Models
- ALWAYS: Explicit column types: `Column(String(255))` not `Column(String)`
- ALWAYS: Create Alembic migrations for schema changes
- ALWAYS: Name migrations descriptively: `YYYYMMDD_description.py`
- ALWAYS: Use relationships: `relationship("User", back_populates="items")`
- ALWAYS: Add indexes for foreign keys and frequently queried columns

### Security
- ALWAYS: Hash passwords with bcrypt
- ALWAYS: Validate JWT tokens with `get_current_user` dependency
- ALWAYS: Check permissions before write operations: `tienePermiso(user, "write")`
- NEVER: Store passwords in plain text
- NEVER: Log sensitive data (passwords, tokens)

---

## PROJECT STRUCTURE

```
backend/
├── app/
│   ├── main.py              # FastAPI app initialization
│   ├── api/                 # (legacy - being migrated)
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
│   └── scripts/             # Cron jobs, data sync
├── alembic/
│   ├── versions/            # DB migrations
│   └── env.py
└── requirements.txt
```

---

## PATTERNS

### FastAPI Endpoint

```python
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api", tags=["productos"])

@router.get("/productos", response_model=List[ProductoResponse])
async def get_productos(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user)
) -> List[ProductoResponse]:
    """
    Retrieve all productos with pagination.
    Requires authentication.
    """
    # Business logic here
    productos = await fetch_productos(skip, limit)
    return productos
```

### SQLAlchemy Model

```python
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class Producto(Base):
    __tablename__ = "productos_erp"
    
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), nullable=False, unique=True)
    descripcion = Column(String(255), nullable=False)
    costo = Column(Integer, nullable=False)
    marca_id = Column(Integer, ForeignKey("marcas.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    marca = relationship("Marca", back_populates="productos")
    
    # Indexes
    __table_args__ = (
        Index("idx_producto_codigo", "codigo"),
        Index("idx_producto_marca", "marca_id"),
    )
```

### Alembic Migration

```python
"""add_titulo_ml_to_productos_erp

Revision ID: 5cf5f4b6e839
Revises: previous_revision
Create Date: 2025-01-15 10:30:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '5cf5f4b6e839'
down_revision = 'previous_revision'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('productos_erp', sa.Column('titulo_ml', sa.String(255), nullable=True))
    op.create_index('idx_productos_titulo_ml', 'productos_erp', ['titulo_ml'])

def downgrade():
    op.drop_index('idx_productos_titulo_ml', table_name='productos_erp')
    op.drop_column('productos_erp', 'titulo_ml')
```

### Authentication Dependency

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.core.config import settings
from app.models.user import User
from app.core.database import SessionLocal

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    Validate JWT token and return current user.
    Raises 401 if token is invalid or user not found.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    db.close()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user
```

### Permission Check

```python
from app.utils.permisos import tienePermiso

@router.post("/productos", response_model=ProductoResponse)
async def create_producto(
    producto: ProductoCreate,
    current_user: User = Depends(get_current_user)
):
    """Create new producto. Requires 'config' permission."""
    if not tienePermiso(current_user, "config"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para esta operación"
        )
    
    # Business logic...
    return created_producto
```

---

## NAMING CONVENTIONS

| Entity | Pattern | Example |
|--------|---------|---------|
| Router file | `{domain}.py` | `productos.py`, `ventas.py` |
| Model file | `{entity}.py` | `user.py`, `producto.py` |
| Service file | `{domain}_service.py` | `pricing_service.py` |
| Migration | `YYYYMMDD_description.py` | `20250115_add_titulo_ml.py` |
| Endpoint | `/api/{resource}` | `/api/productos` |
| Database table | `{entity}_erp` or `tb_{entity}` | `productos_erp`, `tb_usuarios` |

---

## COMMON PITFALLS

### Backend
- ❌ Don't query DB in loops → Use `joinedload()` or bulk operations
- ❌ Don't return DB models directly → Use Pydantic response models
- ❌ Don't hardcode config → Use environment variables
- ❌ Don't skip migrations → Always run `alembic upgrade head`
- ❌ Don't use `select *` → Specify columns explicitly
- ❌ Don't forget indexes → Add indexes for foreign keys and filters

---

## COMMANDS

```bash
# Development
cd backend
source venv/bin/activate  # or activate virtualenv
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Database
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1

# Dependencies
pip install -r requirements.txt
pip freeze > requirements.txt
```

---

## QA CHECKLIST

- [ ] All functions have type hints
- [ ] Endpoints have response models
- [ ] Auth/permissions checked where needed
- [ ] No bare `except:` blocks
- [ ] Migrations created for schema changes
- [ ] Indexes added for foreign keys
- [ ] No hardcoded config values
- [ ] No sensitive data in logs
- [ ] Error messages are user-friendly

---

## REFERENCES

- FastAPI docs: https://fastapi.tiangolo.com
- SQLAlchemy docs: https://docs.sqlalchemy.org
- Alembic docs: https://alembic.sqlalchemy.org
- Backend code review rules: `/AGENTS.md.backup` (original)
