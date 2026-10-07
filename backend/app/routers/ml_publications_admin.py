"""Router: operator endpoints of the ML publications store (design D19, "Admin endpoint").

- `GET /ml-publications/status` (`ml_ops.ver`): the read-only report of `services.ml_publications.status`. No ML
  call, no write, a 5 s statement timeout; an empty store answers zeros and nulls.
- `GET /ml-publications/settings` (`ml_ops.ver`) and `PUT /ml-publications/settings/{key}` (`ml_ops.gestionar`):
  the runtime settings, through the allow-list and validation of `settings_store`. The author is the
  authenticated user, never a body field. Turning a flag on marks its handler `requested`.
- `POST /ml-publications/enqueue` (`ml_ops.gestionar`): at most 100 items at lane 0. Accepted even while
  `refresh.enabled` is off; the answer says so.
- `POST /ml-publications/jobs/{job}/request` (`ml_ops.gestionar`): run a handler on the worker's next pass;
  `scan` accepts `{"mode": "full" | "rescan"}`.

Merging this changes nothing at runtime: every flag stays where it is until an operator PUTs it.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.ml_publications import admin
from app.services.ml_publications import status as store_status
from app.services.ml_publications.resources import BUNDLE_RESOURCE, REFRESH_RESOURCES

PERMISO_VER = "ml_ops.ver"
PERMISO_GESTIONAR = "ml_ops.gestionar"

ENQUEUE_MAX = 100

router = APIRouter(prefix="/ml-publications", tags=["ML Publications Admin"])


def get_admin_db(db: Session = Depends(get_db)) -> Session:
    """The session the store tables are read and written through: the request's own (same database as the
    permission check). A separate dependency only so a test can point the store tables elsewhere."""
    return db


def _actor(user: Usuario) -> str:
    return f"user:{user.username or user.id}"


# ── Schemas ──────────────────────────────────────────────────────


class JobOut(BaseModel):
    job: str
    handler: str
    flag: str
    enabled: bool
    disabled: bool
    requested: bool
    failing: bool
    last_run_at: Optional[Any] = None
    last_success_at: Optional[Any] = None
    last_error: Optional[str] = None


class StatusOut(BaseModel):
    """The report of `status.build_status`; a section that failed is null and named in `sections_failed`."""

    generated_at: Any
    kill_switch: bool
    flags: dict[str, bool]
    jobs: list[JobOut]
    queue: Optional[dict[str, Any]] = None
    intake: Optional[dict[str, Any]] = None
    backfill: Optional[list[dict[str, Any]]] = None
    missed_feeds: Optional[dict[str, Any]] = None
    sweep: Optional[dict[str, Any]] = None
    items: Optional[dict[str, Any]] = None
    freshness: Optional[dict[str, dict[str, Any]]] = None
    lag_p95_seconds_24h: Optional[float] = None
    lag_samples_24h: int = 0
    completeness: Optional[dict[str, dict[str, Any]]] = None
    counters: dict[str, Any]
    events: Optional[dict[str, Any]] = None
    links: Optional[dict[str, Any]] = None
    top_changed_paths: Optional[list[dict[str, Any]]] = None
    sections_failed: list[str]


class SettingOut(BaseModel):
    key: str
    value: Any
    source: str


class SettingsOut(BaseModel):
    kill_switch: bool
    settings: list[SettingOut]


class SettingIn(BaseModel):
    value: Any


class SettingWriteOut(SettingOut):
    requested: Optional[str] = Field(default=None, description="handler marked `requested` by turning a flag on")


class EnqueueIn(BaseModel):
    item_ids: list[Annotated[str, StringConstraints(pattern=admin.ITEM_ID_PATTERN)]] = Field(
        min_length=1, max_length=ENQUEUE_MAX, description="e.g. MLA935110613"
    )
    resources: list[str] = Field(default=[BUNDLE_RESOURCE], min_length=1)

    @field_validator("resources")
    @classmethod
    def _known_resources(cls, resources: list[str]) -> list[str]:
        unknown = [r for r in resources if r not in REFRESH_RESOURCES]
        if unknown:
            raise ValueError(f"unknown resource(s) {unknown}; known: {', '.join(REFRESH_RESOURCES)}")
        return resources


class EnqueueOut(BaseModel):
    enqueued: int
    lane: int
    resources: list[str]
    refresh_enabled: bool
    note: Optional[str] = None
    missing_from_bundle_resources: list[str]


class RequestIn(BaseModel):
    mode: Optional[Literal["full", "rescan"]] = Field(default=None, description="scan only: kind of the next lap")


class RequestOut(BaseModel):
    job: str
    handler: str
    requested: bool
    mode: Optional[str] = None
    enabled: bool
    note: Optional[str] = None


# ── Reads (ml_ops.ver) ───────────────────────────────────────────


@router.get("/status", response_model=StatusOut)
def get_status(
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_admin_db),
) -> dict[str, Any]:
    """Read-only report: jobs, queue, intake, backfill, freshness, completeness, events, links, counters."""
    try:
        return store_status.build_status(db)
    finally:
        db.rollback()  # ends the read-only transaction; nothing was written


@router.get("/settings", response_model=SettingsOut)
def get_settings(_user: Usuario = Depends(require_permiso(PERMISO_VER))) -> dict[str, Any]:
    """Every runtime setting with its effective value and source (`db`, `env`, `kill_switch`, `unreadable`)."""
    return admin.list_settings()


# ── Operator actions (ml_ops.gestionar) ──────────────────────────


@router.put("/settings/{key}", response_model=SettingWriteOut)
def put_setting(
    key: str,
    body: SettingIn,
    user: Usuario = Depends(require_permiso(PERMISO_GESTIONAR)),
    db: Session = Depends(get_admin_db),
) -> dict[str, Any]:
    """Write one allow-listed setting. Turning a flag on marks its handler `requested`."""
    try:
        return admin.update_setting(db, key, body.value, _actor(user))
    except admin.UnknownSetting as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Configuración desconocida: {key}") from exc
    except admin.InvalidSetting as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/enqueue", response_model=EnqueueOut)
def enqueue(
    body: EnqueueIn,
    _user: Usuario = Depends(require_permiso(PERMISO_GESTIONAR)),
    db: Session = Depends(get_admin_db),
) -> dict[str, Any]:
    """Enqueue up to 100 items at lane 0 (served first, still paced). Accepted while `refresh.enabled` is off."""
    return admin.enqueue_items(db, body.item_ids, body.resources)


@router.post("/jobs/{job}/request", response_model=RequestOut)
def request_job(
    job: str,
    body: RequestIn = RequestIn(),
    user: Usuario = Depends(require_permiso(PERMISO_GESTIONAR)),
    db: Session = Depends(get_admin_db),
) -> dict[str, Any]:
    """Run a handler on the worker's next pass; `scan` also takes the mode of its next lap."""
    try:
        return admin.request_job(db, job, mode=body.mode, actor=_actor(user))
    except admin.UnknownJob as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Trabajo desconocido: {job}") from exc
    except admin.InvalidSetting as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except admin.ModeNotApplicable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="`mode` solo aplica al trabajo `scan`"
        ) from exc
